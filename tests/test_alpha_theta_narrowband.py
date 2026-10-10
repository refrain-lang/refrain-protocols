from pathlib import Path

import numpy as np
import pytest

from refrain import parse
from refrain.amp_profile import load_amp_profile
from refrain.eval_ import Evaluator
from refrain.resolver import resolve


ROOT = Path(__file__).resolve().parents[1]
REFRAIN = ROOT / "protocols" / "eeg" / "alpha_theta_narrowband.refrain"
Q21 = load_amp_profile(
    str(Path(__import__("refrain").__file__).parent / "amp_profiles" / "q21.json")
)


def _resolve():
    return resolve(parse(REFRAIN.read_text()), amp=Q21)


def _band_for(ir, derive_name: str):
    expression = ir.derives[derive_name].expression
    bandpass = expression.args[0].value.args[0].value.args[0].value
    band = next(arg.value for arg in bandpass.args if arg.name == "band")
    return tuple(getattr(item, "value", getattr(item, "target", None)) for item in band.elements)


def test_narrowband_protocol_uses_brain_trainer_crossover_bands():
    ir = _resolve()
    assert _band_for(ir, "theta_envelope") == (
        "control/theta_lo_hz",
        "control/theta_hi_hz",
    )
    assert _band_for(ir, "alpha_envelope") == (
        "control/alpha_lo_hz",
        "control/alpha_hi_hz",
    )
    assert _band_for(ir, "slow_envelope") == (3.0, 5.0)
    assert set(ir.inhibits) == {"slow", "fast"}


def test_narrowband_crossover_bands_are_configurable_at_session_setup():
    ir = _resolve()
    expected = {
        "theta_lo_hz": (6.0, 4.0, 7.0),
        "theta_hi_hz": (8.0, 7.0, 9.0),
        "alpha_lo_hz": (9.0, 8.0, 11.0),
        "alpha_hi_hz": (11.0, 10.0, 13.0),
    }
    for name, (default, low, high) in expected.items():
        control = ir.controls[name]
        assert control.type_kind == "frequency"
        assert control.default.value == default
        assert control.range_low.value == low
        assert control.range_high.value == high
        assert control.live_tunable is False


def test_narrowband_reward_target_defaults_to_approach_shaping_and_is_live_tunable():
    ir = _resolve()
    assert not ir.thresholds.keys() & {"theta_t"}
    target = ir.controls["reward_ratio_target"]
    assert target.default.value == 0.85
    assert target.range_low.value == 0.5
    assert target.range_high.value == 1.0
    assert target.live_tunable is True
    event = ir.reward.event
    condition = next(arg.value for arg in event.args if arg.name == "condition")
    assert condition.callee == "all_of"
    component = condition.args[0].value.elements[0]
    assert component.callee == "above"
    assert component.args[0].value.target == "derive/theta_alpha_ratio"
    assert component.args[1].value.target == "control/reward_ratio_target"
    duration = next(arg.value for arg in event.args if arg.name == "duration")
    assert duration.value == 1000


def test_narrowband_feedback_is_held_and_graded_by_crossover_depth():
    ir = _resolve()
    assert {"feedback_approach", "feedback_crossover", "feedback_sustained"} <= set(ir.output)
    assert ir.meta.fields["feedback_style"].value == "layered_texture"
    assert ir.meta.fields["feedback_approach_channel"].value == "feedback_approach"
    assert ir.meta.fields["feedback_crossover_channel"].value == "feedback_crossover"
    assert ir.meta.fields["feedback_sustained_channel"].value == "feedback_sustained"
    assert ir.output["audio_gain"].stream_type.value_kind == "scalar"
    assert ir.output["audio_chime"].stream_type.value_kind == "event"
    cue = ir.output["sustained_theta_cue"]
    assert cue.stream_type.value_kind == "event"
    assert cue.callee == "dwell_rearm"
    assert ir.meta.fields["legacy_sustained_cue_channel"].value == "sustained_theta_cue"


def test_narrowband_theta_progress_uses_a_frozen_settle_reference():
    ir = _resolve()
    reference = ir.controls["theta_reference_uv"]
    assert reference.type_kind == "voltage"
    assert reference.live_tunable is True
    assert reference.seed is not None
    assert reference.seed.from_entity == "derive/theta_envelope"
    assert reference.seed.window_ms == 60_000
    assert reference.seed.target_pct.value == 50
    assert ir.controls["theta_rise_pct"].default.value == 25
    assert {"theta_progress", "ratio_progress"} <= set(ir.derives)
    assert {"feedback_theta_progress", "feedback_ratio_progress"} <= set(ir.output)
    assert ir.session.phases[0].name == "settle"
    assert ir.session.phases[0].output_muted is True


@pytest.mark.parametrize("backend", ["python", "rust"])
def test_authored_theta_rise_changes_early_texture_before_ratio_target(backend):
    """Authored synthetic components test code behavior, not clinical efficacy."""
    source = REFRAIN.read_text().replace(
        "duration = 2 min;  output_muted = true",
        "duration = 2 s;  output_muted = true", 1,
    ).replace("window = 60 s; target_pct = 50", "window = 1 s; target_pct = 50")
    brainbit = load_amp_profile(
        str(Path(__import__("refrain").__file__).parent / "amp_profiles" / "brainbit_flex.json")
    )
    ir = resolve(parse(source), amp=brainbit, bindings={"slow_guard": "off", "fast_guard": "off"})
    evaluator = Evaluator.live(
        ir, sample_rate_hz=250, channel_names=("Pz",),
        record_streams=True, backend=backend,
    )
    evaluator.start()
    outputs = []
    for chunk_index in range(8):
        t = (chunk_index * 250 + np.arange(250)) / 250
        theta_amplitude = 5 if chunk_index < 4 else 10
        authored_signal = (
            theta_amplitude * np.sin(2 * np.pi * 7 * t)
            + 20 * np.sin(2 * np.pi * 10 * t)
        )[:, None]
        evaluator.step_chunk(authored_signal)
        outputs.append(float(evaluator.last_streams()["output/feedback_approach"][-1]))
        if chunk_index == 7:
            assert evaluator.last_taps()["derive/theta_alpha_ratio"] < 0.85
    assert evaluator.seed_report()["theta_reference_uv"]["status"] == "seeded"
    assert outputs[2] == pytest.approx(0.1, abs=0.02)
    assert outputs[5] > outputs[2] + 0.5


@pytest.mark.parametrize("backend", ["python", "rust"])
def test_fast_guard_catches_a_burst_without_muting_a_gradual_rise(backend):
    """Authored fast activity separates a slow drift from a brief large surge."""
    source = REFRAIN.read_text().replace(
        "duration = 2 min;  output_muted = true",
        "duration = 2 s;  output_muted = true", 1,
    ).replace("window = 60 s; target_pct = 50", "window = 1 s; target_pct = 50")
    brainbit = load_amp_profile(
        str(Path(__import__("refrain").__file__).parent / "amp_profiles" / "brainbit_flex.json")
    )
    ir = resolve(parse(source), amp=brainbit, bindings={"slow_guard": "off"})
    evaluator = Evaluator.live(
        ir, sample_rate_hz=250, channel_names=("Pz",),
        record_streams=True, backend=backend,
    )
    evaluator.start()
    rng = np.random.default_rng(7)
    drift_muted = []
    burst_muted = []
    for second in range(46):
        t = second + np.arange(250) / 250
        fast_amplitude = max(1.0, 4.0 + 0.3 * second + rng.normal(0, 1.2))
        if second == 44:
            fast_amplitude += 45.0
        authored_signal = (
            5 * np.sin(2 * np.pi * 7 * t)
            + 10 * np.sin(2 * np.pi * 10 * t)
            + fast_amplitude * np.sin(2 * np.pi * 25 * t)
        )[:, None]
        for start in range(0, 250, 25):
            evaluator.step_chunk(authored_signal[start : start + 25])
            muted = bool(evaluator.last_taps()["muted"])
            if 10 <= second < 40:
                drift_muted.append(muted)
            if second == 44:
                burst_muted.append(muted)

    assert np.mean(drift_muted) < 0.15
    assert np.mean(burst_muted) > 0.20
