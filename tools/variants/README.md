# Stage 2 trigger arms

The protocol variants behind the Stage 2 measurements in
`coherence-recorder/docs/superpowers/specs/2026-11-21-smr-spindle-protocol-design.md`
(§13) and the change ledger dated 2026-11-23.

These are **tool inputs, not protocols.** Each carries a placeholder
(`__BAR__` or `__WAXPCT__`) that its driver substitutes per recording, so none
of them resolves as written. That is why they live here rather than under
`protocols/` or `drafts/` — the catalog builder and every corpus test scan
those two directories only, and a file with a placeholder in it would fail all
of them.

They were kept in a session scratchpad until 2026-11-25, which meant every
published Stage 2 figure was reproducible on exactly one machine, in a
directory that routine cleanup deletes. That is the only reason they are
committed.

## What each arm is

| file | trigger condition | bar comes from |
|---|---|---|
| `wax_tmpl.refrain` | level **and** slope > 0 | `__BAR__` literal |
| `wax_levelonly.refrain` | level only | `__BAR__` literal |
| `wax_slopeonly.refrain` | slope > 0 only | — (no bar) |
| `wax_pctbar.refrain` | level **and** slope > 0 | `percentile(__WAXPCT__, window: 2 min)` |
| `wax_pctbar_levelonly.refrain` | level only | `percentile(__WAXPCT__, window: 2 min)` |
| `wax_artflag.refrain` | level **and** slope > 0 | `__BAR__` literal |
| `wax_artflag_exempt.refrain` | as above, plus `exempt = ["audio_chime"]` | `__BAR__` literal |

Every arm fires its chime through `dwell(..., duration: 4 ms)` — a nominal
duration standing in for "commit on contact", since the engine has no
zero-duration commit. The 500 ms published criterion stays on `reward.event`
in all of them, so the criterion keeps its accounting while the chime runs
early.

## What they measured

Isolating the two halves of the trigger (§13.1, n=12, one degenerate
recording excluded):

| arm | caught | fizzled | fires/min |
|---|---|---|---|
| `wax_tmpl` — level and climb | 39.2% | 36.7% | 7.8 |
| **`wax_levelonly` — level alone** | **41.0%** | **34.4%** | **8.0** |
| `wax_slopeonly` — climb alone | 62.5%* | 74.1%* | 35.1* |

\* unfiltered, n=13.

Dropping the climb test improves catch and false-fire together at identical
timing, so the gradient — §7.3's "novel element" — is a net cost and comes
out. Climb alone fires 35 times a minute with three quarters of its
commitments landing on nothing, because the envelope is rising about half the
time.

Replacing the per-recording oracle bar with a live-computable rolling
percentile (§13.7):

| arm | recall | precision | fires/min |
|---|---|---|---|
| oracle (per-recording, non-causal) | 68.2% | 65.2% | 14.5 |
| **`wax_pctbar` at pct 93** | **68.0%** | **62.9%** | **15.1** |

A 0.2-point recall gap against a bar no live session can compute. This is what
makes Stage 2 shippable without per-subject calibration machinery: a
`percentile` threshold is the same primitive the protocol already uses for
`smr_t`.

`wax_artflag` / `wax_artflag_exempt` are the arms behind the ledger's
guard-action work, not the trigger work: both give 17.1 reward onsets/min,
30.3% held, 18.2% heard, 34.3% silent — identical to each other, which is how
`exempt` was shown to be inert on a protocol whose holds are all in the reward
stage.

## Running them

```sh
# per-recording oracle bar; ONSET_K sets the bar as a fraction of each
# recording's median spindle peak (default 0.8)
python tools/score_onset_trigger.py tools/variants/wax_levelonly.refrain rust 4

# the percentile sweep, oracle arm as an in-run control
python tools/pctbar_sweep.py tools/variants/wax_tmpl.refrain tools/variants/wax_pctbar.refrain
```

`ONSET_CORPUS` points at the recording corpus. `ONSET_REFRACTORY_MS` sets the
refractory the scorer applies **in Python** — every figure above was taken at
its 1000 ms default. Nothing in the protocol declares that refractory and no
host enforces one today, so it is a property of the measurement, not of the
protocol.

## Timing language

Call it an **early-commitment trigger**, not a waxing or onset trigger. It
fires a median 388 ms *after* a spindle's physiological start — about 68 ms
over the signal path's 320 ms floor, and some 430 ms earlier than the 500 ms
criterion can manage. It does not anticipate onsets. See §13.8.

---

# Scoring against a reference that is not the protocol's own rule (2026-11-28)

Everything above this line was scored against ground truth built from the band
the protocol trains and the rule shape it uses, computed non-causally. That
validates latency and filter fidelity. It cannot validate the burst
definition. The figures below come from `tools/burst_reference.py` and
`tools/score_burst_trigger.py`, on refrain v0.27.0 (Rust core), over 12
resting recordings from OpenNeuro ds003478 (CC0; Cz against linked mastoids,
eyes open and closed, about six scored minutes each). **The file-format corpus
the sections above use was not available for this work, so no figure below is
on the same recordings as any figure above.** Reward time is the one quantity
measured on both, and it agrees: `smr_consolidated` 59.3% here against 59.8%
there, `smr_spindle` 28.7% against 30.3%, `smr` 14.4% against 13.1%.

## There is no expert-scored reference, and the published detectors find little

No public recording of waking EEG carries human-scored bursts (DREAMS, MASS
and MODA are sleep). So each reference was run on the recording and on a
phase-randomised surrogate of it — same power spectrum, no burst structure:

| reference | events/min | on noise | recordings where real > noise | median length |
|---|---|---|---|---|
| **circular** — the old ground truth | 13.98 | 14.48 | 4/12 | 747 ms |
| YASA `spindles_detect` (sleep detector, unmodified) | 0.00 | 0.00 | 5/12 | 608 ms |
| bycycle, code defaults, ≥ 3 cycles | 21.54 | 21.65 | 7/12 | 330 ms |
| bycycle, ≥ 3 cycles, every cycle inside 12–16 Hz | 0.59 | 0.24 | 7/12 | 217 ms |
| bycycle, ≥ 7 cycles | 3.47 | 1.10 | 12/12 | 811 ms |
| ridge (eBOSC-style), ≥ 3 cycles | 2.32 | 1.96 | 9/12 | 271 ms |
| ridge, ≥ 5 cycles | 0.42 | 0.12 | 11/12 | 412 ms |
| envelope > 2.5 × median (Belinskaia 2020) | 13.60 | 5.95 | 12/12 | 148 ms |

Read the first row first. **The old ground truth finds as many "spindles" in
noise as in EEG**, because an 80th-percentile rule manufactures the same event
count on anything. The 13–14 spindles a minute every earlier section reports
is a property of that rule.

Three things follow, and none of them is a decision:

- **By a sleep-spindle definition there are no spindles here.** YASA's median
  is zero. Its thresholds were set on N2 sleep and it has never been validated
  awake, so this says the word does not transfer, not that nothing happens.
- **bycycle's "12–16 Hz bursts" are mostly alpha.** 62% of its burst cycles
  are under 12 Hz. Held to in-band cycles it finds 0.6 a minute.
- **Short events are as common in noise as in EEG; long ones are not.** At
  three cycles bycycle and the ridge detector are within 20% of their own
  noise rates (the in-band bycycle variant is 2.5x its own, on 0.6 events a
  minute). At five to
  seven cycles (roughly 400–800 ms) real exceeds noise 3.2–3.5×, and those
  events are rare: 0.4–3.5 a minute. This is the independent evidence on the
  duration criterion. It cuts both ways — a 500 ms rule keeps the events that
  are distinguishable from noise and rejects most of what there is — and the
  decision stays with the owner.

What *is* robustly non-noise is amplitude: the envelope spends 3.0% of the
time above 2.5× its median against 1.1–1.4% on noise, inside eyes-open and
eyes-closed blocks separately (12/12 each). A percentile bar cannot see that,
by construction. A multiple of the median can.

## Triggers, on the engine

One replay of each recording and one of its surrogate per row. `ridge3` (209
events) at ±300 ms unless a row says otherwise.

| trigger | chimes/min | on noise | real/noise | recall | precision | lift | in-burst | lag |
|---|---|---|---|---|---|---|---|---|
| **`smr_burst`** | 6.8 | 4.0 | **1.75** (12/12) | 56.5% | 24.9% | 5.94 | **77.1%** | 220 ms |
| — without the shape test | 11.5 | 6.2 | 1.95 (12/12) | 63.2% | 15.9% | 3.79 | 77.3% | 204 ms |
| — without the re-arm | 8.0 | 4.9 | 1.72 (12/12) | 56.9% | 24.3% | 5.78 | 77.3% | 220 ms |
| — re-arm 1000 ms | 6.3 | 3.9 | 1.58 (12/12) | 50.2% | 24.3% | 5.79 | 76.2% | 220 ms |
| — 1 s minimum gap in Python | 6.4 | 3.9 | 1.65 (12/12) | 52.2% | 24.0% | 5.72 | 77.1% | 220 ms |
| — on the 320 ms tapered envelope | 6.1 | 2.9 | 1.99 (12/12) | 52.2% | 26.1% | 6.23 | 33.9% | 364 ms |
| `wax_pctbar_levelonly`, pct 93, unthrottled | 21.9 | 23.5 | 0.90 (2/12) | 71.8% | 11.6% | 2.76 | 44.0% | 324 ms |
| — pct 93, 1 s gap in Python (the published arm) | 15.2 | 18.1 | 0.82 (0/12) | 64.6% | 12.4% | 2.95 | 40.0% | 328 ms |
| — pct 97, unthrottled (nearest in rate) | 9.5 | 11.6 | 0.86 (2/12) | 54.5% | 17.8% | 4.25 | 34.2% | 364 ms |
| `smr_spindle`, its 500 ms chime | 10.5 | 9.8 | 1.09 (7/12) | 25.4% | 6.6% | 1.57 | 58.5% | 156 ms |
| `smr`, its chime | 25.8 | 23.1 | 1.07 (9/12) | 39.2% | 5.0% | 1.19 | 69.5% | 30 ms |
| `smr_consolidated`, reward onsets (no chime) | 89.5 | 98.6 | 0.88 (0/12) | 79.4% | 3.6% | 0.85 | 91.0% | −8 ms |

`in-burst` is, of the bursts caught, the share whose first chime came before
the burst ended; `lag` is that chime minus the burst's start. Recall climbs
with the firing rate regardless of the rule, so compare rows at similar rates:
at 6.8 against 9.5 chimes a minute the burst trigger and the 97th-percentile
bar catch the same share (56.5% / 54.5%), and differ in precision (24.9% /
17.8%), in whether noise sets them off (1.75 / 0.86) and in when they land
(77.1% / 34.2% in-burst).

The match window, on `smr_burst` against `ridge3`:

| window | recall | precision | chance | lift |
|---|---|---|---|---|
| ± 500 ms | 59.3% | 26.7% | 6.0% | 4.48 |
| ± 300 ms | 56.5% | 24.9% | 4.2% | 5.94 |
| ± 200 ms | 55.0% | 23.5% | 3.3% | 7.15 |
| ± 100 ms | 51.7% | 21.9% | 2.4% | 9.26 |

Against the two same-family references, for the record and not as evidence:
`amp2.5` at ±300 ms 43.4% recall / 82.2% precision; `circular` at ±500 ms
38.7% / 80.2% against 37.8% chance.

## The refractory

`dwell_rearm` on a bare level condition **is** a declarable refractory. The
earlier finding that it "never elapses" was about a condition with the slope
term in it, true 49% of the time; without the slope the condition is false
most of the session and a 300 ms re-arm elapses between bursts. It costs 0.4
points of recall for 15% fewer chimes. A 1 s re-arm costs 6.3 points, and the
1 s minimum gap the scorer used to apply in Python costs 4.3. On the
percentile arm the unthrottled trigger fires 44% more than the 1 s-gap one
(21.9 against 15.2 a minute), which reproduces the earlier 46%.

## What was not measured

- **`threshold_style = "baseline"` on a sustained state.** This corpus
  alternates eyes open and closed every 1–3 minutes, inside the 2 min window,
  so there is no sustained state in it. On that alternation a rolling 40th
  percentile registers the eyes-closed rise about as well as a threshold fixed
  from the first two minutes: 11.1 against 12.3 points of time above
  threshold, computed on the engine's envelope and not through the reward.
- **Trainees.** These are untrained adults at rest.
- **A maximum duration**, and within-burst frequency stability as a causal
  criterion.

## Reproducing

```sh
export BURST_CORPUS=/path/to/ds003478        # openneuro.org/datasets/ds003478
python tools/burst_reference.py              # the reference table
python tools/score_burst_trigger.py protocols/eeg/smr_burst.refrain protocols/eeg/smr_consolidated.refrain
BURST_SUBST=WAXPCT=93 BURST_MIN_GAP_MS=1000 python tools/score_burst_trigger.py tools/variants/wax_pctbar_levelonly.refrain
```

The ablation rows are `smr_burst.refrain` with one substitution each: the
`above("smr_dominance", 1.0)` line deleted; `dwell_rearm(... rearm: 300 ms)`
replaced by `dwell(...)`; `rearm: 1000 ms`; and `, kind: "weighted"` deleted
with `smr_latency` defaulting to 320 ms. The surrogate is one draw per
recording, seeded by the recording's position. Needs `mne`, `statsmodels`,
and `yasa` / `bycycle` for the rows that bear their names.
