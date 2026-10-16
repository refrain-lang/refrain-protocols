# Narrowband melodic feedback implementation plan

> **For agentic workers:** Implement inline using `superpowers:executing-plans`; use test-first changes and verify each repository independently.

**Goal:** Add a separate narrowband alpha/theta protocol with gentle, distinct continuous approach, crossover, and sustained sounds, plus a migration inventory for Recorder-specific protocol logic.

**Architecture:** Keep the present narrowband signal and guard rules. Give the new protocol its own ID and feedback asset declaration. Reuse Recorder's continuous three-role mixer and previews, supplying bundled, original WAVs automatically when the protocol names an approved built-in asset set. External music remains steady and separately controlled. Protocol semantics live in Refrain; Recorder only renders audio and stores sessions.

**Tech Stack:** Refrain DSL, Python/pytest, Recorder FastAPI and React/TypeScript, 44.1-kHz stereo PCM WAV.

**Spec:** In-chat design approved by the user's “let's build it” message on 2026-10-06.

## Global constraints

- Preserve `alpha_theta` and `alpha_theta_narrowband` unchanged.
- New catalog ID: `alpha_theta_narrowband_melodic`; keep 6–8 Hz theta, 9–11 Hz alpha, 3–5 Hz slow and 15–56 Hz fast guards.
- Literal crossover remains theta/alpha ≥ 1.00, independent of the shaping target.
- Background media remains steady under guards; positive feedback fades rather than cutting it out.
- Bundled sounds are original, loopable, licensed by authorship, and subject to the existing feedback ceiling.
- Clinical claims are out of scope. Synthetic tests prove authored signal behavior only.

## Review focus

- Missing or damaged bundled WAV: setup/start returns a clear error before training.
- Protocol ID from an untrusted custom file must not select arbitrary filesystem paths.
- Quiet stages and paused/muted states do not produce feedback.
- Guard activity suppresses reward layers without silencing external media.
- A new protocol appears distinctly in the picker while both existing versions remain.

### Task 1: Protocol and companion guide

**Files:** Create `protocols/eeg/alpha_theta_narrowband_melodic.refrain`, `protocols/eeg/alpha_theta_narrowband_melodic.md`, `tests/test_alpha_theta_narrowband_melodic.py`; regenerate `catalog.json`.

**Interface:** Emit the existing semantic channels `feedback_approach`, `feedback_crossover`, and `feedback_sustained`; declare `feedback_style = "layered_texture"` and `feedback_asset_bundle = "narrowband_melodic_v1"`.

- [ ] Write a failing resolver test for the new ID, bands, guards, output channels, asset bundle and unchanged existing ID.
- [ ] Run that test and confirm failure because the new file is absent.
- [ ] Add the new protocol with the same signal/guard controls and a distinct title and provenance. Add its companion guide and regenerate the catalog.
- [ ] Run focused protocol tests and verify the new entry resolves.

### Task 2: Bundled sounds and Recorder setup

**Files:** Add an original deterministic sound-generation script and three generated WAVs under `recorder/backend/nf/assets/feedback/narrowband_melodic_v1/`; modify `recorder/backend/nf/texture_manifest.py`, `protocol_meta.py`, `api.py`, `frontend/src/types.ts`, `frontend/src/components/NFSetupDialog.tsx`; add focused tests.

**Interface:** A protocol metadata `feedback_asset_bundle` selects only an allowlisted bundled asset directory when the operator leaves `texture_asset_dir` empty. Explicit operator directories continue to work. Existing `layered_texture` playback and preview APIs remain intact.

- [ ] Write failing tests for resolving the allowlisted bundle and rejecting invalid bundle names, and for WAV format/loop/clipping checks.
- [ ] Run tests and confirm the expected failures.
- [ ] Implement the bundle resolver, metadata read, setup default, and original WAV assets. Use the same resolver for preview and session start.
- [ ] Run focused backend tests and frontend typecheck.

### Task 3: Migration note and final checks

**Files:** Create `docs/recorder-to-refrain-alpha-theta-migration.md` in the protocol repository.

- [ ] Record the hard-coded semantic decisions in Recorder, target ownership, priority and prerequisite Refrain capabilities. Keep device/audio implementation in Recorder.
- [ ] Run protocol and Recorder focused suites, inspect both diffs for accidental changes to existing protocols or user's unrelated audio edits, and report limits of verification.
