# Changelog

## [0.1.0] — unreleased
Initial seed of the reference protocol library. **All protocols `status = "draft"` (untested).**

### Added
- Metadata-organized library (flat `protocols/`, navigated by `meta` tags, not folders).
- Tag contract: `schema/protocol-meta.schema.json` (incl. the `status` axis: draft/roadmap/reviewed/stable).
- 32 generated operant up/down protocols (adaptive + baseline pairs) across the ADHD/Attention, Sensorimotor/Sleep, Alertness/Performance, Calm/Anxiety, Mood/Trauma, and Deep/Meditative goals.
- Specials: weighted composite (uses the `number` weight kind), alpha/theta crossover, interhemispheric alpha coherence, frontal alpha asymmetry, HRV resonance.
- `drafts/scp_cz.refrain` — SCP roadmap draft enumerating the four engine gaps it needs.
- Docs: host-app chooser guide, tagging, conventions, evidence policy, contributing.
- `tools/gen_seed_protocols.py` (regenerates the operant set), `tools/build_catalog.py` (derived cache).
- CI: parse gate + meta-schema validation + catalog-drift check.
- `critical_fluctuation.refrain` — a new **non-operant** paradigm: dynamical
  neurofeedback that cues on "critical fluctuations" (early-warning signals —
  rising variance + critical slowing down) of an impending critical transition,
  **across a broad band set** (declared once in `bands { }`, fanned out per band)
  at **any** site. `status=draft`; resolves on refrain >= 0.10.0 (`autocorr` +
  the `bands` fan-out). Refs: Scheffer 2009; Dakos 2012; Maturana 2020; Yang 2012.

### Changed
- Bumped the `refrain` pin to **v0.10.0** (CI install + `pyproject`), which ships
  the `autocorr` primitive and the `bands { }` fan-out — so `critical_fluctuation`
  now resolves, not just parses.
- Trained bands are now a **clinician knob**: each EEG-training band is a single
  `*_center` frequency control (set at session setup, frozen during the run)
  instead of a baked `(lo, hi)` literal. Uses bandpass's center/bandwidth
  (geometric) form — `center = sqrt(lo*hi)`, `ratio = hi/lo` — so behaviour is
  unchanged at the default. 35 protocols affected.
- Adaptive (percentile) protocols expose the **target reward %** as a live
  `reward_pct` control (was a baked 70/30 literal — the single most-adjusted
  clinician knob). 19 protocols affected.
- Physiological-definition bands (HRV LF 0.04–0.15 Hz, interhemispheric alpha
  coherence) intentionally keep literal bands and expose only `reward_pct`.

### Depends on (see ROADMAP)
- refrain `number` control kind (for the composite protocol to `resolve()`).
- refrain `read_meta`/`catalog` public API (host metadata reads).
