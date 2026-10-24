"""Replaying a recorded session through refrain, following its own log."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("scipy")
refrain = pytest.importorskip("refrain")
from refrain.eval_ import Evaluator  # noqa: E402
from refrain.resolver import resolve  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from session_fixture import build_session  # noqa: E402
from session_report.replay import ReplayResult, replay_session, step_through  # noqa: E402
from session_report.session import load_session  # noqa: E402

FS = 100.0
CHUNK = 4
CHANS = ("A1", "Pz")

PROTOCOL = '''
protocol "tiny" {
  meta { version = "1.0.0" evidence = "exploratory" description = "t" title = "t" summary = "t"
         family = "t" status = "draft" modality = "eeg" }
  requires { coupling = "ac" sample_rate = ">= 100 Hz" impedance = "not_required" markers = "not_required" }
  input "raw" { montage = referential(active: "Pz", reference: "A1") }
  derive "scaled" { formula = "raw" * gain }
  reward { event = dwell(condition: above("scaled", 1000 uV), duration: 1000 ms) }
  output { level = "scaled" }
  controls {
    gain = number { default = 1.0  range = (0.0, 100.0)  label = "Gain"  live_tunable = true }
  }
  session {
    phases = [
      phase { name = "settle"; duration = 1 s; output_muted = true; mode = timed_with_floor },
      phase { name = "work"; duration = 1 min; mode = timed_with_floor },
    ]
  }
}
'''


def _ir(tmp_path):
    path = tmp_path / "tiny.refrain"
    path.write_text(PROTOCOL)
    return resolve(refrain.parse_file(str(path)), None)


def _session(tmp_path, markers, *, n=400):
    eeg = np.column_stack([np.zeros(n), np.ones(n)])            # Pz - A1 == 1
    folder = build_session(tmp_path / "s", fs=FS, channel_names=list(CHANS), eeg=eeg, chunk=CHUNK,
                           protocol_id="tiny", markers=markers, telemetry=[])
    return load_session(folder)


def _change(t_s, name="gain", value=3.0, engine=3.0, previous=None, source="clinician"):
    rec = {"type": "control_change", "name": name, "value": value, "source": source, "t_s": t_s}
    if engine is not None:
        rec["engine_value"] = engine
    if previous is not None:
        rec["previous_value"] = previous
    return rec


def _gain(result):
    return [t["derive/scaled"] for t in result.taps_per_chunk]


def _replay(tmp_path, markers, *, follow_log=True, n=400, mutate=None):
    s = _session(tmp_path, markers, n=n)
    if mutate:
        mutate(s)
    return replay_session(s, _ir(tmp_path), CHANS, follow_log=follow_log)


def test_control_change_applies_before_the_next_chunk(tmp_path):
    r = _replay(tmp_path, [(40, _change(0.4, engine=3.0))])    # after chunk 9 (samples 36..39)
    g = _gain(r)
    assert g[9] == 1.0 and g[10] == 3.0 and g[-1] == 3.0
    assert [(a["name"], a["value"], a["status"]) for a in r.applied] == [("gain", 3.0, "applied")]
    assert r.control_timeline["gain"] == [(0, 1.0), (10, 3.0)]
    assert r.chunk_sample_offsets[:3] == [0, 4, 8] and len(r.chunk_sample_offsets) == 100


def test_warmup_seed_is_compared_not_applied(tmp_path, monkeypatch):
    calls = []
    real = Evaluator.set_control
    monkeypatch.setattr(Evaluator, "set_control", lambda self, n, v: (calls.append((n, v)), real(self, n, v))[1])
    seed = _change(0.4, engine=None, previous=10.0, source="warmup_seed", value=5.0)
    r = _replay(tmp_path, [(40, seed)])
    assert calls == []
    assert [a["status"] for a in r.applied] == ["compared"] and r.applied[0]["name"] == "gain"
    assert set(_gain(r)) == {1.0}
    assert r.control_timeline["gain"] == [(0, 1.0)]       # a seed is never a starting value either


def test_starting_value_comes_from_the_first_logged_previous_value(tmp_path):
    # value 2 <-> engine 20 is a x10 scale, so previous_value 3 means the session began at 30
    first = _change(0.4, value=2.0, engine=20.0, previous=3.0)
    later = _change(2.0, value=4.0, engine=40.0, previous=2.0)
    r = _replay(tmp_path, [(40, first), (200, later)])
    g = _gain(r)
    assert g[0] == 30.0 and g[9] == 30.0 and g[10] == 20.0
    assert r.control_timeline["gain"][0] == (0, 30.0)
    assert r.applied[0]["status"] == "initial" and r.applied[0]["value"] == 30.0


def test_no_starting_override_when_previous_equals_the_default(tmp_path):
    r = _replay(tmp_path, [(40, _change(0.4, value=3.0, engine=3.0, previous=1.0))])
    assert [a["status"] for a in r.applied] == ["applied"]
    assert r.control_timeline["gain"][0] == (0, 1.0)


def test_logged_phase_change_is_followed(tmp_path):
    phase = {"type": "phase_change", "phase_index": 1, "phase_name": "work", "t_s": 2.0}
    followed = _replay(tmp_path, [(200, phase)])                # after chunk 49
    idx = [t["phase/index"] for t in followed.taps_per_chunk]
    assert idx[49] == 0 and idx[50] == 1                        # held past its 1 s floor until the log advanced
    alone = _replay(tmp_path, [(200, phase)], follow_log=False)
    idx = [t["phase/index"] for t in alone.taps_per_chunk]
    assert idx[24] == 0 and idx[26] == 1                        # the comparison replay runs its own clock


def test_logged_phase_change_ahead_of_the_replay_advances_it(tmp_path):
    phase = {"type": "phase_change", "phase_index": 1, "phase_name": "work", "t_s": 0.2}
    r = _replay(tmp_path, [(20, phase)])                        # after chunk 4
    idx = [t["phase/index"] for t in r.taps_per_chunk]
    assert idx[4] == 0 and idx[5] == 1


def test_compare_skips_unknown_controls(tmp_path):
    recs = [(40, _change(0.4, name="not_in_this_protocol", engine=5.0)), (80, _change(0.8, engine=3.0))]
    r = _replay(tmp_path, recs, follow_log=False)
    assert [s["name"] for s in r.skipped] == ["not_in_this_protocol"]
    assert [a["name"] for a in r.applied] == ["gain"]
    assert _gain(r)[-1] == 3.0


def test_applied_advice_sets_its_control_and_other_advice_does_not(tmp_path):
    ok = {"type": "advice_event", "kind": "applied", "control": "gain", "engine_value": 7.0, "t_s": 0.4}
    other = {"type": "advice_event", "kind": "suggested", "control": "gain", "engine_value": 9.0, "t_s": 0.8}
    r = _replay(tmp_path, [(40, ok), (80, other)])
    assert _gain(r)[-1] == 7.0


def test_pause_and_resume_freeze_the_phase_clock(tmp_path, monkeypatch):
    calls = []
    real = Evaluator.set_clock_frozen
    monkeypatch.setattr(Evaluator, "set_clock_frozen", lambda self, f: (calls.append(f), real(self, f))[1])
    pause = {"type": "session_state", "action": "pause", "t_s": 0.2}
    resume = {"type": "session_state", "action": "resume", "t_s": 3.0}
    _replay(tmp_path, [(20, pause), (300, resume)])
    assert calls == [True, False]


def _spy_resets(monkeypatch):
    calls = []
    real = Evaluator.reset_held_outputs
    monkeypatch.setattr(Evaluator, "reset_held_outputs", lambda self: (calls.append(1), real(self))[1])
    return calls


def test_layered_texture_resets_held_outputs_after_each_control_change(tmp_path, monkeypatch):
    calls = _spy_resets(monkeypatch)
    _replay(tmp_path, [(40, _change(0.4))], mutate=lambda s: s.meta.update(audio={"feedback_style": "layered_texture"}))
    assert len(calls) == 1
    calls.clear()
    _replay(tmp_path / "plain", [(40, _change(0.4))])
    assert calls == []


def test_a_gap_between_chunks_resets_held_outputs(tmp_path, monkeypatch):
    calls = _spy_resets(monkeypatch)

    def gap(s):
        s.chunk_starts = [i * CHUNK / FS + (2.0 if i >= 10 else 0.0) for i in range(len(s.chunks))]

    _replay(tmp_path, [], mutate=gap)
    assert len(calls) == 1


def test_step_through_keeps_only_the_requested_streams(tmp_path):
    ir = _ir(tmp_path)
    X = np.column_stack([np.zeros(40), np.ones(40)])
    chunks = [X[i:i + CHUNK] for i in range(0, 40, CHUNK)]
    r = step_through(ir, FS, CHANS, chunks, skip_warmup=True, keep_streams=("scaled",))
    assert isinstance(r, ReplayResult) and list(r.streams) == ["scaled"] and len(r.streams["scaled"]) == 40
    full = step_through(ir, FS, CHANS, chunks, skip_warmup=True)
    assert {"scaled", "raw"} <= set(full.streams)
