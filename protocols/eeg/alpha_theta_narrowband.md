# Narrow-band alpha/theta crossover

Companion guide for [`alpha_theta_narrowband.refrain`](alpha_theta_narrowband.refrain).

## Status

| Field | Value |
| --- | --- |
| Protocol version | 1.4.0 |
| Library status | **Draft — untested as a complete system** |
| Evidence tag | Exploratory |
| Default site | Pz, referenced to the amplifier reference |
| Default session | 36 minutes |

This protocol is an implementable interpretation of Brain-Trainer's published
ALP1C feedback description. It is not their proprietary design file and has
not been shown to reproduce its signal processing, sounds, or reported outcomes.

## Training rule

The protocol compares a 6–8 Hz theta envelope with a 9–11 Hz alpha envelope.
The live **Reward ratio target** defaults to 0.85. A clinician can lower it
during a run to shape toward crossover when crossings are too brief to sustain
useful feedback, or raise it toward 1.00 as performance stabilizes. The literal
crossover statistic remains theta/alpha at or above 1.00 regardless of this
shaping setting.

The shaping reward condition is separate from the literal crossover. During
the two-minute Settle stage, the final 60 seconds of theta-envelope values
seed a fixed median reference. At the start of Deep, the approach texture has
a low 10% floor. Its level adds up to 65% as theta rises from that reference
to 25% above it, plus up to 25% as the theta/alpha ratio rises from the live
reward target to literal crossover. The theta contribution can therefore
increase before the ratio reaches the reward target; a fall in alpha alone
does not fill it. The theta-rise span defaults to 25% and can be adjusted
during training. The seeded reference can also be adjusted, but changing it
changes the meaning of subsequent progress. Neither control changes what
counts as literal crossover. The ratio contribution disappears below its
target; at target 1.00 there is no graded ratio interval. In the new rendering,
the protocol holds a literal crossover for one second before moving to its
crossover layer, and for three seconds before moving to its sustained layer.
Both dwell durations can be adjusted during a session within their declared
bounds. A guard, quiet phase, or pause resets the hold.

The theta reference is a proportional feedback anchor, not a pass/fail theta
gate. There is no alpha-down inhibit. A reward target below 1.00 shapes
feedback toward crossover; it must not be reported as literal crossover, and
alpha is not treated as unwanted activity. Let Settle run at least 60 seconds:
advancing sooner leaves the reference unseeded and feedback fails quiet rather
than guessing a baseline. The Settle median is not screened for artifacts, so
review the signal and guards if the reference appears implausible.

The four band edges are available under Advanced setup. Their defaults preserve
the published 6–8 Hz theta and 9–11 Hz alpha ranges. They are fixed when the
session starts; changing filters during a run would make its earlier and later
measurements incomparable.

## Feedback contract

| Output | Meaning |
| --- | --- |
| `feedback_approach` | Early texture level: 10% floor, up to 65% from theta rising above its Settle reference, up to 25% from ratio progress |
| `feedback_theta_progress` | Theta-rise contributor, 0–1 relative to the frozen Settle reference and live rise span |
| `feedback_ratio_progress` | Ratio contributor, 0–1 from the live reward target to literal theta-over-alpha |
| `feedback_crossover` | True after one continuous clean second with theta/alpha at or above 1.00 |
| `feedback_sustained` | True after three continuous clean seconds with theta/alpha at or above 1.00 |
| `audio_chime`, `audio_gain` | Legacy event and gain channels retained for older renderers |

The approach, crossover, and sustained outputs are semantic values. A host can map them to
three synchronized audio textures, with sustained taking priority over
crossover and crossover over approach. In this mode Recorder plays no ordinary
or sustained gong. The separate YouTube/background track stays at a manually
chosen steady volume. The local texture changes gently with the EEG, under its
own volume ceiling, attack, release, contrast, and trim controls. Legacy
rendering still uses `audio_chime` and `audio_gain` if chosen explicitly.

The approved local files are `01-approach-dark-soft.wav`,
`02-crossover-warm-open.wav`, and `03-sustained-deep-full.wav`: aligned
90-second stereo, 44.1 kHz, 16-bit PCM variants. They are supplied from an
operator-selected folder rather than bundled in this open-source repository
until redistribution rights are recorded. Recorder stores their SHA-256 hashes
in the capture manifest. A recording may therefore identify its assets even
if the local folder changes later.

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
| Settle | 2 min | Quiet; final 60 s seeds theta reference |
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
or warning sounds. The three local continuous textures are user-approved
artwork for this application; they are not Brain-Trainer assets or a validated
clinical intervention. The exact source prompt, creation service, account
license, and redistribution permission still need to be recorded before
any public binary distribution.

1. Brain-Trainer. *Brain-Trainer Designs Manual*, ALP1C Alpha Theta, pp. 12–13,
   June 6, 2020. <https://brain-trainer.com/downloads/Designs_List_Brain-Trainer.pdf>
2. Brain-Trainer. “BT2 ALP: Alpha-Theta.”
   <https://brain-trainer.com/support/resources/bt2-alp-alpha-theta/>
3. Peniston, E. G., & Kulkosky, P. J. (1989). Alpha-theta brainwave training
   and beta-endorphin levels in alcoholics. *Alcoholism: Clinical and
   Experimental Research, 13*(2), 271–279.
   <https://doi.org/10.1111/j.1530-0277.1989.tb00325.x>
