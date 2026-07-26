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
    # smr_theta_cz was retired 2026-07 (git mv'd to protocols/eeg/legacy/,
    # dropped from TABLE) — use another still-generated TABLE entry instead
    # so this test keeps exercising a freshly-regenerated file.
    src = (ROOT / "protocols" / "eeg" / "fm_theta_up_fz.refrain").read_text()
    assert 'threshold_style = mode' in src
    assert 'title' in src and 'family' in src
    ir_adaptive = resolve(parse(src), amp=_AMP)
    assert ir_adaptive.thresholds["env_t"].threshold_call.callee == "percentile"
    ir_baseline = resolve(parse(src), amp=_AMP, bindings={"threshold_style": "baseline"})
    assert ir_baseline.thresholds["env_t"].threshold_call.callee == "absolute"
