from pathlib import Path

import pytest

import refrain
from refrain.amp_profile import load_amp_profile
from refrain.parser import parse
from refrain.resolver import resolve

ROOT = Path(__file__).resolve().parents[1]
# Three of these four are amp-neutral (montage reads `amp.reference`) since
# the 2026-07 portability sweep and so fail closed at amp=None; resolve
# against a clinical amp that declares every operant site (q21). The fourth
# (smr_up_c4_brainbit, retired/legacy) still hardcodes "device" and ignores
# the amp argument, so passing one uniformly here is harmless.
_AMP = load_amp_profile(Path(refrain.__file__).parent / "amp_profiles" / "q21.json")

# The 4 collapsed BrainBit-origin adaptive/baseline pairs (phase 2b1). Maps
# each protocol core to the threshold names whose `type` is mode-switched by
# `threshold_style`. Always-adaptive artifact guards (hbeta_t in smr_up_c4 /
# beta_focus_staged, emg in smr_classic) are excluded — they stay percentile
# in both modes and are not part of this assertion.
#
# 2026-07 library reorg: protocols/brainbit/ was dissolved (every protocol
# made amp-portable via amp.reference; device-specific folder no longer
# needed). Three of these four dropped their now-inaccurate "_brainbit"
# filename/identifier suffix when relocated to protocols/eeg/; smr_up_c4
# was already retired (git mv'd to protocols/eeg/legacy/, status=legacy,
# original name kept per the legacy-retirement convention) before this reorg.
_MODE_SWITCHED_THRESHOLDS = {
    "smr_classic_cz": ["smr_t", "theta_t"],
    "smr_graded_cz": ["smr_t", "theta_t"],
    "smr_up_c4_brainbit": ["smr_t"],
    "beta_focus_staged_fz": ["beta_t", "theta_t", "hbeta_t"],
}

# smr_classic_cz retired 2026-07 (retire-the-absorbed-duplicates sweep):
# superseded by the configurable SMR template (protocols/eeg/smr.refrain,
# site knob = Cz). git mv'd to protocols/eeg/legacy/, status=legacy, still
# runnable/tested here, just relocated.
_RELOCATED = {
    "smr_up_c4_brainbit": ROOT / "protocols" / "eeg" / "legacy",
    "smr_classic_cz": ROOT / "protocols" / "eeg" / "legacy",
}


def _path_for(name):
    return _RELOCATED.get(name, ROOT / "protocols" / "eeg") / f"{name}.refrain"


@pytest.mark.parametrize("name", _MODE_SWITCHED_THRESHOLDS)
def test_default_mode_switched_thresholds_are_percentile(name):
    src = _path_for(name).read_text()
    ir = resolve(parse(src), amp=_AMP)  # bindings=None -> default threshold_style="adaptive"
    for tname in _MODE_SWITCHED_THRESHOLDS[name]:
        assert ir.thresholds[tname].threshold_call.callee == "percentile"


@pytest.mark.parametrize("name", _MODE_SWITCHED_THRESHOLDS)
def test_baseline_binding_mode_switched_thresholds_are_absolute(name):
    src = _path_for(name).read_text()
    ir = resolve(parse(src), amp=_AMP, bindings={"threshold_style": "baseline"})
    for tname in _MODE_SWITCHED_THRESHOLDS[name]:
        assert ir.thresholds[tname].threshold_call.callee == "absolute"
