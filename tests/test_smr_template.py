# Copyright 2026 Refrain Protocols Authors.
"""The configurable SMR template (protocols/eeg/smr.refrain) replaces the whole
SMR family (smr_up_c4, smr_classic_cz, smr_theta_cz, smr_graded_cz, and their
retired BrainBit forks) with one clinician-tunable template instead of a file
per site/threshold-style/band-edge combination.

This locks down the two properties that make it trustworthy as the canonical
reference the other four goal templates copy the shape of:

- it resolves with NO bindings beyond the site (a click-and-go default), on
  both a clinical amp and a consumer amp, from one source — same pattern as
  test_amp_neutral.py and test_alpha_coherence_consolidation.py;
- the canonical defaults (site Cz, SMR 12-15 / theta 4-7 / high-beta 20-30 Hz)
  and the live_tunable split (band edges frozen, rates tunable) are
  hard-coded here so a silent default drift fails this test, not just a
  human reading the .refrain file.
"""
from __future__ import annotations

from pathlib import Path

import pytest

refrain = pytest.importorskip("refrain")
from refrain.amp_profile import load_amp_profile  # noqa: E402
from refrain.resolver import resolve  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PROF = Path(refrain.__file__).parent / "amp_profiles"
BRAINBIT = load_amp_profile(PROF / "brainbit_flex.json")
Q21 = load_amp_profile(PROF / "q21.json")

PATH = ROOT / "protocols" / "eeg" / "smr.refrain"

# Canonical defaults from the standard clinical menu (docs/fork-audit-2026-07.md):
# SMR (12-15 Hz) up at Cz, theta (4-7 Hz) and high-beta (20-30 Hz) inhibited.
_BAND_EDGES = {
    "smr_lo_hz": 12.0,
    "smr_hi_hz": 15.0,
    "theta_lo_hz": 4.0,
    "theta_hi_hz": 7.0,
    "hbeta_lo_hz": 20.0,
    "hbeta_hi_hz": 30.0,
}
_RATE_CONTROLS = ("smr_reward_pct", "theta_inhibit_rate", "hbeta_inhibit_rate", "artifact_strictness")


@pytest.fixture(scope="module")
def src() -> str:
    return PATH.read_text()


def test_file_exists():
    assert PATH.exists()


@pytest.mark.parametrize("amp", [Q21, BRAINBIT], ids=["q21", "brainbit"])
def test_resolves_with_no_bindings_beyond_default(src: str, amp):
    # No `bindings=` at all — the canonical default site (Cz) is hostable on
    # both a clinical amp and a 4-channel consumer amp, so the template must
    # run in one click on either.
    ir = resolve(refrain.parse(src), amp=amp)
    assert set(ir.thresholds) == {"smr_t", "theta_t", "hbeta_t"}
    assert "emg" in ir.inhibits


def test_canonical_band_edges_are_hardcoded(src: str):
    ir = resolve(refrain.parse(src), amp=Q21)
    for name, expected_hz in _BAND_EDGES.items():
        control = ir.controls[name]
        assert control.type_kind == "frequency", name
        assert control.default.value == expected_hz, (
            f"{name} default drifted: expected {expected_hz} Hz, got {control.default.value}"
        )
        assert control.default.unit == "Hz", name


def test_band_edges_are_not_live_tunable(src: str):
    ir = resolve(refrain.parse(src), amp=Q21)
    for name in _BAND_EDGES:
        assert ir.controls[name].live_tunable is False, (
            f"{name} must be live_tunable=false — it bakes into the filter at "
            "resolve time and the recorder's envelope classifier refuses to "
            "caption a live-tunable edge"
        )


def test_rate_controls_are_live_tunable(src: str):
    ir = resolve(refrain.parse(src), amp=Q21)
    for name in _RATE_CONTROLS:
        assert ir.controls[name].live_tunable is True, f"{name} must be live_tunable=true"


def test_canonical_site_default_is_cz(src: str):
    ir = resolve(refrain.parse(src), amp=Q21)
    assert ir.controls["site"].default_placement == ("Cz",)


def test_reward_and_inhibit_rate_defaults(src: str):
    # Hard-coded so a silent tweak to the standard clinical menu fails here.
    ir = resolve(refrain.parse(src), amp=Q21)
    assert ir.controls["smr_reward_pct"].default.value == 40
    assert ir.controls["theta_inhibit_rate"].default.value == 80
    assert ir.controls["hbeta_inhibit_rate"].default.value == 75


def test_threshold_style_and_artifact_guard_default_on(src: str):
    ir = resolve(refrain.parse(src), amp=Q21)
    assert ir.controls["threshold_style"].default_mode == "adaptive"
    assert ir.controls["artifact_guard"].default_mode == "on"


def test_baseline_mode_folds_all_three_thresholds_to_absolute(src: str):
    ir = resolve(refrain.parse(src), amp=Q21, bindings={"threshold_style": "baseline"})
    for name in ("smr_t", "theta_t", "hbeta_t"):
        assert ir.thresholds[name].threshold_call.callee == "absolute"


def test_adaptive_mode_folds_all_three_thresholds_to_percentile(src: str):
    ir = resolve(refrain.parse(src), amp=Q21)
    for name in ("smr_t", "theta_t", "hbeta_t"):
        assert ir.thresholds[name].threshold_call.callee == "percentile"


def test_artifact_guard_off_pins_target_pct_to_the_window_ceiling(src: str):
    # See the .refrain header: refrain's inhibit resolver requires `threshold`
    # to be a literal constructor call (no top-level mode fold like
    # threshold.type gets), so on/off is folded one level down inside the
    # target_pct ARGUMENT. "off" pins it to 100 rather than removing the
    # inhibit, which the engine has no mechanism for within one protocol file.
    ir = resolve(refrain.parse(src), amp=Q21, bindings={"artifact_guard": "off"})
    emg = ir.inhibits["emg"]
    target_pct_arg = next(a for a in emg.threshold.args if a.name == "target_pct")
    assert target_pct_arg.value.value == 100


def test_artifact_guard_on_uses_the_tunable_strictness_control(src: str):
    ir = resolve(refrain.parse(src), amp=Q21, bindings={"artifact_guard": "on"})
    emg = ir.inhibits["emg"]
    target_pct_arg = next(a for a in emg.threshold.args if a.name == "target_pct")
    assert target_pct_arg.value.target == "control/artifact_strictness"


def test_site_binds_to_every_sensorimotor_group_member(src: str):
    # C4 reproduces the retired smr_up_c4 family member; C3/Cz cover the rest
    # (docs/fork-audit-2026-07.md, test_retired_protocols.py).
    for site in ("C3", "Cz", "C4"):
        ir = resolve(refrain.parse(src), amp=Q21, bindings={"site": site})
        montage = ir.inputs["raw"].montage
        active_arg = next(a for a in montage.args if a.name == "active")
        assert active_arg.value.value == site


def test_advanced_controls_meta_matches_the_basic_two():
    ir = resolve(refrain.parse(PATH.read_text()), amp=Q21)
    fields = ir.meta.fields
    advanced = {e.value for e in fields["advanced_controls"].elements}
    all_controls = set(ir.controls)
    basic = all_controls - advanced
    assert basic == {"threshold_style", "smr_reward_pct"}, (
        f"Basic surface drifted: expected only threshold_style + smr_reward_pct, got {basic}"
    )
