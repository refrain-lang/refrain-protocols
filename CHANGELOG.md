# Changelog

## Unreleased

## 0.4.0 — the guards stop silencing the tone

### Changed
- **`smr_spindle`: theta and the low-alpha shoulder no longer mute.** They are
  `flag()` inhibits still carrying `kind = "artifact"`, so a contaminated
  sample still freezes the reward hold — the tone simply keeps playing through
  it. Measured on 13 recordings, three arms one line apart, one invocation:

  | theta/low action | onsets/min | held | heard | silent |
  |---|---|---|---|---|
  | `mute(release: 200 ms)` (before) | 10.7 | 27.8% | 6.8% | 65.8% |
  | `mute(release: 0 ms)` | 17.1 | 30.3% | 11.5% | 49.8% |
  | **`flag()`** (now) | **17.1** | **30.3%** | **18.2%** | **34.3%** |

  Audible reward nearly triples and silence halves. The middle arm is why the
  credit is split honestly: it still mutes, yet reproduces the flag arm's
  reward side to the decimal — so the **entire** reward-side gain is the 200 ms
  release hangover coming off the artifact mask, and none of it is the change
  of action. A mute-action artifact inhibit feeds the mask its *gated* signal,
  which carries the release; a flag feeds the raw condition, which does not.
  16.0 of the 31.5 silence points are the hangover; 15.5 are the silencing.

  That middle arm is **not** a candidate. A release exists to stop an audio
  gate chattering across its threshold, and at 0 ms the tone can flick on and
  off — which the measurement cannot see, since it reports how *much* of the
  window is silent, not how often it changed. A `flag()` has no audio gate, so
  there is nothing to chatter.

  **The cost:** theta and the alpha shoulder stop taking the tone away, so a
  trainee hears the shaping tone through mild contamination that used to
  silence it. The reward is unaffected. If either guard must silence, the
  measurement prices that choice at 31.5 points of audible time.
- **The `refrain` floor is `>= 0.26.0`, and not optionally.** An artifact label
  on a `flag()` makes this protocol emit IR wire version **0.7**, which a
  v0.25.x engine refuses at load. The previous mute form emitted 0.6, and so
  does the `release: 0 ms` arm — the wire version follows the feature used,
  never the size of the diff. CI checks out the same tag.

### Fixed
- The v0.3.0 entry below described high-beta and muscle as "artifact mutes".
  They are **plain** mutes — `kind` is unset on both — and the difference is
  load-bearing: at the reward stage refrain applies only the observability
  mask, so an unlabelled mute does not freeze the hold. Those two guards
  silence the tone while the streak keeps counting, which means a reward can be
  credited for SMR the trainee never heard. Corrected in place; noted here
  because v0.3.0 is already tagged and anyone diffing against that tag will see
  the text move.

## 0.3.0 — the spindle-contingent SMR protocol

### Added
- **`protocols/eeg/smr_spindle.refrain`** — SMR training contingent on a
  *sustained spindle* rather than an instantaneous threshold crossing. One
  12–16 Hz `band_envelope` at 320 ms declared latency carries the reward; the
  criterion is a 500 ms `dwell` with a 120 ms dip `tolerance`. Theta and the
  low-alpha shoulder are `kind = "artifact"` inhibits, so a contaminated
  sample freezes the hold instead of resetting it; high-beta and muscle are
  plain mutes, which silence the tone WITHOUT freezing the hold. An always-on continuous tone shapes toward the criterion and
  a ding marks the dwell.
- `tests/test_smr_spindle.py` — pins the band wiring, the reward shape, the
  percentile-only high-beta guard and the resolve-time duration control. Each
  docstring says which fact it establishes, so a later edit that breaks one
  knows what it broke.
- **`tests/test_both_backends.py`** — every protocol must build and step on
  BOTH evaluator backends. It exists because one did not: `smr_spindle` gave
  its inhibits `metric = passthrough(input: <derive>)`, which the Python
  resolver accepts (it checks only that the metric is a call) and which
  `refrain-core`'s compute dispatch panics on, because `passthrough` lives in
  that crate only as a montage. A host resolves `backend="auto"` to Rust
  whenever the wheel is importable, and the recorder ships the wheel — so a
  real session runs Rust, and 46 of 47 protocols were fine while nothing in
  CI could see the one that was not.
- `tools/measure_spindle_front_end.py` and additions to
  `tools/measure_envelopes.py`: per-inhibit activity, a decomposition of the
  reward over its `reward/condition[n]` taps, and a `_med()` that prints `--`
  rather than a confident `0.0%` when nothing measured a figure.

### Changed
- **The reward criterion pays out.** As first written the protocol rewarded
  **1.2%** of a block against a 25–40% design target. Not a tuning problem:
  every marginal was calibrated (SMR above its own threshold 60.7% of the
  time, the two vetoes satisfied 81% and 85%), but a 500 ms criterion over
  three correlated terms almost never completes, because one dipping sample
  in any term zeroes the streak. Moving theta and the low band out of the
  conjunction into artifact inhibits, plus the 120 ms tolerance, reaches
  **27.8% reward time** at 10.7 reward onsets per minute on the
  thirteen-recording replay (median, real engine).
- The `refrain` floor is **`>= 0.25.1`**, and CI checks out the same tag. It
  carries the dip `tolerance` on `dwell` / `dwell_rearm` / `hold_for` and the
  `kind` label on inhibits that this protocol needs. The floor, the CI pin and
  whatever a session actually has installed are three separate declarations;
  they move together or the first two stop meaning anything — the CI pin was
  left at v0.24.0 in the first draft of that bump, which would have validated
  the whole corpus against a refrain below the declared floor.
- Two inhibit-band thresholds and their baseline-mode microvolt controls are
  **gone** rather than left as declarations nothing reads. An inhibit's
  threshold must be a literal constructor call, so neither guard can take the
  `threshold_style` switch; in "baseline" mode only the SMR reward threshold
  becomes an operator-set value and all three guards keep chasing 2-minute
  rolling percentiles.

### Fixed
- `smr_spindle` could not have started a session (see `test_both_backends.py`
  above). The inhibit metric is now `linear(..., midpoint: 0 uV, slope: 1)`,
  verified equivalent to the `passthrough` form to 8.3e-15 on
  `output/audio_gain`.
- The protocol header discounted its own silence figure wrongly. It told the
  reader that half of the measured muting was the warmup phase "by design";
  the harness runs `skip_warmup=True`, which bypasses a leading output-muted
  phase, so **none** of it is warmup. The honest figure is 65.8% of the scored
  window silent with 6.8% delivered as audible reward — worse than the note
  implied.
- `tools/measure_envelopes.py` printed per-inhibit rows as `mute <name>` while
  reading the `inhibit/<name>` tap, which reports when a guard is **above
  threshold**. For a `mute` action the real muting is strictly larger (the
  gate drags a 200 ms release behind every crossing); for a `flag` action it
  is zero. An A-B proved the label wrong — swapping two guards to flags moved
  the aggregate muted share 66.3% → 34.2% while those rows did not move at
  all. Renamed `active <name>`.

### Also in this release
#### Tooling
- `tools/session_report/`: `python -m tools.session_report <session_folder>
  [--protocol PATH | --protocols-ref REF] [--compare PATH ...] [--json OUT]`
  reports how the protocol behaved in a saved coherence-recorder session. It
  replays the session's real EEG through refrain, following the session's own
  log (clinician control changes at the moment they happened, applied advice,
  pause and resume, phase advances), and always reconciles that replay against
  what the live run recorded. Disagreement is printed first with a verdict,
  because every other number is only as trustworthy as the replay behind it.
  Not run in CI (sessions are clinical and do not ship); its parts are
  unit-tested.
- Reward is judged against an offline, zero-phase version of the protocol's
  own reward condition, for any protocol rather than only SMR. Judging it
  against the protocol's own envelope would be circular, since that envelope
  lags by design. Mutes are judged against a high-frequency muscle measure
  that nothing in the protocol produced, so a guard cannot grade itself.
- The report states its own choices: the muscle band and its measured noise
  floor, the match tolerance, the trusted window and the excluded warmup span.
- `tools/session_report/xdf_chunks.py` reads the recorder's raw XDF chunk by
  chunk in file order. pyxdf merges chunks and discards that order, which the
  replay needs, so this adds no dependency.
- `tools/measure_envelopes.py`'s replay stepping core is now shared with the
  session report; its behaviour is unchanged.

## 0.2.0 — declared-latency tooling (no protocol changes)

First tagged release of the corpus. It also carries every "Unreleased" section
below.

### Breaking
- **`refrain` floor raised to v0.24.0** (CI pin and `pyproject`'s dependency
  floor, up from the off-main commit `0319168` / >= 0.23.0). v0.24.0 changed
  the coherence segment length (`nperseg` 188 -> 125 at 250 Hz, 192 -> 128 at
  256 Hz) that `alpha_coherence` depends on, so a host on v0.23.0 would run
  it with different numbers; and the coming family redesigns use
  `band_envelope`, which v0.24.0 ships. The floor is literal rather than
  advisory.

### Changed
- `smr`, `alpha_up`, `beta_attention` and `high_beta_down` leave the editor
  round-trip test's known-gaps list: refrain v0.24.0's editor describes and
  renders control-bound band edges (refrain#109), so they are now gated by
  the round-trip test instead.

### Added
- `tools/measure_envelopes.py`: replays a protocol over EDF recordings and
  reports each envelope's delay and accuracy against a zero-phase reference,
  plus reward onsets per minute and time held. Not run in CI (the recordings
  are clinical and do not ship); its scoring is unit-tested.
- `tests/test_declared_latency.py`: every live envelope is a `band_envelope`
  at or above its bandwidth floor, excluded with a reason, or in a file
  waiting on a named roadmap item. `legacy/` is guarded as frozen.
- `docs/research/2026-10-21-feedback-design-by-protocol.md` (literature review
  of feedback design per protocol) and
  `docs/superpowers/specs/2026-10-21-protocol-feedback-roadmap-design.md`.

### Not changed, and why
- No protocol moves to `band_envelope` yet. A one-for-one swap made every
  envelope faster and more accurate, but on replayed recordings it cut time
  holding a reward from 8.5–39.9 % to 0.4–10.1 % across the protocols: the
  old smoothing stage was steadier than the real signal, and the reward rules
  depended on it. Each family migrates together with its reward redesign;
  see the roadmap.

## Unreleased — protocol autopilot

Refrain v0.22.0 adds protocol-declared autopilot: a session-time advisor that
watches training and applies or suggests small control changes, sourced and
bounded by the protocol itself rather than judged against a generic default.

### Breaking
- **`refrain` floor raised to v0.22.0** (CI pin and `pyproject`'s dependency
  floor, both up from v0.21.0 / >= 0.10.0). Distributed protocols may now use
  v0.22 syntax — `as "name"` on a reward check, a protocol-wide
  `autopilot { }` block, and a per-control `autopilot = ...` policy — which
  an older `refrain` cannot even parse, not just resolve.

### Added
- `alpha_theta.refrain` (v1.3.0) carries an autopilot policy: the crossover
  target tightens automatically in 0.05 steps within 0.5–1.0, while the theta
  reward rate and the baseline-mode theta threshold are suggestion-only. The
  policy targets 10–35% of training time in reward, watches the delta and
  EMG guards, and is tagged evidence `exploratory` — the target band was
  carried over from earlier guidance software and needs to be re-confirmed
  against recorded sessions before it is relied on.
- The companion guide (`alpha_theta.md`) gains an Autopilot section
  documenting the same policy in practitioner-facing terms.
- `docs/protocol-guide-template.md` gains an optional Autopilot section for
  any protocol that adds a policy of its own.

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
