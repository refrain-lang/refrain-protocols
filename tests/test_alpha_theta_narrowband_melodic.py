"""Contract for the separately selectable melodic narrowband protocol."""

from pathlib import Path

import numpy as np
import pytest

from refrain import parse
from refrain.amp_profile import load_amp_profile
from refrain.eval_ import Evaluator
from refrain.ir_json import ir_to_json_obj
from refrain.resolver import resolve


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "protocols/eeg/alpha_theta_narrowband_melodic.refrain"
EXISTING = ROOT / "protocols/eeg/alpha_theta_narrowband.refrain"
AMP = load_amp_profile(
    str(Path(__import__("refrain").__file__).parent / "amp_profiles/q21.json")
)


def test_melodic_is_separate_with_the_same_narrowband_training_rule():
    ir = resolve(parse(PROTOCOL.read_text()), amp=AMP)
    original = resolve(parse(EXISTING.read_text()), amp=AMP)

    assert ir.name == "alpha_theta_narrowband_melodic"
    assert original.name == "alpha_theta_narrowband"
    assert set(ir.inhibits) == {"slow", "fast"}
    assert set(ir.derives) == set(original.derives)
    assert ir.controls["reward_ratio_target"].default.value == 0.85
    assert ir.controls["crossover_dwell"].default.value == 1.0
    assert ir.controls["sustained_dwell"].default.value == 3.0
    assert {"feedback_approach", "feedback_crossover", "feedback_sustained"} <= set(ir.output)
    assert ir.meta.fields["feedback_style"].value == "layered_texture"
    assert ir.meta.fields["feedback_asset_bundle"].value == "narrowband_melodic_v1"
    assert ir.meta.fields["feedback_crossover_attack_s"].value == 1.0
    assert ir.meta.fields["feedback_sustained_attack_s"].value == 1.5


def test_melodic_declares_its_three_feedback_layers():
    ir = resolve(parse(PROTOCOL.read_text()), amp=AMP)
    assert ir.feedback.external_background is True
    assert [(entry.role, entry.output, entry.priority) for entry in ir.feedback.entries] == [
        ("approach", "feedback_approach", 10),
        ("crossover", "feedback_crossover", 20),
        ("sustained", "feedback_sustained", 30),
    ]
    assert [entry.attack_ms for entry in ir.feedback.entries] == [4000, 1000, 1500]
    assert ir_to_json_obj(ir)["refrain_ir_version"] == "0.5"


def test_melodic_approach_has_an_audible_floor_before_crossover():
    """An authored signal checks output math, not a clinical state."""
    source = PROTOCOL.read_text().replace(
        "duration = 2 min;  output_muted = true",
        "duration = 2 s;  output_muted = true", 1,
    ).replace("window = 60 s; target_pct = 50", "window = 1 s; target_pct = 50")
    ir = resolve(parse(source), amp=AMP, bindings={"slow_guard": "off", "fast_guard": "off"})
    evaluator = Evaluator.live(
        ir, sample_rate_hz=250, channel_names=("Pz",),
        record_streams=True, backend="python",
    )
    evaluator.start()
    for second in range(5):
        if second == 4:
            evaluator.set_control("theta_reference_uv", 100.0)
        t = second + np.arange(250) / 250
        signal = 5 * np.sin(2 * np.pi * 7 * t) + 20 * np.sin(2 * np.pi * 10 * t)
        evaluator.step_chunk(signal[:, None])
    assert evaluator.last_taps()["derive/theta_alpha_ratio"] < 0.85
    assert evaluator.last_streams()["output/feedback_approach"][-1] == pytest.approx(0.30, abs=0.03)
