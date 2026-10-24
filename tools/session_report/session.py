"""Load a recorder session folder and resolve its protocol the way the recorder did.

``load_session`` turns raw.xdf, feedback-history.jsonl and feedback-session.json
into one ``Session``. It never requires a footer or a summary file: a session
that ended uncleanly still loads. Anything the loader doubts is written to
``Session.notes`` rather than swallowed.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

import refrain
from refrain.amp_profile import AmpProfile, load_amp_profile
from refrain.ir_json import ir_to_json_obj
from refrain.resolver import resolve

from measure_envelopes import montage_channels
from session_report.xdf_chunks import read_xdf_items

# recorder device.model -> bundled refrain amp profile
AMP_PROFILES = {"BrainBit Flex": "brainbit_flex"}
# JSONL records that change what the protocol does; losing one changes the replay
CONTROL_TYPES = frozenset({"control_change", "phase_change", "session_state", "advice_event"})
RECORDER_PYPROJECT = Path("~/git/coherence-recorder/pyproject.toml").expanduser()


@dataclass
class TimedEvent:
    after_chunk: int                 # index of the EEG chunk this follows; -1 = before the first
    record: dict


@dataclass
class Session:
    meta: dict
    fs: float
    channel_names: list[str]
    chunks: list[np.ndarray]
    events: list[TimedEvent]
    history: list[dict]
    telemetry: list[dict]
    notes: list[str] = field(default_factory=list)


def _read_history(path: Path, notes: list[str]) -> list[dict]:
    if not path.exists():
        return []
    lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
    out = []
    for i, ln in enumerate(lines):
        try:
            out.append(json.loads(ln))
        except ValueError:
            if i != len(lines) - 1:
                raise ValueError(f"{path}: line {i + 1} is not JSON")
            notes.append("feedback-history.jsonl ends with a partial line, which was ignored")
    return out


def _chunk_for_time(cum_end: np.ndarray, t_s: float, fs: float) -> int:
    n = int(round(t_s * fs))
    if n <= 0 or len(cum_end) == 0:
        return -1
    return min(int(np.searchsorted(cum_end, n, side="left")), len(cum_end) - 1)


def load_session(folder: Path) -> Session:
    folder = Path(folder)
    meta = json.loads((folder / "feedback-session.json").read_text())
    notes: list[str] = []
    infos, items, read = read_xdf_items(folder / "raw.xdf")
    if read.stopped_early:
        notes.append(f"XDF read stopped early at byte {read.bytes_parsed} of {read.file_size}: "
                     f"{read.reason}; later samples and markers are missing")

    eeg = [i for i in sorted(infos.values(), key=lambda s: s.stream_id)
           if i.channel_format != "string" and i.srate > 0]
    if not eeg:
        raise ValueError(f"{folder / 'raw.xdf'} has no EEG stream")
    stream = eeg[0]
    fs = stream.srate
    declared = (meta.get("device") or {}).get("sample_rate_hz")
    if declared is not None and abs(float(declared) - fs) > 0.01:
        notes.append(f"sample rate disagrees: EEG stream says {fs:g} Hz, feedback-session.json says "
                     f"{float(declared):g} Hz; using the stream's")

    chunks: list[np.ndarray] = []
    events: list[TimedEvent] = []
    for it in items:
        if it.kind == "samples" and it.stream_id == stream.stream_id:
            chunks.append(it.data)
        elif it.kind == "marker":
            events.append(TimedEvent(len(chunks) - 1, it.marker))

    history = _read_history(folder / "feedback-history.jsonl", notes)

    # The XDF marker stream can end before the history does (unclean exit). Control
    # records past its last marker are placed by time instead of dropped.
    xdf_times = [e.record["t_s"] for e in events if isinstance(e.record.get("t_s"), (int, float))]
    last_xdf = max(xdf_times, default=float("-inf"))
    cum_end = np.cumsum([len(c) for c in chunks])
    late = [r for r in history if r.get("type") in CONTROL_TYPES
            and isinstance(r.get("t_s"), (int, float)) and r["t_s"] > last_xdf]
    if late:
        events += [TimedEvent(_chunk_for_time(cum_end, r["t_s"], fs), r) for r in late]
        events.sort(key=lambda e: e.after_chunk)          # stable: XDF order kept within a chunk
        span = f"{min(r['t_s'] for r in late):.1f} to {max(r['t_s'] for r in late):.1f} s"
        notes.append(f"{len(late)} control record(s) came after the last XDF marker "
                     f"(t_s {last_xdf:.1f}); placed from feedback-history.jsonl by time, "
                     f"covering t_s {span}")

    return Session(meta=meta, fs=fs, channel_names=list(stream.channel_names), chunks=chunks,
                   events=events, history=history,
                   telemetry=[r for r in history if r.get("type") == "telemetry"], notes=notes)


def _amp_for(session: Session) -> AmpProfile:
    model = (session.meta.get("device") or {}).get("model")
    name = AMP_PROFILES.get(model)
    if name is None:
        raise ValueError(f"no bundled amp profile for device model {model!r}")
    return load_amp_profile(Path(refrain.__file__).parent / "amp_profiles" / f"{name}.json")


def resolve_for_session(session: Session, protocol_path: Path):
    """Resolve the protocol as the recorder did; return (IR, amp, evaluator channel order)."""
    amp = _amp_for(session)
    bindings = {**session.meta.get("placements", {}), **session.meta.get("modes", {})}
    ir = resolve(refrain.parse_file(str(protocol_path)), amp, bindings=bindings)
    chans = tuple(sorted(amp.channel_names()))
    have = {c.upper() for c in session.channel_names}
    for name in sorted(montage_channels(ir_to_json_obj(ir), set(chans))):
        if name.upper() not in have:
            raise ValueError(f"recording lacks channel {name!r} that the protocol reads")
    return ir, amp, chans


def recorder_pinned_ref(pyproject: Path = RECORDER_PYPROJECT) -> str | None:
    """The tag or sha the recorder pins refrain-protocols to, or None if unreadable."""
    try:
        text = Path(pyproject).read_text()
    except OSError:
        return None
    m = re.search(r"refrain-protocols\s*@\s*git\+\S+?@([^\s\"'#]+)", text)
    return m.group(1) if m else None


def _git(repo: Path, *args: str) -> bytes:
    try:
        return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True).stdout
    except subprocess.CalledProcessError as e:
        why = e.stderr.decode("utf-8", "replace").strip() or f"exit status {e.returncode}"
        raise ValueError(f"git {' '.join(args)} failed in {repo}: {why}") from e


def default_protocol_path(session: Session, repo: Path, ref: str | None = None) -> tuple[Path, str, str]:
    """Find the protocol file whose id matches the session; return (path, sha256, source)."""
    repo = Path(repo)
    pid = session.meta["protocol_id"]
    pattern = re.compile(r'^\s*protocol\s+"%s"' % re.escape(pid), re.MULTILINE)
    if ref is None:
        for p in sorted((repo / "protocols").rglob("*.refrain")):
            data = p.read_bytes()
            if pattern.search(data.decode("utf-8", "replace")):
                return p, hashlib.sha256(data).hexdigest(), "working tree"
        raise ValueError(f"no protocol {pid!r} under {repo / 'protocols'}")
    commit = _git(repo, "rev-parse", f"{ref}^{{commit}}").decode().strip()
    names = _git(repo, "ls-tree", "-r", "--name-only", commit, "protocols").decode().splitlines()
    for name in names:
        if not name.endswith(".refrain"):
            continue
        data = _git(repo, "show", f"{commit}:{name}")
        if pattern.search(data.decode("utf-8", "replace")):
            tmp = Path(tempfile.mkdtemp(prefix="session_report_")) / Path(name).name
            tmp.write_bytes(data)
            return tmp, hashlib.sha256(data).hexdigest(), f"ref {commit}"
    raise ValueError(f"no protocol {pid!r} at {ref} ({commit[:12]})")
