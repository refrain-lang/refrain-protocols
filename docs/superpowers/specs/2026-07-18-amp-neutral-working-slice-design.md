# Amp-neutral working slice — `smr_theta_cz` runs on two amps from one source — Design

- **Date:** 2026-07-18
- **Status:** design (approved; ready to plan)
- **Scope:** `refrain-protocols` — one protocol re-authored amp-neutral + the corpus-gate harness changes that let it pass CI.
- **Depends on:** `refrain` **v0.15.0** released (ships `amp.reference`; PR #69 + the `release: v0.15.0` PR). `placement` already shipped (v0.6+).
- **Relationship:** the first increment of sub-project #4 (library re-authoring) of the device-agnostic protocol platform (Linear **WOR-142**). Consumes the engine spec `refrain/docs/superpowers/specs/2026-07-16-amp-reference-abstraction-design.md`. Full-amp gate coverage is tracked separately as **WOR-163**.

## The goal, in one sentence

**Prove the amp abstraction end to end on a real clinical protocol: one `smr_theta_cz` source, authored once, resolves and runs correctly on both a consumer amp (BrainBit → `device`) and a clinical amp (Q21 → `linked_ears`) — asserted in CI.**

## Why a slice, not the whole set

Converting one protocol surfaces every integration problem the full re-authoring will hit (the `amp=None` gate break, the site/placement coupling, the `requires` floor) at 1/38th the blast radius. Once the slice is green in CI, converting the rest is repetition. This increment is the proof; the sweep is follow-on.

## The transformation

`protocols/smr_theta_cz.refrain` today hardcodes the montage in two places:

```refrain
requires { sample_rate = ">= 256 Hz"; channels = ["Cz"] }
input "raw" { montage = referential(active: "Cz", reference: "linked_ears") }
```

Re-authored amp-neutral:

```refrain
requires { sample_rate = ">= 250 Hz"; channels = ["Cz"] }   # 250, not 256 — see below
input "raw" { montage = referential(active: site, reference: amp.reference) }
controls {
  site = placement { kind = "active"; default = "Cz"; allowed = sensorimotor }
  # ... existing controls unchanged ...
}
```

Three coupled changes, each load-bearing:

1. **`reference: amp.reference`** — the montage reference comes from the connected amp. Folds to `device` on BrainBit (its dedicated ear-reference is pre-applied) and `linked_ears` on Q21 (which declares A1/A2). This is the whole point.
2. **Site as a `placement`** — `active: "Cz"` becomes `active: site`, a `placement` control (`kind = "active"`, `default = "Cz"`, `allowed = sensorimotor`). Reference-neutral alone is insufficient: the site is hardcoded too, and "author once, run anywhere" needs the operator to bind the electrode per device. `Cz` is a channel **both** target amps declare, so the default resolves on each.
3. **`requires.sample_rate = ">= 250 Hz"`** — BrainBit runs at 250 Hz, so `>= 256` fail-closes there and the protocol could not resolve on the very amp we are proving. The SMR/theta reward band tops out near 18 Hz, so 250 Hz is honest headroom, not a fudge. This is a *slice-scoped* fix; general `requires`-neutrality across the set stays a non-goal (a separate authoring pass).

`requires.channels` stays `["Cz"]` — the **active site only**. Whether reference electrodes are needed is now amp-dependent (BrainBit → none; Q21 → A1/A2, which Q21 supplies), so it is resolved per-amp against the amp's channel set (`resolver.py:313`), never declared statically. The consistency lint from the engine spec keys on the *literal* `linked_ears` spelling and does not fire on `amp.reference`.

**No BrainBit file is merged or deleted in this increment.** `smr_theta_cz` has no exact BrainBit twin (the exact-twin composite pair needs the `number` control kind to `resolve()`, a separate dependency). Fork-dedup — merging a generic + BrainBit pair into one file — is the follow-on, and it is where the metadata-union question binds. Recorded ruling for then: the merged file resets to **`status = "draft"`** (a structurally new artifact, not yet clinically re-reviewed in its merged form) while carrying both vocabularies' governance fields. For this slice, `smr_theta_cz` keeps its existing `status = "draft"` and its metadata is untouched except that `hardware = "generic"` is dropped (the file is now genuinely amp-neutral, not "generic hardware").

## The harness

Re-authoring one protocol breaks the corpus gates, which resolve everything at `amp=None`. Three changes:

### 1. Task 0 — the glob fix (do first, its own commit)

`tests/test_corpus_roundtrip.py:26` uses a non-recursive `glob("*.refrain")`, so all 16 `protocols/brainbit/*.refrain` are silently excluded from the only test that proves a protocol is renderable and resolvable. Change to `rglob` (matching `tests/test_catalog.py` and `tools/build_catalog.py`). This lands first, under the existing test, so the re-authoring happens under real coverage. Expect it to pull the BrainBit files into the gate — confirm they pass at `amp=None` (they use literal `device`, which resolves without a profile) before proceeding.

### 2. Roundtrip gate — per-file, two-amp for amp-readers

The roundtrip test becomes amp-aware, per file:

- **Detection:** a protocol is "amp-reading" if its source contains the token `amp.` (word-boundary). Simple, explicit, and does not depend on catching a resolver error.
- **Amp-reading protocols:** resolve against **both** `brainbit_flex` and `q21`, asserting the describe→render→resolve IR round-trips and is valid on each. This is the two-amp DoD assertion baked into CI.
- **All other protocols:** resolve at `amp=None`, exactly as today — no behaviour change for the literal-reference corpus.

The two profiles are loaded from the installed `refrain` package's `amp_profiles/` (`brainbit_flex.json`, `q21.json`). Full-amp coverage is **WOR-163**.

### 3. Fuzz gate — resolve the amp-reader with an amp

`refrain fuzz protocols/ --library lib --seed 42` currently resolves at `amp=None`; the one amp-reader would error there and fail the build. `refrain fuzz` already accepts `--amp`. The mechanism (settle early in the plan — it is the main implementation risk): run the existing `amp=None` fuzz over the literal corpus unchanged, plus a targeted fuzz of the amp-reading subset against each of the two profiles (`--amp brainbit_flex`, `--amp q21`). Do **not** globally switch the whole corpus to one amp — that would silently change resolution for every literal protocol and could mask regressions. The primary CI proof is the roundtrip two-amp assertion (§2); the fuzz gate must simply not error on the amp-reader and should exercise its behaviour on at least one amp.

## Definition of done

1. `protocols/smr_theta_cz.refrain` is amp-neutral (`amp.reference` + `placement` site + `>= 250 Hz`).
2. It resolves to valid IR on `brainbit_flex` (reference folds → `device`) **and** `q21` (→ `linked_ears`).
3. On synthetic EEG, its montage produces a **live, non-zero** stream on both amps — the flatline that the pre-abstraction `linked_ears` form exhibits on a BrainBit is gone. (This mirrors the engine-side proof already demonstrated.)
4. Corpus gates green: roundtrip (now `rglob`, two-amp for the amp-reader, `amp=None` for the rest), catalog freshness, and fuzz.
5. `catalog.json` regenerated and committed.

## Sequencing

Gated on the engine release: **(a)** merge `refrain` PR #69 → **(b)** cut + merge `release: v0.15.0` (tag it) → **(c)** in `refrain-protocols`, repin CI from v0.14.0 to v0.15.0 → **(d)** this slice. Steps (a)–(c) are prerequisites; the slice cannot go green in CI until the pinned engine can resolve `amp.reference`. Development/proof can proceed earlier against a local editable v0.15.0 build.

## Non-goals

- **Converting the rest of the set.** One protocol; the sweep is follow-on.
- **Fork-dedup** (merging + deleting BrainBit twins) and the **metadata union** — deferred to the increment that converts exact-twin concepts.
- **The deferred engine hardening** (the `linked_ears` fail-closed runtime break + the consistency lint). That is a separate `refrain` increment; this slice needs neither (Q21 has ear electrodes, so its runtime path already works, and the amp-neutral form never hits the literal-`linked_ears` lint).
- **General `requires`-neutrality** beyond the one `>= 250 Hz` fix this slice requires.
- **Full-amp gate coverage** — WOR-163.

## Appendix: why the site must be a placement, concretely

A protocol whose active site is a channel the amp does not declare fails the resolver's `requires.channels` check (`resolver.py:313`). `brainbit_flex` declares only `Cz/F3/F4/Pz`. So a literal `active: "C4"` protocol *cannot* resolve on a BrainBit — the electrode isn't there. `Cz` happens to be on both target amps, which is why the slice's default resolves cleanly; but the general fix is a `placement` the host binds to whatever electrode the operator actually placed. Reference-neutral without site-neutral is not device-neutral.
