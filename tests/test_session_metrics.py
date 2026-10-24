# Copyright 2026 Refrain Protocols Authors.
"""The muscle index and every metric the report prints, against planted answers.

One synthetic session carries every answer in its plant: three 13.5 Hz bursts
over quiet EEG (so the reward has something true to hit), two 80 Hz muscle
bursts (one of them inside a muted phase), a two-second clinician pause and two
seconds of muted audio. Each metric is then checked against the plant or against
a relation that must hold whatever the filters do -- never against a number a
previous run happened to print.
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
from session_report.metrics import session_metrics  # noqa: E402
from session_report.muscle import MUSCLE_FACTOR, muscle_band, muscle_episodes  # noqa: E402
from session_report.replay import replay_session  # noqa: E402
from session_report.session import load_session  # noqa: E402
from session_report.truth import true_episodes, truth_streams  # noqa: E402

FS = 250.0
CHUNK = 5                               # 20 ms, the resolution of a per-chunk tap
SECONDS = 90.0
N = int(SECONDS * FS)
T = np.arange(N) / FS
CHANS = ("A1", "Pz")
SETTLE_S = 20.0                         # phase 0: output muted end to end
DWELL_MS = 250.0
CHUNK_MS = 1000.0 * CHUNK / FS
SAMPLE_MS = 1000.0 / FS
WINDOW = (2500, 21000)                  # what the zero-phase filters can be trusted on
THRESHOLD_UV = 5.0

PAUSE_S, RESUME_S = 25.0, 27.0
AUDIO_MUTED_S = (40.0, 42.0)
SMR_ONSETS = (30.0, 50.0, 70.0)
SMR_LEN_S = 1.5
MUSCLE_ONSETS = (5.0, 60.0)             # 5.0 s is inside the muted settle phase
MUSCLE_LEN_S = 0.4


def _protocol(*, muted_throughout: bool = False) -> str:
    phases = ('phase { name = "settle"; duration = 20 s; output_muted = true }, '
              'phase { name = "work"; duration = 70 s; mode = timed_with_floor }')
    if muted_throughout:
        phases = 'phase { name = "dark"; duration = 90 s; output_muted = true }'
    return 'protocol "metrics_smr" {' + '''
  meta { version = "1.0.0" evidence = "exploratory" description = "t" title = "t" summary = "t"
         family = "t" status = "draft" modality = "eeg" }
  requires { coupling = "ac" sample_rate = ">= 250 Hz" impedance = "not_required" markers = "not_required" }
  input "raw" { montage = referential(active: "Pz", reference: "A1") }
  derive "smr_envelope" { from = "raw"
    pipeline = [ bandpass(band: (12 Hz, 15 Hz), order: 4), hilbert(), magnitude(), smooth(tau: 250 ms) ] }
  threshold "smr_t" { signal = "smr_envelope" type = absolute(5 uV) }
  reward { event = dwell(condition: above("smr_envelope", "smr_t"), duration: 250 ms)
           continuous = sigmoid("smr_envelope" / "smr_t", midpoint: 1.0, steepness: 3) }
  output { audio_chime = reward.event
           audio_gain = reward.event.holds ? reward.continuous : 0 }
''' + f"  session {{ phases = [ {phases} ] }}\n}}\n"


def _eeg_band(t: np.ndarray) -> np.ndarray:
    """Alpha and theta, well clear of the 12-15 Hz reward band."""
    return 10.0 * np.sin(2 * np.pi * 10.0 * t) + 6.0 * np.sin(2 * np.pi * 6.0 * t)


def _hf_floor(t: np.ndarray) -> np.ndarray:
    """A steady 90 Hz floor: the instrument noise every real recording has in the muscle band.

    It is a single tone at an exact number of cycles per 100 ms window, so the
    muscle index's baseline is the same in every window. Broadband noise would do
    the same job on average, but a 100 ms power estimate of white noise exceeds 3x
    its own median about once a minute, which would make these tests coin flips.
    """
    return 2.0 * np.sin(2 * np.pi * 90.0 * t)


def _quiet_eeg(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return _eeg_band(T) + _hf_floor(T) + 0.2 * rng.standard_normal(N)


def _with_bursts(pz: np.ndarray, onsets, length, hz, amplitude) -> np.ndarray:
    out = pz.copy()
    for onset in onsets:
        on = (T >= onset) & (T < onset + length)
        out[on] += amplitude * np.sin(2 * np.pi * hz * T[on])
    return out


def _phase_markers(muted_throughout: bool) -> list[tuple[int, dict]]:
    """Phase records as a recorder writes them: a little after refrain's own clock.

    The log's wall clock runs behind refrain's sample clock (the real session drifts
    ~3 s over 34 minutes), so a logged phase change always arrives after the phase
    actually turned over.
    """
    if muted_throughout:
        return [(0, {"type": "phase_change", "phase_index": 0, "phase_name": "dark", "t_s": 0.0})]
    at = SETTLE_S + 0.1
    return [(0, {"type": "phase_change", "phase_index": 0, "phase_name": "settle", "t_s": 0.0}),
            (int(at * FS), {"type": "phase_change", "phase_index": 1, "phase_name": "work",
                            "t_s": at})]


def _audio_frames() -> list[dict]:
    """10 Hz telemetry that mutes the audio for AUDIO_MUTED_S, as the recorder logs it."""
    out = []
    for k in range(int(SECONDS * 10)):
        t = k / 10.0
        out.append({"type": "telemetry", "t_s": t, "audio_muted": AUDIO_MUTED_S[0] <= t < AUDIO_MUTED_S[1]})
    return out


def _plant(tmp_path: Path, *, smr=(), muscle=(), paused=True, muted_throughout=False,
           text=None, pz=None, phase_markers=None, telemetry=None, audio=None, manifest=None):
    """Build, replay and measure a planted session; return (metrics, extras)."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "p.refrain"
    path.write_text(text if text is not None else _protocol(muted_throughout=muted_throughout))
    ir = resolve(refrain.parse_file(str(path)), None)
    ir_json = ir_to_json_obj(ir)

    pz = _quiet_eeg(31) if pz is None else pz
    pz = _with_bursts(pz, smr, SMR_LEN_S, 13.5, 12.0)
    pz = _with_bursts(pz, muscle, MUSCLE_LEN_S, 80.0, 40.0)
    markers = _phase_markers(muted_throughout) if phase_markers is None else list(phase_markers)
    if paused:
        markers += [(int(PAUSE_S * FS), {"type": "session_state", "action": "pause", "t_s": PAUSE_S}),
                    (int(RESUME_S * FS), {"type": "session_state", "action": "resume", "t_s": RESUME_S})]
    folder = build_session(tmp_path / "s", fs=FS, channel_names=list(CHANS),
                           eeg=np.column_stack([np.zeros(N), pz]), chunk=CHUNK,
                           protocol_id="metrics_smr", markers=markers,
                           telemetry=_audio_frames() if telemetry is None else telemetry,
                           audio=audio, manifest=manifest)
    session = load_session(folder)
    replay = replay_session(session, ir, CHANS, follow_log=True)
    truth, _ = truth_streams(ir_json, replay, session.fs)
    res = true_episodes(ir_json, truth, replay, session.fs)
    eps = muscle_episodes(pz, FS)
    return session_metrics(session, replay, res, eps, session.fs, ir_json=ir_json), (res, eps, replay)


def test_muscle_episodes_found():
    """Planted 80 Hz bursts are found; a signal with only EEG-band content gives none."""
    assert muscle_band(FS) == (70.0, 112.5)                  # min(120, 0.45 * 250)
    assert MUSCLE_FACTOR == 3.0
    assert muscle_episodes(_eeg_band(T), FS) == []            # no muscle-band content at all
    base = _eeg_band(T) + _hf_floor(T)
    assert muscle_episodes(base, FS) == []                    # a steady floor is not an episode

    onsets = (8.0, 15.0, 22.0)
    found = muscle_episodes(_with_bursts(base, onsets, 0.4, 80.0, 40.0), FS)
    spans = [(a / FS, b / FS) for a, b in found]
    assert len(found) == 3, spans
    for (start, end), onset in zip(found, onsets):
        assert abs(start / FS - onset) <= 0.1, spans
        assert 0.3 <= (end - start) / FS <= 0.8, spans

    # 70 Hz is above 0.45 * 150 Hz, so there is no muscle band to measure at all
    assert muscle_band(150.0) is None
    assert muscle_episodes(_eeg_band(T)[:4500], 150.0) == []


def test_metrics_on_planted_session(tmp_path):
    m, (res, eps, replay) = _plant(tmp_path, smr=SMR_ONSETS, muscle=MUSCLE_ONSETS)

    # --- what was looked at ---
    assert m["judged"] is True and tuple(m["window"]) == WINDOW
    assert m["elapsed_s"] == pytest.approx(SECONDS, abs=0.1)
    assert m["window_s"] == pytest.approx((WINDOW[1] - WINDOW[0]) / FS, abs=0.01)

    # --- true episodes: one per planted burst ---
    assert m["episodes"] == 3, [(a / FS, b / FS) for a, b in res.episodes]
    assert m["episodes_per_min"] == pytest.approx(3.0 / (m["window_s"] / 60.0))
    assert m["episode_len_ms"]["median"] == pytest.approx(SMR_LEN_S * 1000.0, abs=250.0)
    assert m["episode_len_ms"]["p90"] >= m["episode_len_ms"]["median"]

    # --- every strong burst got a ding, inside the burst ---
    assert m["rewarded_in_episode"] == 1.0
    assert m["rewarded_by_end_plus_250"] == 1.0
    assert m["reward_onsets"] == 3
    assert m["rewards_per_min"] == pytest.approx(3.0 / (m["elapsed_s"] / 60.0))
    assert m["stray_rewards_per_min"] == 0.0
    curve = m["deadline_curve"]
    assert sorted(curve) == [200, 300, 400, 500, 1000]
    assert [curve[k] for k in sorted(curve)] == sorted(curve[k] for k in sorted(curve))
    assert curve[1000] == 1.0

    # --- latency: the two measures differ by the protocol's own dwell ---
    # The ding fires one dwell after the protocol's condition first holds, so the gap
    # between "ding, from the true onset" and "condition true, from the true onset" is
    # the 250 ms dwell, to within the chunk a tap is read at.
    ding = m["latency_from_episode_ms"]["median"]
    condition = m["latency_from_condition_true_ms"]["median"]
    assert abs((ding - condition) - DWELL_MS) <= CHUNK_MS + SAMPLE_MS, (ding, condition)
    assert m["latency_from_episode_ms"]["p90"] >= ding
    # the filter's own delay: the live envelope cannot cross a threshold it is only
    # 40 % of the way to later than its measured lag against the zero-phase truth
    lag_ms, r = m["derive_lag_r"]["smr_envelope"]
    assert 0.0 <= condition <= lag_ms + CHUNK_MS
    assert lag_ms > 0.0 and r > 0.5
    # the continuous output crosses its midpoint at the same threshold the dwell counts
    # from, so it rises no later than the ding
    assert 0.0 <= m["continuous_rise_ms"]["median"] <= ding

    # --- mutes: three sources planted, one left at zero ---
    assert m["mute_share"]["artifact"] == 0.0                # this protocol declares no inhibit
    assert m["mute_share"]["phase"] == pytest.approx(SETTLE_S / SECONDS, abs=0.01)
    assert m["mute_share"]["pause"] == pytest.approx((RESUME_S - PAUSE_S) / SECONDS, abs=0.01)
    assert m["mute_share"]["audio"] == pytest.approx(
        (AUDIO_MUTED_S[1] - AUDIO_MUTED_S[0]) / SECONDS, abs=0.01)
    muted_s = SETTLE_S + (RESUME_S - PAUSE_S) + (AUDIO_MUTED_S[1] - AUDIO_MUTED_S[0])
    assert m["unmuted_s"] == pytest.approx(SECONDS - muted_s, abs=0.3)
    # the reward can only hold inside three 1.5 s bursts, all of them in unmuted time
    assert 0.0 < m["reward_share_of_unmuted"] <= 3 * (SMR_LEN_S + 0.5) / m["unmuted_s"]
    # every episode is in unmuted time, so none was lost to a mute
    assert m["episodes_lost_to_mute"] == {"artifact": 0, "phase": 0, "pause": 0, "audio": 0, "any": 0}

    # --- muscle: one of the two planted bursts is inside the muted settle phase ---
    assert len(eps) == 2, [(a / FS, b / FS) for a, b in eps]
    assert 0.3 <= m["muscle_time_muted"] <= 0.7
    assert m["muted_without_muscle"] > 0.95          # 0.4 s of muscle in ~24 s of mute

    # --- dings decided against dings heard ---
    assert m["ding_decided_vs_rendered"]["decided"] == 3
    assert m["ding_decided_vs_rendered"]["by_channel"]["audio_chime"]["decided"] == 3
    assert m["ding_decided_vs_rendered"]["logged"] == 0
    assert m["ding_decided_vs_rendered"]["rendered"] == 0

    # --- thresholds: absolute, so flat in every block ---
    blocks = m["thresholds_per_block"]["smr_t"]
    assert [b["block"] for b in blocks] == ["settle", "work"]
    assert all(b["start"] == THRESHOLD_UV and b["end"] == THRESHOLD_UV and b["drift"] == 0.0
               for b in blocks)

    # --- per phase: the settle phase has no unmuted time at all ---
    settle, work = m["per_phase"]
    assert (settle["name"], work["name"]) == ("settle", "work")
    assert settle["mute_share"]["phase"] == 1.0
    assert settle["reward_share_of_unmuted"] is None          # nothing was unmuted in it
    assert settle["rewards_per_min"] == 0.0
    assert work["rewards_per_min"] > 0.0


def test_empty_session_metrics_are_defined(tmp_path):
    """No bursts and no rewards: rates are 0, latencies are None, nothing raises."""
    m, (res, eps, _) = _plant(tmp_path, smr=(), muscle=())

    assert res.judged is True and res.episodes == [] and eps == []
    assert m["judged"] is True and m["episodes"] == 0 and m["reward_onsets"] == 0

    # a rate over a positive elapsed time with no events is a well-defined zero
    assert m["rewards_per_min"] == 0.0
    assert m["episodes_per_min"] == 0.0
    assert m["stray_rewards_per_min"] == 0.0
    assert m["reward_share_of_unmuted"] == 0.0

    # a share or a latency whose own denominator is zero says nothing
    assert m["rewarded_in_episode"] is None
    assert m["rewarded_by_end_plus_250"] is None
    assert m["episode_len_ms"] == {"median": None, "p90": None}
    assert m["latency_from_episode_ms"] == {"median": None, "p90": None}
    assert m["latency_from_condition_true_ms"] == {"median": None, "p90": None}
    assert m["continuous_rise_ms"] == {"median": None}
    assert all(v is None for v in m["deadline_curve"].values())
    assert m["muscle_time_muted"] is None                     # no muscle, so no share of it
    assert m["muted_without_muscle"] == 1.0                   # the settle phase, with no muscle in it
    assert m["episodes_lost_to_mute"]["any"] == 0
    assert m["ding_decided_vs_rendered"] == {"decided": 0, "rendered": 0, "logged": 0, "by_channel": {}}
    assert m["mute_share"]["phase"] == pytest.approx(SETTLE_S / SECONDS, abs=0.01)
    for phase in m["per_phase"]:
        assert phase["rewards_per_min"] == 0.0


REVIEW_META = '''review_version = 1  review_ratio_stream = "theta_alpha_ratio"
         review_target_control = "reward_ratio_target"  review_literal_threshold = 1.0'''
RATIO = 'protocol "metrics_ratio" {' + '''
  meta { version = "1.0.0" evidence = "exploratory" description = "t" title = "t" summary = "t"
         family = "t" status = "draft" modality = "eeg"
         ''' + REVIEW_META + ''' }
  requires { coupling = "ac" sample_rate = ">= 250 Hz" impedance = "not_required" markers = "not_required" }
  input "raw" { montage = referential(active: "Pz", reference: "A1") }
  derive "theta_envelope" { from = "raw"
    pipeline = [ bandpass(band: (6 Hz, 8 Hz), order: 4), hilbert(), magnitude(), smooth(tau: 500 ms) ] }
  derive "alpha_envelope" { from = "raw"
    pipeline = [ bandpass(band: (9 Hz, 11 Hz), order: 4), hilbert(), magnitude(), smooth(tau: 500 ms) ] }
  derive "theta_alpha_ratio" { formula = "theta_envelope" / "alpha_envelope" }
  reward { event = dwell(condition: above("theta_alpha_ratio", reward_ratio_target), duration: 1000 ms)
           continuous = sigmoid("theta_alpha_ratio", midpoint: 1.0, steepness: 4) }
  output { audio_chime = reward.event }
  controls { reward_ratio_target = number { default = 1.0  range = (0.5, 2.0)
                                            label = "Target ratio"  live_tunable = true } }
  session { phases = [ phase { name = "work"; duration = 90 s; mode = timed_with_floor } ] }
}
'''
CROSSOVER_S = (30.0, 60.0)
STATE_FRAMES = (("approach", 600), ("crossover", 200), ("sustained", 100))


def _crossover_eeg() -> np.ndarray:
    """Alpha-dominant EEG, with theta overtaking alpha for CROSSOVER_S."""
    pz = 10.0 * np.sin(2 * np.pi * 10.0 * T) + 3.0 * np.sin(2 * np.pi * 7.0 * T)
    over = (T >= CROSSOVER_S[0]) & (T < CROSSOVER_S[1])
    pz[over] = (20.0 * np.sin(2 * np.pi * 7.0 * T[over]) + 3.0 * np.sin(2 * np.pi * 10.0 * T[over]))
    return pz


def _state_frames() -> list[dict]:
    """Telemetry carrying the layered-texture feedback state, as the recorder logs it."""
    out, k = [], 0
    for state, count in STATE_FRAMES:
        for _ in range(count):
            out.append({"type": "telemetry", "t_s": k / 10.0, "audio_muted": False,
                        "feedback_state": state})
            k += 1
    return out


def test_protocol_views_follow_the_contract_a_protocol_declares(tmp_path):
    """The review ratio and target, and time in each layered-texture feedback state."""
    m, _ = _plant(tmp_path / "meta", text=RATIO, pz=_crossover_eeg(), paused=False,
                  phase_markers=[], telemetry=_state_frames(),
                  audio={"feedback_style": "layered_texture"})

    ratio = m["protocol_views"]["ratio"]
    assert ratio["ratio_stream"] == "theta_alpha_ratio"
    assert ratio["target_control"] == "reward_ratio_target"
    assert ratio["declared_in"] == "the protocol's own meta"
    assert ratio["literal_threshold"] == 1.0
    # theta overtakes alpha for 30 of the 90 s replayed
    assert 0.25 <= ratio["share_above_target"] <= 0.40, ratio["share_above_target"]
    assert [(b["start_s"], b["end_s"]) for b in ratio["buckets"]] == [(0.0, 60.0), (60.0, 90.0)]
    assert all(b["target_median"] == 1.0 for b in ratio["buckets"])
    assert ratio["buckets"][0]["share_above_target"] > 0.4      # the crossover is in this bucket
    # only the live envelope's own decay after the crossover ends reaches the next one
    assert 0.0 < ratio["buckets"][1]["share_above_target"] < 0.1

    state = m["protocol_views"]["feedback_state"]
    assert state["frames"] == dict(sorted(STATE_FRAMES))
    assert state["reported_frames"] == sum(n for _, n in STATE_FRAMES)
    assert state["share"]["approach"] == pytest.approx(600 / 900)

    # the same contract read from the session manifest instead, for a protocol that
    # does not declare it itself
    bare = RATIO.replace(REVIEW_META, "")
    assert "review_ratio_stream" not in bare
    contract = {"version": 1, "ratio_stream": "theta_alpha_ratio",
                "target_control": "reward_ratio_target", "literal_threshold": 1.0}
    m = _plant(tmp_path / "manifest", text=bare, pz=_crossover_eeg(), paused=False,
               phase_markers=[], telemetry=_state_frames(),
               manifest={"review_contract": contract})[0]
    assert m["protocol_views"]["ratio"]["declared_in"] == "the session manifest's review contract"
    assert "feedback_state" not in m["protocol_views"]          # this session declares no texture


def test_a_session_muted_end_to_end_rewards_nobody(tmp_path):
    """Every sample muted: no share of unmuted time exists, and every episode is lost."""
    m, (res, _, _) = _plant(tmp_path, smr=SMR_ONSETS, muted_throughout=True, paused=False)

    assert m["mute_share"]["phase"] == 1.0 and m["unmuted_s"] == 0.0
    assert m["reward_share_of_unmuted"] is None                 # no unmuted time to take a share of
    assert m["episodes"] == 3 and m["rewarded_in_episode"] == 1.0
    # the protocol still decided every reward; the trainee could not hear any of them
    assert m["episodes_lost_to_mute"] == {"artifact": 0, "phase": 3, "pause": 0, "audio": 0, "any": 3}
    assert m["per_phase"][0]["reward_share_of_unmuted"] is None
