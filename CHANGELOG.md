# Changelog

## Unreleased — biosignal reframe (BREAKING)

The library is now a general-purpose **biosignal** training-protocol library:
modality-neutral, and general-wellness rather than clinical in what it ships.
No protocol's behaviour changed — no pipeline, threshold, reward, or inhibit
was touched, and the fuzzer result is byte-identical to `main`
(4/4 and 22/22 pass, 0 violations, 0 errors).

### Breaking
- **`goals` vocabulary replaced.** `adhd_attention`→`focus_attention`,
  `calm_anxiety`→`calm_stress`, `sensorimotor_sleep`→`sleep_quality`,
  `mood_regulation`→`mood_balance`. `trauma_recovery` is removed;
  `interoception` is new. Hosts bucket unknown values into "Other" as before.
- **`modality` widened** to `eeg`, `ecg`, `hrv`, `gsr`, `emg`, `temp`, `resp`;
  default stays `eeg`. Every EEG protocol now declares it explicitly.
- **`hardware`**: `clinical_amp` → `research_amp`.
- **Dropped from distributed files:** `indication`, `population`,
  `safety_monitoring`, `outcome_measures`. A host that needs them keeps them
  host-side. `control_ref` is kept.

### Changed
- `evidence` and `citation` describe how established a **technique** is and
  where it comes from — provenance, not efficacy. The tiers are unchanged.
- 21 files carried an `evidence` value that was never in the enum (19 `demo`,
  2 `clinical`). Each now carries the tier a same-technique file in the
  library already claimed — from its own protocol family where one existed
  (6 files), otherwise from the nearest family training the same thing. No
  file's tier was raised past a claim already in the library.
- Comments, titles, and summaries describe the signal training rather than a
  condition. Citations keep their real paper titles.

### Added
- `tests/test_corpus_schema.py` — validates every protocol against the whole
  schema. Its absence is why the `evidence` drift went unnoticed.
- `tests/test_neutrality.py` — forbids the dropped fields and indication
  language in distributed prose.

## [0.1.0] — unreleased
Initial seed of the reference protocol library. **All protocols `status = "draft"` (untested).**

### Added
- Metadata-organized library (flat `protocols/`, navigated by `meta` tags, not folders).
- Tag contract: `schema/protocol-meta.schema.json` (incl. the `status` axis: draft/roadmap/reviewed/stable).
- 32 generated operant up/down protocols (adaptive + baseline pairs) across the ADHD/Attention, Sensorimotor/Sleep, Alertness/Performance, Calm/Anxiety, Mood/Trauma, and Deep/Meditative goals.
- Specials: weighted composite (uses the `number` weight kind), alpha/theta crossover, interhemispheric alpha coherence, frontal alpha asymmetry, HRV resonance.
- `drafts/scp_cz.refrain` — SCP roadmap draft enumerating the four engine gaps it needs.
- Docs: host-app chooser guide, tagging, conventions, evidence policy, contributing.
- `tools/build_catalog.py` (derived cache).
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
