# Fork audit: `protocols/brainbit/*.refrain` vs `protocols/*.refrain` (2026-07)

Purpose: gate a later task that will merge/move protocol files. Every file below was
**read in full** (not grepped, not inferred from filename). Where the evidence is
ambiguous, this doc says so explicitly rather than guessing.

Top-level corpus is NOT homogeneous — this matters for every pairing below:

- **"Family A" (16 of 22 top-level files)** — the single-envelope up/down templates
  (`alpha_up_pz`, `alpha_down_pz`, `beta_up_c3`, `beta_up_fz`, `fm_theta_up_fz`,
  `hibeta_down_cz`, `peak_alpha_up_pz`, `slow_down_cz`, `slow_down_fz`, `smr_theta_cz`,
  `smr_up_c4`, `theta_beta_cz`, `theta_beta_fz`, `theta_down_cz`, `theta_down_fz`,
  `theta_up_pz`). All of them: read `montage = referential(..., reference: amp.reference)`,
  declare `threshold_style = mode { choices = ["adaptive","baseline"] }`, have a
  `thr_uv` voltage control with `seed = percentile {...}`, gate on
  `sample_rate = ">= 250 Hz"` (already 250, not 256), and run the same staged
  4×5-min-block/2-min-rest session shape.
- **"Family B" (6 of 22 top-level files)** — `alpha_coherence_c3c4`, `alpha_theta_pz`,
  `composite_smr_theta_cz`, `critical_fluctuation`, `faa_f3f4`, `hrv_resonance`. These
  hardcode `reference: "linked_ears"` (or `passthrough()` for HRV) — **not**
  `amp.reference` — gate on `sample_rate = ">= 256 Hz"`, have no `threshold_style`
  mode control, and (except `alpha_theta_pz`) declare **no `session {}` block at all**.

**This splits the "two-edit fork" story in the task background into two different
stories** — see Finding F1 below.

## 1. Summary table

| # | `protocols/brainbit/` file | Top-level counterpart | Verdict |
|---|---|---|---|
| 1 | `alpha_symmetry_c3c4_brainbit` | `alpha_coherence_c3c4` | **real pair, mechanism diverges** — UNCERTAIN which side is canonical (§2.1) |
| 2 | `alpha_theta_pz_brainbit` | `alpha_theta_pz` | merge-keeping-top (add brainbit's EMG inhibit) (§2.2) |
| 3 | `alpha_up_pz_brainbit` | `alpha_up_pz` | merge-keeping-top (mode toggle + seed + staged session) (§2.3) |
| 4 | `beta_focus_staged_fz_brainbit` | `beta_up_fz` | merge-keeping-brainbit (3-band/`block` logic is the real recipe) (§2.4) |
| 5 | `composite_smr_theta_cz_brainbit` | `composite_smr_theta_cz` | **hybrid needed** — neither side alone is complete (§2.5) |
| 6 | `high_beta_down_cz_brainbit` | `hibeta_down_cz` | merge-keeping-top (mode toggle + staged session) (§2.6) |
| 7 | `smr_up_c4_brainbit` | `smr_up_c4` | **hybrid needed** — top's staged session + brainbit's hbeta guard (§2.7) |
| 8 | `beta_up_cz_brainbit` | `theta_beta_cz` (candidate only) | UNCERTAIN — flag for clinician, do not auto-merge (§2.8) |
| 9 | `placement_alpha_coherence_pair_brainbit` | none | no-counterpart-keep (§3) |
| 10 | `placement_smr_active_brainbit` | none | no-counterpart-keep (§3) |
| 11 | `placement_smr_bipolar_brainbit` | none | no-counterpart-keep (§3) |
| 12 | `placement_smr_set_brainbit` | none | no-counterpart-keep (§3) |
| 13 | `smr_classic_baseline_staged_cz_brainbit` | none | no-counterpart-keep (§3) |
| 14 | `smr_classic_cz_brainbit` | none | no-counterpart-keep (§3) |
| 15 | `smr_cz_brainbit_modulating` | none | no-counterpart-keep (§3) |
| 16 | `smr_graded_cz_brainbit` | none | no-counterpart-keep (§3) |

**Count: 7 confirmed real pairs, 1 uncertain pairing, 8 no-counterpart files.**

---

## 2. Real pairs (detail)

### 2.1 `alpha_coherence_c3c4` ↔ `alpha_symmetry_c3c4_brainbit`

- **threshold_style mode control:** neither side has one. Top's `meta.threshold_style
  = "adaptive"` is a literal string, not a `mode {}` control block. Brainbit has no
  `threshold_style` field at all.
- **seed percentile warmup:** neither side has a `seed = percentile {...}` block (no
  `thr_uv`-style control on either side).
- **montage:** top — `input "left" { montage = referential(active: "C3", reference:
  "linked_ears") }` (and `"right"`/`C4` likewise). Brainbit — `input "raw_c3" {
  montage = referential(active: "C3", reference: "device") }` (and `raw_c4`/`C4`
  likewise). **Neither reads `amp.reference`** — top hardcodes `"linked_ears"`, not the
  portable read the task background describes.
- **sample_rate:** top `>= 256 Hz`; brainbit `>= 250 Hz`. The relaxation *does* apply
  here.
- **What one has that the other lacks:** this is the important one. Top-level's
  `derive "alpha_coh" { formula = coherence(input_a: "left", input_b: "right", band:
  (8 Hz, 12 Hz), window: 2 s) }` is **genuine phase coherence**. Brainbit's
  `alpha_asymmetry = rectify("alpha_c3_envelope" - "alpha_c4_envelope")` is an
  **amplitude-difference stand-in** — its own header comment says so explicitly:
  *"Honest framing: this is amplitude symmetry, not phase coherence... This protocol
  is the v0.0-authorable stand-in. When Refrain v0.1 ships, this file gets replaced
  with a `c3_c4_alpha_coherence_brainbit.refrain` that uses the real coherence
  primitive."* Brainbit also has a `session {}` block (warmup 120s / training 20 min /
  cooldown 30s) that top-level entirely lacks.
- **Verdict:** real pair by intent (same site pair, same `flow_connectivity` goal,
  `meta.family = "alpha_coherence_c3c4"` on the brainbit side literally names the
  top-level file) but **not by mechanism**. See Finding F2 — the coherence primitive
  the brainbit file says it's waiting for **already exists and is already used
  elsewhere in this same folder** (`placement_alpha_coherence_pair_brainbit`, which
  requires "refrain >= 0.6.1"). This stand-in is stale by the project's own stated
  plan. UNCERTAIN what should happen: replace this file with a real-coherence C3/C4
  variant, retire it in favor of `placement_alpha_coherence_pair_brainbit` bound to
  C3/C4, or keep amplitude-symmetry deliberately (dry BrainBit electrodes may make
  true phase coherence unreliable — plausible but unconfirmed). Do not silently merge
  these into one file.

### 2.2 `alpha_theta_pz` ↔ `alpha_theta_pz_brainbit`

- **threshold_style mode control:** neither (this is a crossover protocol — `direction
  = "crossover"` — no percentile threshold at all on either side).
- **seed percentile:** neither.
- **montage:** top — `referential(active: "Pz", reference: "linked_ears")`. Brainbit —
  `referential(active: "Pz", reference: "device")`. Again neither is `amp.reference`.
- **sample_rate:** top `>= 256 Hz`; brainbit `>= 250 Hz` (relaxation applies).
- **What top has that brainbit lacks:** `alpha_center` / `theta_center` **frequency
  controls** (tunable band centers, default 9.798 Hz / 5.657 Hz) — brainbit hardcodes
  literal `(8 Hz, 12 Hz)` / `(4 Hz, 8 Hz)` bands with **no controls block at all**.
  This is a real regression (loses clinician tunability).
- **What brainbit has that top lacks:** an `inhibit "emg" { metric = bandpower(input:
  "raw", band: (50 Hz, 100 Hz), ...); action = mute(release: 200 ms) }` — a genuinely
  useful addition for an eyes-closed/reclined protocol, absent from top-level.
- **Session shape differs:** top runs two 15-min deep blocks with a rest between
  (`settle 2min → deep1 15min → rest1 2min → deep2 15min → cooldown 2min`); brainbit
  runs one continuous 30-min block (`settle 3min → training 30min → return 2min`).
- **Verdict:** real pair (family match, same paradigm). To merge: carry over top's
  frequency controls, keep brainbit's EMG inhibit, decide the reference scheme
  (neither `linked_ears` nor `device` is portable `amp.reference`), and get a
  clinician call on which session shape (two 15-min blocks vs one 30-min block) is
  intended — this is a real pacing difference, not cosmetic drift.

### 2.3 `alpha_up_pz` ↔ `alpha_up_pz_brainbit`

- **threshold_style mode control:** top has it (`mode { choices = ["adaptive",
  "baseline"] }`); **brainbit does not** — brainbit's `threshold "alpha_t"` is a bare
  `percentile(target_pct: alpha_reward_pct, window: 2 min)` with no baseline/absolute
  option at all.
- **seed percentile:** top has `thr_uv = voltage { ...; seed = percentile { from:
  "env", window: 60 s, target_pct: reward_pct } }`; brainbit has **no `thr_uv` control,
  no seed** — dropped entirely.
- **montage:** top — `referential(active: "Pz", reference: amp.reference)`. Brainbit
  — `referential(active: "Pz", reference: "device")`. This is the clean case of the
  task's stated fork story (amp.reference → device).
- **sample_rate:** top `>= 250 Hz`; brainbit `>= 250 Hz` — **identical, no
  relaxation happened here** (top-level Family A files were already 250 Hz).
- **Reward-rate control renamed and re-ranged:** top's `reward_pct` defaults to 70,
  range (50, 90); brainbit's `alpha_reward_pct` defaults to 40, range (15, 70) — a
  different default/range under a different name, not just a rename.
- **Session shape:** top runs the full staged 4×5-min-block/2-min-rest structure
  (~34 min total); brainbit collapses to one continuous 20-min block (`warmup 120s →
  training 20min → cooldown 30s`, ~23.5 min total).
- **Verdict:** real pair (family match, identical site/band/direction). Canonical:
  top-level's structure (mode toggle, seed, staged session) — brainbit dropped
  clinically meaningful controls, not just cosmetic ones. The differing reward-rate
  default/range needs a clinician decision before collapsing to one value.

### 2.4 `beta_up_fz` ↔ `beta_focus_staged_fz_brainbit`

- **threshold_style mode control:** **both** have it — this is the one Family-A pair
  where brainbit kept the toggle (`choices = ["adaptive", "baseline"]`, present on all
  three of its thresholds: `beta_t`, `theta_t`, `hbeta_t`).
- **seed percentile:** top has one seed (`thr_uv`, pct = `reward_pct`). Brainbit has
  **three** — `beta_threshold_uv` (seed pct 40), `theta_threshold_uv` (seed pct 80),
  `hbeta_threshold_uv` (seed pct 80) — richer, not just duplicated.
- **montage:** top — `referential(active: "Fz", reference: amp.reference)`. Brainbit
  — `referential(active: "Fz", reference: "device")`. Clean case of the stated fork
  story.
- **sample_rate:** top `>= 250 Hz`; brainbit `>= 250 Hz` — identical, no relaxation.
- **What brainbit has that top lacks:** this is the big one. Top-level's `beta_up_fz`
  is a **single-band** envelope (`bands = ["beta"]` in meta, one `derive "env"`,
  citation just "frontal beta activation"). Brainbit implements the actual **three-band
  Egner & Gruzelier (2004) recipe** — `beta_envelope` (13-19 Hz) up, `theta_envelope`
  (4-8 Hz) AND `high_beta_envelope` (22-30 Hz) both required down
  (`all_of([above(beta,...), below(theta,...), below(hbeta,...)])`) — plus an explicit
  `block "beta_focus" { threshold = ["beta_t","theta_t","hbeta_t"] }` construct that
  **no top-level file anywhere uses**.
- **Verdict:** real pair by site+direction (both train beta-up at Fz), but the two
  files are not really "the same protocol with drift" — brainbit's version is a
  clinically fuller superset of what top-level's generic single-band draft attempts.
  **Do not** default to top-level's simpler shape when reconciling — the theta/hbeta
  inhibits and the `block` construct are load-bearing, not incidental. If one file
  must be retired, it should likely be top-level's plain single-band draft (redundant
  once the richer version exists), not the reverse. Flagging as UNCERTAIN whether
  "merge" is even the right operation here vs. keeping both as distinct protocols
  (simple beta-up vs. full theta/beta/hbeta focus training).

### 2.5 `composite_smr_theta_cz` ↔ `composite_smr_theta_cz_brainbit`

- **threshold_style mode control:** neither (weighted-composite protocols, no
  percentile threshold construct on either side — reward/inhibit are named
  sigmoid components).
- **seed percentile:** neither.
- **montage:** top — `referential(active: "Cz", reference: "linked_ears")`. Brainbit
  — `referential(active: "Cz", reference: "device")`. Neither is `amp.reference`.
- **sample_rate:** top `>= 256 Hz`; brainbit `>= 250 Hz` — relaxation applies here.
- **What top has that brainbit lacks:** `smr_center` / `theta_center` **frequency
  controls** (tunable centers) — brainbit hardcodes literal `(12 Hz, 15 Hz)` /
  `(4 Hz, 8 Hz)` bands, no controls for them. Also: top's `w_smr` / `w_theta` weight
  controls are typed as `number` (unitless, range 0-4) — the **correct** kind per top's
  own comment (*"NOTE: requires refrain >= the release that adds the `number` control
  kind; it parses today but won't resolve until then"*). Brainbit's `w_smr`/`w_theta`
  are typed as `percent` with the identical (0,4) range and identical defaults
  (1.0/0.6) — a dimensionally wrong control kind, almost certainly because brainbit
  was forked **before** the `number` kind existed and was never updated after
  top-level was.
- **What brainbit has that top lacks:** a `session {}` block entirely (`warmup 90s →
  training 30min → cooldown 30s`). **Top-level has no session block at all** — this
  file is currently unplayable as a staged session without one.
- **Verdict:** real pair (exact family-name match, near-identical reward math), but
  **neither file is complete** — this is the clearest case in the corpus where the
  task's warning ("the direction of divergence is not consistent") is literally true
  within one pair: top-level carries the newer control-kind fix and the tunable
  centers; brainbit carries the only session block. A reconciled file needs top's
  frequency controls + `number`-kind weights, PLUS brainbit's session block, PLUS a
  decided-on portable reference.

### 2.6 `hibeta_down_cz` ↔ `high_beta_down_cz_brainbit` (the task's given example — confirmed)

- **threshold_style mode control:** top has it; brainbit does not (`hbeta_t` is a bare
  `percentile(target_pct: hbeta_reward_rate, window: 2 min)`, no baseline branch).
- **seed percentile:** top has `thr_uv` with `seed = percentile {...}`; brainbit has
  no equivalent control.
- **montage:** top — `referential(active: "Cz", reference: amp.reference)`. Brainbit
  — `referential(active: "Cz", reference: "device")`.
- **sample_rate:** top `>= 250 Hz`; brainbit `>= 250 Hz` — identical, no relaxation.
- **Reward-rate control renamed/re-ranged:** top's `reward_pct` default 30, range
  (10, 50); brainbit's `hbeta_reward_rate` default 60, range (30, 85) — again not a
  simple rename, the numbers move.
- **Session shape:** top runs the full staged 4×5-min structure; brainbit collapses to
  one continuous 20-min block.
- **Verdict:** confirmed real pair, same shape of divergence as §2.3. Canonical:
  top-level's mode-toggle + seed + staged session; the differing reward-rate
  default/range needs a clinician decision.

### 2.7 `smr_up_c4` ↔ `smr_up_c4_brainbit`

- **threshold_style mode control:** **both** have it (this is the second Family-A pair,
  along with §2.4, where brainbit kept the toggle instead of dropping it).
- **seed percentile:** both have one (`thr_uv`/`smr_threshold_uv`, pct 40) — matching
  pattern, though brainbit's voltage range is narrower (0.5-10 uV vs top's 0.5-30 uV).
- **montage:** top — `referential(active: "C4", reference: amp.reference)`. Brainbit
  — `referential(active: "C4", reference: "device")`. Clean case of the stated fork
  story.
- **sample_rate:** top `>= 250 Hz`; brainbit `>= 250 Hz` — identical, no relaxation.
- **What brainbit has that top lacks:** a `high_beta_envelope` (22-30 Hz) artifact
  guard with its own `hbeta_inhibit_rate` control — top-level's version is pure
  single-band SMR with no artifact rejection at all.
- **What top has that brainbit lacks:** the full staged 4×5-min-block/2-min-rest
  session — brainbit collapses to one continuous 20-min block.
- **Verdict:** real pair (family match). Like §2.5, divergence runs in both
  directions within the same pair — brainbit added a real safety feature (hbeta
  guard) top-level lacks, while top-level kept a session structure brainbit dropped.
  Reconcile by carrying both forward, not by picking a "winner" wholesale.

### 2.8 `beta_up_cz_brainbit` — UNCERTAIN, candidate `theta_beta_cz`

No top-level file is named `beta_up_cz`, and `beta_up_cz_brainbit`'s own
`meta.family = "beta_up_cz"` doesn't match anything at top level either — unlike every
confirmed pair above, where the brainbit `family` field names an existing top-level
file verbatim (or, for §2.1/§2.6, close enough to be unambiguous).

Best candidate by site+band: `theta_beta_cz` (Cz, direction=up, meta.bands =
["beta","theta"], `env_center` default 16.4317 Hz spanning 13.15-19.72 Hz). Brainbit's
reward band is 15-20 Hz beta with a genuine theta inhibit (4-8 Hz) and hbeta guard
(22-30 Hz) — closely overlapping range. But:

- `theta_beta_cz`'s own implementation is (like the rest of Family A) a **single**
  envelope — despite `bands = ["beta", "theta"]` in its meta, it does not actually
  implement a theta-down component. So the "match" is a metadata-level band-list
  match, not an implementation match.
- Citations differ: top cites "Lubar (theta/beta)"; brainbit cites "Egner &
  Gruzelier (2004)" — related but named as distinct sources by the file authors.
- Goals differ: top `goals = ["adhd_attention"]`; brainbit `goals =
  ["alertness_performance"]`.

**This is genuinely uncertain.** I'm not confident enough in this pairing to
recommend a merge, and forcing it into either "real pair" or "no-counterpart" would
overstate the evidence. Flag for a clinician/protocol-owner decision: does
`beta_up_cz_brainbit` supersede `theta_beta_cz`, or is it a deliberately distinct
Cz-specific protocol that should stand alone? **Do not merge automatically.**

---

## 3. No-counterpart files (8) — must not be merged or retired

Verifying each of the initial pass's claims against the file text, plus files the
initial pass omitted:

- **`placement_alpha_coherence_pair_brainbit`** — CONFIRMED no counterpart, but with a
  nuance the initial pass's one-line gloss ("coherence") doesn't capture: it uses the
  same `coherence()` primitive as `alpha_coherence_c3c4`, but is a **clinician-
  parameterized site-pair** protocol (`placement { kind = "pair" }`, default `(F3,F4)`,
  allowed `[(F3,F4),(C3,C4),(P3,P4)]`) — no top-level file offers a placement control
  at all, and its default pair isn't even C3/C4. It's a demonstration of a Refrain
  feature (parameterized placement), not a fork of any single fixed-site file.
- **`placement_smr_active_brainbit`** — **not in the initial pass's list at all**, but
  it belongs in the same bucket as the two placement files the initial pass did flag:
  `placement { kind = "active" }`, clinician picks one site from `["C3","Cz","C4"]`
  at resolve time. No top-level file uses a placement control. No counterpart.
- **`placement_smr_bipolar_brainbit`** — CONFIRMED. `placement { kind = "bipolar" }`
  binds a clinician-chosen `(active, reference)` pair into `bipolar(pair: motor)`; no
  top-level file uses bipolar montage. No counterpart.
- **`placement_smr_set_brainbit`** — CONFIRMED. `placement { kind = "set" }` fans the
  whole derive/threshold chain out per site in a clinician-chosen set (Mode 2a); no
  top-level file replicates a pipeline across a site set. No counterpart.
- **`smr_classic_baseline_staged_cz_brainbit`** — CONFIRMED, but the reason is broader
  than "declares a `block`". It's one of **four** SMR-at-Cz brainbit files that all
  share `meta.family = "smr_cz"` (none of them match any top-level filename) and that
  explicitly cross-reference each other as siblings (see below) — not independent
  duplicates of `smr_theta_cz`, but a deliberately differentiated internal family.
  This file: baseline-fixed thresholds only (no mode toggle), no EMG inhibit (its
  header explains why: on the BrainBit Flex a relative HF-band guard trips on
  amplifier noise, not muscle, so it was deliberately omitted), 4×5-min staged blocks
  via an explicit `block "smr_up"`.
- **`smr_classic_cz_brainbit`** — **not in the initial pass's list**, also part of the
  "smr_cz" family (same `meta.family`). The "faithful Sterman/Lubar operant": SMR up
  with a *loose* theta veto (80th-percentile threshold) and a dedicated EMG inhibit
  (50-100 Hz). Its own header explicitly says it supersedes "the retired 3-condition
  demo" and names `smr_graded_cz_brainbit` as "its modern counterpart" — i.e., these
  files know about each other and are intentionally distinct, not accidental forks.
- **`smr_cz_brainbit_modulating`** — CONFIRMED (continuous `audio_gain =
  reward.continuous`, ungated by `event.holds`, vs the classic file's gated output).
  Also part of the "smr_cz" family. Its header references a sibling file
  `smr_cz_brainbit.refrain` that **does not exist** under that name in the current
  tree (only `smr_classic_cz_brainbit.refrain` does) — likely renamed at some point
  and the comment never updated; noted in Finding F3 below.
- **`smr_graded_cz_brainbit`** — **not in the initial pass's list**, also part of the
  "smr_cz" family. Continuous weighted composite (SMR-up + theta-down, `reward.composite`),
  baseline/adaptive anchors selectable via `threshold_style` mode. No top-level file
  implements this shape at Cz with SMR+theta as a composite (the one top-level file
  that does composite reward at Cz, `composite_smr_theta_cz`, uses fixed 6/8 uV
  midpoints, not adaptive percentile anchors, and has no mode toggle).

**All four "smr_cz" files must be preserved as distinct protocols** — collapsing them
into one (or into `smr_theta_cz`) would destroy three working, deliberately
differentiated implementations.

---

## 4. Findings — flagged prominently

**F1 — the "two-edit fork" story in the task background is only half-true.**
It accurately describes the 16 Family-A-derived pairs (montage `amp.reference` →
`"device"`, cleanly true in §2.3/§2.4/§2.6/§2.7). It does **not** accurately describe
the Family-B-derived pairs (§2.1, §2.2, §2.5): their top-level ancestor hardcodes
`reference: "linked_ears"`, never `amp.reference` — so "revert device back to
amp.reference" would be introducing a *new* reference scheme, not restoring the prior
one, and `linked_ears` (multi-channel software re-reference) is not numerically
equivalent to a generic single hardware reference. Similarly, the "`>=256 Hz` relaxed
to `>=250 Hz`" edit is real only for the 3 Family-B pairs that have brainbit
counterparts (§2.1, §2.2, §2.5) — every Family-A pair already reads `>= 250 Hz` at
top level, so there is no sample-rate divergence to "fix" in §2.3/§2.4/§2.6/§2.7 at
all. A later task that mechanically reverts both edits across all 16 files would be a
no-op on sample_rate for most of them and would silently invent a reference scheme
for the Family-B pairs that never existed in the ancestor.

**F2 — `alpha_symmetry_c3c4_brainbit` is the audit's most important correction to the
initial pass**, and arguably a bug in its own right, independent of this audit. The
initial pass characterized it as a standalone "asymmetry" paradigm with no
counterpart. It is not standalone: it names `alpha_coherence_c3c4` as its family,
targets the identical site pair and goal, and its own header explicitly says it is a
*temporary* stand-in for real coherence, planned for replacement once a
`coherence()` primitive shipped. That primitive has since shipped and is in active
use two files over, in `placement_alpha_coherence_pair_brainbit`. This file is stale
by the codebase's own stated plan.

**F3 — stale cross-references, evidence of files renamed/removed without updating
comments.** `smr_cz_brainbit_modulating`'s header names a sibling
`smr_cz_brainbit.refrain` that doesn't exist (current file is
`smr_classic_cz_brainbit.refrain`). `smr_classic_baseline_staged_cz_brainbit`'s header
names a sibling `smr_classic_baseline_cz_brainbit.refrain` that doesn't exist either.
`beta_focus_staged_fz_brainbit`'s header names a companion
`beta_focus_baseline_staged_fz_brainbit.refrain` that also doesn't exist (that file's
own `threshold_style` mode control already covers both cases in one file, which may
be why the separate file was never created — but the comment wasn't cleaned up).
None of these are counterpart candidates for this audit (the named files aren't in
the tree), but they're a signal that this folder has had at least one prior rename/
consolidation pass whose comments didn't get updated — worth a cleanup pass
independent of the merge task.

**F4 — the initial pass under-counted "no counterpart" files by 3.**
`placement_smr_active_brainbit`, `smr_classic_cz_brainbit`, and
`smr_graded_cz_brainbit` were not mentioned in the initial pass at all, but on
reading, none of them has a real top-level counterpart either — they round out the
"placement_smr" trio and the "smr_cz" quartet respectively.

**F5 — two pairs (§2.5 `composite_smr_theta_cz`, §2.7 `smr_up_c4`) diverge in *both*
directions simultaneously** — each side has something clinically load-bearing the
other lacks (frequency controls + correct control kind + session block vs. a safety
inhibit; staged session vs. an artifact guard). These cannot be resolved by "pick the
newer/richer file, drop the other" — a straight merge needs pieces from both sides.

**F6 — one pairing (§2.4 `beta_up_fz`/`beta_focus_staged_fz_brainbit`) may not be a
"fork that drifted" at all, but a generic single-band placeholder next to its own
fuller clinical implementation.** If so, "merge" is the wrong verb — the plain
top-level file may simply be redundant once the fuller version exists, and should be
retired on its own merits rather than reconciled line-by-line with its sibling.

**F7 — one pairing (§2.8 `beta_up_cz_brainbit`) I cannot confirm at all.** Unlike
every other file in this folder, its `meta.family` string doesn't match anything in
`protocols/`. I'm flagging it as UNCERTAIN rather than forcing it into either bucket.
