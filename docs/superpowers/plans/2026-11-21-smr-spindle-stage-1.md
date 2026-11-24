# SMR spindle protocol, stage 1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One new `protocols/eeg/smr_spindle.refrain` that rewards 12–16 Hz spindles on a single declared-latency envelope, with an always-on continuous tone and a ding on a 500 ms duration criterion.

**Architecture:** Structurally a copy of `protocols/eeg/smr.refrain` (its `site` placement control, `threshold_style` mode, amp-portable reference, EMG guard, staged session), with four changes: every envelope becomes a one-stage `band_envelope` carrying a declared latency; the reward band widens to 12–16 Hz; the duration criterion goes to 500 ms; and the continuous tone is ungated so it tracks amplitude rather than only sounding during a held reward. High-beta leaves the reward conjunction and becomes a mute.

**Tech Stack:** refrain v0.24.0 (Python + Rust `refrain_core`), `.refrain` DSL, pytest.

**Spec:** `coherence-recorder: docs/superpowers/specs/2026-11-21-smr-spindle-protocol-design.md`

## Global Constraints

- **refrain v0.24.0 only.** No `tolerance` on a hold and no `kind = "artifact"` on an inhibit — both are v0.25.0 parameters, and v0.24 refuses the IR wire version v0.25 emits. So **no dip-tolerant hold in this stage.**
- **Every envelope derive must be a bare `band_envelope`.** `tests/test_declared_latency.py::_classify` returns `"migrated"` only for a chain of exactly `["band_envelope"]`. A new file is not in `WAITING`, so a four-stage chain — or `band_envelope` followed by anything — fails as `"unlisted"`.
- **Each declared latency must be at or above `1000 / (hi - lo)` ms** at the band's default edges (`test_declared_latency_clears_the_bandwidth_floor`).
- `band_envelope(band: tuple_2_numbers, latency: duration, taps: ratio?)` — `band` and `latency` are both **required**.
- **Band edges stay `live_tunable = false`.** They bake at resolve time; the recorder refuses to caption a tunable edge, and `BandpassImpl` has no `update_control` hook.
- **`reward.event` must be a plain `dwell(...)`** whose condition is `all_of([...])` — two hardcoded resolver checks, and `_extract_dwell_components` returns an empty list otherwise, which blanks the live bottom strip and the debrief's per-veto breakdown.
- **An `inhibit`'s `threshold` and `action` must each be a literal constructor call.** A mode ternary does not fold there; fold it one level down, inside a call argument.
- Research Use Only. No clinical claims in any `meta` string.
- Declared latencies, verbatim from the spec's measurement (§11): **SMR 12–16 Hz at 320 ms** (floor 250), **theta 4–7 Hz at 340 ms** (floor 334), **low-band 8–12 Hz at 320 ms** (floor 250), **high-beta 16–30 Hz at 120 ms** (floor 72).

## Deviations from the spec, declared

1. **Thresholds are a rolling 2-minute percentile, not held per block.** REC-15 settled per-block holding, but `freeze(release:)` holds a *signal* at its last value — it is not a threshold-holding mechanism, and v0.24.0 has no other. Per-block holding arrives with REC-15.
2. **No dip-tolerant hold** — see Global Constraints.
3. **This file lands ahead of REC-15**, against the spec's decision 1. It adopts REC-15's *settled decisions* (loose optional theta veto, high-beta as a mute, muscle mute, always-on tone) rather than re-deriving them, so the two files should not drift. It does **not** touch `smr.refrain`, so that file's place in `WAITING` is undisturbed.

## Review Focus

- **A practitioner widens the band to 12–20 Hz.** Edges are tunable at resolve time, so the 320 ms declared latency would then sit far above an 8 Hz band's 125 ms floor — harmless. The dangerous direction is *narrowing*: 12–13 Hz has a 1000 ms floor, and the guard test only checks **defaults**, so a narrowed band silently ships a filter less accurate than the chain it replaced. Task 1 pins a test on the floor at the declared default and a comment naming the hazard; the engine cannot reject it at runtime.
- **The low-band veto sits inside the reward band for a trainee whose alpha peak is 12 Hz.** Then `below("low_envelope", ...)` vetoes the very signal being rewarded, and reward time collapses toward zero. Task 2 tests that the veto defaults loose enough (85th percentile) that this degrades rather than deadlocks.
- **The ungated tone with no EMG guard would sonify muscle.** The tone tracks raw amplitude with nothing gating it, so a jaw clench becomes a loud tone — the opposite of the contingency. Task 3 tests that the mute silences the tone, not just the ding.
- **`threshold_style = "baseline"` with unseeded voltages** gives a cold start whose absolute µV defaults were chosen for a 12–15 Hz band. Task 1 carries seeds on all four voltage controls.
- **A 500 ms criterion plus a new low-band veto may drive reward time under 15%**, the spec's back-out floor. No unit test can catch this; Task 3 records it as the replay gate that must run before the file is offered to a trainee.

---

### Task 1: The protocol file resolves, with declared-latency envelopes

**Files:**
- Create: `protocols/eeg/smr_spindle.refrain`
- Test: `tests/test_smr_spindle.py`

**Interfaces:**
- Consumes: nothing.
- Produces: protocol id `"smr_spindle"`; derives `smr_envelope`, `theta_envelope`, `low_envelope`, `high_beta_envelope`; thresholds `smr_t`, `theta_t`, `low_t`; controls `threshold_style`, `smr_reward_pct`, `site`, `smr_lo_hz`, `smr_hi_hz`, `theta_lo_hz`, `theta_hi_hz`, `low_lo_hz`, `low_hi_hz`, `hbeta_lo_hz`, `hbeta_hi_hz`, `smr_latency`, `theta_inhibit_rate`, `low_inhibit_rate`, `hbeta_inhibit_rate`, `artifact_guard`, `artifact_strictness`, `spindle_duration`, `smr_threshold_uv`, `theta_threshold_uv`, `low_threshold_uv`, `hbeta_threshold_uv`.

- [ ] **Step 1: Write the failing test**

Import `_chain` and `_num` from `tests/test_declared_latency.py` rather than
reimplementing them — that module already walks a derive's callee chain and reads a
number-or-default node.

```python
# tests/test_smr_spindle.py
from test_declared_latency import _chain, _num

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

def test_every_envelope_is_one_stage_with_its_declared_latency():
    ir = ir_to_json_obj(resolve(refrain.parse_file(str(PATH)), Q21))
    for derive, (_, _, want_ms) in _ENVELOPES.items():
        names, call = _chain(ir["derives"][derive]["expression"])
        assert names == ["band_envelope"], f"{derive} is {names}"
        args = {a["name"]: a["value"] for a in call["args"] if a["name"]}
        assert _num(args["latency"]) == want_ms

def test_each_declared_latency_clears_its_bandwidth_floor():
    for derive, (lo, hi, ms) in _ENVELOPES.items():
        assert ms >= 1000.0 / (hi - lo), derive

def test_band_edges_and_latency_are_not_live_tunable():
    # They bake at resolve time; a tunable edge is silently ignored by the
    # engine and refused a caption by the recorder.
    ir = ir_to_json_obj(resolve(refrain.parse_file(str(PATH)), Q21))
    for name in list(_BAND_EDGES) + ["smr_latency"]:
        assert ir["controls"][name]["live_tunable"] is False
```

- [ ] **Step 2: Run it and watch it fail**

Run: `pytest tests/test_smr_spindle.py -q`
Expected: FAIL — `smr_spindle.refrain` does not exist.

- [ ] **Step 3: Write `protocols/eeg/smr_spindle.refrain`**

Copy `protocols/eeg/smr.refrain` and change: each of the four `derive` blocks becomes a single `band_envelope(band: (lo, hi), latency: <control>)`; add the `low_envelope` derive and its `low_t` threshold and `low_lo_hz`/`low_hi_hz`/`low_inhibit_rate`/`low_threshold_uv` controls; `smr_hi_hz` default 16 Hz; `hbeta_lo_hz` default **16 Hz** so the veto's lower edge meets the reward band's upper edge with nothing open between (the shipped 20 Hz leaves 16–20 Hz unwatched — the spec's §7.1 correction). Add `smr_latency = duration { default = 320 ms; range = (250 ms, 600 ms); live_tunable = false }`. Keep the header comment block's structure and write the *reasons* for each changed default into it.

- [ ] **Step 4: Run both the new test and the library-wide guard**

Run: `pytest tests/test_smr_spindle.py tests/test_declared_latency.py -q`
Expected: PASS. The guard must classify every new envelope as `"migrated"`; if it reports `"unlisted"`, a chain has something after `band_envelope`.

- [ ] **Step 5: Commit**

```bash
git add protocols/eeg/smr_spindle.refrain tests/test_smr_spindle.py
git commit -m "Add a spindle-contingent SMR protocol on one declared-latency envelope"
```

---

### Task 2: The veto arrangement — high-beta mutes, it does not withhold

**Files:**
- Modify: `protocols/eeg/smr_spindle.refrain`
- Modify: `tests/test_smr_spindle.py`

**Interfaces:**
- Consumes: Task 1's derives and thresholds.
- Produces: `reward.event` as `dwell(condition: all_of([above smr, below theta, below low]), duration: spindle_duration)`; inhibits `emg` and `hbeta`, both with `mute(...)` actions.

- [ ] **Step 1: Write the failing tests**

```python
def test_reward_conjunction_is_smr_above_with_two_loose_vetoes():
    # REC-15: theta veto optional and loose; high-beta LEAVES the reward and
    # becomes a mute. So high_beta_envelope must not appear in the conjunction.
    ir = ir_to_json_obj(resolve(refrain.parse_file(str(PATH)), Q21))
    terms = _dwell_terms(ir)                      # [(callee, signal), ...]
    assert ("above", "smr_envelope") in terms
    assert ("below", "theta_envelope") in terms
    assert ("below", "low_envelope") in terms
    assert not any(s == "high_beta_envelope" for _, s in terms)

def test_high_beta_is_an_inhibit_that_mutes():
    # An inhibit's action lands in the IR as action_kind/action_release_ms,
    # not as a nested call node.
    ir = ir_to_json_obj(resolve(refrain.parse_file(str(PATH)), Q21))
    assert ir["inhibits"]["hbeta"]["action_kind"] == "mute"

def test_duration_criterion_is_the_published_floor():
    # AASM defines a spindle as >= 0.5 s. Replaces the shipped 250 ms dwell.
    ir = ir_to_json_obj(resolve(refrain.parse_file(str(PATH)), Q21))
    assert _num(ir["controls"]["spindle_duration"]["default"]) == 500.0

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
```

- [ ] **Step 2: Run them and watch them fail**

Run: `pytest tests/test_smr_spindle.py -q -k "conjunction or high_beta or duration or deadlock or reward_rates"`
Expected: FAIL — high-beta is still a `below(...)` term in the conjunction, inherited from the copy.

- [ ] **Step 3: Rewire the reward block and add the high-beta inhibit**

Move `below("high_beta_envelope", "hbeta_t")` out of `all_of([...])`. Add an `inhibit "hbeta"` whose `metric` is the `high_beta_envelope` derive, whose `threshold` is a literal `percentile(target_pct: hbeta_inhibit_rate, window: 2 min)`, and whose `action` is `mute(release: 200 ms)`. Add the `low_envelope` veto term to the conjunction. Replace `duration: 250 ms` with `duration: spindle_duration` and add `spindle_duration = duration { default = 500 ms; range = (250 ms, 1500 ms); live_tunable = true }`.

- [ ] **Step 4: Run the file's tests and the library gates**

Run: `pytest tests/test_smr_spindle.py tests/test_declared_latency.py tests/test_catalog.py tests/test_schema_fields.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add protocols/eeg/smr_spindle.refrain tests/test_smr_spindle.py
git commit -m "High-beta mutes the spindle protocol instead of withholding its reward"
```

---

### Task 3: Two channels — an always-on tone and a ding

**Files:**
- Modify: `protocols/eeg/smr_spindle.refrain`
- Modify: `tests/test_smr_spindle.py`

**Interfaces:**
- Consumes: Tasks 1 and 2.
- Produces: `output { audio_chime = reward.event; audio_gain = reward.continuous }`, which lands in the IR under the singular key `output` as two `reward_field` nodes.

- [ ] **Step 1: Write the failing tests**

```python
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
    assert gain["field_path"] == "continuous"

def test_the_ding_is_the_reward_event():
    ir = ir_to_json_obj(resolve(refrain.parse_file(str(PATH)), Q21))
    chime = ir["output"]["audio_chime"]
    assert (chime["node"], chime["field_path"]) == ("reward_field", "event")

def test_the_mute_silences_the_tone_not_only_the_ding():
    # An ungated tone tracks raw amplitude, so without this a jaw clench
    # becomes a LOUD tone -- the inverse of the contingency.
    ir = ir_to_json_obj(resolve(refrain.parse_file(str(PATH)), Q21))
    for name in ("emg", "hbeta"):
        assert ir["inhibits"][name]["action_kind"] == "mute"
```

- [ ] **Step 2: Run them and watch them fail**

Run: `pytest tests/test_smr_spindle.py -q -k "ungated or ding or silences"`
Expected: FAIL — `audio_gain` is still the inherited conditional.

- [ ] **Step 3: Replace the output block**

`audio_gain = reward.continuous`, keeping `reward.continuous` as the `sigmoid("smr_envelope" / "smr_t", midpoint: 1.0, steepness: 3)` from the template. Write into the header comment that the tone's delay is envelope plus transport plus audio **on rising edges only** — the renderer attacks at 50 ms and releases at 300 ms (`audio_renderer.py:125-126`), so the falling edge is ~620 ms until that asymmetry is fixed, and cite the recorder's latency document §9 for the fix shape.

- [ ] **Step 4: Run the whole suite**

Run: `pytest tests/ -q`
Expected: PASS, except the five pre-existing `[rust]` parametrisations that raise `ImportError` for the `refrain_core` wheel CI builds with maturin.

- [ ] **Step 5: Commit**

```bash
git add protocols/eeg/smr_spindle.refrain tests/test_smr_spindle.py
git commit -m "Ungate the spindle protocol's tone so shaping arrives before the ding"
```

---

## After the plan: the gate that decides whether this is offered to anyone

Reward time must land **25–40% median on the replay corpus at default controls**, backing out below 15% or above 60% (REC-15's gate, from Arns 2014, recorded as contested). A 500 ms criterion and a new low-band veto both push reward time *down*, so if it lands under 15% the 500 ms criterion becomes a control with a lower default rather than a fixed constant. Run it with `tools/session_report/` against the corpus before this file is offered in the picker. **No unit test substitutes for this.**
