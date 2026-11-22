from pathlib import Path

import pytest

refrain = pytest.importorskip("refrain")
from refrain.amp_profile import load_amp_profile  # noqa: E402
from refrain.ir_json import ir_to_json_obj  # noqa: E402
from refrain.resolver import resolve  # noqa: E402
from test_declared_latency import _chain, _num  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "protocols" / "eeg" / "smr_spindle.refrain"
_PROFILES = Path(refrain.__file__).parent / "amp_profiles"
Q21 = load_amp_profile(str(_PROFILES / "q21.json"))
BRAINBIT = load_amp_profile(str(_PROFILES / "brainbit_flex.json"))

_BAND_EDGES = {
    "smr_lo_hz": 12.0, "smr_hi_hz": 16.0,
    "theta_lo_hz": 4.0, "theta_hi_hz": 7.0,
    "low_lo_hz": 8.0, "low_hi_hz": 12.0,
    "hbeta_lo_hz": 16.0, "hbeta_hi_hz": 30.0,
}
# derive -> (lo, hi, declared ms). Floors: 250, 334, 250, 72.
_ENVELOPES = {
    "smr_envelope":      (12.0, 16.0, 320.0),
    "theta_envelope":    (4.0, 7.0, 340.0),
    "low_envelope":      (8.0, 12.0, 320.0),
    "high_beta_envelope": (16.0, 30.0, 120.0),
}
_PREFIX = {
    "smr_envelope": "smr", "theta_envelope": "theta",
    "low_envelope": "low", "high_beta_envelope": "hbeta",
}


def _dwell_terms(ir):
    """[(callee, derive name)] for each term of reward.event's all_of."""
    ev = ir["reward"]["event"]
    assert ev["callee"] == "dwell"
    cond = next(a["value"] for a in ev["args"] if a["name"] == "condition")
    assert cond["callee"] == "all_of"
    return [
        (t["callee"], t["args"][0]["value"]["target"].split("/", 1)[1])
        for t in cond["args"][0]["value"]["elements"]
    ]

def test_resolves_on_both_amps_with_no_bindings():
    for amp in (Q21, BRAINBIT):
        assert resolve(refrain.parse_file(str(PATH)), amp) is not None

def test_band_edge_defaults_are_the_measured_ones():
    # 12-16 Hz: settled by measurement, not literature. 11-16 is the worst
    # option (alpha shoulder 2.2x denser than the core); 12-17 is 20 ms faster,
    # inside the sweep's own step, for twice the contamination.
    ir = ir_to_json_obj(resolve(refrain.parse_file(str(PATH)), Q21))
    for name, hz in _BAND_EDGES.items():
        assert ir["controls"][name]["default"]["value"] == hz

def test_reward_is_smr_up_with_theta_and_low_band_vetoes():
    # `below` on the inhibit bands: `above` there would reward high alpha.
    ir = ir_to_json_obj(resolve(refrain.parse_file(str(PATH)), Q21))
    assert _dwell_terms(ir) == [
        ("above", "smr_envelope"),
        ("below", "theta_envelope"),
        ("below", "low_envelope"),
    ]

def test_every_envelope_is_one_stage_with_its_declared_latency():
    ir = ir_to_json_obj(resolve(refrain.parse_file(str(PATH)), Q21))
    for derive, (_, _, want_ms) in _ENVELOPES.items():
        names, call = _chain(ir["derives"][derive]["expression"])
        assert names == ["band_envelope"], f"{derive} is {names}"
        args = {a["name"]: a["value"] for a in call["args"] if a["name"]}
        assert _num(args["latency"]) == want_ms
        # The band is wired to this derive's own control pair, not another
        # band of the same width.
        lo, hi, _ = _ENVELOPES[derive]
        lo_el, hi_el = args["band"]["elements"]
        assert (_num(lo_el), _num(hi_el)) == (lo, hi), derive
        prefix = _PREFIX[derive]
        assert lo_el["target"] == f"control/{prefix}_lo_hz", derive
        assert hi_el["target"] == f"control/{prefix}_hi_hz", derive

# The bandwidth-floor check lives in test_declared_latency.py, which reads the
# real bands and latencies from every protocol on disk; do not re-add it here
# against local constants.

def test_band_edges_and_latency_are_not_live_tunable():
    # They bake at resolve time; a tunable edge is silently ignored by the
    # engine and refused a caption by the recorder.
    ir = ir_to_json_obj(resolve(refrain.parse_file(str(PATH)), Q21))
    for name in list(_BAND_EDGES) + ["smr_latency"]:
        assert ir["controls"][name]["live_tunable"] is False
