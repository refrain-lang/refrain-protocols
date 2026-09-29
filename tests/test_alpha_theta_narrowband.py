from pathlib import Path

from refrain import parse
from refrain.amp_profile import load_amp_profile
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


def test_narrowband_reward_is_strict_crossover_without_theta_threshold():
    ir = _resolve()
    assert not ir.thresholds.keys() & {"theta_t"}
    event = ir.reward.event
    condition = next(arg.value for arg in event.args if arg.name == "condition")
    assert condition.callee == "above"
    assert condition.args[0].value.target == "derive/theta_envelope"
    assert condition.args[1].value.target == "derive/alpha_envelope"
    duration = next(arg.value for arg in event.args if arg.name == "duration")
    assert duration.value == 1000


def test_narrowband_feedback_is_held_and_graded_by_crossover_depth():
    ir = _resolve()
    assert set(ir.output) == {"audio_gain", "audio_chime"}
    assert ir.output["audio_gain"].stream_type.value_kind == "scalar"
    assert ir.output["audio_chime"].stream_type.value_kind == "event"
