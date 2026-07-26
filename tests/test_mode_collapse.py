from pathlib import Path

import pytest

import refrain
from refrain.amp_profile import load_amp_profile
from refrain.parser import parse
from refrain.resolver import resolve

ROOT = Path(__file__).resolve().parents[1]
# The cores are amp-neutral (montage reads `amp.reference`) and so fail closed at
# amp=None. Resolve against a clinical amp that declares every operant site (q21);
# the threshold folding checked here is independent of the amp.
_AMP = load_amp_profile(Path(refrain.__file__).parent / "amp_profiles" / "q21.json")

# The 16 collapsed generic cores (families that had adaptive+baseline pairs).
_COLLAPSED = [
    "alpha_down_pz", "alpha_up_pz", "beta_up_c3", "beta_up_fz", "fm_theta_up_fz",
    "hibeta_down_cz", "peak_alpha_up_pz", "slow_down_cz", "slow_down_fz",
    "smr_theta_cz", "smr_up_c4", "theta_beta_cz", "theta_beta_fz",
    "theta_down_cz", "theta_down_fz", "theta_up_pz",
]

# smr_up_c4 and beta_up_fz were both retired (git mv'd to protocols/eeg/legacy/,
# status=legacy; dropped from tools/gen_seed_protocols.py's TABLE so neither is
# regenerated at a stale path) — smr_up_c4 superseded by the configurable SMR
# template (2026-07), beta_up_fz superseded by the fuller three-band
# protocols/eeg/beta_focus_staged_fz.refrain (2026-07, ex-BrainBit fork). Both
# are still runnable/tested here, just relocated.
#
# 2026-07 library reorg: the flat protocols/ top level was dissolved into
# protocols/eeg/ (amp-portable, no device-specific folder) — the other 14
# cores now live there instead of at their original protocols/ path.
#
# Retire-the-absorbed-duplicates sweep (2026-07): 10 more of these were git
# mv'd to protocols/eeg/legacy/ (status=legacy, dropped from
# tools/gen_seed_protocols.py's TABLE) once a configurable goal template
# reproduced each by configuration alone — smr_theta_cz/alpha_up_pz/
# theta_up_pz/hibeta_down_cz/theta_down_cz/theta_down_fz/slow_down_cz/
# slow_down_fz/beta_up_c3/theta_beta_cz. Still runnable/tested here, just
# relocated.
_RELOCATED = {
    "smr_up_c4": ROOT / "protocols" / "eeg" / "legacy",
    "beta_up_fz": ROOT / "protocols" / "eeg" / "legacy",
    "smr_theta_cz": ROOT / "protocols" / "eeg" / "legacy",
    "alpha_up_pz": ROOT / "protocols" / "eeg" / "legacy",
    "theta_up_pz": ROOT / "protocols" / "eeg" / "legacy",
    "hibeta_down_cz": ROOT / "protocols" / "eeg" / "legacy",
    "theta_down_cz": ROOT / "protocols" / "eeg" / "legacy",
    "theta_down_fz": ROOT / "protocols" / "eeg" / "legacy",
    "slow_down_cz": ROOT / "protocols" / "eeg" / "legacy",
    "slow_down_fz": ROOT / "protocols" / "eeg" / "legacy",
    "beta_up_c3": ROOT / "protocols" / "eeg" / "legacy",
    "theta_beta_cz": ROOT / "protocols" / "eeg" / "legacy",
}


def _path_for(name):
    return _RELOCATED.get(name, ROOT / "protocols" / "eeg") / f"{name}.refrain"


@pytest.mark.parametrize("name", _COLLAPSED)
def test_default_resolves_adaptive_percentile(name):
    src = _path_for(name).read_text()
    ir = resolve(parse(src), amp=_AMP)  # default threshold_style="adaptive"
    assert ir.thresholds["env_t"].threshold_call.callee == "percentile"


@pytest.mark.parametrize("name", _COLLAPSED)
def test_baseline_binding_resolves_absolute(name):
    src = _path_for(name).read_text()
    ir = resolve(parse(src), amp=_AMP, bindings={"threshold_style": "baseline"})
    assert ir.thresholds["env_t"].threshold_call.callee == "absolute"
