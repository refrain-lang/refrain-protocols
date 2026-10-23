"""Authored-signal checks for the theta-up continuous feedback variant.

These cases establish code behavior, not clinical efficacy or real EEG truth.
"""
from pathlib import Path

import numpy as np
import pytest

from refrain import parse
from refrain.amp_profile import load_amp_profile
from refrain.eval_ import Evaluator
from refrain.resolver import resolve


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "protocols" / "eeg" / "alpha_theta_narrowband_theta_rise.refrain"
AMP = load_amp_profile(
    str(Path(__import__("refrain").__file__).parent / "amp_profiles" / "brainbit_flex.json")
)


def _run_case(*, theta_after: float, alpha_after: float, backend: str) -> tuple[float, float, float, float]:
    source = PROTOCOL.read_text().replace(
        "duration = 2 min;  output_muted = true",
        "duration = 45 s;  output_muted = true", 1,
    ).replace("window = 60 s; target_pct = 50", "window = 1 s; target_pct = 50")
    ir = resolve(parse(source), amp=AMP, bindings={"slow_guard": "off", "fast_guard": "off"})
    evaluator = Evaluator.live(
        ir, sample_rate_hz=250, channel_names=("Pz",),
        record_streams=True, backend=backend,
    )
    evaluator.start()
    before = after = ratio = crossover = 0.0
    for second in range(69):
        t = second + np.arange(250) / 250
        theta = 5.0 if second < 63 else theta_after
        alpha = 20.0 if second < 63 else alpha_after
        signal = (theta * np.sin(2 * np.pi * 7 * t) + alpha * np.sin(2 * np.pi * 10 * t))[:, None]
        evaluator.step_chunk(signal)
        value = float(evaluator.last_streams()["output/feedback_approach"][-1])
        if second == 62:
            before = value
        if second == 66:
            after = value
            ratio = float(evaluator.last_taps()["derive/theta_alpha_ratio"])
            crossover = float(evaluator.last_streams()["output/feedback_crossover"][-1])
    return before, after, ratio, crossover


@pytest.mark.parametrize("backend", ["python", "rust"])
def test_theta_rise_brightens_approach_before_crossover_without_alpha_help(backend):
    before, after, ratio, crossover = _run_case(theta_after=10.0, alpha_after=20.0, backend=backend)
    assert ratio < 1.0
    assert after > before + 0.30
    assert crossover == 0


@pytest.mark.parametrize("backend", ["python", "rust"])
def test_alpha_drop_alone_does_not_brighten_theta_approach(backend):
    before, after, ratio, crossover = _run_case(theta_after=5.0, alpha_after=3.0, backend=backend)
    assert ratio > 1.0
    assert after <= before + 0.05
    assert crossover > 0


@pytest.mark.parametrize("backend", ["python", "rust"])
def test_modest_ten_percent_theta_rise_is_audibly_graded(backend):
    before, after, ratio, crossover = _run_case(
        theta_after=5.5, alpha_after=20.0, backend=backend,
    )
    assert ratio < 1.0
    assert crossover == 0
    assert after > before + 0.30
