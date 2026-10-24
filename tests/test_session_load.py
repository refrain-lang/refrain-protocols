"""Loading a recorder session and resolving its protocol the way the recorder did."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("scipy")
pytest.importorskip("refrain")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from session_fixture import build_session  # noqa: E402
from session_report.session import (  # noqa: E402
    default_protocol_path, load_session, recorder_pinned_ref, resolve_for_session,
)

PROTOCOL = ROOT / "protocols" / "eeg" / "alpha_theta_narrowband.refrain"
BINDINGS = dict(placements={"site": "Pz"}, modes={"slow_guard": "off", "fast_guard": "on"})


def _session(tmp_path, *, markers=(), telemetry=(), n=1000, footer=True, **kw):
    return build_session(tmp_path, fs=250, channel_names=["Pz"], eeg=np.zeros((n, 1)), chunk=25,
                         protocol_id="alpha_theta_narrowband", markers=list(markers),
                         telemetry=list(telemetry), footer=footer, **{**BINDINGS, **kw})


def test_default_protocol_path_finds_by_protocol_id(tmp_path):
    s = load_session(_session(tmp_path))
    path, sha, source = default_protocol_path(s, ROOT)
    assert path == PROTOCOL
    assert sha == hashlib.sha256(PROTOCOL.read_bytes()).hexdigest()
    assert source == "working tree"


def test_default_protocol_path_at_ref(tmp_path):
    s = load_session(_session(tmp_path))
    path, sha, source = default_protocol_path(s, ROOT, ref="HEAD")
    committed = (ROOT / "protocols/eeg/alpha_theta_narrowband.refrain").read_bytes()
    assert sha == hashlib.sha256(committed).hexdigest()
    assert source.startswith("ref ") and len(source) > 10
    assert path.read_bytes() == committed
    assert ROOT not in path.parents          # temp copy lives outside the repo


def test_load_session_places_events_after_their_chunk(tmp_path):
    rec = {"type": "control_change", "t_s": 0.4}
    s = load_session(_session(tmp_path, markers=[(100, rec)]))
    assert [(e.after_chunk, e.record["t_s"]) for e in s.events] == [(3, 0.4)]
    assert s.fs == 250 and s.channel_names == ["Pz"]
    assert len(s.chunks) == 40 and all(len(c) == 25 for c in s.chunks)
    assert s.notes == []


def test_missing_channel_is_refused_by_name(tmp_path):
    s = load_session(_session(tmp_path, placements={"site": "Cz"}))
    with pytest.raises(ValueError, match="'Cz'"):
        resolve_for_session(s, PROTOCOL)


def test_unknown_device_model_is_refused(tmp_path):
    s = load_session(_session(tmp_path, device_model="Acme Cap 9000"))
    with pytest.raises(ValueError, match="Acme Cap 9000"):
        resolve_for_session(s, PROTOCOL)


def test_resolve_returns_sorted_amp_channel_order(tmp_path):
    s = load_session(_session(tmp_path))
    ir, amp, chans = resolve_for_session(s, PROTOCOL)
    assert chans == tuple(sorted(amp.channel_names())) and "Pz" in chans


def test_events_lost_from_the_xdf_are_placed_from_the_history(tmp_path):
    kept = {"type": "control_change", "t_s": 1.0}
    lost = [{"type": "control_change", "t_s": 2.0}, {"type": "phase_change", "t_s": 3.0}]
    tele = [{"type": "telemetry", "t_s": 2.5}]
    d = _session(tmp_path, n=1250, markers=[(250, kept)], telemetry=tele)
    # build_session writes every marker to both files, so drop the lost ones from the XDF
    # by building a second session that holds only the kept one, then reuse its history.
    d2 = _session(tmp_path / "x", n=1250, markers=[(250, kept)], telemetry=tele)
    (d2 / "feedback-history.jsonl").write_text(
        (d / "feedback-history.jsonl").read_text()
        + "".join(json.dumps(r) + "\n" for r in lost))
    s = load_session(d2)
    assert [e.record["t_s"] for e in s.events] == [1.0, 2.0, 3.0]
    assert [e.after_chunk for e in s.events] == [9, 19, 29]     # 2 s = sample 500 = chunk 19
    assert len(s.history) == 4 and len(s.telemetry) == 1
    assert any("2 " in n and "2.0" in n and "3.0" in n for n in s.notes)


def test_truncated_xdf_is_noted(tmp_path):
    d = _session(tmp_path)
    raw = (d / "raw.xdf").read_bytes()
    (d / "raw.xdf").write_bytes(raw[:-40])
    s = load_session(d)
    assert any("stopped early" in n for n in s.notes)


def test_recorder_pinned_ref_reads_tag_or_sha(tmp_path):
    for ref in ("v0.2.0", "a" * 40):
        p = tmp_path / "pyproject.toml"
        p.write_text('deps = [\n  "refrain @ git+https://github.com/refrain-lang/refrain.git@v0.24.0",\n'
                     f'  "refrain-protocols @ git+https://github.com/refrain-lang/refrain-protocols.git@{ref}",\n]\n')
        assert recorder_pinned_ref(p) == ref
    assert recorder_pinned_ref(tmp_path / "missing.toml") is None
