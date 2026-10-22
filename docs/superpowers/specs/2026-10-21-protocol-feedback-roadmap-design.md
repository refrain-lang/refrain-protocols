# Protocol feedback roadmap — design

Status: draft for review, 2026-10-21.
Evidence base: `docs/research/2026-10-21-feedback-design-by-protocol.md` (literature review, six
research strands) and the replay measurements summarised below.

## Why

The declared-latency migration (session brief `2026-10-19-SESSION-BRIEF-migrate-protocols.md`,
punch-list item 11) assumed that replacing the four-stage envelope
(`bandpass -> hilbert -> magnitude -> smooth`) with `band_envelope(band:, latency:)` would leave
what counts as a reward unchanged. Measurement showed it does not.

On 13 resting recordings replayed through each protocol (resting EEG, not training sessions),
every envelope got faster and more accurate, and time holding a reward collapsed in every
protocol:

| Protocol | Old chain | `band_envelope` |
|---|---|---|
| `smr_classic_baseline_staged_cz` | 27.5 % | 8.9 % |
| `placement_smr_bipolar` | 21.1 % | 10.1 % |
| `alpha_theta_narrowband` (both files) | 16.2 % | 3.6 % |
| `smr` | 14.7 % | 3.4 % |
| `beta_focus_staged_fz` | 12.4 % | 1.0 % |
| `beta_attention` | 12.3 % | 3.3 % |
| `high_beta_down` | 10.3 % | 0.4 % |
| `alpha_up` | 8.5 % | 1.7 % |
| `alpha_theta` | 39.9 % | 0.7 % |

The old `smooth` stage made envelopes steadier than the true envelope (1.3 threshold crossings/s
on 12–15 Hz, against about 2.0 for the true envelope and 2.3–2.6 for any accurate filter). The
reward rules (`dwell` of 250 ms, or 1 s for alpha-theta, unbroken, over two or three AND-ed
conditions) only worked on that blurred signal.

The literature review's conclusion, which this roadmap adopts:

- Burst rhythms (SMR, beta, alpha) need fast feedback; the one study that varied delay found
  lasting change at 244 ms total and none at 744 ms (Belinskaya et al. 2020). Keep the fast filter.
- Move "sustained" out of the signal and into a forgiving reward rule; use fewer AND-ed
  conditions; treat muscle as a mute, not a reward condition; hold thresholds per block.
- Positive studies targeted 25–40 % reward time (Arns 2014); the only direct comparison favoured
  an easy ~80 % (Nam & Choi 2020). Our post-swap figures (0.4–10 %) are far below either.
- Slow protocols (alpha-theta, coherence, asymmetry, HRV) work on seconds-to-minutes timescales;
  filter speed barely matters there and smoothing is appropriate.

## Goals

1. Land what the declared-latency branch got right, without changing any protocol's rewards.
2. Give refrain the primitives the redesigns need, once, before redesigning.
3. Redesign each protocol family to the evidence, one family per PR, each gated on a measured
   reward rate.
4. Validate the SMR redesign on live sessions before treating it as the template for the rest.

## Non-goals

- Proving clinical efficacy. The review is clear that blinded trials of SMR and theta/beta show
  no advantage over sham; this roadmap is about delivering feedback the way the evidence and
  learning theory say it should be delivered.
- The synthetic training bench (`open-eeg-synth` + simulated trainee). Parked; may return as a
  sanity check after Stage 3's SMR family.
- Changing `legacy/` (frozen), or the alpha-theta audio assets.

## Anti-goals

- Restoring smoothing to make the old reward rates come back. That gives back the delay the
  migration removed and is what the evidence argues against for burst rhythms.
- A protocol redesign that lands before the refrain primitive it needs, then gets redone.
- A reward-rate gate measured on resting recordings presented as evidence that a design trains
  better. Replay checks catch broken designs (never or always rewarding); they do not rank good
  ones.
- Changing what counts as a reward as a side effect. Every reward change is a recorded design
  decision in the protocol's header and in the PR.

## Constraints (unchanged from the brief and the user's rulings)

- `legacy/` is frozen. Retiring a file means moving it into `legacy/`, never deleting it.
- Never widen bands. Order-2 band-pass filters are refuted.
- Work against `main`. Corpus version 0.1.0 → 0.2.0 is cut by the other session after Stage 1
  merges.
- Every live protocol stays inside the editor's round-trip subset unless listed in
  `KNOWN_GAPS` with a reason.
- refrain CI runs 12–28 minutes a round; batch refrain changes into one PR.
- pytest exit code captured immediately, never after a pipe; no `-q` on refrain's suite.

## Stage 1 — ship the safe parts of `feat/declared-latency-envelope` (decided: ship)

Contents:

- Already committed (`7802a72`): `refrain >= 0.24.0`, CI checkout of `v0.24.0`, the four
  flagships moved out of `KNOWN_GAPS`, the changelog entry.
- `tools/measure_envelopes.py` (replays a protocol over EDF recordings, reports envelope
  lag/accuracy against a zero-phase reference and reward onsets/held %).
- `tests/test_declared_latency.py`, changed from "every envelope is migrated" to "every envelope is
  `band_envelope` with latency at or above its bandwidth floor, **or** listed with the reason it
  waits". Each four-stage envelope is listed as waiting on its family's Stage 3 PR. `legacy/`
  stays guarded as frozen.
- The literature review, committed as `docs/research/2026-10-21-feedback-design-by-protocol.md`
  (from `reports/`), and this roadmap.
- **No protocol changes.** The working-tree edit to `smr.refrain` is reverted; its measurements
  go into the PR description.
- PR description doubles as the findings note for the session that wrote the brief: the
  reward-collapse table, the contradiction with the brief's premise, the per-band latency picks
  (kept for Stage 3), and the open questions (who bumps 0.2.0; REC-15 "delete" versus the
  move-to-legacy rule).

Gate: refrain-protocols suite green, catalog unchanged, refrain's suite and drift gate green, and
`gen_editor_fixtures.py` unchanged against the branch.

## Stage 2 — refrain primitives (decided: before any protocol redesign)

One refrain PR, one release, then the protocols repo pins it.

1. **A hold that forgives brief dips.** `dwell`, `dwell_rearm` and `hold_for` all reset on any
   dip (verified in 0.24.0). Needed: either a dip-tolerant dwell (the condition may drop for up
   to `tolerance` without resetting the clock) or a two-line threshold (on above an upper line,
   off only below a lower one), or both. Syntax is refrain's call. Must have: Python and Rust
   core parity, IR-JSON schema bump, editor describe/render support, fuzzer oracle coverage.
2. **Thresholds held per block.** Rolling 2-minute percentiles are a form of auto-thresholding
   (Sherlin 2011 critique; the blinded ADHD trial held thresholds for five sessions). Today
   (0.24.0) an absolute threshold can be seeded once, at the end of warmup, and only under the
   baseline threshold style (`smr_classic_baseline_staged_cz` does this). *Builder's call, made
   here:* the redesigned SMR, beta and alpha protocols default to the baseline style (one
   baseline from warmup, held); Stage 2 adds **optional re-seeding at a block boundary from the
   previous block's data**, so a practitioner can let thresholds step between blocks but never
   drift within one. Rolling percentiles remain available as a non-default style.
3. **Muscle mute on a per-person absolute level.** The shipped guard's rolling-percentile
   threshold "poisons itself": sustained tension becomes the new normal within 2 minutes and
   stops tripping it, and it mutes 20–26 % of the time even with no muscle present (measured in
   the bench design review). *Builder's call:* the guard's level is seeded from warmup (for
   example a multiple of the warmup median) and held, consistent with Paluch 2017's advice to
   calibrate per person. Uses the same seeding mechanism as item 2.
4. **Verify, and fix if needed, that an inhibit's `mute` silences the continuous output**, not
   only the event, and that the phase mute is visible to hosts and taps (the design review found
   the `muted` tap reflects only inhibits, not phase mutes).

*Builder's call on scope:* Stage 2 covers only what families 1–3 need. The slow families (4, 6)
are expected to manage with existing primitives: alpha-theta keeps `band_envelope` followed by an
explicit `smooth` (the latency test is changed to accept that shape for listed slow protocols,
with the smoothing time recorded as part of the declared delay), and `faa_f3f4` is rewritten from
centre+ratio bands to explicit edges. If either family finds a real language gap, that is a second,
later refrain release; those families are not urgent.

### Stage 2b — recorder: continuous-tone gain smoothing

Owned by the coherence-recorder session (agreed 2026-10-21).

The recorder's audio renderer smooths gain asymmetrically (`_GAIN_ATTACK_TAU_S = 0.05`,
`_GAIN_RELEASE_TAU_S = 0.30`, `recorder/backend/nf/audio_renderer.py:70-71`). For an always-on
tone tracking SMR the slow release adds roughly 250 ms to every "SMR has dropped" change.

**Constraint: do not retune the module constants.** The 0.30 s release exists to stop a
reward-gated gain (`audio_gain = reward.event.holds ? continuous : 0`) from pumping at the chime
rate (the audible "warble"), and every existing dwell protocol still needs it. Smoothing becomes a
property of the gain source: fast and symmetric for a continuous channel, asymmetric as now for a
reward-gated one.

**Not verified:** the renderer's mute is a hard zero and un-mute fades in over the attack
constant, so the "declared 200 ms mute release delivered as ~300 ms" recorded on REC-15 is not
renderer behaviour. If it is real it comes from the engine-level inhibit path, not yet located.
Do not carry the 300 ms figure as fact until the recorder session reports the measured value.

Sequencing: after the recorder's pin bump; blocks no Stage 3 PR; lands before Stage 4.

### Stage 2c — measure the delay model before Stage 3 (recorder session)

The recorder session re-runs `measure_nf_latency.py` for its pin bump and will report real values
for the poll wait, the cFIR threshold-crossing time and audio output. That validates or breaks the
delay model below while Stage 3 is still cheap to re-sequence.

The amplifier's Bluetooth hop (modelled at 20–50 ms) cannot be measured by that harness and is
the one hop that could invalidate the model: at 120 ms the strong-burst total passes 400 ms and
the Stage 4 gate gets tight. It needs hardware and a new method (for example a physical event at
the electrode captured on the same clock as the speaker output). Scheduled with the user's
recordings in Stage 4, earlier if the hardware is to hand.

Gate: refrain suite and drift gate green; fuzzer scenarios covering the new hold (dip shorter
than tolerance keeps the hold, longer resets it, chunk-boundary cases); editor round-trip of an
example protocol using each new primitive.

## Stage 3 — protocol families, one PR each, in this order

Each PR: redesign to the review's recommendations, `band_envelope` at the per-band latencies
already picked (below), header records the design decisions and their sources, editor
round-trip passes, and the replay gate below. Each reward change is listed in the PR.

**Reward time, as the gates measure it** (*builder's call*): the share of *unmuted* time during
which the reward hold is on (the forgiving hold for families 1–3). Tone-in-range time (the
continuous tone above its midpoint) and muted time are reported alongside, not gated.

**SMR family structure (decided by the user, 2026-10-21):** `smr_classic_baseline_staged_cz`
folds into `smr.refrain` as a staging mode (four 5-minute blocks with 2-minute rests on one
baseline; its header's rationale moves into `smr.refrain`'s header), and the staged file is then
**moved into `legacy/`**, not deleted. The nine SMR files already in `legacy/` stay, frozen.
`placement_smr_bipolar` and `placement_smr_set` stay live (different montage function and
placement kind) and are redesigned alongside. This resolves REC-15's "delete" in favour of the
move-to-`legacy/` rule; REC-15 is updated to say so.

| # | Family (files) | Redesign | Replay gate |
|---|---|---|---|
| 1 | SMR: `smr`, `placement_smr_bipolar`, `placement_smr_set`, `smr_classic_baseline_staged_cz` (this is REC-15) | Continuous tone always on, tracking SMR; ding for ~250 ms sustained SMR with the dip-tolerant hold; theta veto optional and loose; high-beta leaves the reward and becomes a mute; thresholds held per block; muscle mute silences the tone | Reward time 25–40 % median on the replay corpus at default controls; muted time reported; no recording at 0 % or 100 % |
| 2 | Beta: `beta_attention`, `beta_focus_staged_fz` | As SMR, plus a muscle mute above the trained band that silences the tone, calibrated per person; blink handling at Fz | As SMR, plus a deliberate-clench recording shows the tone muted during clenches |
| 3 | `alpha_up` | Fast continuous tone; reward burst onsets rather than long holds; eyes-open default; optional individual-alpha band; muscle mute | As SMR |
| 4 | Alpha-theta: `alpha_theta`, `alpha_theta_narrowband`, `alpha_theta_narrowband_melodic` | Crossover judged over seconds to minutes, not a 1 s unbroken hold; slow smoothing kept (explicit, declared); delta and muscle mutes kept; audio contract unchanged | Behaves sensibly on the eyes-closed recordings (reward present, not saturated); audio channels unchanged |
| 5 | `high_beta_down` | Decision first: keep with an honest description and a pausing muscle detector (45–70 Hz), or move to `legacy/` | Depends on the decision |
| 6 | `alpha_coherence`, `faa_f3f4`, `critical_fluctuation`, `hrv_resonance` | Declared latencies and scoring windows that match their timescales (coherence 1–3 s; asymmetry 1–5 s; HRV waveform fast, LF power ~90 s); `critical_fluctuation` labelled experimental | Unchanged reward behaviour unless a change is recorded |

Per-band `band_envelope` latencies (shortest on a 20 ms grid at or above the bandwidth floor and
matching the old chain's accuracy on the replay corpus): 12–15 Hz 360 ms; 4–7 Hz 340; 20–30 Hz
100; 15–18 Hz 340; 13–19 Hz 180; 22–30 Hz 140; 8–12 Hz 260; 4–8 Hz 260; 2–4, 3–5, 6–8, 9–11 Hz
500; 15–56 Hz 60. Stage 3 may revisit these downward for burst rhythms: Belinskaya's effective
group used a less accurate 100 ms setting.

## Stage 4 — live validation (recordings by the user)

The user records (decided 2026-10-21):

1. **A clench recording** before family 2's gate: a few minutes on the BrainBit Flex with
   deliberate jaw clenches, clench times marked. It also joins the replay corpus for every later
   gate.
2. **A few live SMR sessions** with the Stage 3 SMR design once Stages 2 and 2b have shipped to the
   recorder.

What the live sessions check, and what sends the SMR design back:

- Reward time in practice inside 25–40 % at default controls (back if outside 15–60 %).
- Clenches mute the tone (back if a deliberate clench is not muted).
- The dip-tolerant hold feels continuous rather than stuttering (the user's judgement).
- End-to-end delay from electrode to sound, measured on the recorder for the first time (see
  below). Back if the always-on tone's rise is slower than about 500 ms on wired audio.

Stage 4 does **not** block families 2–3 from being built or merged; its results feed back as
tuning.

## Expected delay with the new design (model, not yet measured)

Hops from the recorder's latency report (`coherence-recorder/recorder/docs/nf-latency-measurement.md`,
re-measured 2026-10-15) plus a simulated step through cFIR at 360 ms on 12–15 Hz. Time from an SMR
burst starting to the always-on tone reaching its midpoint (the sigmoid midpoint sits at the SMR
threshold):

| Hop | Strong burst (5×) | Weak burst (1.5×) |
|---|---|---|
| Amplifier Bluetooth (bound, unmeasured) | 20–50 | 20–50 |
| Recorder poll (mean) | 5 | 5 |
| cFIR 360 ms envelope reaches the threshold | 188 | 332 |
| Recorder gain ramp (50 ms attack) | ~25 | ~25 |
| Audio out, laptop speakers | 65 | 65 |
| **Total, laptop speakers** | **~305–335 ms** | **~450–480 ms** |
| Total, dedicated audio interface | ~245–275 ms | ~390–420 ms |

Today's design reaches the trainee at ~885 ms on speakers (the tone waits for the full hold). The
ding follows the tone by the 250 ms hold, by design. Falling changes are ~250 ms slower until
Stage 2b lands. Clean steps flatter the filter; real bursts ramp, so live figures will be slower.

Faster SMR figures elsewhere usually come from a leakier filter (a 2-pole band-pass reacts in
20–60 ms but passes 35 % of 10 Hz alpha, against 2 % for cFIR at 360 ms), from alpha rather than
SMR, or from quoting the filter without transport and audio.

## Tracking

One Linear ticket per stage in the Coherence Recorder project, linked to REC-15 (SMR redesign),
REC-10 (declared-latency adoption) and REC-18 (reward-rate measurement). Stage 3 family 1 is
REC-15 itself, updated to this design. Each family gets its own detailed plan
(`docs/superpowers/plans/`) when its turn comes.

## Open questions

1. Dip tolerance and two-line-threshold values: no study gives them. Choose by replay against the
   25–40 % target, then check on live sessions.
2. Whether `high_beta_down` stays (Stage 3, family 5).
3. Whole-system delay on the recorder is unmeasured; Stage 2c measures most hops, Stage 4 the
   amplifier's Bluetooth hop.

Resolved 2026-10-21 by the recorder session: corpus **0.2.0 is cut from Stage 1** (same protocols,
refrain floor >= 0.24.0, new tooling), so the recorder bumps refrain, refrain-core and
refrain-protocols in one commit and pins a tag rather than a commit SHA. **0.3.0 is the SMR family**
(Stage 3 #1), the first release that changes what a trainee hears.

## Calls made in this document (not decided by the user)

- Redesigned SMR, beta and alpha protocols default to baseline thresholds held per session;
  re-seeding at block boundaries is optional (Stage 2, item 2).
- The muscle mute moves to a per-person level seeded at warmup (Stage 2, item 3).
- Stage 2 covers only families 1–3; slow families use existing primitives, with a later refrain
  release only if a real gap appears.
- The recorder's gain smoothing change (Stage 2b) is in scope and must precede Stage 4.
- "Reward time" for gates = share of unmuted time the reward hold is on.
- Stage 4 does not block families 2–3.

## Left to the builder

PR boundaries inside a stage, exact test names, the replay corpus selection (same 13 recordings
by default, plus the user's clench recording once it exists), and wording of protocol headers.
