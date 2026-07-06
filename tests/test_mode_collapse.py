from pathlib import Path

import pytest

from refrain.parser import parse
from refrain.resolver import resolve

ROOT = Path(__file__).resolve().parents[1]

# The 16 collapsed generic cores (families that had adaptive+baseline pairs).
_COLLAPSED = [
    "alpha_down_pz", "alpha_up_pz", "beta_up_c3", "beta_up_fz", "fm_theta_up_fz",
    "hibeta_down_cz", "peak_alpha_up_pz", "slow_down_cz", "slow_down_fz",
    "smr_theta_cz", "smr_up_c4", "theta_beta_cz", "theta_beta_fz",
    "theta_down_cz", "theta_down_fz", "theta_up_pz",
]


@pytest.mark.parametrize("name", _COLLAPSED)
def test_default_resolves_adaptive_percentile(name):
    src = (ROOT / "protocols" / f"{name}.refrain").read_text()
    ir = resolve(parse(src))  # amp=None; default threshold_style="adaptive"
    assert ir.thresholds["env_t"].threshold_call.callee == "percentile"


@pytest.mark.parametrize("name", _COLLAPSED)
def test_baseline_binding_resolves_absolute(name):
    src = (ROOT / "protocols" / f"{name}.refrain").read_text()
    ir = resolve(parse(src), bindings={"threshold_style": "baseline"})
    assert ir.thresholds["env_t"].threshold_call.callee == "absolute"
