"""Structural gates for smr_spindle.refrain - and they are the ONLY gates.

Everything here reads the resolved IR: wiring, bands, declared latencies,
defaults, which output channel carries what. Nothing here runs the engine.

That matters because the repo's behavioural gate does not cover this file
either. `refrain fuzz` decides whether it can represent a protocol by looking
for bandpass SOS coefficients on the reward derive (refrain/fuzz/surface.py:453
`if derive.sos is None`); a one-stage `band_envelope` has none, so the fuzzer
reports

    SKIPPED (unsupported: non-bandpass (coherence) reward signal)

which names the wrong cause - there is no coherence reward here - and, per
.github/workflows/ci.yml, a typed SKIP does not fail the build. Verified at
refrain v0.24.0 and again at v0.25.1: this protocol SKIPs where smr.refrain
and high_beta_down.refrain both PASS.

So no automated check in this repository confirms that the engine behaves the
way the protocol header says it does. Green CI on this file means it parses,
resolves, carries valid metadata and is wired as written. It is also not
specific to this file: test_declared_latency.py's WAITING list says every
family migrates to `band_envelope`, and each migration drops its protocol out
of the fuzz gate the same way. Upstream `refrain` has to classify a
band_envelope reward before that gate means anything here.
"""
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
# high_beta is the one latency NOT chosen for speed: it feeds a mute, where a
# twitchy estimate is the failure mode, so it declares 320 ms - four and a half
# times its own floor - to fire on sustained contamination rather than on every
# excursion.
_ENVELOPES = {
    "smr_envelope":      (12.0, 16.0, 320.0),
    "theta_envelope":    (4.0, 7.0, 340.0),
    "low_envelope":      (8.0, 12.0, 320.0),
    "high_beta_envelope": (16.0, 30.0, 320.0),
}
_PREFIX = {
    "smr_envelope": "smr", "theta_envelope": "theta",
    "low_envelope": "low", "high_beta_envelope": "hbeta",
}


def _dwell_args(ir) -> dict:
    """The dwell's arguments by name, asserting the reward event IS a dwell."""
    ev = ir["reward"]["event"]
    assert ev["callee"] == "dwell", ev["callee"]
    return {a["name"]: a["value"] for a in ev["args"] if a.get("name")}


def _condition_terms(cond: dict) -> list[tuple[str, str, str]]:
    """[(callee, derive, threshold)] for a reward condition.

    Accepts both shapes the library uses - a single comparison, or an
    `all_of([...])` of them - so a change from one to the other shows up as a
    changed term LIST rather than as this helper raising.
    """
    terms = (
        cond["args"][0]["value"]["elements"]
        if cond["callee"] == "all_of"
        else [cond]
    )
    return [
        (
            t["callee"],
            t["args"][0]["value"]["target"].split("/", 1)[1],
            t["args"][1]["value"]["target"].split("/", 1)[1],
        )
        for t in terms
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

def test_the_reward_is_smr_alone_held_with_dip_tolerance():
    # The whole hold mechanism in one gate, because the three facts are one
    # decision (measured 2026-11-22, design doc section 12.7):
    #
    #   SMR alone is above threshold 61.0% of the time and theta or the alpha
    #   shoulder is high 30.3% of the time, so the old three-term conjunction
    #   held continuously for 500 ms just 1.3% of a block - against a 25-40%
    #   design target. Theta and the low band moved OUT of the condition and
    #   became `kind = "artifact"` inhibits (which freeze the dwell's streak
    #   instead of resetting it), and the dwell got 120 ms of dip tolerance.
    #   Result: 27.8% median reward time replayed through the real evaluator,
    #   30.7% in the cheap transcription that swept the candidates. Both are
    #   inside the 25-40% target band; a smaller tolerance would not be, once
    #   the engine's three points come off.
    #
    # So: one term, reading its own threshold; no inhibit band inside the
    # condition; and the tolerance present as a literal. Splitting these into
    # three tests pinned one fact three times and would let a partial revert
    # pass two of them.
    ir = ir_to_json_obj(resolve(refrain.parse_file(str(PATH)), Q21))
    args = _dwell_args(ir)
    assert _condition_terms(args["condition"]) == [("above", "smr_envelope", "smr_t")]
    assert _num(args["tolerance"]) == 120.0
    # A LITERAL, not a control: DwellImpl bakes tolerance_samples in its
    # constructor and has no update_control hook, so a bound control would be
    # silently discarded. `duration` right beside it is a control_ref, which
    # is safe only because it bakes at resolve time too.
    assert args["tolerance"]["node"] == "number", args["tolerance"]
    assert args["duration"]["target"] == "control/spindle_duration"


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


def test_the_two_vetoes_are_artifact_inhibits_and_the_two_guards_are_not():
    # `kind = "artifact"` is the load-bearing word. refrain's dwell checks
    # observability BEFORE the condition (eval_.py, the hold_for/dwell arm),
    # so an artifact-labelled mute freezes the streak AND the dip counter;
    # without the label a contaminated stretch longer than the tolerance would
    # reset the streak through the dip path and the restructuring would buy
    # nothing.
    #
    # The map is pinned WHOLE, including the two that carry no label. At the
    # reward stage refrain applies the observability mask only - never the
    # eligibility mask - so a plain mute does not make the condition false
    # there: the streak keeps counting through an EMG or high-beta mute, and a
    # reward can be credited for SMR measured while the trainee heard nothing.
    # Labelling the EMG guard `artifact` too would stop that. It is a
    # signal-definition call (is 50-100 Hz muscle "unobservable EEG" or just
    # "not now"?), so it is NOT made here - but it is pinned so the answer is
    # a deliberate edit rather than a drift.
    ir = ir_to_json_obj(resolve(refrain.parse_file(str(PATH)), Q21))
    assert {n: i.get("kind") for n, i in ir["inhibits"].items()} == {
        "emg": None,
        "hbeta": None,
        "theta": "artifact",
        "low": "artifact",
    }
    for name, derive, rate in (
        ("theta", "theta_envelope", "theta_inhibit_rate"),
        ("low", "low_envelope", "low_inhibit_rate"),
    ):
        inh = ir["inhibits"][name]
        assert inh["action_kind"] == "mute", name
        assert inh["action_release_ms"] == 200.0, name
        # Each watches its OWN derive through its OWN rate control: a swap
        # would resolve and pass a shape-only check while vetoing on the
        # wrong band. The derive is the identity's positional argument — see
        # test_high_beta_is_an_inhibit_that_mutes for why it is `linear` and
        # not `passthrough`.
        assert inh["metric"]["callee"] == "linear", name
        assert inh["metric"]["args"][0]["value"]["target"] == f"derive/{derive}", name
        assert inh["threshold"]["callee"] == "percentile", name
        pct = next(a["value"] for a in inh["threshold"]["args"] if a["name"] == "target_pct")
        assert pct["target"] == f"control/{rate}", name


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
    #
    # The metric must be a primitive call, so an existing derive is carried
    # through `linear(x, midpoint: 0 uV, slope: 1)` — the affine identity.
    # NOT `passthrough`, which reads as the obvious choice and is wrong twice
    # over: its implementation is an identity MONTAGE requiring a
    # single-channel source, and refrain-core never implemented it as a
    # compute primitive, so the protocol built on Python and raised
    # `RuntimeError: ... PoC: unsupported compute primitive "passthrough"` on
    # the Rust backend — which is the one a recorder session runs. Pinned by
    # callee here and by both backends in test_both_backends.py.
    assert hb["metric"]["callee"] == "linear"
    arg = hb["metric"]["args"][0]["value"]
    assert arg["target"] == "derive/high_beta_envelope"
    slope = next(a["value"] for a in hb["metric"]["args"] if a["name"] == "slope")
    midpoint = next(a["value"] for a in hb["metric"]["args"] if a["name"] == "midpoint")
    assert (slope["value"], midpoint["value"]) == (1.0, 0.0), "not the identity"
    assert hb["threshold"]["callee"] == "percentile"
    target_pct = next(a["value"] for a in hb["threshold"]["args"] if a["name"] == "target_pct")
    assert target_pct["target"] == "control/hbeta_inhibit_rate"
    # The window is pinned too: a drift to 10 s would chase short-term noise.
    window = next(a["value"] for a in hb["threshold"]["args"] if a["name"] == "window")
    assert (window["value"], window["unit"]) == (2.0, "min")


def test_in_baseline_mode_only_the_reward_threshold_goes_absolute():
    # An inhibit's threshold must be a literal constructor call, and choosing
    # between absolute(...) and percentile(...) is a choice at the top level,
    # not inside an argument where the `threshold_style` switch could be
    # folded. So moving theta and the low band into inhibits cost them their
    # baseline-mode microvolt thresholds: all four guards now chase 2-minute
    # rolling percentiles in BOTH styles, and only the SMR reward threshold
    # becomes an operator-set value.
    #
    # Pinned because it is a capability loss, not a tidy-up: a rolling
    # percentile cannot see a SUSTAINED elevation by construction - a trainee
    # drowsy throughout still has to beat their own 80th percentile to trip
    # the theta guard - and the absolute thresholds were the one configuration
    # that could. The header says what restoring them would take.
    ir = ir_to_json_obj(
        resolve(refrain.parse_file(str(PATH)), Q21, bindings={"threshold_style": "baseline"})
    )
    for name, inh in ir["inhibits"].items():
        assert inh["threshold"]["callee"] == "percentile", name
    # Only one declared threshold is left, and in baseline mode it reads the
    # operator's own microvolt control - the callee alone would pass on
    # absolute(value: <anything>).
    assert sorted(ir["thresholds"]) == ["smr_t"]
    call = ir["thresholds"]["smr_t"]["threshold_call"]
    assert call["callee"] == "absolute"
    value = next(a["value"] for a in call["args"] if a["name"] == "value")
    assert value["target"] == "control/smr_threshold_uv"


def test_duration_criterion_is_the_published_floor():
    # AASM defines a spindle as >= 0.5 s. Replaces the shipped 250 ms dwell,
    # and the dwell reads the control rather than a literal.
    ir = ir_to_json_obj(resolve(refrain.parse_file(str(PATH)), Q21))
    assert _num(ir["controls"]["spindle_duration"]["default"]) == 500.0
    ev = ir["reward"]["event"]
    dur = next(a["value"] for a in ev["args"] if a["name"] == "duration")
    assert dur["target"] == "control/spindle_duration"


def test_veto_defaults_stay_at_their_loose_settings():
    # What this establishes: the two band guards keep MARGINALLY loose
    # defaults. That is necessary and NOT sufficient for the case it was
    # written for - a trainee whose alpha peak sits at 12 Hz, inside the
    # low-band guard and the reward band at once.
    #
    # It cannot see that case at all. Both thresholds are rolling percentiles,
    # so they self-normalise: how often either guard fires is fixed by its
    # target_pct whatever the spectrum looks like, and these numbers cannot
    # move. What that trainee loses now is OBSERVABLE TIME - every sample the
    # low-band guard mutes freezes the dwell and silences the tone - so the
    # reward degrades by arriving later rather than by being vetoed.
    #
    # The 13-fold collapse measured on a synthetic 20 uV 12 Hz peak
    # (26 -> 2 reward events per 150 s) was measured under the OLD three-term
    # conjunction and does NOT describe this shape: there is no joint
    # condition left to collapse. Re-measuring it on this shape is still
    # owed - a behavioural test on an authored 12 Hz signal (the pattern in
    # test_alpha_theta_narrowband.py), or a replay with that subject's
    # spectrum.
    ir = ir_to_json_obj(resolve(refrain.parse_file(str(PATH)), Q21))
    assert ir["controls"]["theta_inhibit_rate"]["default"]["value"] >= 80
    assert ir["controls"]["low_inhibit_rate"]["default"]["value"] >= 85


def test_the_mute_guard_sits_at_the_rare_end_of_its_range():
    # The high-beta guard takes the SOUND away rather than withholding one
    # reward, and with a percentile threshold how often it fires is set by the
    # percentile, not by the trainee: at target P it is above itself
    # (100 - P)% of samples by construction. So the one guard that can silence
    # the tone must sit where crossings are RARE. 95 is the loosest its range
    # allows and matches the EMG guard's artifact_strictness; the inherited 75
    # would have muted a quarter of every block on a clean recording.
    #
    # Pinned because nothing else does: the two conjunction vetoes have the
    # test above, and this control is the one whose default decides how much
    # of the ungated tone a trainee hears.
    ir = ir_to_json_obj(resolve(refrain.parse_file(str(PATH)), Q21))
    hbeta = ir["controls"]["hbeta_inhibit_rate"]
    assert hbeta["default"]["value"] == 95
    # ...and that is the loose END, not a value with room above it.
    assert hbeta["range_high"]["value"] == 95
    # Looser than both conjunction vetoes, the opposite way round from
    # smr.refrain's 75, where high-beta cost one reward instead of the tone.
    for veto in ("theta_inhibit_rate", "low_inhibit_rate"):
        assert hbeta["default"]["value"] > ir["controls"][veto]["default"]["value"], veto


def test_no_guard_rate_can_be_read_as_a_reward_rate():
    # The recorder inverts a slider (shows and sends 100 - value) for an
    # adaptive up-train reward-rate control, decided STRUCTURALLY rather than
    # by name: recorder/backend/feedback/manifest.py's _is_reward_rate_control
    # looks for a control feeding `target_pct` of a declared percentile
    # THRESHOLD whose crossing drives an `above(...)` reward condition.
    #
    # Under the old shape the theta and low-band rates were excluded because
    # their thresholds fed `below(...)`. They are now excluded for a stronger
    # reason - they feed no declared threshold at all, only an inhibit's own
    # literal percentile - and `smr_reward_pct` is the only control that
    # reaches one. Pinned so a guard rate can never arrive in the UI with its
    # direction flipped.
    ir = ir_to_json_obj(resolve(refrain.parse_file(str(PATH)), Q21))
    feeding_thresholds = {
        next(
            a["value"]["target"]
            for a in t["threshold_call"]["args"]
            if a["name"] == "target_pct"
        ).removeprefix("control/")
        for t in ir["thresholds"].values()
        if t["threshold_call"]["callee"] == "percentile"
    }
    assert feeding_thresholds == {"smr_reward_pct"}


def test_every_advanced_control_exists():
    # advanced_controls is a hand-maintained list of names. A control removed
    # from the file leaves a dangling entry, which the recorder reads as a
    # control to hide - so the stale name hides nothing, and nothing says so.
    #
    # Read off the RESOLVED IR object, not ir_to_json_obj: the JSON emitter's
    # `controls` map carries only the numeric/typed controls and drops `mode`
    # and `placement` ones, so `site`, `artifact_guard` and `threshold_style`
    # would look dangling there.
    ir = resolve(refrain.parse_file(str(PATH)), Q21)
    declared = set(ir.controls)
    listed = {
        e["value"]
        for e in ir_to_json_obj(ir)["meta"]["advanced_controls"]["elements"]
    }
    assert listed - declared == set(), sorted(listed - declared)
    # ...and the two NOT listed are the basic pair, so a new control cannot
    # arrive un-triaged.
    assert declared - listed == {"threshold_style", "smr_reward_pct"}


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
