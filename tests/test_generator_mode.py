import subprocess
import sys
from pathlib import Path

import refrain
from refrain.amp_profile import load_amp_profile
from refrain.parser import parse
from refrain.resolver import resolve

ROOT = Path(__file__).resolve().parents[1]
# The generated cores are amp-neutral (montage reads `amp.reference`), so they
# fail closed at amp=None. Resolve against a clinical amp that declares every
# operant site (q21) to exercise the threshold folding below.
_AMP = load_amp_profile(Path(refrain.__file__).parent / "amp_profiles" / "q21.json")


def _regen():
    subprocess.run([sys.executable, "tools/gen_seed_protocols.py"], cwd=ROOT, check=True)


def test_generator_emits_one_file_per_target_no_baseline():
    _regen()
    baselines = list((ROOT / "protocols" / "eeg").glob("*_baseline.refrain"))
    assert baselines == [], f"generator still emitting baseline files: {baselines}"


def test_generated_core_has_mode_and_resolves_both_ways():
    _regen()
    # TABLE is now EMPTY (2026-07): the last four still-generated entries —
    # theta_beta_fz, peak_alpha_up_pz, fm_theta_up_fz, alpha_down_pz — were
    # dropped once the five configurable goal templates (widened to 1-45 Hz,
    # any site) absorbed them too, so _regen() above emits zero files at
    # protocols/eeg/ (verified separately by
    # test_generator_emits_one_file_per_target_no_baseline's empty glob).
    # There is no longer a "still generated" top-level file to repoint at.
    # This test's real subject is the shared emit()-templated mode-collapse
    # shape (single `env_t` threshold gated by a `threshold_style` mode
    # control) — read it off a legacy copy of that same generated shape
    # instead: smr_theta_cz was retired well before this sweep (superseded by
    # protocols/eeg/smr.refrain) and is guaranteed to keep parsing/resolving
    # under the retirement contract (tests/test_retired_protocols.py).
    src = (ROOT / "protocols" / "eeg" / "legacy" / "smr_theta_cz.refrain").read_text()
    assert 'threshold_style = mode' in src
    assert 'title' in src and 'family' in src
    ir_adaptive = resolve(parse(src), amp=_AMP)
    assert ir_adaptive.thresholds["env_t"].threshold_call.callee == "percentile"
    ir_baseline = resolve(parse(src), amp=_AMP, bindings={"threshold_style": "baseline"})
    assert ir_baseline.thresholds["env_t"].threshold_call.callee == "absolute"
