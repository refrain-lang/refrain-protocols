# Device-agnostic protocol platform (amp-neutral library) — Design

- **Date:** 2026-07-06
- **Status:** design (proposed; not yet scheduled)
- **Scope:** cross-repo — `refrain` (engine), `refrain-protocols` (library), `coherence-recorder`, `coherence-portal`, `cc-mobile`
- **Relationship:** this is the "done right" version of what we called *Phase 2 Slice B2* (hardware→amp-profile merge). It supersedes the narrow "merge the ~5 overlapping files" idea, which the investigation below showed is low-value.

## The goal, in one sentence

**Author each protocol once, hardware-neutral; the connected device's amp profile supplies everything hardware-specific — so one library serves every device, with no per-device copies, ever.**

## Why (the problem)

The library is split into a **generic set** and a **BrainBit set** that are hardware-duplicated for overlapping concepts. Worse than the duplication itself: **every new concept needs a hand-authored per-device copy to run on a new device**, and adding a third amplifier (Muse, OpenBCI, DragonEEG) means re-cloning the library. That is O(protocols × devices) hand-maintenance, and it has already produced drift (stale cross-references, divergent metadata vocabularies).

An investigation (2026-07-06) found the generic and BrainBit versions of the same concept differ in three ways:

| | Generic | BrainBit |
|---|---|---|
| Montage reference | `linked_ears` | `device` |
| `requires` | `≥256 Hz` | `coupling=ac`, `≥250 Hz` |
| Band definition | `bandpass(center: env_center, bandwidth: ratio(…))` (tunable) | `bandpass(band: (12 Hz, 15 Hz))` (fixed literal) |
| Artifact guards | none | some add a high-beta/EMG guard |

The reference and `requires` are clean hardware deltas. The band form is an **authoring choice, not a clinical one** (the parameterized form subsumes the fixed band as a default). The artifact-guard difference is driven by hardware capability (a consumer amp's HF band is amplifier noise, so an EMG guard is dropped). So the split is *mostly* hardware, plus one non-hardware inconsistency (band form) that should simply be standardized.

## The ideal end-state

One flat, device-agnostic library. A protocol declares its montage against an **abstract reference** and its artifact guards **conditional on amp capability**; at resolve time the connected amp profile fills in the reference, the sample rate, the available sites, and which guards apply. The `brainbit/` folder disappears. Adding a device is one amp-profile JSON and zero protocol edits.

## What each surface needs

### Engine (`refrain`) — the enabling features
1. **Amp-profile enrichment.** Add a `reference` field (the amp's hardware reference: `device` | `linked_ears` | `mastoids` | …) and a small **capability vocabulary** the resolver and protocols can key off — at minimum `clean_hf_floor: bool` (whether a high-frequency EMG guard is meaningful on this amp). (`amp_profile.py` today has coupling / sample_rates / channels / impedance / markers / adc — none of these.)
2. **Montage reference from the amp.** Support `referential(active: site, reference: from_amp)` so the reference resolves from the connected profile instead of a baked literal. (Today `reference` is a string literal; `from_amp` is new.)
3. **Capability-conditional blocks.** A way to include/exclude a named decl (an `inhibit`) based on an amp capability — e.g. drop the EMG guard when `amp.clean_hf_floor == false`. This can reuse the resolve-time folding machinery the `mode` control already uses (a `when amp.<cap>` guard on the decl, folded away at resolve time), so it is an extension of an existing pattern, not a new subsystem.

### Protocol library (`refrain-protocols`)
1. **Re-author overlapping concepts as amp-neutral cores:** `reference: from_amp`, the parameterized band form, capability-conditional guards. Retire the per-device copies.
2. **Retire the `brainbit/` folder** — one flat library. Hardware stops being a folder or a filename; it is purely an amp-profile concern.
3. **Standardize the band form** on parameterized center+ratio (the fixed BrainBit bands become defaults). Verify no clinical regression per device.
4. **What stays distinct:** feedback-style clusters (classic/graded/modulating), placement variants, and session shapes are *different protocols*, not hardware variants — they are unaffected. Only pure hardware-duplicate pairs merge. A device that genuinely needs special handling can still `extends` the neutral core and override — amp-neutral is the default, not a straitjacket.

### Recorder (`coherence-recorder`)
1. **Device-aware amp profile:** `resolve()` uses the *connected* device's profile (`_amp_profile_path_for_protocol()` stops hardcoding `brainbit_flex.json`).
2. **Repoint discovery** from `protocols/brainbit/` to the unified library, and update `default_protocol`.

### Portal (`coherence-portal`) + Mobile (`cc-mobile`)
1. **Portal:** the sidecar compile passes the **client's target-device** amp profile so assigned IR bakes for the right hardware.
2. **Mobile:** its off-device compile passes the device amp profile (instead of `amp=None`); assigned protocols ride the portal unchanged.

## Migration (non-breaking, sequenced)

1. **Engine features** (amp-profile fields + `from_amp` + capability-conditional guards) — additive, shipped as a new `refrain` release.
2. **Library re-authoring** behind the new features; keep the old per-device files as shims until consumers migrate.
3. **Recorder** device-awareness + discovery repoint (coordinated: recorder must move before the folder is retired).
4. **Portal / mobile** compile device-awareness.
5. **Retire** the `brainbit/` folder + shims once all consumers are on the unified library.

## Value

- **One library, any device.** Adding an amplifier = one amp-profile JSON, zero protocol copies.
- **Kills O(protocols × devices) duplication permanently**, and the drift it causes.
- **New concepts serve every device automatically** — no hand-authored per-device copies, ever.

## Non-goals

- Not merging the feedback/placement/session variants (those are distinct protocols).
- Not forcing device-tuned protocols to be neutral where a real clinical reason exists — `extends` remains the escape hatch.

## Open questions (to resolve during engine planning)

- Exact syntax for `reference: from_amp` and the capability-conditional guard (`when amp.<cap>` vs an amp-profile-driven drop).
- The amp-profile **capability vocabulary** (which flags beyond `clean_hf_floor`).
- Whether standardizing the band form has any per-device clinical implication.

## Effort & ownership (rough)

| Surface | Owner | Size |
|---|---|---|
| Amp-profile fields + `from_amp` + capability-conditional | engine team | medium |
| Re-author library amp-neutral, retire `brainbit/` | library team | medium (gated on engine) |
| Device-aware resolve + discovery repoint | recorder team | medium |
| Sidecar compile device-awareness | portal team | small–medium |
| Mobile compile amp profile | mobile team | small |

Multi-team, sequenced; a platform initiative, not a single sprint.

## Prerequisite already shipped

`refrain 0.12.0`'s `mode` control + resolve-time folding (adaptive/baseline, feedback) is the pattern the capability-conditional guard extends — so this builds on machinery already in production, not a green field.
