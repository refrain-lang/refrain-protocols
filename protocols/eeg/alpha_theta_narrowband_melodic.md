# Narrow-band alpha/theta with melodic feedback

Companion guide for [`alpha_theta_narrowband_melodic.refrain`](alpha_theta_narrowband_melodic.refrain).

## Status and purpose

**Draft; exploratory; not validated as a complete training system.** This is a separate, selectable audio version of `alpha_theta_narrowband`. It retains that protocol's signal path, guards, session stages, controls, and distinction between shaping reward and literal crossover. It changes the feedback artwork and how Recorder obtains it; it does not replace the layered-texture version or the broader-band `alpha_theta` protocol.

The default site is Pz. The measured envelopes compare 6–8 Hz theta and 9–11 Hz alpha. A live reward-ratio target of 0.85 shapes approach feedback, while *literal crossover* always means theta/alpha ≥ 1.00. A frozen theta reference is seeded during the final 60 seconds of the two-minute Settle stage. The approach output starts at 30% so the pad remains perceptible, adds up to 50% as theta rises above that reference, and adds up to 20% for ratio progress toward literal crossover. It can therefore respond before the reward ratio is reached. Literal crossover and sustained crossover require 1 and 3 continuous clean seconds respectively by default. Those dwell times and the rise span are live controls. There is no separate alpha-down inhibit.

## What the client hears

| Layer | Trigger | Audio |
| --- | --- | --- |
| External background | Operator-selected YouTube or other media | Steady volume, set separately from feedback |
| Approach | `feedback_approach`, including theta rise from its Settle reference | Soft, low pad; level changes gradually |
| Crossover | `feedback_crossover` after clean literal crossover dwell | Slow, gentle six-note melody in the same musical position as the pad |
| Sustained | `feedback_sustained` after clean sustained dwell | The same melody with lower harmony |

The three synchronized stereo WAVs are original, generated locally by Recorder's `generate_narrowband_melodic.py`. They are bundled under `narrowband_melodic_v1` and require no downloaded asset folder. Recorder's continuous mixer changes layers over seconds, with a one-second crossover entry and 1.5-second sustained entry by default for brief crossings. The operator can adjust the feedback ceiling, attack, release, contrast, and layer trims. The preview buttons audition each layer before starting. A clinician may deliberately override the bundle with another aligned three-file WAV set using the declared filenames.

The 3–5 Hz slow and 15–56 Hz fast guards withhold positive feedback. Recorder fades toward a quiet pad under a guard; the external background keeps playing. Pause, quiet stages, and operator mute silence Recorder feedback. A guard is a signal-quality or activity flag, not proof of a particular mental state. Inspect the guard readout before changing thresholds. The stages are Settle 2 min, Deep 1 15 min, Rest 1 2 min, Deep 2 15 min, and Cooldown 2 min.

## How this differs from Brain-Trainer ALP1C

Brain-Trainer's published ALP1C instructions describe 6–8 Hz theta versus 9–11 Hz alpha, a continuously playing chant, alpha-linked nature-sound level, a MIDI melody whose volume and pitch follow theta dominance, and distinct slow/fast warning sounds. This protocol adopts the narrow-band crossover and guard bands, but uses operator-selected background media and original sustained audio layers. The pre-crossover theta-rise layer and three-second sustained harmony are local design choices. It does **not** reproduce Brain-Trainer's proprietary design, adaptive target-setting procedure, music, or warning sounds. No claim is made that these substitutions are clinically equivalent.

1. Brain-Trainer. *Brain-Trainer Designs Manual*, “ALP1C Alpha Theta,” pp. 12–13 (June 6, 2020). <https://brain-trainer.com/downloads/Designs_List_Brain-Trainer.pdf>
2. Brain-Trainer. “BT2 ALP: Alpha-Theta.” <https://brain-trainer.com/support/resources/bt2-alp-alpha-theta/>
3. Peniston, E. G., & Kulkosky, P. J. (1989). *Alpha-theta brainwave training and beta-endorphin levels in alcoholics*. <https://doi.org/10.1111/j.1530-0277.1989.tb00325.x>

Session measures such as crossover percentage and longest clean hold describe this recording. They do not establish a subjective state or treatment effect.
