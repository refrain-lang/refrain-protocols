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
from session_report.__main__ import _phase_lines  # noqa: E402
from session_report.metrics import session_metrics  # noqa: E402
from session_report.muscle import (  # noqa: E402
    MUSCLE_FACTOR, NOISE_EPISODES_PER_MIN, muscle_band, muscle_episodes,
    noise_floor_per_min,
)
from session_report.replay import replay_session  # noqa: E402
from session_report.session import load_session  # noqa: E402
from session_report.truth import true_episodes, truth_streams  # noqa: E402

FS = 250.0
CHUNK = 5                               # 20 ms, the resolution of a per-chunk tap
SECONDS = 90.0
N = int(SECONDS * FS)
T = np.arange(N) / FS
CHANS = ("A1", "Pz")
DWELL_MS = 250.0
CHUNK_MS = 1000.0 * CHUNK / FS
SAMPLE_MS = 1000.0 / FS
WINDOW = (2500, 21000)                  # what the zero-phase filters can be trusted on
THRESHOLD_UV = 5.0

# The phase plan mirrors the real protocol's shape -- a muted settle that refrain treats
# as the warmup window, then work, a muted mid-session rest, and more work -- because
# warmup is excluded from every figure and a muted phase that is NOT warmup is where the
# mute metrics have to be exercised.
SETTLE_S = 15.0                         # phase 0, output muted: refrain's warmup window
REST_S = (60.0, 70.0)                   # phase 2, output muted, mid-session
WARMUP_END = int(SETTLE_S * FS)
MEASURED_S = (N - WARMUP_END) / FS      # the span every whole-session figure covers
PAUSE_S, RESUME_S = 20.0, 22.0
AUDIO_MUTED_S = (45.0, 47.0)
SMR_ONSETS = (25.0, 40.0, 75.0)
SMR_LEN_S = 1.5
# 5 s is inside warmup, 30 s is unmuted work, 62 s is inside the muted rest
MUSCLE_ONSETS = (5.0, 30.0, 62.0)
MUSCLE_LEN_S = 0.4


def _protocol(*, paused_throughout: bool = False) -> str:
    phases = ('phase { name = "settle"; duration = 15 s; output_muted = true }, '
              'phase { name = "work"; duration = 45 s; mode = timed_with_floor }, '
              'phase { name = "rest"; duration = 10 s; output_muted = true }, '
              'phase { name = "work2"; duration = 20 s; mode = timed_with_floor }')
    if paused_throughout:
        # no output_muted first phase, so refrain declares no warmup at all and the whole
        # session can be muted by a pause the log never resumes
        phases = 'phase { name = "work"; duration = 90 s; mode = timed_with_floor }'
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


def _phase_markers(paused_throughout: bool) -> list[tuple[int, dict]]:
    """Phase records as a recorder writes them: a little after refrain's own clock.

    The log's wall clock runs behind refrain's sample clock (the real session drifts
    ~3 s over 34 minutes), so a logged phase change always arrives after the phase
    actually turned over.
    """
    if paused_throughout:
        return [(0, {"type": "phase_change", "phase_index": 0, "phase_name": "work", "t_s": 0.0})]
    edges = [(0, 0, "settle"), (SETTLE_S, 1, "work"), (REST_S[0], 2, "rest"),
             (REST_S[1], 3, "work2")]
    out = []
    for at, index, name in edges:
        late = at + 0.1 if at else 0.0
        out.append((int(late * FS), {"type": "phase_change", "phase_index": index,
                                     "phase_name": name, "t_s": late}))
    return out


def _audio_frames(*, state_until=None) -> list[dict]:
    """10 Hz telemetry that mutes the audio for AUDIO_MUTED_S, as the recorder logs it.

    With ``state_until`` the frames also carry refrain's session state, which is the
    report's preferred source for where warmup ended.
    """
    out = []
    for k in range(int(SECONDS * 10)):
        t = k / 10.0
        frame = {"type": "telemetry", "t_s": t,
                 "audio_muted": AUDIO_MUTED_S[0] <= t < AUDIO_MUTED_S[1]}
        if state_until is not None:
            frame["state"] = "warmup" if t < state_until else "run"
        out.append(frame)
    return out


def _ding_records(times) -> list[tuple[int, dict]]:
    """Logged dings, as the recorder writes them: refrain's clock, nothing rendered.

    These are what ``reconcile.frame_positions`` uses to place telemetry frames on
    refrain's clock, so a session whose first ding comes long after warmup -- which is
    every session whose warmup phase is output-muted, the real one included -- has no
    anchor at all before its warmup ends.
    """
    return [(int(t * FS), {"type": "reward_event", "channel": "audio_chime", "kind": "event",
                           "value": None, "rendered_sound": False, "t_s": t}) for t in times]


def _plant(tmp_path: Path, *, smr=(), muscle=(), paused=True, paused_throughout=False,
           text=None, pz=None, phase_markers=None, telemetry=None, audio=None, manifest=None,
           dings=()):
    """Build, replay and measure a planted session; return (metrics, extras)."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "p.refrain"
    path.write_text(text if text is not None else _protocol(paused_throughout=paused_throughout))
    ir = resolve(refrain.parse_file(str(path)), None)
    ir_json = ir_to_json_obj(ir)

    pz = _quiet_eeg(31) if pz is None else pz
    pz = _with_bursts(pz, smr, SMR_LEN_S, 13.5, 12.0)
    pz = _with_bursts(pz, muscle, MUSCLE_LEN_S, 80.0, 40.0)
    markers = (_phase_markers(paused_throughout) if phase_markers is None
               else list(phase_markers))
    if paused_throughout:
        # a pause at the very first sample that the log never resumes
        markers += [(0, {"type": "session_state", "action": "pause", "t_s": 0.0})]
    elif paused:
        markers += [(int(PAUSE_S * FS), {"type": "session_state", "action": "pause", "t_s": PAUSE_S}),
                    (int(RESUME_S * FS), {"type": "session_state", "action": "resume", "t_s": RESUME_S})]
    markers += _ding_records(dings)
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

    # the noise floor the report prints is only claimed for rates it was measured at
    assert noise_floor_per_min(FS) == NOISE_EPISODES_PER_MIN[FS]
    assert noise_floor_per_min(256.0) is None


def test_metrics_on_planted_session(tmp_path):
    m, (res, eps, replay) = _plant(tmp_path, smr=SMR_ONSETS, muscle=MUSCLE_ONSETS)

    # --- what was looked at: the trusted window, minus warmup ---
    assert m["judged"] is True and tuple(m["window"]) == WINDOW
    assert m["warmup"]["end_sample"] == WARMUP_END          # the muted settle phase
    assert m["warmup"]["declared_end_sample"] == WARMUP_END
    assert m["warmup"]["logged_end_sample"] is None         # this log carries no state field
    assert "first phase" in m["warmup"]["source"]
    assert m["elapsed_s"] == pytest.approx(MEASURED_S, abs=0.1)
    assert m["window_s"] == pytest.approx((WINDOW[1] - WARMUP_END) / FS, abs=0.01)

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
    # the bursts are isolated, so the condition was not already holding at any true start
    assert m["condition_already_true_at_start"] == 0
    # the filter's own delay: the live envelope cannot cross a threshold it is only
    # 40 % of the way to later than its measured lag against the zero-phase truth
    lag_ms, r = m["derive_lag_r"]["smr_envelope"]
    assert 0.0 <= condition <= lag_ms + CHUNK_MS
    assert lag_ms > 0.0 and r > 0.5
    # the continuous output crosses its midpoint at the same threshold the dwell counts
    # from, so it rises no later than the ding
    assert 0.0 <= m["continuous_rise_ms"]["median"] <= ding

    # --- the ding duration distribution: the reward hold's own run lengths ---
    holds = m["reward_hold_len_ms"]
    # a hold starts one dwell into a burst and can outlast it only by the envelope's decay
    assert DWELL_MS < holds["median"] < SMR_LEN_S * 1000.0
    assert holds["p90"] >= holds["median"]

    # --- mutes: three sources planted, one left at zero, all measured after warmup ---
    rest_s = REST_S[1] - REST_S[0]
    assert m["mute_share"]["artifact"] == 0.0                # this protocol declares no inhibit
    assert m["mute_share"]["phase"] == pytest.approx(rest_s / MEASURED_S, abs=0.01)
    assert m["mute_share"]["pause"] == pytest.approx((RESUME_S - PAUSE_S) / MEASURED_S, abs=0.01)
    assert m["mute_share"]["audio"] == pytest.approx(
        (AUDIO_MUTED_S[1] - AUDIO_MUTED_S[0]) / MEASURED_S, abs=0.01)
    muted_s = rest_s + (RESUME_S - PAUSE_S) + (AUDIO_MUTED_S[1] - AUDIO_MUTED_S[0])
    assert m["unmuted_s"] == pytest.approx(MEASURED_S - muted_s, abs=0.3)
    # the reward can only hold inside three 1.5 s bursts, all of them in unmuted time
    assert 0.0 < m["reward_share_of_unmuted"] <= 3 * (SMR_LEN_S + 0.5) / m["unmuted_s"]
    # every episode is in unmuted time, so none was lost to a mute
    assert m["episodes_lost_to_mute"] == {"artifact": 0, "phase": 0, "pause": 0, "audio": 0, "any": 0}

    # --- muscle: three bursts planted, one in warmup and one inside the muted rest ---
    assert len(eps) == 3, [(a / FS, b / FS) for a, b in eps]
    # the warmup burst is not measured at all, so of the two that are, one was muted
    assert 0.3 <= m["muscle_time_muted"] <= 0.7
    assert m["muted_without_muscle"] > 0.9           # 0.4 s of muscle in 14 s of mute

    # --- dings decided against dings heard ---
    assert m["ding_decided_vs_rendered"]["decided"] == 3
    assert m["ding_decided_vs_rendered"]["by_channel"]["audio_chime"]["decided"] == 3
    assert m["ding_decided_vs_rendered"]["logged"] == 0
    assert m["ding_decided_vs_rendered"]["rendered"] == 0

    # --- thresholds: absolute, so flat in every block, warmup block included ---
    blocks = m["thresholds_per_block"]["smr_t"]
    assert [b["block"] for b in blocks] == ["settle", "work", "rest", "work2"]
    assert all(b["start"] == THRESHOLD_UV and b["end"] == THRESHOLD_UV and b["drift"] == 0.0
               for b in blocks)

    # --- per phase ---
    settle, work, rest, work2 = m["per_phase"]
    assert [p["name"] for p in m["per_phase"]] == ["settle", "work", "rest", "work2"]
    # the settle phase is entirely warmup, so nothing in it was measured at all
    assert settle["elapsed_s"] == 0.0
    assert settle["rewards_per_min"] is None and settle["mute_share"]["phase"] is None
    assert settle["reward_share_of_unmuted"] is None
    # the rest phase is muted but is not warmup: it is measured, and has no unmuted time
    assert rest["mute_share"]["phase"] == 1.0
    assert rest["reward_share_of_unmuted"] is None
    assert rest["rewards_per_min"] == 0.0
    assert rest["muscle_time_muted"] == 1.0                   # the 62 s burst, inside it
    assert work["rewards_per_min"] > 0.0 and work2["rewards_per_min"] > 0.0


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
    assert m["reward_hold_len_ms"] == {"median": None, "p90": None}
    assert m["condition_already_true_at_start"] == 0
    assert m["muscle_time_muted"] is None                     # no muscle, so no share of it
    assert m["muted_without_muscle"] == 1.0                   # the rest phase, with no muscle in it
    assert m["episodes_lost_to_mute"]["any"] == 0
    assert m["ding_decided_vs_rendered"] == {"decided": 0, "rendered": 0, "logged": 0, "by_channel": {}}
    assert m["mute_share"]["phase"] == pytest.approx((REST_S[1] - REST_S[0]) / MEASURED_S, abs=0.01)
    for phase in m["per_phase"][1:]:                          # phase 0 is all warmup: None
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


def _state_frames(*, state_until=None) -> list[dict]:
    """Telemetry carrying the layered-texture feedback state, as the recorder logs it."""
    out, k = [], 0
    for state, count in STATE_FRAMES:
        for _ in range(count):
            t = k / 10.0
            frame = {"type": "telemetry", "t_s": t, "audio_muted": False,
                     "feedback_state": state}
            if state_until is not None:
                frame["state"] = "warmup" if t < state_until else "run"
            out.append(frame)
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

    # The same view on a session with a warmup and a first ding well after it: the warmup
    # frames are excluded. Placing them on refrain's clock instead would collapse every
    # frame before that ding onto it, putting the whole warmup after the boundary and
    # counting all of it -- the same defect as reading the warmup boundary that way.
    warm = 20.0
    m_warm, _ = _plant(tmp_path / "warm", text=RATIO, pz=_crossover_eeg(), paused=False,
                       phase_markers=[], telemetry=_state_frames(state_until=warm),
                       dings=(30.2,), audio={"feedback_style": "layered_texture"})
    assert m_warm["warmup"]["end_sample"] == int(warm * FS)
    state = m_warm["protocol_views"]["feedback_state"]
    assert state["measured_from_s"] == pytest.approx(warm)
    # the first 200 frames are warmup, and all of them were "approach"
    assert state["frames"] == {"approach": 400, "crossover": 200, "sustained": 100}
    assert m_warm["protocol_views"]["ratio"]["share_measured_from_s"] == pytest.approx(warm)

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
    """Every sample muted by a pause the log never resumes: nothing reached anybody."""
    m, (res, _, _) = _plant(tmp_path, smr=SMR_ONSETS, paused_throughout=True)

    # no output_muted first phase, so there is no warmup to exclude and the whole
    # recording is measured -- and all of it is muted by the pause
    assert m["warmup"]["end_sample"] == 0 and m["elapsed_s"] == pytest.approx(SECONDS, abs=0.1)
    assert m["mute_share"]["pause"] == 1.0 and m["unmuted_s"] == 0.0
    assert m["reward_share_of_unmuted"] is None                 # no unmuted time to take a share of
    assert m["episodes"] == 3 and m["rewarded_in_episode"] == 1.0
    # the protocol still decided every reward; the trainee could not hear any of them
    assert m["episodes_lost_to_mute"] == {"artifact": 0, "phase": 0, "pause": 3, "audio": 0, "any": 3}
    assert m["per_phase"][0]["reward_share_of_unmuted"] is None
    assert any("never resumes" in note for note in m["notes"])


def test_warmup_comes_from_the_log_when_it_says_and_a_clash_is_named(tmp_path):
    """The live telemetry's state field is preferred, and a disagreement is reported."""
    # the log says warmup ended at 14.5 s, the protocol declares 15 s: close enough that
    # only the source is worth reporting
    m, _ = _plant(tmp_path / "agree", smr=SMR_ONSETS, telemetry=_audio_frames(state_until=14.5))
    assert m["warmup"]["source"] == "the live telemetry's state field, on the log's own clock"
    assert m["warmup"]["end_sample"] == int(14.5 * FS)
    assert m["warmup"]["declared_end_sample"] == WARMUP_END
    assert m["elapsed_s"] == pytest.approx((N - 14.5 * FS) / FS, abs=0.1)
    assert not any("but the protocol declares" in note for note in m["notes"])

    # the log says warmup ran five seconds longer than the protocol declares: the log is
    # what ran, so it is used, and the difference is named rather than resolved
    m, _ = _plant(tmp_path / "clash", smr=SMR_ONSETS, telemetry=_audio_frames(state_until=20.0))
    assert m["warmup"]["end_sample"] == int(20.0 * FS)
    assert any("but the protocol declares" in note for note in m["notes"])
    assert any("20.0 s" in note and "15.0 s" in note for note in m["notes"])

    # The real session's shape: warmup is output-muted, so no ding can be logged during
    # it and the first one lands seconds later. Reading the boundary through the ding
    # anchors would collapse every warmup frame onto that first ding and exclude the
    # seconds between -- 126.7 s instead of 119.8 s on the real session.
    m, _ = _plant(tmp_path / "late-ding", smr=SMR_ONSETS,
                  telemetry=_audio_frames(state_until=14.5), dings=(25.2, 40.2, 75.2))
    assert m["warmup"]["logged_end_sample"] == int(14.5 * FS)
    assert m["warmup"]["end_sample"] == int(14.5 * FS)
    assert m["elapsed_s"] == pytest.approx((N - 14.5 * FS) / FS, abs=0.1)

    # a session the log says never left warmup: there is no time after it to measure, so
    # every figure is unmeasured -- including the counts, which would otherwise read as
    # "we looked and found none"
    m, _ = _plant(tmp_path / "never", smr=SMR_ONSETS,
                  telemetry=_audio_frames(state_until=SECONDS + 1))
    assert m["warmup"]["end_sample"] == N and m["elapsed_s"] == 0.0
    assert m["episodes"] is None and m["reward_onsets"] is None
    assert m["rewards_per_min"] is None and m["mute_share"]["phase"] is None
    assert any("warmup covers the whole replay" in note for note in m["notes"])
    assert m["condition_already_true_at_start"] is None       # nothing was looked at
    assert all("entirely warmup, so nothing in it was measured" in line
               for line in _phase_lines(m)[1:])


def test_a_phase_warmup_cut_into_is_labelled_by_what_was_measured(tmp_path):
    """A rate over the tail of a phase must not be printed under the whole phase's span.

    The real session's warmup ends at 119.71 s against a declared 120 s settle phase, so
    its settle row covers the last third of a second of a two-minute phase -- and one
    reward decision landing in that sliver is a three-digit rewards-per-minute if the row
    is read as covering the two minutes.
    """
    m, _ = _plant(tmp_path, smr=SMR_ONSETS, telemetry=_audio_frames(state_until=14.5))

    settle, work = m["per_phase"][0], m["per_phase"][1]
    assert (settle["start_s"], settle["end_s"]) == (0.0, pytest.approx(SETTLE_S, abs=0.05))
    assert settle["measured_from_s"] == pytest.approx(14.5, abs=0.05)
    assert settle["elapsed_s"] == pytest.approx(SETTLE_S - 14.5, abs=0.05)
    assert work["measured_from_s"] == work["start_s"]          # warmup ended before it began
    # and the report says which span each figure covers
    printed = _phase_lines(m)
    assert "settle 0.0-15.0 s (measured from 14.5 s, 0.5 s)" in printed[1], printed
    assert "work 15.0-60.1 s (45.1 s)" in printed[2], printed


def test_the_documented_noise_floor_still_describes_the_detector():
    """The floor the report prints is a measured figure, so it must not go stale.

    The table in ``muscle.py`` was measured over four seeds of 36 minutes per rate, which
    is far too slow for a test; ten minutes of one seed is enough to catch a detector that
    has drifted far from what the report claims about it.
    """
    for fs, documented in sorted(NOISE_EPISODES_PER_MIN.items()):
        minutes = 10.0
        noise = np.random.default_rng(4242).standard_normal(int(minutes * 60 * fs))
        measured = len(muscle_episodes(noise, fs)) / minutes
        assert documented / 3.0 <= max(measured, 0.1) <= documented * 3.0, (fs, measured, documented)
