from pathlib import Path

import pytest

from refrain.parser import parse
from refrain.resolver import resolve

ROOT = Path(__file__).resolve().parents[1]

# The 4 collapsed BrainBit adaptive/baseline pairs (phase 2b1). Maps each
# protocol core to the threshold names whose `type` is mode-switched by
# `threshold_style`. Always-adaptive artifact guards (hbeta_t in smr_up_c4 /
# beta_focus_staged, emg in smr_classic) are excluded — they stay percentile
# in both modes and are not part of this assertion.
_MODE_SWITCHED_THRESHOLDS = {
    "smr_classic_cz_brainbit": ["smr_t", "theta_t"],
    "smr_graded_cz_brainbit": ["smr_t", "theta_t"],
    "smr_up_c4_brainbit": ["smr_t"],
    "beta_focus_staged_fz_brainbit": ["beta_t", "theta_t", "hbeta_t"],
}


@pytest.mark.parametrize("name", _MODE_SWITCHED_THRESHOLDS)
def test_default_mode_switched_thresholds_are_percentile(name):
    src = (ROOT / "protocols" / "brainbit" / f"{name}.refrain").read_text()
    ir = resolve(parse(src))  # bindings=None -> default threshold_style="adaptive"
    for tname in _MODE_SWITCHED_THRESHOLDS[name]:
        assert ir.thresholds[tname].threshold_call.callee == "percentile"


@pytest.mark.parametrize("name", _MODE_SWITCHED_THRESHOLDS)
def test_baseline_binding_mode_switched_thresholds_are_absolute(name):
    src = (ROOT / "protocols" / "brainbit" / f"{name}.refrain").read_text()
    ir = resolve(parse(src), bindings={"threshold_style": "baseline"})
    for tname in _MODE_SWITCHED_THRESHOLDS[name]:
        assert ir.thresholds[tname].threshold_call.callee == "absolute"
