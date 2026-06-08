# Conventions

## Filenames
`<target>_<site>[_baseline].refrain` — clear, not over-bearing. Navigated by metadata, not filename.
- **Adaptive** is the bare name; **`_baseline`** is the only variant suffix.
- No `_classic` / `_graded` / `_staged` / `_brainbit` / `_v1`. Hardware, session, and goals live in `meta`.
- `target` encodes band(s)+direction succinctly: `smr_theta`, `theta_beta`, `theta_down`, `slow_down`, `beta_up`, `alpha_up`, `hibeta_down`, `faa`, `alpha_theta`, `alpha_coherence`, `composite_smr_theta`, `hrv_resonance`, …

## Montage
Reference protocols are **vendor-neutral**: `referential(active: "<site>", reference: "linked_ears")`. Amp-specific adaptation (e.g. BrainBit `reference: "device"`, no EMG inhibit) is a `meta.hardware` tag + a host-side overlay — never a `_brainbit` filename.

## Sessions
Default to **≤5-min blocks with rests on one baseline** (`lib/sessions/operant_staged`). The host overrides block length / count / which-blocks by sending a different phase list to the engine. The deliberate exception is **alpha/theta** (long eyes-closed blocks → `lib/sessions/alpha_theta_deep`).

## Specials
SMR stays sensorimotor (Cz/C3/C4) — never Fz. Frontal sites (Fz, F3/F4) carry the theta/beta, theta-down, and asymmetry targets.
