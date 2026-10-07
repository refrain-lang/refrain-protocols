# Alpha/theta logic still owned by Recorder

Inventory for a later migration, recorded while adding `alpha_theta_narrowband_melodic`. This is a design note, not a request to move the code now. The protocol files are the source of signal and reward semantics; Recorder remains responsible for device I/O, audio rendering, media windows, and session storage.

| Priority | Recorder location and current decision | Desired Refrain contract |
| --- | --- | --- |
| 1 | `nf/audio_renderer.py` lists alpha/theta protocol IDs to choose a gong and background sample. | Protocol metadata declares feedback roles and preferred assets. Recorder resolves approved assets by role, without recognizing clinical protocol IDs. |
| 1 | `nf/audio_renderer.py` calculates a sustained theta cue from telemetry using a fixed 3 s dwell and 3 s rearm, separate from the evaluator. | The protocol emits a sustained-crossover event/value with its own dwell and rearm semantics. Recorder renders the emitted event only. |
| 1 | `nf/guidance.py` assumes a `crossover_target`, theta gate, 10%/35% reward cutoffs, and gong-rate limits. | A per-protocol advice/autopilot policy names its inputs, observation window, allowed controls and steps, guard constraints, and evidence text. Recorder displays suggestions and records applied changes. |
| 1 | `nf/summary.py` infers theta/alpha ratios, strict crossover, and feedback-state durations by field names. | Protocol-declared measures and event labels define what is summarized. Recorder performs generic time-window aggregation and preserves raw streams. |
| 2 | `nf/texture_manifest.py` assumes exactly three roles called approach, crossover, sustained and requires aligned WAVs. | Refrain describes an ordered set of semantic feedback layers, priorities, and asset roles. Recorder validates and mixes arbitrary declared layers. |
| 2 | `nf/audio_renderer.py` fixes layer attack/release, guard-bed level, gong cooldown, and state priority. | Refrain declares per-layer transition and suppression policy, bounds, and defaults. Recorder owns the sample-accurate ramp and limiter. |
| 2 | `nf/api.py` and setup UI switch on `feedback_style == layered_texture`, with a few protocol-ID-specific test controls. | Host capabilities expose available rendering styles and testable outputs from the protocol contract; UI renders controls generically. |
| 2 | Observation UI uses alpha/theta-specific chart and `crossover_target` display conventions. | Protocol metadata identifies comparable streams, unit/scaling rules, literal versus shaping targets, and review metrics. Recorder draws the declared views. |
| 3 | YouTube defaults and media-volume behavior live in Recorder settings. | Refrain may declare that a steady external background is compatible and whether feedback may modulate it. Recorder still owns user URL, authentication/window, system volume, and output-device routing. |

The migration needs a versioned Refrain feedback schema for roles, transitions, guard behavior, and report measures, plus a generic host capability negotiation path. Do not move raw audio files, codec handling, macOS routing, YouTube login, device streaming, or capture-file I/O into the protocol language. Preserve existing captures by recording the protocol version, resolved feedback contract, asset hashes, and every live control change.

For the next pass, move one semantic behavior at a time and replay saved clean/guarded/paused telemetry through both paths before deleting host special cases. Treat authored synthetic cases as code checks, not clinical evidence; compare independently labeled real recordings separately.
