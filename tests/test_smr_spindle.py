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


def _dwell_wiring(ir):
    """[(callee, derive name, threshold name)] for each term of reward.event's all_of."""
    ev = ir["reward"]["event"]
    assert ev["callee"] == "dwell"
    cond = next(a["value"] for a in ev["args"] if a["name"] == "condition")
    assert cond["callee"] == "all_of"
    return [
        (
            t["callee"],
            t["args"][0]["value"]["target"].split("/", 1)[1],
            t["args"][1]["value"]["target"].split("/", 1)[1],
        )
        for t in cond["args"][0]["value"]["elements"]
    ]


def _dwell_terms(ir):
    """[(callee, derive name)] - which derive each reward term reads."""
    return [(c, d) for c, d, _ in _dwell_wiring(ir)]


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
    # Each term also reads its OWN threshold: `below(low_envelope, theta_t)`
    # would resolve and pass a derive-only check, but vetoes on the wrong band.
    ir = ir_to_json_obj(resolve(refrain.parse_file(str(PATH)), Q21))
    assert _dwell_wiring(ir) == [
        ("above", "smr_envelope", "smr_t"),
        ("below", "theta_envelope", "theta_t"),
        ("below", "low_envelope", "low_t"),
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
    # spindle_duration too: the plain dwell() has no update_control hook, so a
    # live change would be a silent no-op.
    for name in list(_BAND_EDGES) + ["smr_latency", "spindle_duration"]:
        assert ir["controls"][name]["live_tunable"] is False


def test_reward_conjunction_is_smr_above_with_two_loose_vetoes():
    # High-beta LEAVES the reward and becomes a mute, so high_beta_envelope
    # must not appear in the conjunction.
    ir = ir_to_json_obj(resolve(refrain.parse_file(str(PATH)), Q21))
    terms = _dwell_terms(ir)
    assert ("above", "smr_envelope") in terms
    assert ("below", "theta_envelope") in terms
    assert ("below", "low_envelope") in terms
    assert not any(s == "high_beta_envelope" for _, s in terms)


def test_high_beta_is_an_inhibit_that_mutes():
    # An inhibit's action lands in the IR as action_kind/action_release_ms,
    # not as a nested call node.
    ir = ir_to_json_obj(resolve(refrain.parse_file(str(PATH)), Q21))
    hb = ir["inhibits"]["hbeta"]
    assert hb["action_kind"] == "mute"
    assert hb["action_release_ms"] == 200.0
    assert ir["inhibits"]["emg"]["action_kind"] == "mute"
    # It watches the high-beta derive, with its own percentile threshold fed
    # by the hbeta_inhibit_rate control (not the emg inhibit's strictness).
    # (the metric must be a primitive call, so the derive sits inside
    # passthrough(input: ...), the documented form for an inhibit on a derive)
    assert hb["metric"]["callee"] == "passthrough"
    arg = next(a["value"] for a in hb["metric"]["args"] if a["name"] == "input")
    assert arg["target"] == "derive/high_beta_envelope"
    assert hb["threshold"]["callee"] == "percentile"
    target_pct = next(a["value"] for a in hb["threshold"]["args"] if a["name"] == "target_pct")
    assert target_pct["target"] == "control/hbeta_inhibit_rate"
    # The window is pinned too: a drift to 10 s would chase short-term noise.
    window = next(a["value"] for a in hb["threshold"]["args"] if a["name"] == "window")
    assert (window["value"], window["unit"]) == (2.0, "min")


def test_high_beta_guard_is_percentile_only_in_baseline_mode_too():
    # An inhibit's threshold must be a literal constructor call, so the
    # threshold_style switch cannot reach it. In baseline mode the other three
    # bands go absolute while this one keeps chasing a rolling percentile.
    # Pinned so the asymmetry is explicit, not incidental.
    ir = ir_to_json_obj(
        resolve(refrain.parse_file(str(PATH)), Q21, bindings={"threshold_style": "baseline"})
    )
    assert ir["inhibits"]["hbeta"]["threshold"]["callee"] == "percentile"
    for t in ("smr_t", "theta_t", "low_t"):
        assert ir["thresholds"][t]["threshold_call"]["callee"] == "absolute", t


def test_duration_criterion_is_the_published_floor():
    # AASM defines a spindle as >= 0.5 s. Replaces the shipped 250 ms dwell,
    # and the dwell reads the control rather than a literal.
    ir = ir_to_json_obj(resolve(refrain.parse_file(str(PATH)), Q21))
    assert _num(ir["controls"]["spindle_duration"]["default"]) == 500.0
    ev = ir["reward"]["event"]
    dur = next(a["value"] for a in ev["args"] if a["name"] == "duration")
    assert dur["target"] == "control/spindle_duration"


def test_vetoes_default_loose_enough_not_to_deadlock():
    # A trainee whose alpha peak is 12 Hz has the low-band veto sitting inside
    # the reward band. Loose defaults make that degrade, not deadlock.
    ir = ir_to_json_obj(resolve(refrain.parse_file(str(PATH)), Q21))
    assert ir["controls"]["theta_inhibit_rate"]["default"]["value"] >= 80
    assert ir["controls"]["low_inhibit_rate"]["default"]["value"] >= 85


def test_veto_rates_are_not_flagged_as_reward_rates():
    # manifest.py:_is_reward_rate_control decides the inverted slider
    # STRUCTURALLY, "regardless of its name": a below(...) veto is excluded by
    # construction. This pins that the vetoes feed below(), not above().
    ir = ir_to_json_obj(resolve(refrain.parse_file(str(PATH)), Q21))
    terms = dict((s, c) for c, s in _dwell_terms(ir))
    assert terms["theta_envelope"] == "below"
    assert terms["low_envelope"] == "below"


def test_the_tone_is_ungated():
    # The shipped protocol has audio_gain = reward.event.holds ? continuous : 0,
    # audible only while a reward is held, so the tone and the ding fire at the
    # same instant and there is really only ONE feedback moment. Ungating it is
    # how the latency saving reaches the trainee at all: the tone carries no
    # duration criterion, so it arrives ~500 ms before the ding.
    # The IR key is `output`, singular.
    ir = ir_to_json_obj(resolve(refrain.parse_file(str(PATH)), Q21))
    gain = ir["output"]["audio_gain"]
    assert gain["node"] != "conditional", "the tone is still gated on reward.event.holds"
    assert gain["node"] == "reward_field"
    assert gain["field_path"] == "continuous"


def test_the_ding_is_the_reward_event():
    ir = ir_to_json_obj(resolve(refrain.parse_file(str(PATH)), Q21))
    chime = ir["output"]["audio_chime"]
    assert (chime["node"], chime["field_path"]) == ("reward_field", "event")
