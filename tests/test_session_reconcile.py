"""Does the replay match what ran live? The verdict the whole report leads with."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("scipy")
refrain = pytest.importorskip("refrain")
from refrain.resolver import resolve  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from session_fixture import build_session  # noqa: E402
from session_report.reconcile import reconcile  # noqa: E402
from session_report.replay import ReplayResult, replay_session  # noqa: E402
from session_report.session import load_session  # noqa: E402

FS = 100.0
CHUNK = 4
CHANS = ("A1", "Pz")
N = 1000

PROTOCOL = '''
protocol "tiny" {
  meta { version = "1.0.0" evidence = "exploratory" description = "t" title = "t" summary = "t"
         family = "t" status = "draft" modality = "eeg" }
  requires { coupling = "ac" sample_rate = ">= 100 Hz" impedance = "not_required" markers = "not_required" }
  input "raw" { montage = referential(active: "Pz", reference: "A1") }
  derive "scaled" { formula = "raw" * gain }
  reward { event = dwell(condition: above("scaled", 0.5 uV), duration: 200 ms) }
  output { level = "scaled"
    chime = reward.event }
  controls {
    gain = number { default = 1.0  range = (0.0, 100.0)  label = "Gain"  live_tunable = true }
  }
  session {
    phases = [
      phase { name = "work"; duration = 1 min; mode = timed_with_floor },
    ]
  }
}
'''


def _ir(tmp_path):
    path = tmp_path / "tiny.refrain"
    path.write_text(PROTOCOL)
    return resolve(refrain.parse_file(str(path)), None)


def _eeg():
    on = (np.arange(N) // 100) % 2 == 1                      # 1 s on, 1 s off: a ding every 2 s
    return np.column_stack([np.zeros(N), on * (1 + 0.3 * np.sin(np.arange(N) / 50))])


def _reward_records(events, *, shift=0, scale=1.0):
    out = []
    for e in events:
        rec = {"type": "reward_event", "channel": e["channel"], "kind": e["kind"],
               "t_s": (e["t_sample"] + shift) / FS}
        if e["kind"] == "value":
            rec["value"] = e["value"] * scale
        # file position on a chunk boundary, so logging does not re-chunk the EEG the replay sees
        out.append((-(-(e["t_sample"] + shift) // CHUNK) * CHUNK, rec))
    return out


def _frames(replay, *, wall_skew=0.0, every=5):
    """A telemetry frame every ``every`` chunks, as (sample, record), saying what the replay's taps said."""
    out = []
    for k in range(0, len(replay.taps_per_chunk), every):
        tap, pos = replay.taps_per_chunk[k], replay.chunk_sample_offsets[k]
        out.append((pos, {"type": "telemetry", "t_s": pos / FS + wall_skew * pos / (N * 1.0),
                          "reward_event_holds": bool(tap["reward/event.holds"]),
                          "muted": bool(tap["muted"]), "inhibits": {}}))
    return out


def _case(tmp_path, *, shift=0, scale=1.0, wall_skew=0.0, edit=None):
    """Replay the protocol, log what it did, load that log, and replay it again as the report would."""
    ir = _ir(tmp_path)
    base = load_session(build_session(tmp_path / "a", fs=FS, channel_names=list(CHANS), eeg=_eeg(), chunk=CHUNK,
                                      protocol_id="tiny", markers=[], telemetry=[]))
    first = replay_session(base, ir, CHANS, follow_log=False)
    markers = _reward_records(first.events, shift=shift, scale=scale)
    frames = _frames(first, wall_skew=wall_skew)
    if edit:
        markers, frames = edit(markers, frames)
    s = load_session(build_session(tmp_path / "b", fs=FS, channel_names=list(CHANS), eeg=_eeg(), chunk=CHUNK,
                                   protocol_id="tiny", markers=markers, telemetry=frames))
    return s, replay_session(s, ir, CHANS, follow_log=False)


def test_identical_replay_reconciles(tmp_path):
    s, r = _case(tmp_path)
    assert any(e["kind"] == "event" for e in r.events) and any(e["kind"] == "value" for e in r.events)
    rec = reconcile(s, r, CHUNK)
    assert (rec.events_matched, rec.outputs_within_1pct, rec.telemetry_agree) == (1.0, 1.0, 1.0)
    assert rec.reconciled is True
    assert any("tolerance: 4 sample" in n for n in rec.notes)


def test_shifted_events_fail_reconciliation(tmp_path):
    s, r = _case(tmp_path, shift=3 * CHUNK)
    rec = reconcile(s, r, CHUNK)
    assert rec.events_matched < 0.99 and rec.reconciled is False
    assert any(n.startswith("FAILED dings") for n in rec.notes)


def test_null_telemetry_fields_are_excluded_not_counted_against(tmp_path):
    def blank(markers, frames):
        nulled = [(p, dict(f, muted=None, reward_event_holds=None)) for p, f in frames[:10]]
        return markers, nulled + frames[10:]
    s, r = _case(tmp_path, edit=blank)
    rec = reconcile(s, r, CHUNK)
    assert rec.telemetry_agree == 1.0 and rec.reconciled is True


def test_a_wrong_telemetry_boolean_is_counted(tmp_path):
    def flip(markers, frames):
        return markers, [(p, dict(f, muted=not f["muted"])) for p, f in frames]
    s, r = _case(tmp_path, edit=flip)
    rec = reconcile(s, r, CHUNK)
    assert rec.telemetry_agree == pytest.approx(0.5) and rec.reconciled is False
    assert any(n.startswith("FAILED telemetry") for n in rec.notes)


def test_output_values_just_inside_and_outside_one_percent(tmp_path):
    for sub in ("in", "out"):
        (tmp_path / sub).mkdir()
    inside = reconcile(*_case(tmp_path / "in", scale=1.0099), CHUNK)
    outside = reconcile(*_case(tmp_path / "out", scale=1.0101), CHUNK)
    # zero-valued samples agree at any scale, so only the non-zero ones tell the cases apart
    assert inside.outputs_within_1pct == 1.0 and inside.reconciled is True
    assert outside.outputs_within_1pct < 0.99 and outside.reconciled is False
    assert any(n.startswith("FAILED output values") for n in outside.notes)


def test_frames_are_placed_by_file_position_not_their_own_clock(tmp_path):
    # the wall clock runs 3 s ahead by the end of the 10 s recording
    s, r = _case(tmp_path, wall_skew=3.0)
    rec = reconcile(s, r, CHUNK)
    assert rec.telemetry_agree == 1.0 and rec.reconciled is True
    assert any("wall clock minus refrain clock" in n and "+2." in n for n in rec.notes)


def test_a_check_with_nothing_to_compare_is_unevaluated_not_perfect(tmp_path):
    s, _ = _case(tmp_path, edit=lambda m, f: ([], []))
    rec = reconcile(s, ReplayResult(), CHUNK)                 # nothing logged, nothing replayed
    assert (rec.events_matched, rec.outputs_within_1pct, rec.telemetry_agree) == (None, None, None)
    assert rec.evaluated == {"events": False, "outputs": False, "telemetry": False}
    assert rec.reconciled is False
    assert sum(n.startswith("NOT EVALUATED") for n in rec.notes) == 3


def test_a_protocol_with_no_dings_reconciles_on_the_checks_that_ran(tmp_path):
    s, r = _case(tmp_path)
    s.history[:] = [h for h in s.history if h.get("kind") != "event"]
    r.events[:] = [e for e in r.events if e["kind"] != "event"]
    rec = reconcile(s, r, CHUNK)
    assert rec.events_matched is None and rec.evaluated["events"] is False
    assert rec.outputs_within_1pct == 1.0 and rec.telemetry_agree == 1.0 and rec.reconciled is True


def test_spurious_replay_dings_count_against_the_ding_score(tmp_path):
    s, r = _case(tmp_path, edit=lambda m, f: ([x for x in m if x[1]["kind"] != "event"], f))
    rec = reconcile(s, r, CHUNK)
    assert rec.events_matched == 0.0 and rec.reconciled is False
    assert any("larger of 0 logged and 5 replayed" in n for n in rec.notes)


def test_replay_mismatches_and_unreplayed_chunks_reach_the_notes(tmp_path):
    s, r = _case(tmp_path)
    r.mismatches.append("log enters phase 9 but the replay is in phase 0")
    r.chunks_unreplayed = 7
    notes = " ".join(reconcile(s, r, CHUNK).notes)
    assert "phase 9" in notes and "7 chunk(s) were never replayed" in notes
