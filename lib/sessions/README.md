# Session templates

Canonical `session { phases = [...] }` shapes. Protocols inline a default; the **host overrides** block length / count / which-blocks by sending a different phase list to the engine (durations are literals compiled to sample counts, so override = re-emit the phase list, not mutate a running protocol).

### `operant_staged` (the default)
`warmup 90s → 4×(5min block, timed_with_floor + 2min rest) → cooldown 30s`, on one baseline up front. Nobody trains SMR/θ for 30 min straight; short blocks with rests keep the patient fresh. Used by every operant up/down protocol.

### `alpha_theta_deep`
`settle 2min → 2×(15min block) → cooldown`. The deliberate exception to the ≤5-min rule — alpha/theta crossover needs sustained eyes-closed time to reach the deep state.

### `operant_single`
`warmup → 1×20min → cooldown`. Legacy/quick single-block.

### `baseline_only`
`warmup → baseline capture → stop`. Pre/post measurement, no feedback.

> These are documented here as the agreed shapes; concrete protocols inline the matching `session` block. A future `extends`-based application (once multi-parent composition is confirmed in `refrain/compose.py`) would let protocols reference a template instead of inlining it.
