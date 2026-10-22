# Session report — design

Status: draft for review, 2026-10-22. Roadmap: inserted as Stage 1b of
`docs/superpowers/specs/2026-10-21-protocol-feedback-roadmap-design.md`, before the refrain
primitives (Stage 2, REC-23). Decided by the user: build this first, because it makes every later
step measurable (choosing the dip tolerance in Stage 2, each family's gate in Stage 3, the live
sessions in Stage 4).

## Why

After a feedback session the practitioner and the developers need to know how the protocol did:
did it reward the right things, how often, how fast, and was muscle muted. The recorder already
saves almost everything needed, but nothing turns it into that answer:

| Saved per session (coherence-recorder, on by default) | Missing |
|---|---|
| `raw.xdf`: every EEG sample before refrain, device timestamps; JSON markers | No replay tool |
| `feedback-history.jsonl`: 10 Hz telemetry from refrain taps (envelopes, thresholds, dwell components, reward hold, continuous, muted, inhibits, `output/audio_gain`), plus every reward event, phase change, control change, pause, clinician marker | Telemetry states are thinned to 10 Hz (dings and output channels are not; see the calls below) |
| `feedback-session.json`: protocol id, initial controls, device, channels, manifest | The protocol's source text and hash are not saved, so the exact version that ran is unknown |
| `feedback-summary.json`: time in reward, rewards/min, band trajectories, threshold drift, per-block stats | Nothing about latency, whether dings matched bursts, or whether mutes matched muscle |

Clocks differ: EEG uses device timestamps, telemetry and markers use session-relative wall time,
reward events use refrain's own timestamps.

## Goals

1. Point a command at a saved session folder and get a report of how the protocol behaved, in
   plain language and as JSON.
2. Replay the session's raw EEG through the protocol (or a different version or design of it), so
   two designs can be compared on the same real session.
3. Judge the reward against the signal, not against itself, for any protocol: find the moments
   the protocol's target was truly met, using accurate offline filters, and report which got
   feedback while still happening, how late, and feedback with no target behind it.
4. Judge muting against an independent measure of muscle activity in the raw EEG.
5. Check the replay against what the live log recorded, and say where they disagree.

## Non-goals

- A UI. Output is a printed report and a JSON file; the recorder's summary screen stays as it is.
- HRV and other non-EEG sessions (the EmotiBit session on disk is out of scope).
- Changing the recorder. One recorder change is filed separately (save protocol text and hash).
- Proving a design trains better. A report describes one session.

## Anti-goals

- A report whose replay silently differs from what ran live. Replay and live log are always
  reconciled, and disagreement is reported first, not buried.
- Reward judged only by the protocol's own envelope (circular). Burst detection uses an offline,
  zero-phase, accurate filter independent of the protocol's.
- Mapping EEG channels by position. Channels are mapped by name; a session whose protocol reads a
  channel the recording lacks is refused with that channel named (the earlier corpus-measurement
  mistake recorded on REC-15).
- Session data leaving the machine. Sessions are clinical recordings: reports are written next to
  the session or to a path given; nothing from a real session is committed, and tests use
  synthetic fixtures.

## Inputs

- A session folder: `raw.xdf`, `feedback-history.jsonl`, `feedback-session.json`.
- The protocol: by default the file in this repo whose `protocol "<id>"` matches the session's
  `protocol_id`, resolved against the bundled amp profile for the session's device model, with
  the session's placements and modes as bindings (see "Replay fidelity"). Because the session does not record which version ran, the report states this
  and, when the recorder later saves the source hash, checks it.
- Optional `--compare <file.refrain>` (repeatable): extra designs replayed on the same EEG.
- Controls: the session's `initial_controls`, then each logged `control_change` applied at its
  time in the replay.

## What the report contains

Per protocol replayed (the session's own first, then each comparison), per phase/block and for the
whole session, after warmup:

1. **Reconciliation** (session's own protocol only): replayed reward hold, muted and inhibit states
   against the live 10 Hz telemetry; share of frames that agree. Agreement below a stated level is
   the report's first line.
2. **Reward:** time the reward hold is on as a share of unmuted time; ding onsets per minute; ding
   duration distribution.
3. **True target episodes, for any protocol** (decided by the user 2026-10-22: latency and
   target-hitting are reported for whatever protocol runs, not only SMR). The report builds an
   offline "truth" version of the protocol's own reward condition: every envelope-producing derive
   is replaced by a zero-phase, accurate envelope of the same band from the same input (the
   reference `tools/measure_envelopes.py` already computes), every other derive (ratio, coherence,
   asymmetry) is recomputed from those envelopes or with a centred window, and the reward condition
   is evaluated on them with the replay's own thresholds. Stretches where that truth condition holds
   for at least the protocol's dwell duration are **true target episodes**: an SMR burst, a
   theta-over-alpha crossover, an asymmetry or coherence shift. Reported for every protocol:
   - episodes per minute and their length distribution;
   - share of episodes that got a reward event while still going, and within episode end + 250 ms;
   - reward latency from episode start (median, 90th percentile) and a deadline curve (share
     rewarded within 200, 300, 400, 500, 1000 ms);
   - continuous-output rise latency from episode start;
   - reward events outside any episode (stray rewards per minute);
   - per derive, the live envelope's lag and accuracy against its truth envelope (as
     `measure_envelopes.py` reports today).
   Derives the truth model cannot reproduce (for example one built from a primitive with no offline
   counterpart) are named in the report and their episodes are not judged.
4. **Muscle:** an independent muscle index from the raw EEG (high-frequency power above the EEG
   bands, within the recording's Nyquist), muscle episodes found from it; share of muscle time
   muted, share of muted time with no muscle episode, and bursts lost to muting.
5. **Thresholds:** start/end and drift per block for each threshold.
6. **Protocol-specific views** where the protocol declares them: the review contract fields
   (`review_ratio_stream`, `review_target_control`) add the ratio/target trajectory, and
   layered-texture sessions add time in each feedback state. These are additions to item 3, not a
   replacement for it.

## Constraints

- Lives in `refrain-protocols/tools/`, sharing the replay code in `tools/measure_envelopes.py`
  (factor shared pieces out rather than copy them).
- Reads XDF with `pyxdf` (the recorder already depends on `pyxdf>=1.16`); a tool-only dependency,
  not a dependency of the protocol package.
- Uses refrain's `Evaluator.live(..., record_streams=True)` stepped in the live chunk boundaries
  read from the XDF (see "Replay fidelity"), so the replay sees what live saw; per-sample streams,
  not 10 Hz.
- The first real test case is the one EEG session on disk: subject MCWE, 2026-10-21,
  `alpha_theta_narrowband` on BrainBit Flex at Pz (~35 minutes). It exercises reconciliation,
  reward, muscle and the truth-episode path on a ratio target; synthetic sessions with planted
  bursts test it on an SMR-style target until a real SMR session exists.
- Tests: a synthetic session builder (XDF + JSONL + session JSON, with planted bursts and muscle
  episodes and a known protocol) so every metric has a known answer.

## Replay fidelity — calls made after the design review (2026-10-22)

The review read the recorder code and the MCWE session. These are the builder's calls; each is
reported in the output so a reader can see what the replay did.

1. **The session's own protocol follows the log; comparison designs run free.** For the session's
   own protocol the replay applies, at the moment they happened: clinician control changes
   (`engine_value`, already in refrain units), applied advice (`advice_event` kind "applied", which
   has no `control_change` record), pause and resume (`set_clock_frozen`), held-output resets, and
   phase advances (a logged `phase_change` the replay has not reached by itself is forced; one the
   replay reaches early is held). The logged warmup seed (`control_change` with
   `source: "warmup_seed"`) is **compared, never applied**: applying it disarms the replay's own
   seed. Comparison designs run their own phase clock; logged control changes whose names they
   declare are applied, the rest are skipped and listed.
2. **Exact placement from the XDF order.** The recorder writes each feed chunk and each marker into
   `raw.xdf` in the order they happened. A small chunk-level XDF reader (pyxdf merges chunks and
   discards that order) recovers each event's position between chunks and the live chunk
   boundaries, and the replay steps those same chunks (`coherence` is chunk-dependent). Wall-clock
   `t_s` drifts ~3 s from refrain's sample clock over 34 minutes, so it is used only for labels.
   The reader tolerates a missing footer (unclean end), does no timestamp dejitter, and indexes by
   sample count.
3. **Reconciliation uses refrain-clock records first.** Every ding and every 50 ms output-channel
   value (`audio_gain`, feedback channels) is logged with refrain's own timestamp; those are
   compared sample-for-sample. The 10 Hz telemetry (reward hold, `muted`, inhibits) is a second,
   coarser check. "Reconciled" means: ≥ 99 % of dings matched within one chunk, output channel
   values within 1 % on ≥ 99 % of records, and telemetry states agreeing on ≥ 98 % of frames.
4. **Which protocol and refrain ran.** Until REC-26 lands, the default protocol file is the one at
   the refrain-protocols commit the recorder pins (read from the recorder's pin with `git show`);
   `--protocol` overrides it. The report states the file's sha256, whether it equals repo HEAD,
   the refrain version of the replay, and that the live refrain version is unknown. A failed
   reconciliation is therefore reported with these facts, so "wrong version" and "replay bug" can
   be told apart. After REC-26, the saved source is used and its hash checked.
5. **Amp profile and bindings, as the recorder does it.** The bundled profile is chosen by
   `device.model` (BrainBit Flex → `brainbit_flex.json`). `placements` and `modes` go into
   `resolve(bindings=...)`. `initial_controls` is not applied directly (it carries display units and
   placeholder values for site and mode keys); starting values come from the first logged
   `engine_value` for each control, else the protocol default.
6. **Warmup is kept.** The shared replay code takes `skip_warmup` as a parameter;
   `measure_envelopes.py` keeps `True`, the session report uses `False`.
7. **Ding: decided and heard, both reported.** The protocol's decision (event fired) and what the
   client could hear (`rendered_sound`, and for layered-texture sessions the feedback state and mix)
   are reported side by side. In the MCWE session no chime was rendered; the client heard textures.
8. **Mute sources reported separately:** refrain's artifact mute (`muted`), the phase's
   `output_muted`, clinician pause, and `audio_muted`. "Unmuted time" for the reward share means
   none of the four applies. "Bursts lost to muting" is broken down by source.
9. **Latency both ways.** From burst start (what the trainee experiences, includes the protocol's
   hold) for the deadline curve; and from the moment the reward condition first became true (the
   filter's delay alone). Stage 2 chooses the dip tolerance from the first and checks it against
   the second.
10. **Short events:** dings and sustained cues are logged unthinned on refrain's clock, so they are
    not lost; only the 10 Hz telemetry is thinned. (Corrects the table above.)
11. **Thresholds:** reported from the replay's `record_streams`. The live telemetry's `thresholds`
    field is empty for protocols whose thresholds the recorder does not report (as in MCWE), so
    there is nothing to reconcile them against there.

## Filed separately

A coherence-recorder ticket: save the protocol's source text (or its path and sha256) and the
refrain version in `feedback-session.json`, so a report can replay exactly what ran.

## Left to the builder

Exact burst-detection parameters (level, minimum length) and muscle-index band, chosen and stated
in the report; report layout; CLI flags beyond those named; how the shared replay code is factored.
