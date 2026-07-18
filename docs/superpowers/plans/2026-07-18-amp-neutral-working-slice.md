# Amp-Neutral Working Slice — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-author `smr_theta_cz` as a single amp-neutral protocol (`reference: amp.reference` + a `placement` site) and prove in CI that it resolves and runs on both `brainbit_flex` (→ `device`) and `q21` (→ `linked_ears`) from one source.

**Architecture:** The protocol reads its montage reference and its site from the connected amp/host at resolve time. The corpus test harness gains a dedicated two-amp resolve test for amp-reading protocols, and the fuzz gate splits into a literal-corpus run (`amp=None`, unchanged) plus an amp-reader run (`--amp`). The existing round-trip test is unaffected because `smr_theta_cz` is (and stays) a `KNOWN_GAPS` entry it never resolves.

**Tech Stack:** refrain v0.15.0 (DSL engine, ships `amp.reference`), Python 3, pytest, `refrain fuzz`.

**Spec:** `docs/superpowers/specs/2026-07-18-amp-neutral-working-slice-design.md`

**Depends on:** refrain **v0.15.0** (released; tag `v0.15.0`). The worktree venv is already on v0.15.0.

## Global Constraints

- **Engine pin is v0.15.0.** CI installs `refrain @ git+…@v0.15.0` (two places: `ci.yml:20`, `ci.yml:55`). v0.14.0 cannot resolve `amp.reference`.
- **`amp.reference` fails closed at `amp=None`** by design — resolving an amp-reading protocol without a profile is a `ResolveError`, not a bug. Every gate that resolves such a protocol must supply an amp.
- **A `placement` needs its `allowed` group defined in a `groups { }` block** in the same protocol (e.g. `groups { sensorimotor = ["C3", "Cz", "C4"] }`). Omitting it is `ResolveError: unknown group`.
- **The two gate amps are `brainbit_flex` and `q21`**, loaded from the installed refrain package: `Path(refrain.__file__).parent / "amp_profiles" / "{brainbit_flex,q21}.json"`. Full-amp coverage is Linear **WOR-163** (later).
- **Amp-reader detection is a source scan for the token `amp.`** (`grep -l 'amp\.'`). Literal-reference protocols contain no `amp.` and resolve at `amp=None` exactly as today.
- **`smr_theta_cz` is and remains a `KNOWN_GAPS` entry** (its mode-folded threshold is outside the editor's catalog v1; `describe_protocol` returns `in_subset=False`). It is never resolved through the round-trip `_ir` path.
- Run Python/pytest/refrain via the worktree venv: `./.venv/bin/…`.

## File Structure

- `.github/workflows/ci.yml` — repin engine to v0.15.0; split the fuzz step.
- `tests/test_corpus_roundtrip.py` — `glob`→`rglob`; add 4 BrainBit files to `KNOWN_GAPS`.
- `protocols/smr_theta_cz.refrain` — re-authored amp-neutral.
- `tests/test_amp_neutral.py` — new: the two-amp resolve/fold proof for amp-reading protocols.
- `catalog.json` — regenerated (meta changed).

---

### Task 1: Repin CI to v0.15.0 and verify the current corpus is green on it

**Files:**
- Modify: `.github/workflows/ci.yml` (lines 20 and 55)

**Interfaces:**
- Produces: CI installs refrain v0.15.0. No protocol changes yet — this isolates "does the existing corpus still pass on the new engine (which added `amp.reference` + 3 core fixes)?"

- [ ] **Step 1: Repin both install lines**

In `.github/workflows/ci.yml`, change both occurrences (line 20 in the `validate` job, line 55 in the `fuzz` job):

```yaml
          pip install "refrain @ git+https://github.com/refrain-lang/refrain.git@v0.15.0"
```

(from `@v0.14.0`).

- [ ] **Step 2: Verify the current corpus passes on v0.15.0 (baseline, before any protocol change)**

Run all three gates against the current (unchanged) corpus:

```bash
./.venv/bin/python tools/build_catalog.py && git diff --exit-code catalog.json && echo "CATALOG OK"
./.venv/bin/python -m pytest -q; echo "PYTEST_EXIT=$?"
./.venv/bin/refrain fuzz protocols/ --library lib --seed 42; echo "FUZZ_EXIT=$?"
```

Expected: catalog in sync; pytest exit 0; fuzz exit 0 (the known 26 fuzzed / 12 skipped / 0 errored). Note: pytest's summary line may not flush in this sandbox — trust the exit code. If anything regresses here, STOP and report — it means a v0.15.0 core fix changed corpus behaviour, which must be understood before proceeding.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: pin refrain to v0.15.0 (ships amp.reference)"
```

---

### Task 2: Bring the BrainBit files under the round-trip test (`glob`→`rglob`)

**Files:**
- Modify: `tests/test_corpus_roundtrip.py` (line 26; the `KNOWN_GAPS` set at lines 31-58)
- Test: `tests/test_corpus_roundtrip.py` itself

**Interfaces:**
- Consumes: nothing from Task 1 beyond the engine pin.
- Produces: all 16 `protocols/brainbit/*.refrain` enter the round-trip test — 12 round-trip to equal IR, 4 are flagged as known gaps.

- [ ] **Step 1: Confirm the current exclusion (RED evidence)**

```bash
./.venv/bin/python -c "
from pathlib import Path
ALL=sorted((Path('protocols')).glob('*.refrain'))
print('non-recursive sees', len(ALL), 'files; brainbit included:', any('brainbit' in p.parts for p in ALL))
"
```
Expected: brainbit NOT included (the bug).

- [ ] **Step 2: Switch to `rglob`**

In `tests/test_corpus_roundtrip.py`, line 26:

```python
ALL = sorted((ROOT / "protocols").rglob("*.refrain")) + sorted((ROOT / "drafts").rglob("*.refrain"))
```

(`glob` → `rglob` for both.)

- [ ] **Step 3: Run the round-trip test — 4 BrainBit files will fail as unflagged gaps**

```bash
./.venv/bin/python -m pytest tests/test_corpus_roundtrip.py -q 2>&1 | grep -E "FAILED|error" | head
```
Expected: `test_in_subset_round_trips_to_equal_ir` FAILS for exactly these four (they describe as `in_subset=False` but aren't in `KNOWN_GAPS`): `beta_focus_staged_fz_brainbit.refrain`, `smr_classic_cz_brainbit.refrain`, `smr_graded_cz_brainbit.refrain`, `smr_up_c4_brainbit.refrain`.

- [ ] **Step 4: Add those four to `KNOWN_GAPS`**

In the `KNOWN_GAPS` set (inside `tests/test_corpus_roundtrip.py`), add:

```python
    # BrainBit mode-folded-threshold cores — same catalog-v1 gap as the generic
    # cores above (editor's _match_threshold doesn't recognise the mode-folded
    # conditional). Surfaced when rglob brought protocols/brainbit/ into the test.
    "beta_focus_staged_fz_brainbit.refrain",
    "smr_classic_cz_brainbit.refrain",
    "smr_graded_cz_brainbit.refrain",
    "smr_up_c4_brainbit.refrain",
```

The other 12 BrainBit files describe as `in_subset=True` and round-trip to equal IR — they need no change.

- [ ] **Step 5: Run to green**

```bash
./.venv/bin/python -m pytest tests/test_corpus_roundtrip.py -q; echo "EXIT=$?"
```
Expected: exit 0. The corpus now covers all 16 BrainBit files (12 in-subset round-tripped, 4 flagged gaps).

- [ ] **Step 6: Commit**

```bash
git add tests/test_corpus_roundtrip.py
git commit -m "test: rglob the corpus so protocols/brainbit/ is covered; flag 4 mode-folded cores as gaps"
```

---

### Task 3: Re-author `smr_theta_cz` amp-neutral

**Files:**
- Modify: `protocols/smr_theta_cz.refrain`

**Interfaces:**
- Consumes: the engine's `amp.reference` (v0.15.0) and `placement`.
- Produces: an amp-reading protocol that fails closed at `amp=None`, folds to `device` on BrainBit and `linked_ears` on Q21, and stays a `KNOWN_GAPS` entry (still `in_subset=False`).

- [ ] **Step 1: Write the exact re-authored file**

Replace the contents of `protocols/smr_theta_cz.refrain` with:

```refrain
// smr_theta_cz.refrain  —  DRAFT (status=draft, untested)
// SMR/THETA up-train at Cz, amp-neutral: the montage reference comes from the
// connected amp (device on BrainBit, linked_ears on a clinical amp) and the
// site is a placement the host binds. Sterman; Lubar; Arns 2009.
protocol "smr_theta_cz" {
  meta {
    version         = "0.1.0"
    title           = "Steady focus — boost SMR, calm theta (top of head)"
    summary         = "Rewards a calm-but-alert sensorimotor rhythm at the top of the head while keeping drowsy theta down."
    family          = "smr_theta_cz"
    description     = "SMR/THETA up-train at Cz"
    status          = "draft"
    evidence        = "established"
    citation        = "Sterman; Lubar; Arns 2009"
    goals           = ["adhd_attention", "sensorimotor_sleep"]
    bands           = ["smr", "theta"]
    site            = "Cz"
    direction       = "up"
    threshold_style = "selectable"
    feedback_style  = "discrete"
    session_shape   = "staged"
  }

  requires {
    sample_rate = ">= 250 Hz"
    channels    = ["Cz"]
  }

  groups {
    sensorimotor = ["C3", "Cz", "C4"]
  }

  input "raw" { montage = referential(active: site, reference: amp.reference) }

  derive "env" {
    from = "raw"
    pipeline = [
      bandpass(center: env_center, bandwidth: ratio(1.25), order: 4),
      hilbert(),
      magnitude(),
      smooth(tau: 250 ms),
    ]
  }

  threshold "env_t" {
    signal = "env"
    type = threshold_style == "baseline"
             ? absolute(value: thr_uv)
             : percentile(target_pct: reward_pct, window: 2 min)
    live_tunable = true
  }

  reward {
    event      = dwell(condition: above("env", "env_t"), duration: 250 ms)
    continuous = sigmoid("env" / "env_t", midpoint: 1.0, steepness: 3)
  }

  output {
    audio_chime = reward.event
    audio_gain  = reward.event.holds ? reward.continuous : 0
  }

  controls {
    site = placement {
      kind    = "active"
      default = "Cz"
      allowed = sensorimotor
    }
    threshold_style = mode {
      choices = ["adaptive", "baseline"]
      default = "adaptive"
      label   = "Threshold style"
    }
    env_center = frequency {
      default = 13.4164 Hz
      range   = (10.73 Hz, 16.1 Hz)
      label   = "SMR/THETA band center"
    }
    reward_pct = percent {
      default      = 70
      range        = (50, 90)
      label        = "Target reward %"
      live_tunable = true
    }
    thr_uv = voltage {
      default      = 2.0 uV
      range        = (0.5 uV, 30.0 uV)
      label        = "Threshold (baseline-seeded)"
      live_tunable = true
    }
  }

  session {
    phases = [
      phase { name = "warmup";   duration = 90 s;  output_muted = true },
      phase { name = "block1";   duration = 5 min; mode = timed_with_floor },
      phase { name = "rest1";    duration = 2 min; output_muted = true },
      phase { name = "block2";   duration = 5 min; mode = timed_with_floor },
      phase { name = "rest2";    duration = 2 min; output_muted = true },
      phase { name = "block3";   duration = 5 min; mode = timed_with_floor },
      phase { name = "rest3";    duration = 2 min; output_muted = true },
      phase { name = "block4";   duration = 5 min; mode = timed_with_floor },
      phase { name = "cooldown"; duration = 30 s;  output_muted = true },
    ]
  }
}
```

The four load-bearing deltas vs. the original: montage `active: "Cz"`→`active: site` and `reference: "linked_ears"`→`reference: amp.reference`; a new `groups { sensorimotor = … }` block; a new `site = placement { … }` control; `requires.sample_rate` `">= 256 Hz"`→`">= 250 Hz"`; and `meta.hardware = "generic"` removed (the file is amp-neutral, not "generic hardware").

- [ ] **Step 2: Verify the four behaviours**

```bash
./.venv/bin/python - <<'PY'
from pathlib import Path
import refrain
from refrain import editor
from refrain.amp_profile import load_amp_profile
from refrain.ir_json import ir_to_json_obj
from refrain.resolver import resolve, ResolveError
P = Path(refrain.__file__).parent / "amp_profiles"
BB, Q21 = load_amp_profile(P/"brainbit_flex.json"), load_amp_profile(P/"q21.json")
src = Path("protocols/smr_theta_cz.refrain").read_text()
def refv(ir):
    m = ir["inputs"]["raw"]["montage"]
    return next(a for a in m["args"] if a["name"]=="reference")["value"]["value"]
d = editor.describe_protocol(src); print("describe in_subset:", d["in_subset"], "(want False)")
try: resolve(refrain.parse(src)); print("amp=None: RESOLVED (want fail-closed) !!")
except ResolveError: print("amp=None: fail-closed OK")
print("brainbit ->", refv(ir_to_json_obj(resolve(refrain.parse(src), amp=BB))), "(want device)")
print("q21      ->", refv(ir_to_json_obj(resolve(refrain.parse(src), amp=Q21))), "(want linked_ears)")
PY
```
Expected: `in_subset=False`; `amp=None` fail-closed; brainbit → `device`; q21 → `linked_ears`.

- [ ] **Step 3: Confirm the round-trip + catalog tests still pass (smr_theta_cz stays a gap)**

```bash
./.venv/bin/python -m pytest tests/test_corpus_roundtrip.py tests/test_catalog.py -q; echo "EXIT=$?"
```
Expected: exit 0. (`smr_theta_cz` is in `KNOWN_GAPS`; `test_known_gaps_stay_flagged` asserts `in_subset=False`, and `test_describe_never_crashes` passes.)

- [ ] **Step 4: Commit**

```bash
git add protocols/smr_theta_cz.refrain
git commit -m "feat(protocol): smr_theta_cz is amp-neutral (amp.reference + placement site, requires 250 Hz)"
```

---

### Task 4: Dedicated two-amp resolve proof

**Files:**
- Create: `tests/test_amp_neutral.py`

**Interfaces:**
- Consumes: the amp-reading protocol(s) in the corpus (detected by scanning source for `amp.`), the two shipped profiles.
- Produces: a CI assertion that every amp-reading protocol resolves to valid IR on BrainBit and Q21, folding to the expected reference, with a non-zero montage on synthetic signal.

- [ ] **Step 1: Write the test**

Create `tests/test_amp_neutral.py`:

```python
# Copyright 2026 Refrain Protocols Authors.
"""Amp-neutral protocols (those that read `amp.*`) must resolve on more than one
amp from one source — the working-slice proof. Full-amp coverage is WOR-163."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

refrain = pytest.importorskip("refrain")
from refrain.amp_profile import load_amp_profile  # noqa: E402
from refrain.ir_json import ir_to_json_obj  # noqa: E402
from refrain.primitive_impls import ReferentialImpl  # noqa: E402
from refrain.resolver import ResolveError, resolve  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PROF = Path(refrain.__file__).parent / "amp_profiles"
BRAINBIT = load_amp_profile(PROF / "brainbit_flex.json")
Q21 = load_amp_profile(PROF / "q21.json")

# Amp-reading protocols: source references the `amp` namespace.
AMP_READERS = [
    p for p in sorted(ROOT.glob("protocols/**/*.refrain"))
    if "amp." in p.read_text()
]


def _ref_arg(ir: dict) -> str:
    m = ir["inputs"]["raw"]["montage"]
    return next(a for a in m["args"] if a["name"] == "reference")["value"]["value"]


def test_there_is_at_least_one_amp_reader():
    assert AMP_READERS, "no amp-reading protocol found — did the slice land?"


@pytest.mark.parametrize("path", AMP_READERS, ids=lambda p: p.name)
def test_amp_reader_fails_closed_without_profile(path: Path):
    with pytest.raises(ResolveError):
        resolve(refrain.parse(path.read_text()))


@pytest.mark.parametrize("path", AMP_READERS, ids=lambda p: p.name)
def test_amp_reader_resolves_on_brainbit_and_q21(path: Path):
    src = path.read_text()
    bb = ir_to_json_obj(resolve(refrain.parse(src), amp=BRAINBIT))
    q = ir_to_json_obj(resolve(refrain.parse(src), amp=Q21))
    # BrainBit's dedicated ear-reference is pre-applied -> device; a clinical amp
    # with A1/A2 -> linked_ears. Both must be valid IR.
    assert _ref_arg(bb) == "device"
    assert _ref_arg(q) == "linked_ears"


def test_montage_is_live_not_a_flatline_on_brainbit():
    # The pre-abstraction linked_ears form flatlines on a BrainBit (mean of one
    # channel minus itself = 0). The device fold must produce a live stream.
    rng = np.random.default_rng(1)
    chunk = rng.standard_normal((64, 4)) + np.arange(4)  # Cz/F3/F4/Pz
    out = ReferentialImpl(active="Cz", reference="device",
                          channel_names=("Cz", "F3", "F4", "Pz")).step(chunk)
    assert not np.allclose(out, 0.0)
```

- [ ] **Step 2: Run it**

```bash
./.venv/bin/python -m pytest tests/test_amp_neutral.py -v; echo "EXIT=$?"
```
Expected: all pass (fail-closed, brainbit→device, q21→linked_ears, live montage).

- [ ] **Step 3: Commit**

```bash
git add tests/test_amp_neutral.py
git commit -m "test: prove amp-neutral protocols resolve on brainbit + q21 from one source"
```

---

### Task 5: Split the fuzz gate so the amp-reader is fuzzed with an amp

**Files:**
- Modify: `.github/workflows/ci.yml` (the fuzz job's run step, line 57)

**Interfaces:**
- Consumes: the amp-reader in the corpus (breaks the `amp=None` fuzz run today — it errors with exit 2).
- Produces: a fuzz step that fuzzes literal protocols at `amp=None` (unchanged) and amp-reading protocols with `--amp`.

- [ ] **Step 1: Confirm the break (RED)**

```bash
./.venv/bin/refrain fuzz protocols/ --library lib --seed 42; echo "EXIT=$?"
```
Expected: `errored 1` on `smr_theta_cz.refrain` ("amp.reference requires an amp profile"), non-zero exit — the amp-reader breaks the whole-corpus `amp=None` run.

- [ ] **Step 2: Replace the fuzz run step**

In `.github/workflows/ci.yml`, replace the fuzz job's `run:` (currently `refrain fuzz protocols/ --library lib --seed 42`) with a split that keys off the `amp.` token:

```yaml
        run: |
          set -eu
          AMP="$(python -c 'import refrain,os;print(os.path.join(os.path.dirname(refrain.__file__),"amp_profiles","brainbit_flex.json"))')"
          # Literal protocols (no amp.* reference) — resolve at amp=None, as before.
          LITERAL="$(grep -rL --include='*.refrain' 'amp\.' protocols)"
          echo "Fuzzing literal protocols at amp=None"
          refrain fuzz $LITERAL --library lib --seed 42
          # Amp-reading protocols — resolve against a real amp (brainbit_flex, 250 Hz).
          READERS="$(grep -rl --include='*.refrain' 'amp\.' protocols)"
          if [ -n "$READERS" ]; then
            echo "Fuzzing amp-reading protocols with --amp brainbit_flex"
            refrain fuzz $READERS --library lib --amp "$AMP" --seed 42
          fi
```

Rationale: `grep -rL 'amp\.'` lists files WITHOUT `amp.` (literal); `grep -rl 'amp\.'` lists files WITH it (amp-readers). `refrain fuzz` accepts explicit file paths (`paths [paths …]`), so each set fuzzes under the right amp setting. `$LITERAL`/`$READERS` are left unquoted for word-splitting — `.refrain` filenames have no spaces — which keeps the command portable across CI bash and a local macOS shell (no `mapfile`, a bash-4-only builtin). Auto-scales as more protocols convert. `brainbit_flex` is used for readers because it is 250 Hz (close to the corpus's chosen rate) and `smr_theta_cz` resolves on it.

- [ ] **Step 3: Verify locally (both halves)**

```bash
AMP="$(./.venv/bin/python -c 'import refrain,os;print(os.path.join(os.path.dirname(refrain.__file__),"amp_profiles","brainbit_flex.json"))')"
LITERAL="$(grep -rL --include='*.refrain' 'amp\.' protocols)"
./.venv/bin/refrain fuzz $LITERAL --library lib --seed 42; echo "LITERAL_EXIT=$?"
READERS="$(grep -rl --include='*.refrain' 'amp\.' protocols)"
./.venv/bin/refrain fuzz $READERS --library lib --amp "$AMP" --seed 42; echo "READER_EXIT=$?"
```
Expected: both exit 0. The literal run reproduces the prior pass/skip counts minus `smr_theta_cz`; the reader run fuzzes `smr_theta_cz` (or reports a typed skip) with 0 violations.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: fuzz literal protocols at amp=None + amp-readers with --amp brainbit_flex"
```

---

### Task 6: Regenerate the catalog and run the full gate suite

**Files:**
- Modify: `catalog.json`

**Interfaces:** none.

- [ ] **Step 1: Regenerate the catalog**

`smr_theta_cz`'s meta changed (dropped `hardware`), so `catalog.json` is now stale:

```bash
./.venv/bin/python tools/build_catalog.py
git diff --stat catalog.json
```
Expected: `catalog.json` changes only in `smr_theta_cz`'s entry (e.g. `hardware` now null/absent). Eyeball the diff to confirm nothing unexpected moved.

- [ ] **Step 2: Run every gate the CI runs**

```bash
git diff --exit-code catalog.json >/dev/null && echo "catalog stale — commit it" || true
./.venv/bin/python -m pytest -q; echo "PYTEST_EXIT=$?"
AMP="$(./.venv/bin/python -c 'import refrain,os;print(os.path.join(os.path.dirname(refrain.__file__),"amp_profiles","brainbit_flex.json"))')"
LITERAL="$(grep -rL --include='*.refrain' 'amp\.' protocols)"
./.venv/bin/refrain fuzz $LITERAL --library lib --seed 42; echo "LIT_EXIT=$?"
READERS="$(grep -rl --include='*.refrain' 'amp\.' protocols)"
./.venv/bin/refrain fuzz $READERS --library lib --amp "$AMP" --seed 42; echo "RDR_EXIT=$?"
```
Expected: pytest exit 0 (including the new `test_amp_neutral.py`); both fuzz runs exit 0.

- [ ] **Step 3: Commit the regenerated catalog**

```bash
git add catalog.json
git commit -m "chore: regenerate catalog.json for amp-neutral smr_theta_cz"
```

---

## Post-plan verification (definition of done)

- [ ] `smr_theta_cz.refrain` uses `reference: amp.reference` + a `placement` site + `groups` + `>= 250 Hz`.
- [ ] It resolves to valid IR on `brainbit_flex` (→ `device`) and `q21` (→ `linked_ears`); fails closed at `amp=None`. (Asserted by `tests/test_amp_neutral.py`.)
- [ ] Montage is live (non-zero) on BrainBit — the flatline is gone.
- [ ] All gates green on v0.15.0: `pytest -q`, catalog freshness, and the split fuzz (literal `amp=None` + reader `--amp`).
- [ ] The 16 BrainBit files are now under the round-trip test (12 round-tripped, 4 flagged gaps).

## Non-goals

- Converting any other protocol (one-file slice; the sweep is follow-on).
- Merging/deleting a BrainBit twin (`smr_theta_cz` has none clean) or the metadata union.
- The deferred engine hardening (`linked_ears` fail-closed break + consistency lint).
- Full-amp gate coverage (WOR-163) — the gate uses two representative amps.
