# Copyright 2026 Refrain Protocols Authors.
"""The offline truth model: when did the behaviour a protocol rewards actually happen?

Each test plants a known stretch of the target behaviour in synthetic EEG, replays
it through the protocol itself, and checks that the truth model finds that stretch
back -- at the time it was planted, not at the time the protocol's own laggy
envelope noticed it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("scipy")
refrain = pytest.importorskip("refrain")
from refrain.ir_json import ir_to_json_obj  # noqa: E402
from refrain.resolver import resolve  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from session_fixture import build_session  # noqa: E402
from session_report.replay import replay_session  # noqa: E402
from session_report.session import load_session  # noqa: E402
from session_report.truth import true_episodes, truth_streams  # noqa: E402

FS = 250.0
SECONDS = 30.0
N = int(SECONDS * FS)
CHUNK = 50
CHANS = ("A1", "C3", "C4", "Pz")
T = np.arange(N) / FS
# the stretch of the recording the zero-phase filters can be trusted on
WINDOW = (2500, 6000)

HEADER = '''
  meta { version = "1.0.0" evidence = "exploratory" description = "t" title = "t" summary = "t"
         family = "t" status = "draft" modality = "eeg" }
  requires { coupling = "ac" sample_rate = ">= 250 Hz" impedance = "not_required" markers = "not_required" }
  input "raw" { montage = referential(active: "Pz", reference: "A1") }
'''
PLAN = '  session { phases = [ phase { name = "work"; duration = 2 min; mode = timed_with_floor } ] }\n}\n'
SMR_ENVELOPE = '''
  derive "smr_envelope" { from = "raw"
    pipeline = [ bandpass(band: (12 Hz, 15 Hz), order: 4), hilbert(), magnitude(), smooth(tau: 250 ms) ] }
'''

BURSTS = 'protocol "truth_smr" {' + HEADER + SMR_ENVELOPE + '''
  threshold "smr_t" { signal = "smr_envelope" type = absolute(5 uV) }
  reward { event = dwell(condition: above("smr_envelope", "smr_t"), duration: 250 ms) }
  output { audio_chime = reward.event }
''' + PLAN

LONG_DWELL = BURSTS.replace("duration: 250 ms", "duration: 60 s")
assert LONG_DWELL != BURSTS

RATIO = 'protocol "truth_ratio" {' + HEADER + '''
  derive "theta_envelope" { from = "raw"
    pipeline = [ bandpass(band: (6 Hz, 8 Hz), order: 4), hilbert(), magnitude(), smooth(tau: 500 ms) ] }
  derive "alpha_envelope" { from = "raw"
    pipeline = [ bandpass(band: (9 Hz, 11 Hz), order: 4), hilbert(), magnitude(), smooth(tau: 500 ms) ] }
  derive "theta_alpha_ratio" { formula = "theta_envelope" / "alpha_envelope" }
  reward { event = dwell(condition: above("theta_alpha_ratio", 1.0), duration: 1000 ms) }
  output { audio_chime = reward.event }
''' + PLAN

SLOWING = '''
  derive "band" { from = "raw"
    pipeline = [ bandpass(band: (9 Hz, 11 Hz), order: 4), hilbert(), magnitude(), smooth(tau: 250 ms) ] }
  derive "slowing" { from = "band"; pipeline = [ autocorr(lag: 100 ms, window: 4 s) ] }
'''
REWARDS_SLOWING = 'protocol "truth_auto_in" {' + HEADER + SLOWING + '''
  reward { event = dwell(condition: above("slowing", 0.5), duration: 250 ms) }
  output { audio_chime = reward.event }
''' + PLAN
IGNORES_SLOWING = 'protocol "truth_auto_out" {' + HEADER + SLOWING + '''
  reward { event = dwell(condition: above("band", 5 uV), duration: 250 ms) }
  output { audio_chime = reward.event }
''' + PLAN

CONTROL = 'protocol "truth_control" {' + HEADER + SMR_ENVELOPE + '''
  reward { event = dwell(condition: above("smr_envelope", smr_level_uv), duration: 250 ms) }
  output { audio_chime = reward.event }
  controls { smr_level_uv = voltage { default = 10 uV  range = (1 uV, 50 uV)
                                      label = "Reward level"  live_tunable = true } }
''' + PLAN

BANDED = 'protocol "truth_banded" {' + HEADER + SMR_ENVELOPE + '''
  reward { event = dwell(condition: any_of([
             inside("smr_envelope", low: 4 uV, high: 8 uV),
             all_of([ at_or_above("smr_envelope", 20 uV), below("smr_envelope", 40 uV) ]),
           ]), duration: 250 ms) }
  output { audio_chime = reward.event }
''' + PLAN

COHERENCE = 'protocol "truth_coh" {' + '''
  meta { version = "1.0.0" evidence = "exploratory" description = "t" title = "t" summary = "t"
         family = "t" status = "draft" modality = "eeg" }
  requires { coupling = "ac" sample_rate = ">= 250 Hz" impedance = "not_required" markers = "not_required" }
  input "a" { montage = referential(active: "C3", reference: "A1") }
  input "b" { montage = referential(active: "C4", reference: "A1") }
  derive "alpha_coh" { formula = coherence("a", "b", band: (8 Hz, 12 Hz), window: 2 s) }
  reward { event = dwell(condition: above("alpha_coh", 0.6), duration: 250 ms) }
  output { audio_chime = reward.event }
''' + PLAN


def _noise(seed: int, n: int = N, scale: float = 1.0) -> np.ndarray:
    return scale * np.random.default_rng(seed).standard_normal(n)


def _replay(tmp_path: Path, text: str, channels: dict[str, np.ndarray], markers=()):
    """Resolve ``text``, write a session carrying ``channels``, replay it, return (ir_json, replay)."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "p.refrain"
    path.write_text(text)
    ir = resolve(refrain.parse_file(str(path)), None)
    eeg = np.column_stack([channels.get(c, np.zeros(N)) for c in CHANS])
    folder = build_session(tmp_path / "s", fs=FS, channel_names=list(CHANS), eeg=eeg, chunk=CHUNK,
                           protocol_id="x", markers=list(markers), telemetry=[])
    session = load_session(folder)
    return ir_to_json_obj(ir), replay_session(session, ir, CHANS, follow_log=True)


def _seconds(episodes):
    return [(a / FS, b / FS) for a, b in episodes]


def test_planted_bursts_are_found_as_episodes(tmp_path):
    onsets = [12.0, 16.0, 20.0]
    pz = _noise(3)
    for onset in onsets:
        burst = (T >= onset) & (T < onset + 0.6)
        pz[burst] += 10.0 * np.sin(2 * np.pi * 13.5 * T[burst])

    ir_json, replay = _replay(tmp_path, BURSTS, {"Pz": pz})
    truth, unreproducible = truth_streams(ir_json, replay)
    assert unreproducible == [] and set(truth) == {"smr_envelope"}
    assert len(truth["smr_envelope"]) == N

    res = true_episodes(ir_json, truth, replay, FS)
    assert res.judged is True and res.unreproducible == []
    assert res.window == WINDOW
    # the edge guard is stated in the result, so a report can say what it covered
    guard = [n for n in res.notes if "zero-phase" in n]
    assert len(guard) == 1 and f"samples {WINDOW[0]} to {WINDOW[1]} of {N}" in guard[0]
    assert len(res.episodes) == 3, _seconds(res.episodes)
    for (start, end), onset in zip(res.episodes, onsets):
        assert abs(start / FS - onset) <= 0.060, _seconds(res.episodes)
        assert 0.5 <= (end - start) / FS <= 0.7                  # the planted 0.6 s burst
    assert all(WINDOW[0] <= a and b <= WINDOW[1] for a, b in res.episodes)


def test_ratio_condition_episodes(tmp_path):
    pz = _noise(5) + 10.0 * np.sin(2 * np.pi * 10.0 * T)
    crossover = (T >= 14.0) & (T < 18.0)                         # theta well above alpha
    pz[crossover] = (_noise(6)[crossover] + 20.0 * np.sin(2 * np.pi * 7.0 * T[crossover])
                     + 2.0 * np.sin(2 * np.pi * 10.0 * T[crossover]))

    ir_json, replay = _replay(tmp_path, RATIO, {"Pz": pz})
    truth, unreproducible = truth_streams(ir_json, replay)
    assert unreproducible == []
    assert set(truth) == {"theta_envelope", "alpha_envelope", "theta_alpha_ratio"}
    # the ratio derive is the arithmetic of the two truth envelopes, not a filter of its own
    assert truth["theta_alpha_ratio"] == pytest.approx(truth["theta_envelope"] / truth["alpha_envelope"])

    res = true_episodes(ir_json, truth, replay, FS)
    assert res.judged is True
    assert len(res.episodes) == 1, _seconds(res.episodes)
    start, end = res.episodes[0]
    assert abs(start / FS - 14.0) <= 0.15 and abs(end / FS - 18.0) <= 0.15, _seconds(res.episodes)


def test_unreproducible_derive_is_named_not_judged(tmp_path):
    pz = _noise(7) + 10.0 * np.sin(2 * np.pi * 10.0 * T)

    ir_json, replay = _replay(tmp_path / "in", REWARDS_SLOWING, {"Pz": pz})
    truth, unreproducible = truth_streams(ir_json, replay)
    assert unreproducible == ["slowing"] and set(truth) == {"band"}
    res = true_episodes(ir_json, truth, replay, FS)
    assert res.judged is False and res.unreproducible == ["slowing"]
    assert res.episodes == []
    assert any("slowing" in n for n in res.notes)

    # the same unreproducible derive, but nothing in the reward condition reads it:
    # the protocol is still judged, and the derive is still named.
    ir_json, replay = _replay(tmp_path / "out", IGNORES_SLOWING, {"Pz": pz})
    truth, unreproducible = truth_streams(ir_json, replay)
    assert unreproducible == ["slowing"]
    res = true_episodes(ir_json, truth, replay, FS)
    assert res.judged is True and res.unreproducible == ["slowing"]
    assert res.episodes == [WINDOW]                              # alpha is above 5 uV throughout


def test_a_control_operand_follows_its_mid_session_change(tmp_path):
    # A steady 6 uV SMR carrier. The clinician lowers the reward level from 10 uV to
    # 3 uV at 16 s, so the behaviour only counts as on target from then on.
    pz = _noise(9) + 6.0 * np.sin(2 * np.pi * 13.5 * T)
    lowered = {"type": "control_change", "name": "smr_level_uv", "value": 3.0, "engine_value": 3.0,
               "source": "clinician", "t_s": 16.0}

    ir_json, replay = _replay(tmp_path, CONTROL, {"Pz": pz}, markers=[(4000, lowered)])
    assert replay.control_timeline["smr_level_uv"] == [(0, 10.0), (80, 3.0)]
    truth, _ = truth_streams(ir_json, replay)
    res = true_episodes(ir_json, truth, replay, FS)
    assert res.judged is True
    # one episode, from the change to the end of the trusted window. A truth model that
    # froze the control at its 10 uV default would find none; one that froze it at the
    # final 3 uV would reward the whole window.
    assert res.episodes == [(4000, WINDOW[1])], _seconds(res.episodes)


def test_a_banded_condition_rewards_only_the_plateaus_it_describes(tmp_path):
    # Reward a moderate 12-15 Hz envelope, or a strong one that is not artefact-sized.
    plateaus = [(11.0, 13.5, 6.0), (14.5, 17.0, 60.0), (18.0, 20.5, 30.0)]
    pz = _noise(17, scale=0.3)
    for start, end, amplitude in plateaus:
        on = (T >= start) & (T < end)
        pz[on] += amplitude * np.sin(2 * np.pi * 13.5 * T[on])

    ir_json, replay = _replay(tmp_path, BANDED, {"Pz": pz})
    truth, _ = truth_streams(ir_json, replay)
    res = true_episodes(ir_json, truth, replay, FS)
    assert res.judged is True
    # the 6 uV plateau is inside the window; the 60 uV one is above 20 but not below 40
    assert len(res.episodes) == 2, _seconds(res.episodes)
    (first, second), spans = res.episodes, _seconds(res.episodes)
    assert abs(first[0] / FS - 11.0) <= 0.2 and abs(first[1] / FS - 13.5) <= 0.2, spans
    assert abs(second[0] / FS - 18.0) <= 0.2 and abs(second[1] / FS - 20.5) <= 0.2, spans


def test_coherence_truth_tracks_a_coherent_stretch(tmp_path):
    # Both sites carry the same 10 Hz rhythm from 13 s to 19 s; outside it, C4's
    # alpha is its own independent noise, so the two sites share no phase.
    shared = 10.0 * np.sin(2 * np.pi * 10.0 * T)
    together = (T >= 13.0) & (T < 19.0)
    c3 = _noise(11) + shared
    c4 = _noise(12) + np.where(together, shared, _noise(13, scale=10.0))

    ir_json, replay = _replay(tmp_path, COHERENCE, {"C3": c3, "C4": c4})
    truth, unreproducible = truth_streams(ir_json, replay)
    assert unreproducible == [] and set(truth) == {"alpha_coh"}
    coh = truth["alpha_coh"]
    assert np.median(coh[int(13.5 * FS):int(18.5 * FS)]) > 0.8
    assert np.median(coh[WINDOW[0]:int(12.5 * FS)]) < 0.5

    res = true_episodes(ir_json, truth, replay, FS)
    assert res.judged is True
    assert len(res.episodes) == 1, _seconds(res.episodes)
    start, end = res.episodes[0]
    assert 12.5 <= start / FS <= 13.5 and 18.5 <= end / FS <= 19.5, _seconds(res.episodes)


def test_a_truth_stream_shorter_than_the_replay_is_refused_not_misaligned(tmp_path):
    pz = _noise(19) + 10.0 * np.sin(2 * np.pi * 13.5 * T)
    ir_json, replay = _replay(tmp_path, BURSTS, {"Pz": pz})
    truth, _ = truth_streams(ir_json, replay)
    truth["smr_envelope"] = truth["smr_envelope"][:N - 100]

    res = true_episodes(ir_json, truth, replay, FS)
    assert res.judged is False and res.episodes == []
    assert any("smr_envelope" in n and str(N) in n for n in res.notes)


def test_a_dwell_longer_than_the_trusted_window_yields_no_episodes(tmp_path):
    # The carrier is above threshold from end to end, so only the dwell can rule it out.
    pz = _noise(15) + 10.0 * np.sin(2 * np.pi * 13.5 * T)
    ir_json, replay = _replay(tmp_path / "long", LONG_DWELL, {"Pz": pz})
    truth, _ = truth_streams(ir_json, replay)
    res = true_episodes(ir_json, truth, replay, FS)
    assert res.judged is True and res.episodes == []

    # the same EEG under the 250 ms dwell: one episode, the whole trusted window
    ir_json, replay = _replay(tmp_path / "short", BURSTS, {"Pz": pz})
    truth, _ = truth_streams(ir_json, replay)
    assert true_episodes(ir_json, truth, replay, FS).episodes == [WINDOW]
