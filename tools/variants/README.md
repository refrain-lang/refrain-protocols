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
