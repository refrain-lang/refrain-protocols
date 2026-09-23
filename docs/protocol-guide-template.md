# Protocol companion guide template

Every `.refrain` protocol has a neighboring Markdown guide with the same base
name. For example, `protocols/eeg/foo.refrain` is documented by
`protocols/eeg/foo.md`. Keep the guide synchronized with the protocol version.

The guide serves clinicians, operators, reviewers, and implementers. Explain
the protocol in direct language, while preserving the exact signal and control
names needed to audit the implementation.

Use the following sections. Remove instructional text when creating a guide.

## Status

State the protocol version, maturity status, evidence classification, intended
population, and validation completed in this implementation. Make draft or
untested status prominent.

## Purpose

Describe the intended training goal and what the protocol is designed to
reward or inhibit. Do not turn a research finding into a clinical claim.

## Signal path and training rule

Document electrode placement, reference, frequency bands, derived signals,
thresholds, the complete reward condition, dwell time, and every inhibit.
Include a compact expression of the actual rule where useful.

## Session flow

List each stage, duration, transition mode, whether feedback is active, and
what the client and operator should expect. State the default total duration
and describe any host-provided baseline or warm-up that is outside the
protocol's phase list.

## Feedback

Explain every output channel and its meaning. Separate the protocol output
contract from a particular host's rendering, such as tones, gongs, video,
brightness, or volume.

## Controls

List defaults, ranges, whether each value is live-tunable, and its practical
effect. Explain seeded values and identify controls that require restarting or
resolving the protocol.

## Operator notes

Cover preparation, what to monitor, when feedback is intentionally quiet, and
how to interpret sparse or excessive reward. Include only guidance supported
by the implementation or cited sources.

## Recorded data and review

State what the host should save and which measures are meaningful after a
session. Distinguish measured EEG and observed behavior from interpretation.

## Provenance

Use a table with one row per material design element:

| Element | Origin | What the citation supports | Local adaptation |
| --- | --- | --- | --- |
| Example | Published source, established convention, or local design | Narrow description of the evidence | Exact implementation choice |

Do not imply that a paper validates local filter settings, thresholds, session
timing, feedback sounds, or clinical use unless it actually reports them.

## Evidence limits

Summarize relevant population, sample-size, control, replication, and
generalizability limits. State that a detector or implementation test passing
does not establish clinical efficacy.

## References

Give complete citations with DOI, PMID, trial registration, or another stable
source link when available. Cite primary sources for protocol provenance and
reviews for the state of the broader evidence.

## Revision history

Record the protocol version, date, and material documentation or behavior
change.
