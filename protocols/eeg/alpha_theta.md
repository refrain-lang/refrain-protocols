# Configurable alpha/theta crossover

Companion guide for [`alpha_theta.refrain`](alpha_theta.refrain).

## Status

| Field | Value |
| --- | --- |
| Protocol version | 1.3.0 |
| Library status | **Draft — untested as a complete clinical system** |
| Evidence tag | Demo |
| Default population | Adults 18+ |
| Default site | Pz, referenced to the amplifier reference |
| Default session phases | 36 minutes total |

The protocol parses and runs through the Refrain engine, but its complete
signal path, thresholds, staged session, and host feedback behavior have not
been clinically validated together. It is a clinician-adjustable starting
point rather than a turnkey treatment protocol.

## Purpose

This is an eyes-closed, posterior alpha/theta protocol intended to support a
gradual shift toward relatively greater theta activity. It rewards sustained
theta/alpha ratio values above a clinician-selected target while also requiring
theta to clear its own threshold. The protocol includes delta and EMG guards
to withhold feedback during marked slow activity or probable muscle artifact.

The phrase **crossover** means a theta/alpha ratio of 1.0 or greater. This
implementation can begin below strict crossover to shape an approach toward
that state; its default target is 0.60 and the warm-up can seed a client-specific
starting value.

## Signal path and training rule

The default input is a referential channel at Pz. The active site can be changed
to another placement supported by the host and amplifier.

| Signal | Default band | Processing |
| --- | --- | --- |
| Delta envelope | 2–4 Hz | fourth-order bandpass → Hilbert magnitude → 500 ms smoothing |
| Theta envelope | 4–8 Hz | fourth-order bandpass → Hilbert magnitude → 500 ms smoothing |
| Alpha envelope | 8–12 Hz | fourth-order bandpass → Hilbert magnitude → 500 ms smoothing |
| Theta/alpha ratio | — | theta envelope ÷ alpha envelope |

A reward event requires all of the following:

1. Theta is above `theta_t`.
2. The theta/alpha ratio is above `crossover_target`.
3. Both conditions remain true for 1 second.
4. Neither the delta nor EMG inhibit is active.
5. The current session stage has not muted output.

The displayed time in reward is therefore not simply the percentage of time
that theta is above alpha. It reflects the compound rule and the active guards.

The delta guard uses 2–4 Hz bandpower over 2 seconds and a two-minute adaptive
history. The EMG guard uses 50–100 Hz bandpower over 100 ms and a two-minute
adaptive history. These guards suppress feedback; they are not trained targets.

## Session flow

| Stage | Duration | Feedback | Transition | Purpose in this implementation |
| --- | ---: | --- | --- | --- |
| Settle | 2 min | Quiet | Timed | Eyes-closed settling and stabilization |
| Deep 1 | 15 min | Active | Timed with floor | First sustained training period |
| Rest 1 | 2 min | Quiet | Timed | Deliberate rest between training periods |
| Deep 2 | 15 min | Active | Timed with floor | Second sustained training period |
| Cooldown | 2 min | Quiet | Timed | Gentle return before ending the session |

The phase list totals 36 minutes. A host may collect a separate baseline or
warm-up before these phases begin. `timed_with_floor` allows the host to expose
clinician-controlled hold or advance behavior while retaining the planned
duration.

Settle, Rest 1, and Cooldown intentionally mute protocol feedback. A lack of
gongs during those stages is expected rather than evidence of a broken reward
path.

## Feedback

The protocol exposes two host-neutral outputs:

- `audio_gain` is continuous. It follows a sigmoid transform of the live
  theta/alpha ratio, centered at strict crossover (1.0).
- `audio_chime` is an event emitted when the complete one-second reward rule is
  newly satisfied.

A host decides how to render those channels. Coherence Recorder can map
`audio_gain` to bounded media volume and layer a gong for `audio_chime` over a
visible YouTube music window. The operator's maximum-volume setting caps both
music and gong playback. That rendering is a Recorder integration choice, not
part of the published alpha/theta studies or the Refrain protocol contract.

During an inhibit or muted phase, the protocol output is quiet. The host may
retain an independently configured background-music floor, but must not turn a
muted reward event into a gong.

## Controls

| Control | Default | Range or choices | Live | Effect |
| --- | ---: | --- | :---: | --- |
| Threshold style | Adaptive | Adaptive / baseline | No | Selects rolling-percentile or warm-up-seeded absolute theta threshold |
| Theta reward rate | 15% | 15–70% | Yes | Sets the target percentile behavior of adaptive `theta_t` |
| Crossover target | 0.60 | 0.50–1.00 | Yes | Sets the required theta/alpha ratio; 1.00 is strict crossover |
| Delta/sleep guard | On | On / off | No | Enables the slow-activity inhibit |
| Delta inhibit threshold | 99% | 75–99% | Yes | Sets the delta guard percentile; lower values inhibit more often |
| Training site | Pz | Host-supported posterior placements | No | Selects the active electrode |
| Artifact guard | On | On / off | No | Enables the high-frequency EMG inhibit |
| Artifact strictness | 95% | 50–99% | Yes | Sets the EMG percentile; lower values inhibit more often |
| Theta threshold | 8.0 µV | 2.0–30.0 µV | Yes | Absolute theta threshold when baseline style is selected |

The six band-edge controls are advanced, resolve-time settings. Their defaults
are delta 2–4 Hz, theta 4–8 Hz, and alpha 8–12 Hz. Changing them requires the
protocol to be resolved again rather than adjusted during a live session.

`crossover_target` is seeded from the 65th percentile of the theta/alpha ratio
during a 90-second warm-up when the host supports seed collection. The value
used for a particular session can therefore differ from 0.60. Record both the
initial seeded value and every live adjustment.

## Operator notes

- Confirm a stable posterior signal and comfortable eyes-closed position before
  relying on the reward percentage.
- Keep background music and the gong below the operator-selected maximum volume
  before the client settles.
- Read alpha, theta, their ratio, theta-threshold state, and guard state
  together. A low gong rate has several possible causes.
- Expect the stage indicator to identify Settle, Deep 1, Rest 1, Deep 2, and
  Cooldown explicitly. Feedback is purposefully quiet in the three muted stages.
- Make live changes gradually and preserve each change as an event in the
  session record. Interpretation should use the intervals before and after the
  change rather than only the final session average.

## Recorded data and review

The host should preserve the full EEG recording, the three envelopes, the
theta/alpha ratio, threshold values, guard states, reward state and events,
phase transitions, control changes, audio state, and operator annotations.

Useful descriptive review measures include time in the compound reward rule,
gong rate, ratio trajectory, alpha and theta trajectories, inhibit burden, and
per-stage summaries. These are measured session features. They do not by
themselves establish a therapeutic response, a specific subjective state, or
the cause of imagery reported by a client.

## Provenance

| Element | Origin | What the source supports | Local adaptation |
| --- | --- | --- | --- |
| Alpha/theta neurofeedback | Peniston & Kulkosky (1989, 1991) | Historical use of extended eyes-closed alpha/theta training in small clinical samples | Refrain implementation and current operator workflow |
| Sustained long-form training | Peniston & Kulkosky (1989); Saxby & Peniston (1995) | Published programs used repeated 30- or 40-minute sessions | One 36-minute staged session with a two-minute rest |
| Theta-over-alpha crossover | Alpha/theta training tradition and prior library protocol | Relative alpha/theta change as feedback information | Explicit `theta_envelope / alpha_envelope` signal and adjustable 0.50–1.00 target |
| Pz default and selectable posterior site | Prior Refrain library design | Posterior training is consistent with the protocol family | Pz is the library default; this guide does not attribute that exact choice to every cited study |
| Adaptive theta threshold | Local Refrain design | Not established by the cited clinical papers | Compound reward requires theta above a percentile or seeded absolute threshold |
| Delta and EMG inhibits | Local safety and signal-quality design | Not established as part of the cited Peniston-Kulkosky procedure | 2–4 Hz and 50–100 Hz percentile guards suppress feedback |
| Graded 0.60 crossover target | Local shaping design | The cited work does not validate this numerical target | Warm-up-seeded, live-tunable target below strict crossover |
| Music-volume modulation and gong | Host rendering design | Not evaluated by the cited studies | Recorder maps continuous and event outputs to music level and gong playback |

## Evidence limits

The foundational reports involved small, selected clinical samples and bundled
alpha/theta feedback with other preparation or care. The 1989 report used a
temperature-biofeedback pretraining phase followed by 15 30-minute alpha/theta
sessions. The 1995 study used 20 40-minute sessions. Those designs do not by
themselves validate this implementation's filters, thresholds, guards, staged
36-minute schedule, audio mapping, or use with a different population.

Later reviews describe continued interest in neurofeedback for PTSD while also
identifying substantial risk of bias and heterogeneity in much of the evidence.
Passing parser, engine, audio, or session tests establishes software behavior;
it does not establish clinical efficacy.

## References

1. Peniston, E. G., & Kulkosky, P. J. (1989). Alpha-theta brainwave training
   and beta-endorphin levels in alcoholics. *Alcoholism: Clinical and
   Experimental Research, 13*(2), 271–279.
   [doi:10.1111/j.1530-0277.1989.tb00325.x](https://doi.org/10.1111/j.1530-0277.1989.tb00325.x)
   · [PMID 2524976](https://pubmed.ncbi.nlm.nih.gov/2524976/)
2. Peniston, E. G., & Kulkosky, P. J. (1991). Alpha-theta brainwave
   neuro-feedback therapy for Vietnam veterans with combat-related
   post-traumatic stress disorder. *Medical Psychotherapy, 4*, 47–60.
3. Saxby, E., & Peniston, E. G. (1995). Alpha-theta brainwave neurofeedback
   training: An effective treatment for male and female alcoholics with
   depressive symptoms. *Journal of Clinical Psychology, 51*(5), 685–693.
   [doi:10.1002/1097-4679(199509)51:5<685::AID-JCLP2270510514>3.0.CO;2-K](https://doi.org/10.1002/1097-4679(199509)51:5%3C685::AID-JCLP2270510514%3E3.0.CO;2-K)
   · [PMID 8801245](https://pubmed.ncbi.nlm.nih.gov/8801245/)
4. Steingrimsson, S., et al. (2023). Neurofeedback for post-traumatic stress
   disorder: Systematic review and meta-analysis of clinical and
   neurophysiological outcomes. *European Journal of Psychotraumatology*.
   [PMC10515677](https://pmc.ncbi.nlm.nih.gov/articles/PMC10515677/)

## Revision history

- **1.3.0 — 2026-09-22:** First companion guide. Documents the staged session,
  compound reward rule, delta and EMG guards, host-neutral feedback outputs,
  Recorder rendering example, provenance, and evidence limits.
