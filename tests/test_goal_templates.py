# Copyright 2026 Refrain Protocols Authors.
"""The four remaining configurable EEG goal templates (protocols/eeg/
beta_attention.refrain, high_beta_down.refrain, alpha_up.refrain,
alpha_theta.refrain), authored in the shape of the canonical reference
(protocols/eeg/smr.refrain, locked down by test_smr_template.py).

Locks down the same two properties that make smr.refrain trustworthy, for
each of these four:

- each resolves with NO bindings beyond the site (a click-and-go default),
  on both a clinical amp and a consumer amp, from one source;
- the canonical defaults (site, band edges in Hz, live_tunable split) are
  hard-coded here so a silent default drift fails this test, not just a
  human reading the .refrain file.

The recorder-side checks (recorder.backend.nf.manifest.build_manifest gives
envelope cards with real captions and zero warnings; the up-train templates
each expose exactly one display_as_reward_rate control in "basic"; the
down-train exposes zero) live in the sibling coherence-recorder repo and were
verified by hand against this branch — this repo has no dependency on that
one, so they are not re-asserted here (same boundary test_smr_template.py
already respects: it never imports recorder).
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

EEG = ROOT / "protocols" / "eeg"


def _resolve(name: str, amp, bindings: dict | None = None):
    src = (EEG / f"{name}.refrain").read_text()
    return resolve(refrain.parse(src), amp=amp, bindings=bindings or {})


# ---------------------------------------------------------------------------
# beta_attention.refrain
# ---------------------------------------------------------------------------

_BETA_ATTENTION_BAND_EDGES = {
    "lobeta_lo_hz": 15.0,
    "lobeta_hi_hz": 18.0,
    "theta_lo_hz": 4.0,
    "theta_hi_hz": 8.0,
    "hbeta_lo_hz": 22.0,
    "hbeta_hi_hz": 30.0,
}
_BETA_ATTENTION_RATE_CONTROLS = (
    "lobeta_reward_pct",
    "theta_inhibit_rate",
    "hbeta_inhibit_rate",
    "artifact_strictness",
)


@pytest.mark.parametrize("amp", [Q21, BRAINBIT], ids=["q21", "brainbit"])
def test_beta_attention_resolves_with_no_bindings_beyond_default(amp):
    ir = _resolve("beta_attention", amp)
    assert set(ir.thresholds) == {"lobeta_t", "theta_t", "hbeta_t"}
    assert "emg" in ir.inhibits


def test_beta_attention_canonical_band_edges_are_hardcoded():
    ir = _resolve("beta_attention", Q21)
    for name, expected_hz in _BETA_ATTENTION_BAND_EDGES.items():
        control = ir.controls[name]
        assert control.type_kind == "frequency", name
        assert control.default.value == expected_hz, (
            f"{name} default drifted: expected {expected_hz} Hz, got {control.default.value}"
        )
        assert control.default.unit == "Hz", name


def test_beta_attention_band_edges_are_not_live_tunable():
    ir = _resolve("beta_attention", Q21)
    for name in _BETA_ATTENTION_BAND_EDGES:
        assert ir.controls[name].live_tunable is False, f"{name} must be live_tunable=false"


def test_beta_attention_rate_controls_are_live_tunable():
    ir = _resolve("beta_attention", Q21)
    for name in _BETA_ATTENTION_RATE_CONTROLS:
        assert ir.controls[name].live_tunable is True, f"{name} must be live_tunable=true"


def test_beta_attention_canonical_site_default_is_cz():
    ir = _resolve("beta_attention", Q21)
    assert ir.controls["site"].default_placement == ("Cz",)


def test_beta_attention_reward_and_inhibit_rate_defaults():
    ir = _resolve("beta_attention", Q21)
    assert ir.controls["lobeta_reward_pct"].default.value == 40
    assert ir.controls["theta_inhibit_rate"].default.value == 75
    assert ir.controls["hbeta_inhibit_rate"].default.value == 75


def test_beta_attention_site_binds_to_every_sensorimotor_group_member():
    for site in ("C3", "Cz", "C4"):
        ir = _resolve("beta_attention", Q21, bindings={"site": site})
        montage = ir.inputs["raw"].montage
        active_arg = next(a for a in montage.args if a.name == "active")
        assert active_arg.value.value == site


# ---------------------------------------------------------------------------
# high_beta_down.refrain
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("amp", [Q21, BRAINBIT], ids=["q21", "brainbit"])
def test_high_beta_down_resolves_with_no_bindings_beyond_default(amp):
    ir = _resolve("high_beta_down", amp)
    assert set(ir.thresholds) == {"hbeta_t"}
    assert "emg" in ir.inhibits


def test_high_beta_down_canonical_band_edges_are_hardcoded():
    ir = _resolve("high_beta_down", Q21)
    assert ir.controls["hbeta_lo_hz"].default.value == 22.0
    assert ir.controls["hbeta_hi_hz"].default.value == 30.0
    assert ir.controls["hbeta_lo_hz"].default.unit == "Hz"
    assert ir.controls["hbeta_hi_hz"].default.unit == "Hz"


def test_high_beta_down_band_edges_are_not_live_tunable():
    ir = _resolve("high_beta_down", Q21)
    assert ir.controls["hbeta_lo_hz"].live_tunable is False
    assert ir.controls["hbeta_hi_hz"].live_tunable is False


def test_high_beta_down_rate_controls_are_live_tunable():
    ir = _resolve("high_beta_down", Q21)
    for name in ("hbeta_inhibit_rate", "artifact_strictness"):
        assert ir.controls[name].live_tunable is True


def test_high_beta_down_canonical_site_default_is_cz():
    ir = _resolve("high_beta_down", Q21)
    assert ir.controls["site"].default_placement == ("Cz",)


def test_high_beta_down_inhibit_rate_default():
    ir = _resolve("high_beta_down", Q21)
    assert ir.controls["hbeta_inhibit_rate"].default.value == 30


def test_high_beta_down_has_no_reward_pct_control():
    # Pure down-train: naming a control `*_reward_pct` would flag
    # display_as_reward_rate and invert a slider whose semantics are
    # suppression, not reward.
    ir = _resolve("high_beta_down", Q21)
    assert not any(name.endswith("_reward_pct") for name in ir.controls)


def test_high_beta_down_site_binds_to_every_frontal_group_member():
    for site in ("Fz", "F3", "F4", "Cz"):
        ir = _resolve("high_beta_down", Q21, bindings={"site": site})
        montage = ir.inputs["raw"].montage
        active_arg = next(a for a in montage.args if a.name == "active")
        assert active_arg.value.value == site


# ---------------------------------------------------------------------------
# alpha_up.refrain
# ---------------------------------------------------------------------------

_ALPHA_UP_BAND_EDGES = {
    "alpha_lo_hz": 8.0,
    "alpha_hi_hz": 12.0,
    "hbeta_lo_hz": 22.0,
    "hbeta_hi_hz": 30.0,
}
_ALPHA_UP_RATE_CONTROLS = ("alpha_reward_pct", "hbeta_inhibit_rate", "artifact_strictness")


@pytest.mark.parametrize("amp", [Q21, BRAINBIT], ids=["q21", "brainbit"])
def test_alpha_up_resolves_with_no_bindings_beyond_default(amp):
    ir = _resolve("alpha_up", amp)
    assert set(ir.thresholds) == {"alpha_t", "hbeta_t"}
    assert "emg" in ir.inhibits


def test_alpha_up_canonical_band_edges_are_hardcoded():
    ir = _resolve("alpha_up", Q21)
    for name, expected_hz in _ALPHA_UP_BAND_EDGES.items():
        control = ir.controls[name]
        assert control.type_kind == "frequency", name
        assert control.default.value == expected_hz, name
        assert control.default.unit == "Hz", name


def test_alpha_up_band_edges_are_not_live_tunable():
    ir = _resolve("alpha_up", Q21)
    for name in _ALPHA_UP_BAND_EDGES:
        assert ir.controls[name].live_tunable is False, name


def test_alpha_up_rate_controls_are_live_tunable():
    ir = _resolve("alpha_up", Q21)
    for name in _ALPHA_UP_RATE_CONTROLS:
        assert ir.controls[name].live_tunable is True, name


def test_alpha_up_canonical_site_default_is_pz():
    ir = _resolve("alpha_up", Q21)
    assert ir.controls["site"].default_placement == ("Pz",)


def test_alpha_up_reward_and_inhibit_rate_defaults():
    ir = _resolve("alpha_up", Q21)
    assert ir.controls["alpha_reward_pct"].default.value == 70
    assert ir.controls["hbeta_inhibit_rate"].default.value == 75


def test_alpha_up_site_binds_to_every_posterior_group_member():
    for site in ("P3", "Pz", "P4"):
        ir = _resolve("alpha_up", Q21, bindings={"site": site})
        montage = ir.inputs["raw"].montage
        active_arg = next(a for a in montage.args if a.name == "active")
        assert active_arg.value.value == site


# ---------------------------------------------------------------------------
# alpha_theta.refrain
# ---------------------------------------------------------------------------

_ALPHA_THETA_BAND_EDGES = {
    "alpha_lo_hz": 8.0,
    "alpha_hi_hz": 12.0,
    "theta_lo_hz": 4.0,
    "theta_hi_hz": 8.0,
}
_ALPHA_THETA_RATE_CONTROLS = ("theta_reward_pct", "artifact_strictness")


@pytest.mark.parametrize("amp", [Q21, BRAINBIT], ids=["q21", "brainbit"])
def test_alpha_theta_resolves_with_no_bindings_beyond_default(amp):
    ir = _resolve("alpha_theta", amp)
    assert set(ir.thresholds) == {"theta_t"}
    assert "emg" in ir.inhibits


def test_alpha_theta_canonical_band_edges_are_hardcoded():
    ir = _resolve("alpha_theta", Q21)
    for name, expected_hz in _ALPHA_THETA_BAND_EDGES.items():
        control = ir.controls[name]
        assert control.type_kind == "frequency", name
        assert control.default.value == expected_hz, name
        assert control.default.unit == "Hz", name


def test_alpha_theta_band_edges_are_not_live_tunable():
    ir = _resolve("alpha_theta", Q21)
    for name in _ALPHA_THETA_BAND_EDGES:
        assert ir.controls[name].live_tunable is False, name


def test_alpha_theta_rate_controls_are_live_tunable():
    ir = _resolve("alpha_theta", Q21)
    for name in _ALPHA_THETA_RATE_CONTROLS:
        assert ir.controls[name].live_tunable is True, name


def test_alpha_theta_canonical_site_default_is_pz():
    ir = _resolve("alpha_theta", Q21)
    assert ir.controls["site"].default_placement == ("Pz",)


def test_alpha_theta_reward_rate_default():
    ir = _resolve("alpha_theta", Q21)
    assert ir.controls["theta_reward_pct"].default.value == 40


def test_alpha_theta_site_binds_to_every_posterior_group_member():
    for site in ("P3", "Pz", "P4"):
        ir = _resolve("alpha_theta", Q21, bindings={"site": site})
        montage = ir.inputs["raw"].montage
        active_arg = next(a for a in montage.args if a.name == "active")
        assert active_arg.value.value == site


def test_alpha_theta_crossover_gate_present_alongside_adaptive_bar():
    # Reward requires BOTH the adaptive/baseline bar on theta AND theta above
    # alpha (the actual crossover) — see the .refrain file's header for why
    # this replaces a bare ratio-derive crossover (a third derive would break
    # the recorder's envelope classifier / zero-warnings requirement).
    ir = _resolve("alpha_theta", Q21)
    event = ir.reward.event
    assert event.callee == "dwell"
    condition_arg = next(a for a in event.args if a.name == "condition")
    assert condition_arg.value.callee == "all_of"
    elements = condition_arg.value.args[0].value.elements
    targets = {getattr(el.args[1].value, "target", None) for el in elements}
    assert "threshold/theta_t" in targets
    assert "derive/alpha_envelope" in targets


def test_alpha_theta_no_third_derive():
    # The deviation from the reference: exactly two derives (both real
    # envelope chains), not a third ratio/formula derive.
    ir = _resolve("alpha_theta", Q21)
    assert set(ir.derives) == {"alpha_envelope", "theta_envelope"}


# ---------------------------------------------------------------------------
# advanced_controls meta matches the basic surface — all four
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,basic_rate_control",
    [
        ("beta_attention", "lobeta_reward_pct"),
        ("high_beta_down", "hbeta_inhibit_rate"),
        ("alpha_up", "alpha_reward_pct"),
        ("alpha_theta", "theta_reward_pct"),
    ],
)
def test_advanced_controls_meta_matches_the_basic_surface(name, basic_rate_control):
    ir = _resolve(name, Q21)
    fields = ir.meta.fields
    advanced = {e.value for e in fields["advanced_controls"].elements}
    all_controls = set(ir.controls)
    basic = all_controls - advanced
    assert basic == {"threshold_style", basic_rate_control}, (
        f"{name}: basic surface drifted, expected only threshold_style + "
        f"{basic_rate_control}, got {basic}"
    )
