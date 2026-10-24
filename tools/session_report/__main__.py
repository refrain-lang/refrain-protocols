"""Report how a saved feedback session's protocol behaved.

    python -m tools.session_report <session folder> [--protocol PATH | --protocols-ref REF]
                                   [--compare PATH ...] [--json OUT]

The report leads with the one thing that decides whether to believe the rest: did
the replay do what ran live. Then it says which protocol file and which refrain
produced the numbers, and everything that would make them wrong -- a protocol
that may not be the one that ran, a replay that did not cover the recording, a
phase the replay disagreed about, anything the loader doubted. Only then the
numbers, per protocol: reward, true target episodes and latency, mutes against
an independent muscle measure, threshold drift, envelope lag, and the views a
protocol declares for itself. Every figure is measured after warmup, and the
header says which span that excluded and where that span was read from.

``--json`` writes the same content, so a later report can be diffed against this
one. Nothing from a session is copied anywhere else.
"""
from __future__ import annotations

import sys
from pathlib import Path

# This repo's import root is `tools/`, as tools/measure_envelopes.py and every test
# have always had it. Prepending it here is what makes the documented
# `python -m tools.session_report` invocation work without restructuring either.
_TOOLS = str(Path(__file__).resolve().parent.parent)
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import argparse  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import subprocess  # noqa: E402

import numpy as np  # noqa: E402

import refrain  # noqa: E402
from refrain.ir_json import ir_to_json_obj  # noqa: E402
from refrain.parser import ParseError  # noqa: E402
from refrain.resolver import ResolveError  # noqa: E402

# _share and _per_min are imported rather than reimplemented so that every rate and share
# in the report, printed or stored, obeys the one zero-denominator rule.
from session_report.metrics import (  # noqa: E402
    MUTE_SOURCES, _per_min, _share, session_metrics,
)
from session_report.muscle import (  # noqa: E402
    EDGE_GUARD_S, MIN_WINDOWS, MUSCLE_FACTOR, WINDOW_MS, muscle_band, muscle_episodes,
    noise_floor_per_min,
)
from session_report.reconcile import (  # noqa: E402
    COVERAGE_MARGIN_S, EVENTS_MIN, OUTPUTS_MIN, TELEMETRY_MIN, reconcile,
)
from session_report.replay import replay_session  # noqa: E402
from session_report.session import (  # noqa: E402
    default_protocol_path, load_session, recorder_pinned_ref, resolve_for_session,
)
from session_report.truth import true_episodes, truth_streams  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
# A protocol this tool cannot read or resolve, or a session folder that is not there, is
# a refusal to report, not a crash. refrain's own errors derive from Exception rather
# than ValueError, so they have to be named.
REFUSALS = (ValueError, OSError, ParseError, ResolveError)


# --- formatting: a figure that could not be measured prints as "--", never as None ---

def _pct(value, digits: int = 1) -> str:
    return "--" if value is None else f"{100.0 * value:.{digits}f}%"


def _num(value, fmt: str = "{:.0f}") -> str:
    return "--" if value is None else fmt.format(value)


def _ms(value) -> str:
    return "--" if value is None else f"{value:.0f} ms"


def _say(value, absent: str = "not recorded") -> str:
    """A value the session may not carry, never the word None."""
    return absent if value is None else str(value)


def _phase_label(phase: dict) -> str:
    return phase.get("name") or f"phase {phase.get('index')}"


# --- gathering ---

def _git(repo: Path, *args: str) -> bytes | None:
    try:
        return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None


def _head_state(repo: Path, path: Path, sha: str, source: str) -> str:
    """Whether the protocol file replayed is the one this repo carries at HEAD.

    A file read out of a git ref is compared by commit (it cannot be found by path,
    since it was written to a temporary file); one in the working tree is compared
    by its own content at HEAD.
    """
    if source.startswith("ref "):
        commit = source.removeprefix("ref ").strip()
        head = (_git(repo, "rev-parse", "HEAD^{commit}") or b"").decode().strip()
        if head and head == commit:
            return "equals HEAD (it was read at HEAD)"
        return f"read at {commit[:12]}, which is not HEAD ({head[:12] or 'unknown'}), so it may differ"
    try:
        rel = Path(path).resolve().relative_to(Path(repo).resolve())
    except ValueError:
        return "outside this repository, so it cannot be compared with HEAD"
    blob = _git(repo, "show", f"HEAD:{rel}")
    if blob is None:
        return f"{rel} is not committed at HEAD"
    return "equals HEAD" if hashlib.sha256(blob).hexdigest() == sha else f"DIFFERS from HEAD ({rel})"


def _skipped(replay) -> list[dict]:
    """The logged control changes this replay could not apply, in one shape."""
    return [{"name": s.get("name"), "reason": s.get("reason"), "value": s.get("value"),
             "after_chunk": s.get("after_chunk"), "t_s": (s.get("record") or {}).get("t_s")}
            for s in replay.skipped]


def _replay_protocol(session, path: Path, muscle, *, follow_log: bool):
    """Replay one protocol on this session's EEG and measure it; (entry, the replay)."""
    ir, _amp, channels = resolve_for_session(session, path)
    ir_json = ir_to_json_obj(ir)
    replay = replay_session(session, ir, channels, follow_log=follow_log)
    streams, _unreproducible = truth_streams(ir_json, replay, session.fs)
    truth = true_episodes(ir_json, streams, replay, session.fs)
    metrics = session_metrics(session, replay, truth, muscle, session.fs,
                              ir_json=ir_json, own=follow_log)
    return {"name": ir_json.get("name"), "skipped_controls": _skipped(replay), **metrics}, replay


def build_report(folder: Path, *, protocol: Path | None = None, protocols_ref: str | None = None,
                 compare=(), repo: Path = REPO) -> dict:
    """Load, replay, reconcile and measure a session; return the whole report as data."""
    session = load_session(Path(folder))
    source = "given with --protocol"
    if protocol is None:
        ref = protocols_ref if protocols_ref is not None else recorder_pinned_ref()
        protocol, sha, source = default_protocol_path(session, repo, ref)
    else:
        sha = hashlib.sha256(Path(protocol).read_bytes()).hexdigest()

    samples = sum(len(c) for c in session.chunks)
    raw = np.concatenate(session.chunks) if session.chunks else np.zeros((0, 1))
    muscle = muscle_episodes(raw, session.fs)
    band = muscle_band(session.fs)

    own, replay = _replay_protocol(session, Path(protocol), muscle, follow_log=True)
    # an upper bound only: reconcile matches each event within its own containing chunk
    tolerance = max((len(c) for c in session.chunks), default=1)
    rec = reconcile(session, replay, tolerance)

    protocols = [{"role": "session", "path": str(protocol), "sha256": sha,
                  "head": _head_state(repo, Path(protocol), sha, source), "source": source, **own}]
    for other in compare:
        # A comparison design that cannot be read or does not fit this recording is
        # reported as such; it must not take the rest of the report down with it.
        try:
            got, _ = _replay_protocol(session, Path(other), muscle, follow_log=False)
        except REFUSALS as exc:
            protocols.append({"role": "comparison", "path": str(other), "error": str(exc)})
            continue
        protocols.append({"role": "comparison", "path": str(other),
                          "sha256": hashlib.sha256(Path(other).read_bytes()).hexdigest(), **got})

    device = session.meta.get("device") or {}
    return {
        "tool": {
            "refrain_version": refrain.__version__,
            "live_refrain_version": None,       # REC-26: the recorder does not save it yet
            "reconciliation_tolerance_samples": tolerance,
            "gates": {"events": EVENTS_MIN, "outputs": OUTPUTS_MIN, "telemetry": TELEMETRY_MIN,
                      "coverage_margin_s": COVERAGE_MARGIN_S},
        },
        "session": {
            "folder": str(Path(folder)),
            "protocol_id": session.meta.get("protocol_id"),
            "device_model": device.get("model"),
            "fs": session.fs,
            "channels": list(session.channel_names),
            "samples": samples,
            "duration_s": samples / session.fs if session.fs else None,
            "chunks": len(session.chunks),
            "completed": session.meta.get("completed"),
            "notes": list(session.notes),
        },
        "reconciliation": {
            "reconciled": rec.reconciled,
            "events_matched": rec.events_matched,
            "outputs_within_1pct": rec.outputs_within_1pct,
            "telemetry_agree": rec.telemetry_agree,
            "coverage": rec.coverage,
            "evaluated": rec.evaluated,
            "notes": list(rec.notes),
        },
        "replay": {
            "mismatches": list(replay.mismatches),
            "phase_disagreements": [c for c in replay.phase_checks if not c.get("agrees")],
            "phase_changes_checked": len(replay.phase_checks),
            "chunks_unreplayed": replay.chunks_unreplayed,
        },
        "muscle": {
            "band_hz": list(band) if band else None,
            "factor": MUSCLE_FACTOR,
            "window_ms": WINDOW_MS,
            "min_windows": MIN_WINDOWS,
            "edge_guard_s": EDGE_GUARD_S,
            "episodes": len(muscle),
            "seconds": sum(b - a for a, b in muscle) / session.fs if session.fs else None,
            # what the same rule finds on pure noise at this rate, so a count can be read
            "noise_episodes_per_min": noise_floor_per_min(session.fs),
        },
        "protocols": protocols,
    }


# --- rendering ---

def _verdict(doc: dict) -> str:
    rec = doc["reconciliation"]
    scores = [("dings", rec["events_matched"]), ("output values", rec["outputs_within_1pct"]),
              ("telemetry", rec["telemetry_agree"])]
    parts = [f"{name} {_pct(value)}" if value is not None else f"{name} not evaluated"
             for name, value in scores]
    parts.append(f"coverage {_pct(rec['coverage'], 2)}")
    head = "RECONCILED" if rec["reconciled"] else "DID NOT RECONCILE"
    return f"Reconciliation: {head} — " + ", ".join(parts)


def _provenance(doc: dict) -> list[str]:
    session, tool, entry, muscle = doc["session"], doc["tool"], doc["protocols"][0], doc["muscle"]
    band = f"{muscle['band_hz'][0]:g}-{muscle['band_hz'][1]:g} Hz" if muscle["band_hz"] else "none at this sample rate"
    window = entry.get("window") or [0, 0]
    fs = session["fs"]
    lines = [
        f"  gates: dings >= {EVENTS_MIN:.0%}, output values >= {OUTPUTS_MIN:.0%}, "
        f"telemetry >= {TELEMETRY_MIN:.0%}, coverage within {COVERAGE_MARGIN_S:g} s of the end; "
        f"match tolerance {tool['reconciliation_tolerance_samples']} sample(s)",
        f"Session: {session['folder']}",
        f"  protocol id {_say(session['protocol_id'])} on {_say(session['device_model'])} at "
        f"{fs:g} Hz, channels {', '.join(session['channels'])}, "
        f"{_num(session['duration_s'], '{:.1f}')} s in {session['chunks']} chunk(s), "
        f"ended cleanly: {_say(session['completed'])}",
        f"  protocol file replayed: {entry['path']} ({entry['source']})",
        f"    sha256 {entry['sha256']} — {entry['head']}",
        f"  replay refrain version: {tool['refrain_version']}; live refrain version: not recorded "
        "(the recorder does not save it yet)",
        f"  muscle index: {band} power on {muscle['window_ms']:g} ms windows, an episode at "
        f"{muscle['factor']:g}x the recording's median for at least {muscle['window_ms']:g} ms",
        "  a figure printed as -- had nothing to take a share of (no episodes, no muted time, "
        "nothing measurable), which is not the same as zero",
    ]
    if entry.get("judged") and window[1] > window[0]:
        lines.append(f"  trusted window for true episodes: samples {window[0]} to {window[1]} "
                     f"({window[0] / fs:.1f} s to {window[1] / fs:.1f} s of "
                     f"{_num(session['duration_s'], '{:.1f}')} s)")
    else:
        lines.append(f"  trusted window for true episodes: samples {window[0]} to {window[1]} "
                     "(nothing could be looked at)")
    warmup = entry.get("warmup") or {}
    if warmup.get("end_sample"):
        lines.append(f"  warmup excluded from every figure below: samples 0 to "
                     f"{warmup['end_sample']} (0.0 s to {warmup['end_s']:.1f} s), read from "
                     f"{warmup['source']}; {_num(entry['elapsed_s'], '{:.1f}')} s measured")
    else:
        lines.append(f"  no warmup excluded, according to {warmup.get('source', 'nothing')}")
    return lines


def _caveats(doc: dict) -> list[str]:
    """Everything that would make the numbers below wrong, before the numbers."""
    out = []
    for text in doc["replay"]["mismatches"]:
        out.append(f"  - the protocol file replayed may not be the one that ran: {text}")
    for check in doc["replay"]["phase_disagreements"]:
        out.append(f"  - phase disagreement at t_s {_num(check.get('t_s'), '{:.1f}')}: the log "
                   f"entered phase {_say(check.get('logged_index'))} while the replay was in "
                   f"{_say(check.get('replay_index'))}")
    if doc["replay"]["chunks_unreplayed"]:
        out.append(f"  - {doc['replay']['chunks_unreplayed']} chunk(s) were never replayed because "
                   "the phase plan ended before the recording did")
    for note in doc["reconciliation"]["notes"]:
        if note.startswith("FAILED") or note.startswith("NOT EVALUATED"):
            out.append(f"  - reconciliation: {note}")
    for note in doc["session"]["notes"]:
        out.append(f"  - loading the session: {note}")
    for entry in doc["protocols"]:
        if entry.get("error"):
            out.append(f"  - {entry['path']} could not be replayed: {entry['error']}")
    head = ["", "What would make the numbers below wrong:"]
    return head + (out if out else ["  nothing was flagged"])


def _reconciliation_detail(doc: dict) -> list[str]:
    """Every reconciliation note the caveats did not already lead with.

    The caveats take the FAILED and NOT EVALUATED notes, but the rest are not
    decoration: "N logged reward record(s) lie past the end of the replayed samples"
    and "output channel(s) in the log but never produced by the replay" are how a
    reader sees what was and was not compared, and dropping them would undo the
    reason Task 4 was made to report them in the first place.
    """
    rest = [note for note in doc["reconciliation"]["notes"]
            if not note.startswith(("FAILED", "NOT EVALUATED"))]
    if not rest:
        return []
    return ["", "Reconciliation detail:"] + [f"  - {note}" for note in rest]


def _reward_lines(entry: dict) -> list[str]:
    dings = entry["ding_decided_vs_rendered"]
    out = ["  Reward",
           f"    reward decisions (the protocol's own reward.event, before any mute): "
           f"{_num(entry['reward_onsets'])} ({_num(entry['rewards_per_min'], '{:.2f}')} per minute of "
           f"{_num(entry['elapsed_s'], '{:.1f}')} s replayed)",
           f"    reward held for {_pct(entry['reward_share_of_unmuted'])} of "
           f"{_num(entry['unmuted_s'], '{:.1f}')} s unmuted; each hold lasted "
           f"{_ms(entry['reward_hold_len_ms']['median'])} median, "
           f"{_ms(entry['reward_hold_len_ms']['p90'])} at p90"]
    if dings["logged"] is None:
        out.append(f"    ding channels fired in this replay: {dings['decided']} (this design never "
                   "ran live, so nothing of it was rendered to anyone)")
    else:
        out.append(f"    ding channels fired in this replay: {dings['decided']}; the log recorded "
                   f"{dings['logged']}, of which {dings['rendered']} were rendered to the client")
    for channel, row in dings["by_channel"].items():
        out.append(f"      {channel}: {row['decided']} fired by the replay, "
                   f"{_num(row['logged'])} logged, {_num(row['rendered'])} rendered")
    return out


def _episode_lines(entry: dict) -> list[str]:
    if not entry["judged"]:
        out = ["  True target episodes: this session could not be judged, so no latency is reported"]
        for note in entry["truth_notes"]:
            out.append(f"    why: {note}")
        if entry["unreproducible"]:
            out.append("    derives the truth model cannot reproduce: "
                       + ", ".join(entry["unreproducible"]))
        return out
    curve = " | ".join(f"{k} ms {_pct(entry['deadline_curve'][k])}"
                       for k in sorted(entry["deadline_curve"]))
    return [
        "  True target episodes",
        f"    {_num(entry['episodes'])} episode(s), {_num(entry['episodes_per_min'], '{:.2f}')} per minute "
        f"of the {_num(entry['window_s'], '{:.1f}')} s trusted window; length median "
        f"{_ms(entry['episode_len_ms']['median'])}, p90 {_ms(entry['episode_len_ms']['p90'])}",
        f"    a reward decided while still going: {_pct(entry['rewarded_in_episode'])}; "
        f"by episode end + {entry['settings']['grace_ms']:.0f} ms: "
        f"{_pct(entry['rewarded_by_end_plus_250'])} (decided, not necessarily heard: the "
        "ding line above says what the channels fired)",
        f"    latency from the episode's true start: median "
        f"{_ms(entry['latency_from_episode_ms']['median'])}, p90 "
        f"{_ms(entry['latency_from_episode_ms']['p90'])}",
        f"    of which the filter's own delay, to the protocol's condition first holding: median "
        f"{_ms(entry['latency_from_condition_true_ms']['median'])}, p90 "
        f"{_ms(entry['latency_from_condition_true_ms']['p90'])} — over the rewarded episodes "
        f"except {_num(entry['condition_already_true_at_start'])}, where the condition was "
        "already holding when the behaviour started and the delay cannot be read",
        f"    rewarded within: {curve}",
        f"    continuous output half-rise from the true start: median "
        f"{_ms(entry['continuous_rise_ms']['median'])}",
        f"    stray rewards, with no episode behind them: "
        f"{_num(entry['stray_rewards_per_min'], '{:.2f}')} per minute of the trusted window",
    ]


def _muscle_lines(muscle: dict, recorded_s) -> list[str]:
    """What the muscle measure found, with the noise floor it has to be read against."""
    rate = _per_min(muscle["episodes"], recorded_s)
    floor = muscle["noise_episodes_per_min"]
    read_against = (f"on pure noise at this sample rate the same rule finds about "
                    f"{floor:.2g} a minute, so read the count against that"
                    if floor is not None else
                    "this rule's noise floor has not been measured at this sample rate, so the "
                    "count is not a safe count of real events")
    return [
        f"    muscle: {muscle['episodes']} episode(s), {_num(rate, '{:.2f}')} per minute, "
        f"{_num(muscle['seconds'], '{:.1f}')} s = {_pct(_share(muscle['seconds'], recorded_s))} "
        f"of the {_num(recorded_s, '{:.1f}')} s recorded",
        f"      {read_against}; and the first and last {muscle['edge_guard_s']:g} s cannot be "
        "seen at all (they are the filter's own edge transient)",
    ]


def _mute_lines(entry: dict, muscle: dict, recorded_s) -> list[str]:
    share = entry["mute_share"]
    lost = entry["episodes_lost_to_mute"]
    return [
        "  Mutes and muscle",
        "    muted, by source (one sample can be muted by several): "
        + " | ".join(f"{name} {_pct(share[name])}" for name in MUTE_SOURCES)
        + f" (unmuted {_num(entry['unmuted_s'], '{:.1f}')} s of "
          f"{_num(entry['elapsed_s'], '{:.1f}')} s measured)",
        *_muscle_lines(muscle, recorded_s),
        f"      {_pct(entry['muscle_time_muted'])} of muscle time was muted, and "
        f"{_pct(entry['muted_without_muscle'])} of muted time had no muscle",
        "    episodes lost to mute (muted for the whole episode): "
        + " | ".join(f"{name} {_num(lost[name])}" for name in (*MUTE_SOURCES, "any")),
    ]


def _threshold_lines(entry: dict) -> list[str]:
    if not entry["thresholds_per_block"]:
        return []
    out = ["  Thresholds per block"]
    for name, blocks in entry["thresholds_per_block"].items():
        parts = [f"{b['block'] or ('phase %d' % b['index'])} {b['start']:.3g} -> {b['end']:.3g} "
                 f"(drift {b['drift']:+.3g})" for b in blocks]
        out.append(f"    {name}: " + " | ".join(parts))
    return out


def _lag_lines(entry: dict) -> list[str]:
    if not entry["derive_lag_r"]:
        return []
    out = ["  Envelope lag against an accurate (zero-phase) filter"]
    for name, (lag, r) in entry["derive_lag_r"].items():
        out.append(f"    {name}: {lag:.0f} ms, r {r:.3f}")
    return out


def _phase_span(phase: dict) -> str:
    """A phase's own span, and the measured part of it when warmup took some away."""
    span = f"{phase['start_s']:.1f}-{phase['end_s']:.1f} s"
    measured = phase.get("measured_from_s")
    if measured is not None and measured > phase["start_s"] + 0.05:
        return f"{span} (measured from {measured:.1f} s, {_num(phase['elapsed_s'], '{:.1f}')} s)"
    return f"{span} ({_num(phase['elapsed_s'], '{:.1f}')} s)"


def _phase_lines(entry: dict) -> list[str]:
    if not entry["per_phase"]:
        return []
    out = ["  Per phase"]
    for phase in entry["per_phase"]:
        if not phase["elapsed_s"]:
            out.append(f"    {_phase_label(phase)} {phase['start_s']:.1f}-{phase['end_s']:.1f} s:"
                       " entirely warmup, so nothing in it was measured")
            continue
        head = f"    {_phase_label(phase)} {_phase_span(phase)}"
        out.append(f"{head}: rewards {_num(phase['rewards_per_min'], '{:.2f}')}/min, "
                   f"reward share of unmuted {_pct(phase['reward_share_of_unmuted'])}, "
                   f"episodes {_num(phase['episodes'])} "
                   f"({_num(phase['episodes_per_min'], '{:.2f}')}/min), "
                   f"rewarded in episode {_pct(phase['rewarded_in_episode'])}, "
                   f"muted {_pct(phase['mute_share']['phase'])} by phase")
    return out


def _view_lines(entry: dict) -> list[str]:
    views = entry["protocol_views"]
    if not views:
        return []
    out = ["  Views this protocol declares for itself"]
    ratio = views.get("ratio")
    if ratio:
        out.append(f"    ratio {ratio['ratio_stream']} against "
                   f"{_say(ratio['scored_against'], 'no target this report could resolve')} "
                   f"(declared in {ratio['declared_in']}): "
                   f"{_pct(ratio['share_above_target'])} of the replay above target")
        for bucket in ratio["buckets"]:
            out.append(f"      {bucket['start_s']:.0f}-{bucket['end_s']:.0f} s: ratio "
                       f"{bucket['ratio_median']:.3g}, target "
                       f"{_num(bucket['target_median'], '{:.3g}')}, above "
                       f"{_pct(bucket['share_above_target'])}")
    state = views.get("feedback_state")
    if state:
        if state["frames"]:
            out.append("    layered texture, time in each logged feedback state: " + " | ".join(
                f"{name} {count} frames ({_pct(state['share'][name])})"
                for name, count in state["frames"].items()))
        else:
            out.append(f"    layered texture, but none of the {state['telemetry_frames']} telemetry "
                       "frame(s) reports a feedback state")
    return out


def _protocol_lines(entry: dict, muscle: dict, recorded_s) -> list[str]:
    role = "the session's own protocol" if entry["role"] == "session" else "comparison design"
    out = ["", f"== {role}: {entry.get('name') or Path(entry['path']).name} =="]
    if entry.get("error"):
        return out + [f"  could not be replayed: {entry['error']}"]
    out += _reward_lines(entry)
    out += _episode_lines(entry)
    out += _mute_lines(entry, muscle, recorded_s)
    out += _threshold_lines(entry)
    out += _lag_lines(entry)
    out += _phase_lines(entry)
    out += _view_lines(entry)
    if entry["judged"] and entry["unreproducible"]:
        out.append("  Derives the truth model could not reproduce (they are not in the reward "
                   "condition, so the session was still judged): " + ", ".join(entry["unreproducible"]))
    if entry["skipped_controls"]:
        out.append("  Logged control changes this design could not take")
        for skipped in entry["skipped_controls"]:
            out.append(f"    {_say(skipped['name'], 'an unnamed control')} at t_s "
                       f"{_num(skipped['t_s'], '{:.1f}')}: {_say(skipped['reason'], 'no reason given')}")
    for note in entry["notes"]:
        out.append(f"  note: {note}")
    return out


def render(doc: dict) -> list[str]:
    lines = [_verdict(doc)]
    lines += _provenance(doc)
    lines += _caveats(doc)
    lines += _reconciliation_detail(doc)
    for entry in doc["protocols"]:
        lines += _protocol_lines(entry, doc["muscle"], doc["session"]["duration_s"])
    return lines


def _parse(argv):
    parser = argparse.ArgumentParser(prog="python -m tools.session_report",
                                     description=__doc__.split("\n")[0])
    parser.add_argument("session", type=Path, help="a saved recorder session folder")
    which = parser.add_mutually_exclusive_group()
    which.add_argument("--protocol", type=Path, help="the protocol file to replay (default: the "
                       "one in this repo whose id matches, at the ref the recorder pins)")
    which.add_argument("--protocols-ref", help="read the default protocol at this git ref instead")
    parser.add_argument("--compare", type=Path, action="append", default=[],
                        help="another design to replay on the same EEG (repeatable)")
    parser.add_argument("--json", type=Path, help="write the whole report here as JSON")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = _parse(argv)
    try:
        doc = build_report(args.session, protocol=args.protocol, protocols_ref=args.protocols_ref,
                           compare=args.compare)
    except REFUSALS as exc:                   # a refusal, not a crash: say what and stop
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print("\n".join(render(doc)))
    if args.json:
        try:
            args.json.write_text(json.dumps(doc, indent=1))
        except OSError as exc:                # the report is already printed; say what was lost
            print(f"error: the report was printed but could not be written to "
                  f"{args.json}: {exc}", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
