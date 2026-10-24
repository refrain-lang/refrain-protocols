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
  inhibit "fast" {
    metric    = bandpower(input: "raw", band: (15 Hz, 40 Hz), window: 250 ms)
    threshold = percentile(target_pct: 90, window: 10 s)
    action    = mute(release: 1 ms)
  }
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
                          "muted": bool(tap["muted"]), "inhibits": {"fast": bool(tap["inhibit/fast"])}}))
    return out


def _case(tmp_path, *, shift=0, scale=1.0, wall_skew=0.0, edit=None, eeg=None):
    """Replay the protocol, log what it did, load that log, and replay it again as the report would."""
    ir = _ir(tmp_path)
    base = load_session(build_session(tmp_path / "a", fs=FS, channel_names=list(CHANS), eeg=_eeg() if eeg is None else eeg, chunk=CHUNK,
                                      protocol_id="tiny", markers=[], telemetry=[]))
    first = replay_session(base, ir, CHANS, follow_log=False)
    markers = _reward_records(first.events, shift=shift, scale=scale)
    frames = _frames(first, wall_skew=wall_skew)
    if edit:
        markers, frames = edit(markers, frames)
    s = load_session(build_session(tmp_path / "b", fs=FS, channel_names=list(CHANS), eeg=_eeg() if eeg is None else eeg, chunk=CHUNK,
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


def test_a_state_wrong_on_every_frame_fails_the_telemetry_gate(tmp_path):
    def flip(markers, frames):
        return markers, [(p, dict(f, muted=not f["muted"])) for p, f in frames]
    s, r = _case(tmp_path, edit=flip)
    rec = reconcile(s, r, CHUNK)
    assert rec.telemetry_agree < 0.98 and rec.reconciled is False
    assert any(n.startswith("FAILED telemetry") for n in rec.notes)


def test_one_state_wrong_on_a_few_frames_is_not_diluted_by_the_other_states(tmp_path):
    def flip_some(markers, frames):      # muted wrong on 10 % of frames; two other states are right
        return markers, [(p, dict(f, muted=not f["muted"]) if i % 10 == 0 else f) for i, (p, f) in enumerate(frames)]
    s, r = _case(tmp_path, edit=flip_some)
    rec = reconcile(s, r, CHUNK)
    assert rec.telemetry_agree == pytest.approx(0.9) and rec.reconciled is False
    assert any("muted 45/50" in n for n in rec.notes)


def test_inhibits_are_compared_and_a_flipped_one_is_counted(tmp_path):
    s, r = _case(tmp_path)
    assert all("fast" in f["inhibits"] for f in s.telemetry)
    assert reconcile(s, r, CHUNK).telemetry_agree == 1.0
    for f in s.telemetry:
        f["inhibits"]["fast"] = not f["inhibits"]["fast"]
    rec = reconcile(s, r, CHUNK)
    assert rec.telemetry_agree == 0.0 and rec.reconciled is False
    assert any("inhibit/fast 0/" in n for n in rec.notes)
    assert not any("no matching tap" in n for n in rec.notes)


def test_a_logged_inhibit_the_replay_lacks_counts_as_disagreement(tmp_path):
    s, r = _case(tmp_path)
    for f in s.telemetry:
        f["inhibits"]["ghost"] = False
    rec = reconcile(s, r, CHUNK)
    assert rec.telemetry_agree == 0.0 and any("no matching tap" in n for n in rec.notes)


def test_output_values_clearly_inside_and_outside_one_percent(tmp_path):
    for sub in ("in", "out"):
        (tmp_path / sub).mkdir()
    inside = reconcile(*_case(tmp_path / "in", scale=1.005), CHUNK)
    outside = reconcile(*_case(tmp_path / "out", scale=1.02), CHUNK)
    # zero-valued samples agree at any scale, so only the non-zero ones tell the cases apart
    assert inside.outputs_within_1pct == 1.0 and inside.reconciled is True
    assert outside.outputs_within_1pct < 0.99 and outside.reconciled is False
    assert any(n.startswith("FAILED output values") for n in outside.notes)


def test_a_logged_value_against_a_replayed_zero_is_a_disagreement(tmp_path):
    s, r = _case(tmp_path)
    zeroed = [e for e in r.events if e["kind"] == "value" and e["value"] != 0.0]
    assert zeroed
    for e in zeroed:
        e["value"] = 0.0
    rec = reconcile(s, r, CHUNK)
    assert rec.outputs_within_1pct < 0.99 and rec.reconciled is False


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
    assert any("larger of 0 logged and 2 replayed" in n for n in rec.notes)


def test_replay_mismatches_and_unreplayed_chunks_reach_the_notes(tmp_path):
    s, r = _case(tmp_path)
    r.mismatches.append("log enters phase 9 but the replay is in phase 0")
    r.chunks_unreplayed = 7
    notes = " ".join(reconcile(s, r, CHUNK).notes)
    assert "phase 9" in notes and "7 chunk(s) were never replayed" in notes


def _stopped_early(r, keep_chunks):
    """The replay of ``r`` as if the phase plan had ended after ``keep_chunks`` chunks."""
    end = r.chunk_sample_offsets[keep_chunks]
    r.events[:] = [e for e in r.events if e["t_sample"] < end]
    r.chunks_unreplayed = len(r.chunk_sample_offsets) - keep_chunks
    del r.chunk_sample_offsets[keep_chunks:]
    del r.taps_per_chunk[keep_chunks:]


def test_an_incomplete_replay_fails_on_coverage_not_on_agreement(tmp_path):
    s, r = _case(tmp_path)
    _stopped_early(r, 200)                      # 800 of 1000 samples
    rec = reconcile(s, r, CHUNK)
    assert rec.coverage == pytest.approx(0.8)
    assert (rec.events_matched, rec.outputs_within_1pct, rec.telemetry_agree) == (1.0, 1.0, 1.0)
    assert rec.reconciled is False
    assert any(n.startswith("FAILED coverage") and "80.0000%" in n for n in rec.notes)
    assert any("past the end of the replay and were not compared" in n for n in rec.notes)


def test_a_tiny_covered_prefix_cannot_reconcile(tmp_path):
    s, r = _case(tmp_path)
    _stopped_early(r, 25)                       # a tenth of the recording, all of it agreeing
    rec = reconcile(s, r, CHUNK)
    assert rec.coverage == pytest.approx(0.1) and rec.reconciled is False


def test_a_complete_replay_reports_full_coverage(tmp_path):
    s, r = _case(tmp_path)
    rec = reconcile(s, r, CHUNK)
    assert rec.coverage == 1.0 and not any("coverage" in n for n in rec.notes)


def test_a_replay_a_few_chunks_short_still_reconciles_and_says_so(tmp_path):
    s, r = _case(tmp_path)
    _stopped_early(r, 248)                      # 8 of 1000 samples (0.08 s) short
    rec = reconcile(s, r, CHUNK)
    assert rec.coverage == pytest.approx(0.992) and rec.reconciled is True
    note = next(n for n in rec.notes if n.startswith("coverage:"))
    assert "8 sample(s) (0.080 s) short" in note and "99.2000%" in note and "1 s margin" in note
    assert not any(n.startswith("FAILED coverage") for n in rec.notes)


def test_a_replay_beyond_the_margin_names_the_gap_precisely(tmp_path):
    s, r = _case(tmp_path)
    _stopped_early(r, 200)                      # 2 s short
    rec = reconcile(s, r, CHUNK)
    note = next(n for n in rec.notes if n.startswith("FAILED coverage"))
    assert "200 sample(s) (2.000 s) short" in note and "beyond the 1 s margin" in note and rec.reconciled is False


def test_reward_records_past_the_last_sample_are_always_noted(tmp_path):
    def late(markers, frames):
        extra = {"type": "reward_event", "channel": "level", "kind": "value", "value": 0.5, "t_s": N / FS + 5}
        return markers + [(N + 500, extra)], frames
    s, r = _case(tmp_path, edit=late)
    rec = reconcile(s, r, CHUNK)
    assert rec.coverage == 1.0 and rec.reconciled is True
    assert any(n.startswith("1 logged reward record(s) lie past the end") for n in rec.notes)


def _edge_eeg(*, pre=True, post=True):
    """High-frequency bursts (which toggle the inhibit) before the first ding and after the last."""
    i = np.arange(N)
    burst = ((i // 40) % 2 == 1) & (((i < 300) & pre) | ((i >= 640) & post))
    on = (i >= 400) & (i < 500)
    return np.column_stack([np.zeros(N), 5 * np.sin(2 * np.pi * 30 * i / FS) * burst + 1.5 * on])


def _quiet_edges(first=400, last=500):
    """A log with no reward records before ``first`` or after ``last``, as when output is muted there."""
    return lambda m, f: ([x for x in m if first <= x[0] <= last], f)


def test_frames_before_the_first_ding_are_placed_by_their_own_clock_not_the_first_dings(tmp_path):
    eeg = _edge_eeg(post=False)
    s, r = _case(tmp_path, eeg=eeg, edit=_quiet_edges(last=N))
    pre = [f for f in s.telemetry if f["t_s"] < 3.0]
    assert len({(f["muted"], f["inhibits"]["fast"]) for f in pre}) > 1       # the states really change there
    rec = reconcile(s, r, CHUNK)
    # collapsing every pre-ding frame onto the first ding's time scored this 0.96 and failed the gate
    # The fixture deletes reward records the replay still produces, so the output check now
    # (correctly) objects to values nobody logged; this test is about where frames are placed.
    assert rec.telemetry_agree == 1.0 and not any(n.startswith("FAILED telemetry") for n in rec.notes)
    assert any("before the first or after the last reward_event" in n for n in rec.notes)


def test_frames_after_the_last_ding_are_placed_the_same_way(tmp_path):
    eeg = _edge_eeg(pre=False)
    s, r = _case(tmp_path, eeg=eeg, edit=_quiet_edges(first=0))
    post = [f for f in s.telemetry if f["t_s"] >= 6.4]
    assert len({(f["muted"], f["inhibits"]["fast"]) for f in post}) > 1
    rec = reconcile(s, r, CHUNK)
    # as above: the deleted records are values the replay still produces, so only telemetry is asserted
    assert rec.telemetry_agree == 1.0 and not any(n.startswith("FAILED telemetry") for n in rec.notes)


def test_edge_frames_still_agree_when_the_wall_clock_is_offset(tmp_path):
    # wall clock 0.3 s ahead of refrain at the first ding: the correction uses that measured offset
    eeg = _edge_eeg(post=False)
    s, r = _case(tmp_path, eeg=eeg, wall_skew=0.0, edit=_quiet_edges(last=N))
    for f in s.telemetry:
        f["t_s"] += 0.3
    assert reconcile(s, r, CHUNK).telemetry_agree == 1.0


# --- final review: how much the matching forgave, and values the log never recorded ---

def _plant_shift(tmp_path, shift):
    return reconcile(*_case(tmp_path, shift=shift), CHUNK)


def test_offsets_of_matched_dings_are_reported(tmp_path):
    rec = _plant_shift(tmp_path, 3)
    note = next(n for n in rec.notes if n.startswith("dings matched at offset"))
    assert "median 3 sample(s) (30 ms)" in note and "maximum 3 sample(s) (30 ms)" in note
    (tmp_path / "z").mkdir()
    rec0 = _plant_shift(tmp_path / "z", 0)
    assert "median 0 sample(s) (0 ms)" in next(n for n in rec0.notes if n.startswith("dings matched at offset"))


def test_offsets_of_matched_output_values_are_reported(tmp_path):
    rec = _plant_shift(tmp_path, 2)
    note = next(n for n in rec.notes if n.startswith("output values matched at offset"))
    assert "median 2 sample(s) (20 ms)" in note and "maximum 2 sample(s) (20 ms)" in note


def test_an_event_is_matched_within_its_own_chunk_not_the_longest_chunk(tmp_path):
    # chunks are 4 samples long; a cap of 32 (the longest chunk in some other part of the
    # recording) must not forgive a 20-sample shift
    s, r = _case(tmp_path, shift=20)
    loose = reconcile(s, r, 32)
    assert loose.events_matched < 0.99 and loose.reconciled is False
    assert any("its own containing chunk" in n for n in loose.notes)


def test_a_shift_inside_the_chunk_still_matches_under_a_large_cap(tmp_path):
    rec = reconcile(*_case(tmp_path, shift=3), 32)
    assert rec.events_matched == 1.0


def test_a_replay_channel_the_log_never_recorded_scores_below_one(tmp_path):
    # the protocol file gained a feedback channel after the session ran
    s, _ = _case(tmp_path)
    grown = tmp_path / "grown.refrain"
    grown.write_text(PROTOCOL.replace("chime = reward.event }", 'chime = reward.event\n    extra = "scaled" }'))
    r = replay_session(s, resolve(refrain.parse_file(str(grown)), None), CHANS, follow_log=False)
    assert any(e["channel"] == "extra" for e in r.events)
    rec = reconcile(s, r, CHUNK)
    assert rec.outputs_within_1pct < 0.99
    assert any("extra" in n and "no logged counterpart" in n for n in rec.notes)


def test_extra_replay_values_on_a_logged_channel_score_below_one(tmp_path):
    def thin(markers, frames):
        vals = [i for i, (_, m) in enumerate(markers) if m["kind"] == "value"]
        drop = set(vals[::2])
        return [x for i, x in enumerate(markers) if i not in drop], frames
    s, r = _case(tmp_path, edit=thin)
    rec = reconcile(s, r, CHUNK)
    assert rec.outputs_within_1pct < 0.99
    assert any("replay" in n and "no logged counterpart" in n for n in rec.notes)
