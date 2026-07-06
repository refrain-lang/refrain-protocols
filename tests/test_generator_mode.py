import subprocess
import sys
from pathlib import Path

from refrain.parser import parse
from refrain.resolver import resolve

ROOT = Path(__file__).resolve().parents[1]


def _regen():
    subprocess.run([sys.executable, "tools/gen_seed_protocols.py"], cwd=ROOT, check=True)


def test_generator_emits_one_file_per_target_no_baseline():
    _regen()
    baselines = list((ROOT / "protocols").glob("*_baseline.refrain"))
    assert baselines == [], f"generator still emitting baseline files: {baselines}"


def test_generated_core_has_mode_and_resolves_both_ways():
    _regen()
    src = (ROOT / "protocols" / "smr_theta_cz.refrain").read_text()
    assert 'threshold_style = mode' in src
    assert 'title' in src and 'family' in src
    ir_adaptive = resolve(parse(src))
    assert ir_adaptive.thresholds["env_t"].threshold_call.callee == "percentile"
    ir_baseline = resolve(parse(src), bindings={"threshold_style": "baseline"})
    assert ir_baseline.thresholds["env_t"].threshold_call.callee == "absolute"
