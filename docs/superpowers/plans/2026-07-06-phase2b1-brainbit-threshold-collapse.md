# Phase 2 (slice B1): collapse the 4 BrainBit adaptive/baseline pairs — Implementation Plan

> **For agentic workers:** implement task-by-task; verify IR-equivalence before deleting anything.

**Goal:** Fold each of the four BrainBit adaptive/baseline pairs into ONE `mode`-based file (keeping the *adaptive* file's name so the recorder's `default_protocol` and discovery stay intact), using the `threshold_style` mode control from `refrain 0.12.0`. BrainBit set 20 → 16. Behavior-preserving.

**Tech Stack:** Python 3.12, `refrain 0.12.0` in `.venv`, `pytest`.

## Global Constraints

- Work in `/Users/jcroall/git/refrain-protocols` on branch `feat/phase2b1-brainbit-threshold-collapse`. Use **`.venv/bin/python`** for everything.
- **Keep the adaptive filenames.** The recorder's `default_protocol = "smr_classic_cz_brainbit.refrain"` and its `protocols_dir = protocols/brainbit`; renaming/removing the *adaptive* files breaks it. Only the `_baseline` twins get deleted.
- **Behavior-preserving (the gate):** the collapsed file must resolve to the old *adaptive* file's IR by default, and the old *baseline* file's IR under `bindings={"threshold_style":"baseline"}` — for the `derives`, `inhibits`, `reward`, `output`, `inputs` sections and each threshold's `threshold_call`. (The `controls` map, `session`, protocol `name`, `meta`, and threshold `live_tunable` flags MAY differ — those are the intended additive/benign deltas.)
- Scope: only these 4 pairs in `protocols/brainbit/`. Do not touch other BrainBit files, the generic set, specials, or drafts.
- BrainBit files are NOT in `tests/test_corpus_roundtrip.py`'s glob (top-level `protocols/*.refrain` only), so **no `KNOWN_GAPS` change is needed.**

## The recipe (applied per pair)

Edit the **adaptive** (keep) file in place:

1. **meta:** change `summary` to mention both modes; add `threshold_style = "selectable"`. Apply any per-pair meta note in the table (evidence / safety_monitoring).
2. **Each differing threshold:** replace its `type = percentile(...)` line with a mode conditional, and ensure `live_tunable = true`:
   ```
   type = threshold_style == "baseline"
            ? absolute(value: <voltage_control>)
            : percentile(<the original percentile args>)
   ```
3. **controls:** add the mode control at the top of the block, and add the baseline voltage control(s) at the bottom:
   ```
   threshold_style = mode { choices = ["adaptive", "baseline"]; default = "adaptive"; label = "Threshold style" }
   ```
4. **session:** keep the adaptive file's `warmup` duration (120 s) unchanged — it is a valid superset for the baseline seed handler (which uses only the last 60 s), so both modes work. Do NOT shorten it to 90 s.
5. Delete the `_baseline` twin.

The voltage control block format (match the file's existing indent/style):
```
    <name>_uv = voltage {
      default      = <D> uV
      range        = (<LO> uV, <HI> uV)
      label        = "<Label>"
      live_tunable = true
    }
```

## Per-pair data (exact values, taken from the current files)

**Pair 1 — `smr_classic_cz_brainbit.refrain`** (delete `smr_classic_baseline_cz_brainbit.refrain`)
- `smr_t`: `percentile(target_pct: smr_reward_pct, window: 2 min)` → baseline `absolute(value: smr_threshold_uv)`; add `smr_threshold_uv` voltage default 2.0, range (0.5, 10.0), label "SMR threshold".
- `theta_t`: `percentile(target_pct: theta_inhibit_rate, window: 2 min)` → baseline `absolute(value: theta_threshold_uv)`; add `theta_threshold_uv` voltage default 8.0, range (2.0, 30.0), label "Theta threshold".
- Keep existing percent controls `smr_reward_pct`, `theta_inhibit_rate`. EMG inhibit unchanged. Meta: no evidence/safety change.

**Pair 2 — `smr_graded_cz_brainbit.refrain`** (delete `smr_graded_baseline_cz_brainbit.refrain`)
- `smr_t`: `percentile(target_pct: 50, window: 2 min)` → baseline `absolute(value: smr_anchor_uv)`; add `smr_anchor_uv` voltage default 2.0, range (0.5, 10.0), label "SMR anchor".
- `theta_t`: `percentile(target_pct: 50, window: 2 min)` → baseline `absolute(value: theta_anchor_uv)`; add `theta_anchor_uv` voltage default 5.0, range (1.0, 20.0), label "Theta anchor".
- NOTE: the adaptive graded thresholds have no percent controls (the `50` is a literal) — that's fine, keep the literal in the percentile branch. The adaptive thresholds are NOT currently `live_tunable`; adding `live_tunable = true` for baseline is an accepted benign delta. Keep the weight controls `w_smr`, `w_theta`.

**Pair 3 — `smr_up_c4_brainbit.refrain`** (delete `smr_up_c4_baseline_brainbit.refrain`)
- `smr_t`: `percentile(target_pct: smr_reward_pct, window: 2 min)` → baseline `absolute(value: smr_threshold_uv)`; add `smr_threshold_uv` voltage default 2.0, range (0.5, 10.0), label "SMR threshold".
- Only one threshold (no theta). The high-beta artifact guard (`hbeta_t`) stays adaptive — unchanged. Keep percent `smr_reward_pct`. Meta: keep `evidence = "clinical"` (do not downgrade to demo).

**Pair 4 — `beta_focus_staged_fz_brainbit.refrain`** (delete `beta_focus_baseline_staged_fz_brainbit.refrain`)
- `beta_t`: `percentile(target_pct: beta_reward_pct, window: 2 min)` → baseline `absolute(value: beta_threshold_uv)`; voltage default 1.5, range (0.3, 8.0), label "Beta threshold".
- `theta_t`: `percentile(target_pct: theta_inhibit_rate, window: 2 min)` → baseline `absolute(value: theta_threshold_uv)`; voltage default 6.0, range (1.0, 25.0), label "Theta threshold".
- `hbeta_t`: `percentile(target_pct: hbeta_inhibit_rate, window: 2 min)` → baseline `absolute(value: hbeta_threshold_uv)`; voltage default 1.0, range (0.2, 6.0), label "High-beta threshold".
- Keep percents `beta_reward_pct`, `theta_inhibit_rate`, `hbeta_inhibit_rate`. Meta: set `safety_monitoring = ["pre_session_check", "intra_session_clinician_observation"]` (union of the two).

## Task 1 — collapse + verify each pair

For each pair (do all 4): apply the recipe, then **before deleting the baseline file**, verify IR-equivalence with this check (run via `.venv/bin/python`):

```python
from refrain.parser import parse
from refrain.resolver import resolve
from refrain.ir_json import ir_to_json_obj
import subprocess

def ir(src, **kw):
    return ir_to_json_obj(resolve(parse(src), **kw))

def git_main(path):
    return subprocess.check_output(["git", "show", f"main:{path}"], text=True)

KEEP = "protocols/brainbit/smr_classic_cz_brainbit.refrain"
BASE = "protocols/brainbit/smr_classic_baseline_cz_brainbit.refrain"
SECTIONS = ["inputs", "derives", "inhibits", "reward", "output"]

old_adaptive = ir(git_main(KEEP))          # pre-edit adaptive, from main
old_baseline = ir(git_main(BASE))          # pre-edit baseline, from main
new = open(KEEP).read()                    # the edited collapsed file
new_default  = ir(new)                     # default → adaptive
new_baseline = ir(new, bindings={"threshold_style": "baseline"})

# unchanged sections must match the old adaptive file exactly
for s in SECTIONS:
    assert new_default[s] == old_adaptive[s], f"{s} drifted vs old adaptive"
# thresholds: callee + args match per mode (live_tunable may differ)
def calls(d): return {n: t["threshold_call"] for n, t in d["thresholds"].items()}
assert calls(new_default)  == calls(old_adaptive), "adaptive thresholds differ"
assert calls(new_baseline) == calls(old_baseline), "baseline thresholds differ"
print("OK", KEEP)
```

(Adapt `KEEP`/`BASE` per pair. If `threshold_call` carries a `live_tunable`-like field that legitimately differs, compare only `callee` + `args`.) If a pair fails, fix the edit until it passes — do not delete the baseline until its check is green.

After all 4 verify: `git rm` the 4 `_baseline` files, then `.venv/bin/python tools/build_catalog.py`.

## Task 2 — regression test + full suite

Add `tests/test_brainbit_mode_collapse.py`:
```python
import pytest
from pathlib import Path
from refrain.parser import parse
from refrain.resolver import resolve

ROOT = Path(__file__).resolve().parents[1]
CORES = ["smr_classic_cz_brainbit", "smr_graded_cz_brainbit",
         "smr_up_c4_brainbit", "beta_focus_staged_fz_brainbit"]

@pytest.mark.parametrize("name", CORES)
def test_default_all_percentile(name):
    ir = resolve(parse((ROOT/"protocols"/"brainbit"/f"{name}.refrain").read_text()))
    assert all(t.threshold_call.callee == "percentile" for t in ir.thresholds.values()
               if t.name in _threshold_names(name))

@pytest.mark.parametrize("name", CORES)
def test_baseline_selected_thresholds_absolute(name):
    ir = resolve(parse((ROOT/"protocols"/"brainbit"/f"{name}.refrain").read_text()),
                 bindings={"threshold_style": "baseline"})
    # the mode-switched thresholds are absolute under baseline
    assert any(t.threshold_call.callee == "absolute" for t in ir.thresholds.values())
```
(Simplify to whatever cleanly asserts: default → the mode-switched thresholds are `percentile`; baseline binding → they are `absolute`. The adaptive-only artifact guards like `hbeta_t`/`emg` stay percentile in both — exclude them from the "all absolute" assertion.)

Then `.venv/bin/python -m pytest -q` — expect green (was 172; +8 new checks).

## Task 3 — commit + PR

`git add -u protocols/ catalog.json && git add tests/test_brainbit_mode_collapse.py docs/superpowers/plans/2026-07-06-phase2b1-brainbit-threshold-collapse.md` → commit → push → PR.

## Notes / accepted deltas
- Collapsed adaptive thresholds gain `live_tunable = true` where the graded pair didn't have it — benign (a tuning capability), same as slice 1.
- The collapsed baseline mode uses the adaptive file's 120 s warmup rather than the baseline file's 90 s — benign (the seed handler uses only the last 60 s either way).
- The unused-in-this-mode controls (voltages in adaptive, percents in baseline) are declared but inert — same pattern as the generic collapse.
