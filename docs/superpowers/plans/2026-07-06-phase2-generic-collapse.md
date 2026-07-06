# Phase 2 (slice 1): collapse the generic adaptive/baseline pairs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fold the 16 generic `<target>_<site>` + `<target>_<site>_baseline` protocol pairs into 16 single `mode`-based cores (using the `threshold_style` mode control from `refrain 0.12.0`), and add plain-language `title`/`summary`/`family` metadata — cutting the generic set from 32 files to 16 while making each one human-readable.

**Architecture:** The generator `tools/gen_seed_protocols.py` is reworked to emit ONE file per `TABLE` entry: a `threshold_style = mode { choices = ["adaptive","baseline"]; default = "adaptive" }` control drives a conditional threshold `type` (`... == "baseline" ? absolute(value: thr_uv) : percentile(target_pct: reward_pct, window: 2 min)`), so the single file resolves to the old adaptive protocol by default and the old baseline protocol when bound. The 16 `_baseline` files are deleted; the catalog is regenerated; the collapsed cores are added to `KNOWN_GAPS` (a `mode` control isn't editor-renderable yet, so they report `in_subset = False`).

**Tech Stack:** Python 3.12, `refrain 0.12.0` (installed editable in `.venv`), `pytest`, `jsonschema`.

## Global Constraints

- **Working directory / repo:** all work in `/Users/jcroall/git/refrain-protocols`, on a dedicated branch (e.g. `feat/phase2-generic-collapse`). Run every command from that directory. Use the repo's venv Python: **`.venv/bin/python`** (it has `refrain 0.12.0`; bare `python`/`python3` do NOT).
- **Scope: the generic generated set only.** Do NOT touch `protocols/brainbit/**` (the recorder reads only that folder), the hand-authored specials (`alpha_theta_pz`, `composite_smr_theta_cz`, `alpha_coherence_c3c4`, `faa_f3f4`, `hrv_resonance`, `critical_fluctuation`), or `drafts/scp_cz.refrain`. Only the 16 `TABLE`-generated pairs collapse.
- **Behavior-preserving:** each collapsed core must resolve to the SAME IR as the old adaptive file by default, and the SAME IR as the old baseline file when resolved with `bindings={"threshold_style": "baseline"}`. Verified in Task 4.
- **Additive metadata:** `title`, `summary`, `family`, `feedback_style`, `session_shape` are new optional meta fields; `threshold_style` gains a `"selectable"` value. Do not remove or rename existing fields (the portal's Go parser and the recorder read them).
- **Spec:** `docs/superpowers/specs/2026-07-05-refrain-configurable-protocols-design.md`.
- TDD: write the failing test / assertion first, watch it fail, implement, watch it pass, commit.

## File Structure

- `schema/protocol-meta.schema.json` — add the 5 new optional properties + the `"selectable"` threshold_style enum value.
- `tools/gen_seed_protocols.py` — rework `TABLE` (add `title`/`summary`), `_meta()`, and `emit()` to produce one `mode`-based file per entry; `main()` stops double-emitting.
- `protocols/<target>_<site>.refrain` × 16 — regenerated (collapsed).
- `protocols/<target>_<site>_baseline.refrain` × 16 — deleted.
- `catalog.json` — regenerated (count 59 → 43).
- `tests/test_corpus_roundtrip.py` — add the 16 collapsed cores to `KNOWN_GAPS`.
- `tests/test_mode_collapse.py` — NEW: the behavior-preserving regression gate.
- `tests/test_schema_fields.py` — NEW: validates the new schema fields.

---

### Task 1: Schema — allow the new metadata fields + `selectable` threshold style

**Files:**
- Modify: `schema/protocol-meta.schema.json`
- Test: `tests/test_schema_fields.py` (new)

**Interfaces:**
- Produces: the schema accepts a meta object containing `title` (string), `summary` (string), `family` (string), `feedback_style` (`"discrete"|"graded"|"modulating"`), `session_shape` (`"single"|"staged"|"deep"`), and `threshold_style = "selectable"`; still rejects a doc missing `description`/`status`/`goals`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_schema_fields.py`:

```python
import json
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schema" / "protocol-meta.schema.json").read_text())

_VALID = {
    "description": "SMR/THETA up-train at Cz",
    "status": "draft",
    "goals": ["adhd_attention"],
    "title": "Steady focus — boost SMR (top of head)",
    "summary": "Rewards a calm-but-alert rhythm; the bar can adapt to you or hold fixed.",
    "family": "smr_theta_cz",
    "feedback_style": "discrete",
    "session_shape": "staged",
    "threshold_style": "selectable",
}


def test_new_meta_fields_validate():
    jsonschema.validate(_VALID, SCHEMA)  # must not raise


def test_selectable_threshold_style_allowed():
    doc = {"description": "d", "status": "draft", "goals": ["adhd_attention"],
           "threshold_style": "selectable"}
    jsonschema.validate(doc, SCHEMA)


def test_bad_feedback_style_rejected():
    doc = {"description": "d", "status": "draft", "goals": ["adhd_attention"],
           "feedback_style": "loud"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(doc, SCHEMA)


def test_required_fields_still_enforced():
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"status": "draft", "goals": ["adhd_attention"]}, SCHEMA)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_schema_fields.py -q`
Expected: FAIL — `test_selectable_threshold_style_allowed` raises `ValidationError` (`"selectable"` not in the enum) and `test_bad_feedback_style_rejected` raises the *wrong* way (there's no `feedback_style` property yet, so an invalid value is currently *accepted* → the `pytest.raises` fails).

- [ ] **Step 3: Add the fields to the schema**

In `schema/protocol-meta.schema.json`, add `"selectable"` to the `threshold_style` enum (line 45):

```json
    "threshold_style": {
      "description": "Drives the Adaptive / Baseline filter chip. 'selectable' = the protocol exposes a `mode` control offering both.",
      "enum": ["adaptive", "baseline", "crossover", "selectable"]
    },
```

And add these properties inside `"properties"` (e.g. after `description` at line 9):

```json
    "title": { "type": "string", "description": "Plain-language, goal-first name shown as the primary label (e.g. 'Calm the mind — boost alpha')." },
    "summary": { "type": "string", "description": "One non-specialist sentence describing what the protocol trains." },
    "family": { "type": "string", "description": "Shared id across a concept's variant files; the picker groups by it." },
    "feedback_style": {
      "description": "How feedback is delivered.",
      "enum": ["discrete", "graded", "modulating"]
    },
    "session_shape": {
      "description": "Run structure.",
      "enum": ["single", "staged", "deep"]
    },
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_schema_fields.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add schema/protocol-meta.schema.json tests/test_schema_fields.py
git commit -m "feat(schema): add title/summary/family/feedback_style/session_shape + selectable threshold_style"
```

---

### Task 2: Rework the generator to emit one `mode`-based core per target

**Files:**
- Modify: `tools/gen_seed_protocols.py`
- Test: `tests/test_generator_mode.py` (new)

**Interfaces:**
- Consumes: `refrain 0.12.0` `mode` control; the schema fields from Task 1.
- Produces: `main()` writes exactly one `<name>.refrain` per `TABLE` entry (16 files, no `_baseline`). Each has a `threshold_style` mode control, both `reward_pct` and `thr_uv` controls, a conditional threshold `type`, and `title`/`summary`/`family`/`threshold_style="selectable"` in `meta`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_generator_mode.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_generator_mode.py -q`
Expected: FAIL — the current generator still emits `_baseline` files (`test_generator_emits_one_file_per_target_no_baseline` fails) and the generated `smr_theta_cz.refrain` has no `mode` control.

- [ ] **Step 3: Rework `gen_seed_protocols.py`**

Replace the `TABLE` entries with the 8-tuple form adding `title` and `summary` (verbatim — these are the curated plain-language labels):

```python
TABLE = [
    # name, band, dir, site, goals, band_tags, evidence, citation, title, summary
    ("smr_theta_cz",    (12,15), "up",  "Cz", ["adhd_attention","sensorimotor_sleep"], ["smr","theta"], "established", "Sterman; Lubar; Arns 2009", "Steady focus — boost SMR, calm theta (top of head)", "Rewards a calm-but-alert sensorimotor rhythm at the top of the head while keeping drowsy theta down."),
    ("theta_beta_cz",   (15,18), "up",  "Cz", ["adhd_attention"], ["beta","theta"], "established", "Lubar (theta/beta)", "Sharpen attention — beta up over theta (top of head)", "Trains focused beta up relative to daydreamy theta at the top of the head."),
    ("theta_beta_fz",   (15,18), "up",  "Fz", ["adhd_attention"], ["beta","theta"], "established", "Lubar (theta/beta); frontal-theta excess", "Sharpen attention — beta up over theta (forehead)", "Trains focused beta up relative to theta at the forehead, where theta excess is common in inattention."),
    ("theta_down_cz",   (4,8),   "down","Cz", ["adhd_attention"], ["theta"], "probable", "Lubar (theta downtraining)", "Quiet daydreaming — lower theta (top of head)", "Rewards lowering the slow, drifting theta rhythm at the top of the head."),
    ("theta_down_fz",   (4,8),   "down","Fz", ["adhd_attention"], ["theta"], "probable", "Lubar; frontal-theta excess", "Quiet daydreaming — lower theta (forehead)", "Rewards lowering excess frontal theta associated with mind-wandering."),
    ("slow_down_cz",    (2,7),   "down","Cz", ["alertness_performance","adhd_attention"], ["delta","theta"], "exploratory", "Thatcher; Walker (qEEG-guided slowing)", "Clear mental fog — lower slow waves (top of head)", "Rewards reducing sluggish delta/theta slow-wave activity at the top of the head."),
    ("slow_down_fz",    (2,7),   "down","Fz", ["alertness_performance","adhd_attention"], ["delta","theta"], "exploratory", "Thatcher; Walker (frontal slowing)", "Clear mental fog — lower slow waves (forehead)", "Rewards reducing frontal delta/theta slow-wave activity linked to under-arousal."),
    ("smr_up_c4",       (12,15), "up",  "C4", ["sensorimotor_sleep","calm_anxiety"], ["smr"], "established", "Sterman; Hoedlmoser 2008", "Wind down for sleep — boost SMR (right side)", "Rewards the calm sensorimotor rhythm over the right sensorimotor cortex, associated with sleep spindles and settling."),
    ("beta_up_c3",      (15,18), "up",  "C3", ["alertness_performance","adhd_attention"], ["beta"], "probable", "Othmer & Othmer (arousal model)", "Alert and engaged — boost beta (left side)", "Rewards raising engaged beta activity over the left sensorimotor cortex."),
    ("beta_up_fz",      (15,18), "up",  "Fz", ["alertness_performance"], ["beta"], "probable", "frontal beta activation", "Alert and engaged — boost beta (forehead)", "Rewards raising engaged frontal beta activity."),
    ("alpha_up_pz",     (8,12),  "up",  "Pz", ["calm_anxiety","deep_meditative"], ["alpha"], "probable", "Hardt & Kamiya 1978", "Calm the mind — boost alpha (back of head)", "Rewards raising relaxed alpha waves at the back of the head, the classic eyes-closed calm state."),
    ("hibeta_down_cz",  (22,30), "down","Cz", ["calm_anxiety"], ["high-beta"], "probable", "clinical convention (anxiety/rumination)", "Ease over-arousal — quiet high-beta (top of head)", "Rewards lowering fast high-beta activity associated with anxiety and rumination."),
    ("peak_alpha_up_pz",(9,11),  "up",  "Pz", ["alertness_performance","deep_meditative"], ["alpha"], "exploratory", "Hanslmayr; Gruzelier 2014", "Sharpen peak alpha (back of head)", "Rewards raising the individual peak-alpha frequency band at the back of the head."),
    ("fm_theta_up_fz",  (4,8),   "up",  "Fz", ["deep_meditative","alertness_performance"], ["theta"], "exploratory", "Ishihara & Yoshii; Gruzelier", "Frontal-midline theta — focused calm (forehead)", "Rewards raising frontal-midline theta, associated with focused absorption and meditation."),
    ("alpha_down_pz",   (8,12),  "down","Pz", ["trauma_recovery","deep_meditative"], ["alpha"], "probable", "Kluetsch/Ros/Lanius 2014; Nicholson 2016", "Down-regulate alpha (back of head)", "Rewards lowering alpha at the back of the head, used in trauma-oriented desensitization work."),
    ("theta_up_pz",     (4,8),   "up",  "Pz", ["deep_meditative"], ["theta"], "exploratory", "Gruzelier (creativity/deep states)", "Theta up — reverie state (back of head)", "Rewards raising theta at the back of the head, associated with hypnagogic, creative reverie states."),
]
```

Replace `_meta()` to add the plain-language + family fields and set `threshold_style = "selectable"`:

```python
def _meta(name, desc, ev, cite, goals, bands, site, direction, title, summary):
    g = ", ".join(f'"{x}"' for x in goals)
    b = ", ".join(f'"{x}"' for x in bands)
    return f"""\
  meta {{
    version         = "0.1.0"
    title           = "{title}"
    summary         = "{summary}"
    family          = "{name}"
    description     = "{desc}"
    status          = "draft"
    evidence        = "{ev}"
    citation        = "{cite}"
    goals           = [{g}]
    bands           = [{b}]
    site            = "{site}"
    direction       = "{direction}"
    threshold_style = "selectable"
    feedback_style  = "discrete"
    session_shape   = "staged"
    hardware        = "generic"
  }}"""
```

Replace `emit()` so it takes no `baseline` flag and writes one file with the mode control + conditional threshold + both controls:

```python
def emit(name, band, direction, site, goals, bands, ev, cite, title, summary):
    lo, hi = band
    ref = _SITE_REF[site]
    cmp = "above" if direction == "up" else "below"
    desc = f"{'/'.join(bands).upper()} {direction}-train at {site}"

    center = math.sqrt(lo * hi)
    ratio = hi / lo
    c_lo, c_hi = round(center * 0.8, 2), round(center * 1.2, 2)
    bandpass_call = f"bandpass(center: env_center, bandwidth: ratio({ratio:.6g}), order: 4)"
    center_control = (
        f'    env_center = frequency {{\n'
        f'      default = {center:.6g} Hz\n'
        f'      range   = ({c_lo} Hz, {c_hi} Hz)\n'
        f'      label   = "{"/".join(bands).upper()} band center"\n'
        f'    }}'
    )

    pct = 70 if direction == "up" else 30
    p_lo, p_hi = (50, 90) if direction == "up" else (10, 50)

    thr = (
        '    type = threshold_style == "baseline"\n'
        '             ? absolute(value: thr_uv)\n'
        '             : percentile(target_pct: reward_pct, window: 2 min)\n'
        '    live_tunable = true'
    )
    controls = f"""
  controls {{
    threshold_style = mode {{
      choices = ["adaptive", "baseline"]
      default = "adaptive"
      label   = "Threshold style"
    }}
{center_control}
    reward_pct = percent {{
      default      = {pct}
      range        = ({p_lo}, {p_hi})
      label        = "Target reward %"
      live_tunable = true
    }}
    thr_uv = voltage {{
      default      = 2.0 uV
      range        = (0.5 uV, 30.0 uV)
      label        = "Threshold (baseline-seeded)"
      live_tunable = true
    }}
  }}"""

    body = f"""\
// {name}.refrain  —  DRAFT (status=draft, untested)
// {desc}.  {cite}
protocol "{name}" {{
{_meta(name, desc, ev, cite, goals, bands, site, direction, title, summary)}

  requires {{
    sample_rate = ">= 256 Hz"
    channels    = ["{site}"]
  }}

  input "raw" {{ montage = referential(active: "{site}", reference: "{ref}") }}

  derive "env" {{
    from = "raw"
    pipeline = [
      {bandpass_call},
      hilbert(),
      magnitude(),
      smooth(tau: 250 ms),
    ]
  }}

  threshold "env_t" {{
    signal = "env"
{thr}
  }}

  reward {{
    event      = dwell(condition: {cmp}("env", "env_t"), duration: 250 ms)
    continuous = sigmoid("env" / "env_t", midpoint: 1.0, steepness: 3)
  }}

  output {{
    audio_chime = reward.event
    audio_gain  = reward.event.holds ? reward.continuous : 0
  }}
{controls}
{OPERANT_SESSION}
}}
"""
    (OUT / f"{name}.refrain").write_text(body)
    return name
```

Replace `main()` to emit one file per entry:

```python
def main():
    OUT.mkdir(parents=True, exist_ok=True)
    written = []
    for name, band, direction, site, goals, bands, ev, cite, title, summary in TABLE:
        written.append(emit(name, band, direction, site, goals, bands, ev, cite, title, summary))
    for f in sorted(written):
        print("  wrote protocols/%s.refrain" % f)
    print(f"{len(written)} mode-based protocols generated (all status=draft).")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_generator_mode.py -q`
Expected: PASS — one file per target, no baselines, `smr_theta_cz` has the mode control and resolves percentile (default) / absolute (baseline binding).

- [ ] **Step 5: Commit** (generator + regenerated files together — the regen already ran in the test)

```bash
git add tools/gen_seed_protocols.py protocols/*.refrain tests/test_generator_mode.py
git commit -m "feat(generator): emit one mode-based core per target (collapse adaptive/baseline)"
```

---

### Task 3: Delete stale baselines, regenerate catalog, update KNOWN_GAPS

**Files:**
- Delete: `protocols/*_baseline.refrain` (the 16 stale files)
- Modify: `catalog.json` (regenerated), `tests/test_corpus_roundtrip.py` (`KNOWN_GAPS`)

**Interfaces:**
- Consumes: the collapsed cores from Task 2.
- Produces: 43 `.refrain` files total; `catalog.json` count = 43; the 16 collapsed cores listed in `KNOWN_GAPS` so `test_in_subset_round_trips_to_equal_ir` does not assert them in-subset.

- [ ] **Step 1: Remove the now-duplicate baseline files**

Run:
```bash
git rm protocols/*_baseline.refrain
```
Expected: 16 files removed (`alpha_down_pz_baseline`, `alpha_up_pz_baseline`, `beta_up_c3_baseline`, `beta_up_fz_baseline`, `fm_theta_up_fz_baseline`, `hibeta_down_cz_baseline`, `peak_alpha_up_pz_baseline`, `slow_down_cz_baseline`, `slow_down_fz_baseline`, `smr_theta_cz_baseline`, `smr_up_c4_baseline`, `theta_beta_cz_baseline`, `theta_beta_fz_baseline`, `theta_down_cz_baseline`, `theta_down_fz_baseline`, `theta_up_pz_baseline`).

- [ ] **Step 2: Add the collapsed cores to KNOWN_GAPS + write the failing check**

In `tests/test_corpus_roundtrip.py`, extend `KNOWN_GAPS` (the set literal) with the 16 collapsed core filenames, each annotated as a mode-collapse gap:

```python
    # Mode-collapsed cores: the `mode` control isn't editor-renderable yet, so
    # describe() reports in_subset=False. Editor round-trip support for mode is
    # a later enhancement; until then these are documented gaps.
    "alpha_down_pz.refrain", "alpha_up_pz.refrain", "beta_up_c3.refrain",
    "beta_up_fz.refrain", "fm_theta_up_fz.refrain", "hibeta_down_cz.refrain",
    "peak_alpha_up_pz.refrain", "slow_down_cz.refrain", "slow_down_fz.refrain",
    "smr_theta_cz.refrain", "smr_up_c4.refrain", "theta_beta_cz.refrain",
    "theta_beta_fz.refrain", "theta_down_cz.refrain", "theta_down_fz.refrain",
    "theta_up_pz.refrain",
```

- [ ] **Step 3: Regenerate the catalog**

Run: `.venv/bin/python tools/build_catalog.py`
Expected: `catalog.json: 43 protocols (...)`.

- [ ] **Step 4: Run the full library suite to verify it is green**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS — `test_parses` (all 43 parse), `test_meta_schema` (required fields present), `test_catalog_current` (count 43 == files), `test_corpus_roundtrip` (collapsed cores flagged as gaps, remaining specials still round-trip, `test_known_gaps_stay_flagged` confirms each collapsed core reports `in_subset=False`).

- [ ] **Step 5: Commit**

```bash
git add -A protocols/ catalog.json tests/test_corpus_roundtrip.py
git commit -m "chore: drop 16 duplicate baseline files, regen catalog (59->43), flag mode cores as editor gaps"
```

---

### Task 4: Behavior-preserving regression gate

**Files:**
- Test: `tests/test_mode_collapse.py` (new)

**Interfaces:**
- Consumes: the collapsed cores.
- Produces: proof that every collapsed core resolves to a percentile threshold by default and an absolute threshold under `threshold_style="baseline"`, against `amp=None`.

- [ ] **Step 1: Write the test**

Create `tests/test_mode_collapse.py`:

```python
from pathlib import Path

import pytest

from refrain.parser import parse
from refrain.resolver import resolve

ROOT = Path(__file__).resolve().parents[1]

# The 16 collapsed generic cores (families that had adaptive+baseline pairs).
_COLLAPSED = [
    "alpha_down_pz", "alpha_up_pz", "beta_up_c3", "beta_up_fz", "fm_theta_up_fz",
    "hibeta_down_cz", "peak_alpha_up_pz", "slow_down_cz", "slow_down_fz",
    "smr_theta_cz", "smr_up_c4", "theta_beta_cz", "theta_beta_fz",
    "theta_down_cz", "theta_down_fz", "theta_up_pz",
]


@pytest.mark.parametrize("name", _COLLAPSED)
def test_default_resolves_adaptive_percentile(name):
    src = (ROOT / "protocols" / f"{name}.refrain").read_text()
    ir = resolve(parse(src))  # amp=None; default threshold_style="adaptive"
    assert ir.thresholds["env_t"].threshold_call.callee == "percentile"


@pytest.mark.parametrize("name", _COLLAPSED)
def test_baseline_binding_resolves_absolute(name):
    src = (ROOT / "protocols" / f"{name}.refrain").read_text()
    ir = resolve(parse(src), bindings={"threshold_style": "baseline"})
    assert ir.thresholds["env_t"].threshold_call.callee == "absolute"
```

- [ ] **Step 2: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_mode_collapse.py -q`
Expected: PASS — 32 checks (16 cores × 2 modes), proving each single file covers both the old adaptive and old baseline behavior.

- [ ] **Step 3: Run the whole suite once more (final regression)**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS — full library suite green on the collapsed set.

- [ ] **Step 4: Commit**

```bash
git add tests/test_mode_collapse.py
git commit -m "test: regression gate — every collapsed core resolves adaptive+baseline"
```

---

## Self-Review

**Spec coverage (slice 1 of Phase 2):**
- Spec "collapse the adaptive/baseline pairs into single `mode`-based protocols" → Tasks 2–4. ✓
- Spec "add plain-language `title`/`summary`/`family` + explicit tags" → Tasks 1–2. ✓
- Spec "additive metadata; portal tolerates it" → Task 1 (additive schema; the portal ignores unknown keys). ✓
- Spec "regenerate catalog; KNOWN_GAPS for mode cores" → Task 3. ✓
- Spec "regression-gate; don't break downstream" → Task 4 + Global Constraint leaving `protocols/brainbit/`, specials, and drafts untouched (the recorder reads only `protocols/brainbit/`; the portal parses uploaded files). ✓
- Out of this slice: BrainBit collapse, hardware→amp-profile merge, feedback/session mode collapse → deliberately deferred to later Phase 2 slices coordinated with Phase 3.

**Placeholder scan:** every code step shows the exact code (including all 16 curated titles/summaries) and every run step gives an exact `.venv/bin/python` command + expected result. No TBD/"similar to".

**Type consistency:** `threshold_style == "baseline" ? absolute(...) : percentile(...)` matches the `mode` control fold shipped in `refrain 0.12.0`; the regression assertions read `ir.thresholds["env_t"].threshold_call.callee` (the real `IRThreshold`/`IRCall` fields). The 16-name list is identical in Tasks 3 and 4 and matches the `TABLE` names in Task 2.
