# Stage 1: ship the safe parts of the declared-latency branch — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the refrain 0.24.0 floor, the editor gating, the envelope measurement tool, a guard test that tracks which envelopes still wait for their family's redesign, and the evidence documents — with no protocol changes.

**Architecture:** Branch `feat/declared-latency-envelope` already carries commit `7802a72` (floor, CI pin, flagships out of `KNOWN_GAPS`, changelog). This plan reverts the uncommitted `smr.refrain` migration, reshapes `tests/test_declared_latency.py` from "everything migrated" to "migrated, or waiting on a named family PR", adds unit tests for the pure parts of `tools/measure_envelopes.py`, commits the literature review and roadmap, corrects the changelog, runs every gate, and opens the PR whose description is the findings note for the session that wrote the brief.

**Tech Stack:** Python 3.12, pytest, refrain 0.24.0 + refrain-core 0.24.0, numpy, scipy.

**Spec:** `docs/superpowers/specs/2026-10-21-protocol-feedback-roadmap-design.md` (Stage 1).

## Global Constraints

- No file under `protocols/` changes in this PR. `catalog.json` must be byte-identical to `main`'s after `python tools/build_catalog.py`.
- `legacy/` is frozen.
- pytest exit code captured with `echo $?` immediately after pytest, never after a pipe. No `-q` on refrain's suite.
- Use the scratchpad venv for gates: `/private/tmp/claude-501/-Users-jcroall-git-refrain-protocols/61b6dc55-65e2-45f9-9d0b-46559c738940/scratchpad/venv` (refrain 0.24.0 and refrain-core 0.24.0 from release wheels). The repo's `.venv` has a stale editable refrain 0.21.0; do not use it.
- Never modify the user's refrain checkout at `~/git/refrain/refrain` (it is on another branch with uncommitted files). refrain gates run in a separate `git worktree` at tag `v0.24.0`.
- `research_notes/` and `reports/` stay uncommitted; only the report's copy under `docs/research/` is committed.

## Review Focus

1. **A new live protocol added later with a four-stage envelope and no entry anywhere** — the guard must fail, naming the file. Pinned in Task 2 (`test_unlisted_four_stage_fails`).
2. **A file in the waiting list that has been fully migrated** — the list entry must be removed, or the list rots. Pinned in Task 2 (`test_waiting_files_still_wait`).
3. **A partially migrated file** (one `band_envelope`, one four-stage) — allowed while the file is listed as waiting, but its `band_envelope` derives still face the bandwidth-floor check. Pinned in Task 2 by parametrisation over all `band_envelope` derives regardless of file.
4. **`lag_and_r` on a signal that is its own reference** — must return lag 0 and r ≈ 1; on a reference delayed by a known amount it must return that delay. Pinned in Task 3.
5. **The changelog claiming protocols use `band_envelope`** when none do — corrected in Task 4.

---

### Task 1: Put `smr.refrain` back exactly as `main` has it

**Files:**
- Modify (revert): `protocols/eeg/smr.refrain`

- [ ] **Step 1: Save the migration diff for the PR description**

Run: `git diff protocols/eeg/smr.refrain > /private/tmp/claude-501/-Users-jcroall-git-refrain-protocols/61b6dc55-65e2-45f9-9d0b-46559c738940/scratchpad/smr_migration.diff`
Expected: non-empty file containing three `band_envelope(` lines (latencies 360, 340, 100 ms).

- [ ] **Step 2: Revert**

Run: `git checkout -- protocols/eeg/smr.refrain && git diff --exit-code main -- protocols/`
Expected: exit 0 (no protocol differs from `main`).

No commit: the file returns to its committed state.

### Task 2: Guard test — migrated, excluded, or waiting on a named family

**Files:**
- Modify: `tests/test_declared_latency.py` (new file on this branch, uncommitted)

**Interfaces:**
- Consumes: existing helpers in the file — `_live_envelopes() -> list[tuple[Path, str, list[str], dict]]`, `EXCLUDED: dict[tuple[str, str], str]`, `_FOUR_STAGE`.
- Produces: `WAITING: dict[str, str]` mapping a protocol file name to the roadmap item it waits on; a pure helper `_classify(path_name: str, names: list[str]) -> str` returning one of `"migrated"`, `"bare_bandpass"`, `"excluded"`, `"waiting"`, `"unlisted"` (excluded is decided by the caller passing the derive; see below).

`WAITING` contents (exact keys; values are the roadmap item, Stage 3 numbering):

| Key | Value |
|---|---|
| `smr.refrain`, `placement_smr_bipolar.refrain`, `placement_smr_set.refrain`, `smr_classic_baseline_staged_cz.refrain` | `"Stage 3 #1 SMR family (REC-15)"` |
| `beta_attention.refrain`, `beta_focus_staged_fz.refrain` | `"Stage 3 #2 beta family"` |
| `alpha_up.refrain` | `"Stage 3 #3 alpha_up"` |
| `alpha_theta.refrain`, `alpha_theta_narrowband.refrain`, `alpha_theta_narrowband_melodic.refrain` | `"Stage 3 #4 alpha-theta family"` |
| `high_beta_down.refrain` | `"Stage 3 #5 high_beta_down (keep or retire)"` |

Module docstring: replace "every envelope derive ... is a one-stage `band_envelope`, or is named in EXCLUDED" with: every envelope is a one-stage `band_envelope`, or excluded with a reason, or in a file listed in `WAITING` against the roadmap item that will redesign it; the roadmap path; and one sentence on why (the swap alone collapsed reward holds, so migration happens with each family's reward redesign, not ahead of it).

- [ ] **Step 1: Write the failing tests**

```python
def test_unlisted_four_stage_fails():
    assert _classify("new_protocol.refrain", _FOUR_STAGE) == "unlisted"

def test_waiting_four_stage_passes():
    assert _classify("smr.refrain", _FOUR_STAGE) == "waiting"

def test_band_envelope_is_migrated_anywhere():
    assert _classify("smr.refrain", ["band_envelope"]) == "migrated"
    assert _classify("new_protocol.refrain", ["band_envelope"]) == "migrated"

def test_bare_bandpass_is_not_an_envelope():
    assert _classify("new_protocol.refrain", ["bandpass"]) == "bare_bandpass"

def test_waiting_files_still_wait():
    """A WAITING file with no four-stage envelope left has been migrated: drop it from WAITING."""
    still = {p.name for p, _, names, _ in _live_envelopes() if names == _FOUR_STAGE}
    assert set(WAITING) <= still, sorted(set(WAITING) - still)

def test_waiting_files_exist():
    assert set(WAITING) <= {p.name for p in LIVE}, sorted(set(WAITING) - {p.name for p in LIVE})
```

- [ ] **Step 2: Run to verify they fail**

Run: `<venv>/bin/python -m pytest tests/test_declared_latency.py -v; echo $?`
Expected: the six new tests fail with `NameError` for `_classify` / `WAITING`; exit code 1.

- [ ] **Step 3: Implement `WAITING` and `_classify(path_name, names) -> str`; rewrite `test_envelope_is_declared_or_excluded` to use them**

`_classify` order: `["band_envelope"]` → `"migrated"`; `["bandpass"]` → `"bare_bandpass"`; file in `WAITING` → `"waiting"`; else `"unlisted"`. The parametrised test keeps its EXCLUDED branch first (an excluded derive that has become `["band_envelope"]` still fails, telling the author to drop the exclusion), then asserts `_classify(...) != "unlisted"` with a message naming the file, the chain, and both remedies (migrate it, or add the file to `WAITING` with its roadmap item). `test_declared_latency_clears_the_bandwidth_floor`, `test_legacy_is_frozen` and `test_exclusions_name_real_derives` are unchanged.

- [ ] **Step 4: Run to verify they pass**

Run: `<venv>/bin/python -m pytest tests/test_declared_latency.py -v; echo $?`
Expected: all pass, the bandwidth-floor test reports 0 parametrised cases (skipped or empty is acceptable), exit code 0.

- [ ] **Step 5: Commit**

```bash
git add tests/test_declared_latency.py
git commit -m "Guard declared-latency envelopes: migrated, excluded, or waiting on a named redesign"
```

### Task 3: Unit tests for the measurement tool's pure parts

**Files:**
- Create: `tests/test_measure_envelopes.py`
- Modify: `tools/measure_envelopes.py` (docstring only)

**Interfaces:**
- Consumes: `tools/measure_envelopes.py` — `envelopes(ir_json: dict) -> list[dict]`, `reference_envelope(x, fs, band) -> np.ndarray`, `lag_and_r(est, ref, fs) -> tuple[float, float]`, `ENVELOPE_SHAPES`.
- Import via `sys.path.insert(0, str(ROOT / "tools"))`; skip the module with `pytest.importorskip("scipy")` and `pytest.importorskip("refrain")` (CI installs neither scipy explicitly; refrain pulls numpy and scipy — verify, and skip cleanly if not). `mne` is not needed for these tests and must not be imported at module level (it is already imported lazily inside `load_recordings`).

- [ ] **Step 1: Write the failing tests**

```python
def test_lag_and_r_identity():
    fs = 250.0; x = _burst_signal(fs, seconds=30)   # 13.5 Hz carrier with random 0.5 s bursts, fixed seed
    ref = reference_envelope(x, fs, (12.0, 15.0))
    lag, r = lag_and_r(ref, ref, fs)
    assert lag == 0.0 and r > 0.999

def test_lag_and_r_recovers_a_known_delay():
    fs = 250.0; x = _burst_signal(fs, seconds=30)
    ref = reference_envelope(x, fs, (12.0, 15.0))
    delayed = np.concatenate([np.full(50, ref[0]), ref[:-50]])   # 200 ms
    lag, r = lag_and_r(delayed, ref, fs)
    assert lag == pytest.approx(200.0, abs=4.0) and r > 0.99

def test_envelopes_finds_four_stage_and_band_envelope_in_shipped_smr():
    ir = _resolve("protocols/eeg/smr.refrain")      # resolved against q21, as test_declared_latency does
    found = {e["derive"]: (e["shape"], e["band"]) for e in envelopes(ir)}
    assert found["smr_envelope"] == ("four-stage", (12.0, 15.0))
    assert found["theta_envelope"][0] == "four-stage"
    assert found["high_beta_envelope"][0] == "four-stage"
```

`_burst_signal` and `_resolve` are small test-local helpers.

- [ ] **Step 2: Run to verify they fail**

Run: `<venv>/bin/python -m pytest tests/test_measure_envelopes.py -v; echo $?`
Expected: fail on the missing helpers; exit 1.

- [ ] **Step 3: Write the helpers; add to the tool's docstring one paragraph stating that `held_pct` counts time the reward hold is on including muted time and phase-muted rests, so it is a property of the reward rule, not of what the trainee hears.**

- [ ] **Step 4: Run to verify they pass**

Run: `<venv>/bin/python -m pytest tests/test_measure_envelopes.py -v; echo $?`
Expected: 3 passed; exit 0.

- [ ] **Step 5: Commit**

```bash
git add tests/test_measure_envelopes.py tools/measure_envelopes.py
git commit -m "Add the envelope measurement tool, with tests for its scoring"
```

### Task 4: Evidence documents and a truthful changelog

**Files:**
- Create: `docs/research/2026-10-21-feedback-design-by-protocol.md` (copy of `reports/Neurofeedback feedback design by protocol.md`)
- Add: `docs/superpowers/specs/2026-10-21-protocol-feedback-roadmap-design.md`, `docs/superpowers/plans/2026-10-21-stage1-ship-safe-parts.md`
- Modify: `CHANGELOG.md` (the "Unreleased — declared-latency envelope" section)

- [ ] **Step 1: Copy the report; check every protocol file name it mentions exists under `protocols/eeg/` or `protocols/`**

Run: `grep -oE '[a-z_0-9]+\.refrain' docs/research/2026-10-21-feedback-design-by-protocol.md | sort -u` and compare with `find protocols -name '*.refrain' -not -path '*legacy*'`.
Expected: every name found exists.

- [ ] **Step 2: Rewrite the changelog section**

Retitle to "Unreleased — declared-latency tooling (no protocol changes)". Under **Breaking**, keep the floor bump but replace "Protocols now use `band_envelope`, and the latencies they declare were measured on v0.24.0" with: the floor is literal because v0.24.0 changed the coherence segment length (`nperseg` 188 -> 125 at 250 Hz, 192 -> 128 at 256 Hz) that `alpha_coherence` depends on, and because the coming family redesigns use `band_envelope`. Keep **Changed** (editor gating). Add **Added**: `tools/measure_envelopes.py`; `tests/test_declared_latency.py`; the research review and roadmap. Add **Not changed, and why**: a one-for-one swap to `band_envelope` collapsed time holding a reward in every protocol on replayed recordings (one line with the range 0.4–10 % against 8.5–39.9 % before, and a pointer to the roadmap); protocols migrate with their family's reward redesign.

- [ ] **Step 3: Commit**

```bash
git add docs/research docs/superpowers/specs/2026-10-21-protocol-feedback-roadmap-design.md docs/superpowers/plans/2026-10-21-stage1-ship-safe-parts.md CHANGELOG.md
git commit -m "Record the feedback-design review and the protocol roadmap; correct the changelog"
```

### Task 5: Gates

**Files:** none changed (a fix found here goes back to its task).

- [ ] **Step 1: Catalog unchanged**

Run: `<venv>/bin/python tools/build_catalog.py && git diff --exit-code main -- catalog.json; echo $?`
Expected: exit 0.

- [ ] **Step 2: Full suite**

Run: `<venv>/bin/python -m pytest tests/; echo $?`
Expected: exit 0. Record the pass count (was 816 at `7802a72`, plus this branch's new tests).

- [ ] **Step 3: refrain gates in a separate worktree at v0.24.0**

```bash
git -C ~/git/refrain/refrain worktree add /private/tmp/claude-501/-Users-jcroall-git-refrain-protocols/61b6dc55-65e2-45f9-9d0b-46559c738940/scratchpad/refrain-v0.24.0 v0.24.0
```
In that worktree, create its own venv (`python3.12 -m venv .venv && .venv/bin/pip install -e ".[eval,dev]"`, plus `maturin` and the `refrain-core` build the CI workflow does) and run with it; never install into the scratchpad venv used above:
- `python -m pytest tests/; echo $?` — expected exit 0.
- `PYTHONPATH=. python refrain-core/tools/check_equivalence.py; echo $?` — expected exit 0.
- `python tools/gen_editor_fixtures.py ~/git/refrain-protocols <tmp-out> smr,alpha_up,beta_attention,high_beta_down; echo $?` — expected exit 0 and the four stems present (41 of 44 per the brief).

Remove the worktree afterwards with `git -C ~/git/refrain/refrain worktree remove <path>`.

### Task 6: PR and hand-off (outward-facing: confirm with the user before pushing)

- [ ] **Step 1: Ask the user to confirm pushing the branch and opening the PR.**

- [ ] **Step 2: Push and open the PR against `main`**

PR description sections, in this order:
1. What ships (bullets matching the changelog).
2. What does not ship and why: the reward-collapse table (nine rows, before/after held %), the cause in two sentences, link to the roadmap.
3. For the session that wrote the brief: contradictions of the brief's settled facts (the swap is not reward-neutral; the brief's count of 19 envelopes was 29 live / 27 in scope; "20 bare bandpass" in legacy were centre+ratio envelopes), the per-band latency picks with floors (table from the roadmap), the SMR migration diff from Task 1 Step 1 as a collapsed block, and open questions: 0.2.0 timing now that Stage 1 carries no speed-up; REC-15's delete resolved as move-to-legacy by the user on 2026-10-21.
4. Gates run, with exit codes and counts from Task 5.

End with the attribution line required for PR descriptions.

- [ ] **Step 3: Linear**

Comment on REC-15 with the user's 2026-10-21 decisions (fold the staged file in as a mode, move it to `legacy/`, keep bipolar and set, keep the nine legacy files; target design per the roadmap) and a link to the PR. Create one ticket per roadmap stage (Stage 2 refrain primitives, Stage 2b recorder gain smoothing, Stage 4 live validation including the user's clench recording), each linking REC-15, REC-10 and REC-18. Ask the user before creating tickets if the team or project is unclear.
