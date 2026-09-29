# Narrow-band alpha/theta crossover

Companion guide for [`alpha_theta_narrowband.refrain`](alpha_theta_narrowband.refrain).

## Status

| Field | Value |
| --- | --- |
| Protocol version | 1.0.0 |
| Library status | **Draft — untested as a complete system** |
| Evidence tag | Exploratory |
| Default site | Pz, referenced to the amplifier reference |
| Default session | 36 minutes |

This protocol is an implementable interpretation of Brain-Trainer's published
ALP1C feedback description. It is not their proprietary design file and has
not been shown to reproduce its signal processing, sounds, or reported outcomes.

## Training rule

The protocol compares a 6–8 Hz theta envelope with a 9–11 Hz alpha envelope.
Strict crossover begins when theta exceeds alpha. After that condition remains
true for one second, `audio_chime` marks entry and `audio_gain` remains active
for the duration of the crossover. Its value increases with the theta/alpha
ratio, allowing a host to make sustained feedback slightly fuller or brighter
as theta dominance increases.

There is no separate theta threshold and no alpha-down inhibit. A crossover
cannot earn feedback merely by approaching a target below 1.0, and alpha is not
treated as unwanted activity.

## Feedback contract

| Output | Meaning |
| --- | --- |
| `audio_chime` | Rising-edge event after one second of strict crossover |
| `audio_gain` | Zero outside crossover; graded theta/alpha depth while crossover holds |

Coherence Recorder may render `audio_chime` as the existing gong and
`audio_gain` as a quiet sustained harmonic layer over separately playing music.
The host should use a slow attack and release so small oscillations around the
boundary do not sound abrupt. Background music remains independent.

## Guards

The 3–5 Hz slow guard and 15–56 Hz fast guard withhold positive feedback during
unusually large activity relative to their rolling two-minute histories. They
are local feedback and signal-quality adaptations. Brain-Trainer describes
separate warning sounds for these bands; this protocol's host-neutral contract
uses inhibits, so Recorder mutes positive feedback and identifies the active
guard instead.

The wide fast band is especially sensitive to jaw and neck muscle activity.
An active fast guard does not establish anxiety, rumination, or a cerebral
source.

## Session flow

| Stage | Duration | Feedback |
| --- | ---: | --- |
| Settle | 2 min | Quiet |
| Deep 1 | 15 min | Active |
| Rest 1 | 2 min | Quiet |
| Deep 2 | 15 min | Active |
| Cooldown | 2 min | Quiet |

## Review measures

Preserve strict crossover count, total time, median duration, longest duration,
theta/alpha depth, and the reason each episode ended: theta fell below alpha,
slow guard, fast guard, stage mute, or recording interruption. These are session
measurements and do not by themselves establish a particular subjective state.

## Provenance and references

Brain-Trainer's manual describes 6–8 Hz theta versus 9–11 Hz alpha, a melody
whose pitch and volume increase with theta dominance, alpha-linked nature
sound, and separate 3–5 Hz and 15–56 Hz warning feedback. This implementation
adopts the narrow bands, strict crossover, graded hold feedback, and guard
bands. It does not reproduce their music, nature layer, threshold algorithm,
or warning sounds.

1. Brain-Trainer. *Brain-Trainer Designs Manual*, ALP1C Alpha Theta, pp. 12–13,
   June 6, 2020. <https://brain-trainer.com/downloads/Designs_List_Brain-Trainer.pdf>
2. Brain-Trainer. “BT2 ALP: Alpha-Theta.”
   <https://brain-trainer.com/support/resources/bt2-alp-alpha-theta/>
3. Peniston, E. G., & Kulkosky, P. J. (1989). Alpha-theta brainwave training
   and beta-endorphin levels in alcoholics. *Alcoholism: Clinical and
   Experimental Research, 13*(2), 271–279.
   <https://doi.org/10.1111/j.1530-0277.1989.tb00325.x>
