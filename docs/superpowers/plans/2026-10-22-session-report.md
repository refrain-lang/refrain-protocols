# Session report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A command that takes a saved coherence-recorder feedback session and reports how the protocol behaved: whether the replay matches what ran live, reward and mute time, how fast and how often feedback reached true target moments, and whether mutes matched muscle, for any protocol.

**Architecture:** Five small modules under `tools/session_report/`. They read the session's raw XDF in file order, replay it through refrain's evaluator following the session log, reconcile the replay with the log, build an offline "truth" version of the protocol's reward condition to find true target episodes, find muscle episodes independently, then assemble metrics into a printed report and JSON. The replay and reference-envelope code is shared with `tools/measure_envelopes.py`.

**Tech Stack:** Python 3.12, numpy, scipy, refrain 0.24.0 (`Evaluator.live`, `step_chunk`, `set_control`, `advance_phase`, `hold`, `set_clock_frozen`, `reset_held_outputs`, `last_streams`, `last_taps`), pytest. No new dependency (a minimal XDF chunk reader replaces pyxdf, which merges chunks and drops their order).

**Spec:** `docs/superpowers/specs/2026-10-22-session-report-design.md`

## Global Constraints

- No session data is committed or copied off the machine. Tests use synthetic sessions built in `tmp_path`. The one real session on disk is used only in the final, local smoke run.
- Channels are mapped by name, never by position. A protocol that reads a channel the recording lacks is refused, naming the channel.
- Amp profile: the bundled refrain profile chosen by the session's `device.model` (`"BrainBit Flex"` → `brainbit_flex.json`); `placements` and `modes` go to `resolve(bindings=...)`.
- The session's own protocol follows the log; comparison protocols (`--compare`) run their own phase clock and get only name-matched control changes. Skipped changes are listed.
- The warmup-seed `control_change` (`source == "warmup_seed"`) is compared, never applied.
- Reconciled means: ≥ 99 % of reward events matched within one chunk, output-channel values within 1 % on ≥ 99 % of records, and telemetry states agreeing on ≥ 98 % of frames.
- Deadline curve thresholds: 200, 300, 400, 500, 1000 ms. "Within episode end + 250 ms" is the late-but-useful window.
- Mute sources are reported separately: `muted` (artifact), phase `output_muted`, pause, `audio_muted`. "Unmuted" means none of the four.
- Use the scratchpad venv for tests: `/private/tmp/claude-501/-Users-jcroall-git-refrain-protocols/61b6dc55-65e2-45f9-9d0b-46559c738940/scratchpad/venv/bin/python`. The repo `.venv` is stale.
- Work on branch `feat/session-report` from `main`.

## Review Focus

1. **A session that ended uncleanly** (no stream footer, no `feedback-summary.json`, `completed: false`). It must still load. Pinned in Task 1 (`test_reader_tolerates_missing_footer`).
2. **A protocol whose reward condition uses something the truth model cannot reproduce.** It must report that derive as not judged and still produce every other section. Pinned in Task 5 (`test_unreproducible_derive_is_named_not_judged`).
3. **A control change for a control the comparison protocol does not declare.** It must be skipped and listed, not crash. Pinned in Task 3 (`test_compare_skips_unknown_controls`).
4. **A recording missing a channel the protocol reads.** It must be refused, naming the channel. Pinned in Task 2 (`test_missing_channel_is_refused_by_name`).
5. **A session with zero true episodes, or zero reward events.** Rates and percentages must be 0 or `None`, never a division error. Pinned in Task 6 (`test_empty_session_metrics_are_defined`).

---

### Task 1: XDF chunk reader, and a synthetic session builder for tests

**Files:**
- Create: `tools/session_report/__init__.py` (empty), `tools/session_report/xdf_chunks.py`
- Create: `tests/session_fixture.py` (test helper: writes XDF + JSONL + session JSON)
- Test: `tests/test_session_xdf.py`

**Interfaces:**
- Produces:
  - `read_xdf_items(path: Path) -> tuple[dict[int, StreamInfo], list[Item]]`. `StreamInfo` is a dataclass with `stream_id: int`, `name: str`, `channel_format: str`, `channel_names: list[str]` and `srate: float`. `Item` is a dataclass with `kind: Literal["samples","marker"]`, `stream_id: int`, `data: np.ndarray | None` (samples × channels, float64), `timestamps: np.ndarray`, `marker: dict | None` (the parsed JSON label) and `index: int` (file order).
  - Test helper `build_session(dir: Path, *, fs: float, channel_names: list[str], eeg: np.ndarray, chunk: int, protocol_id: str, markers: list[tuple[int, dict]], telemetry: list[dict], footer: bool = True, device_model: str = "BrainBit Flex", placements: dict | None = None, modes: dict | None = None) -> Path`. `markers` are `(sample_index, record)` pairs written between chunks at that position. It writes `raw.xdf`, `feedback-history.jsonl` (markers plus telemetry, each with `type` and `t_s`) and `feedback-session.json` (keys as in a real session: `protocol_id`, `plugin_id`, `device{model, sample_rate_hz, channels}`, `placements`, `modes`, `initial_controls`, `completed`).

XDF format: the magic `XDF:`, then chunks of variable-length-int length, a uint16 tag and the content. Tags: 1 = file header, 2 = stream header (uint32 id + XML), 3 = samples (uint32 id, varlen n, per sample: a timestamp byte 0 or 8 followed by a double, then values), 4 = clock offset, 6 = stream footer. Markers are stream 2, `string`, one value per sample: varlen length + UTF-8. Match the recorder's writer (`coherence-recorder/recorder/backend/xdf_writer.py`): read it, do not import it.

- [ ] **Step 1: Write the failing tests**

```python
def test_reader_preserves_chunk_and_marker_order(tmp_path):
    d = build_session(tmp_path, fs=250, channel_names=["Pz"], eeg=np.arange(1000.)[:, None], chunk=25,
                      protocol_id="p", markers=[(100, {"type": "control_change", "t_s": 0.4})], telemetry=[])
    infos, items = read_xdf_items(d / "raw.xdf")
    kinds = [i.kind for i in items]
    assert kinds[:5] == ["samples"] * 4 + ["marker"]          # marker after sample 100 = after chunk 4
    assert np.concatenate([i.data for i in items if i.kind == "samples"])[:, 0].tolist() == list(range(1000))
    assert infos[1].channel_names == ["Pz"] and infos[1].srate == 250

def test_reader_tolerates_missing_footer(tmp_path):
    d = build_session(tmp_path, fs=250, channel_names=["Pz"], eeg=np.zeros((500, 1)), chunk=25,
                      protocol_id="p", markers=[], telemetry=[], footer=False)
    _, items = read_xdf_items(d / "raw.xdf")
    assert sum(len(i.data) for i in items if i.kind == "samples") == 500
```

- [ ] **Step 2: Run and see them fail** — `<venv>/bin/python -m pytest tests/test_session_xdf.py -v`. Expected: ImportError.
- [ ] **Step 3: Implement `read_xdf_items` and the `build_session` helper.** No dejittering; timestamps are returned as stored.
- [ ] **Step 4: Run and see them pass.** Expected: 2 passed.
- [ ] **Step 5: Commit** — `git add tools/session_report tests/session_fixture.py tests/test_session_xdf.py && git commit -m "Read recorder XDF chunks in file order"`

### Task 2: Session loader, protocol and amp resolution

**Files:**
- Create: `tools/session_report/session.py`
- Test: `tests/test_session_load.py`

**Interfaces:**
- Consumes: `read_xdf_items` (Task 1).
- Produces:
  - `load_session(folder: Path) -> Session`. `Session` is a dataclass with: `meta: dict` (feedback-session.json); `fs: float`; `channel_names: list[str]`; `chunks: list[np.ndarray]` (live chunk boundaries, EEG stream only); `events: list[TimedEvent]` (markers placed by chunk position: `TimedEvent(after_chunk: int, record: dict)`); `history: list[dict]` (all JSONL records); `telemetry: list[dict]` (`type == "telemetry"`).
  - `resolve_for_session(session: Session, protocol_path: Path) -> tuple[IR, AmpProfile, tuple[str, ...]]`. It picks the bundled amp profile by `meta["device"]["model"]` (mapping: `"BrainBit Flex"` → `brainbit_flex`; unknown model → `ValueError` naming it), passes `bindings = {**meta["placements"], **meta["modes"]}`, and returns the evaluator channel order. A protocol channel missing from the recording raises `ValueError(f"recording lacks channel {name!r} that the protocol reads")`.
  - `default_protocol_path(session: Session, repo: Path, ref: str | None = None) -> tuple[Path, str, str]`: the file under `repo/protocols` whose `protocol "<id>"` equals `meta["protocol_id"]`. With `ref`, the file's content at that git ref is written to a temp file (`git show ref:path`). Returns path, sha256 and the source ("ref <sha>" or "working tree"). The CLI's default `ref` is the refrain-protocols commit the recorder pins, read from `~/git/coherence-recorder/pyproject.toml` (the `refrain-protocols @ git+...@<sha>` or tag line) when that file exists, else the working tree; `--protocols-ref` overrides it.

- [ ] **Step 1: Write the failing tests:** `test_default_protocol_path_at_ref` (with `ref="HEAD"` the returned sha256 equals that of the committed file); `test_load_session_places_events_after_their_chunk` (a marker written at sample 100 with chunk 25 has `after_chunk == 3`, the 0-based index of the 4th chunk); `test_missing_channel_is_refused_by_name` (a protocol reading `Cz` against a `["Pz"]` recording raises with `'Cz'` in the message); `test_unknown_device_model_is_refused`; `test_default_protocol_path_finds_by_protocol_id` (`"alpha_theta_narrowband"` → `protocols/eeg/alpha_theta_narrowband.refrain`).
- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run and see them pass.**
- [ ] **Step 5: Commit** — `"Load a recorder session and resolve its protocol the way the recorder did"`

### Task 3: Log-following replay, and the shared replay core

**Files:**
- Create: `tools/session_report/replay.py`
- Modify: `tools/measure_envelopes.py`: move the evaluator stepping into `tools/session_report/replay.py::step_through` and import it back; behaviour unchanged (`skip_warmup=True` there).
- Test: `tests/test_session_replay.py`; `tests/test_measure_envelopes.py` must stay green.

**Interfaces:**
- Consumes: `Session`, `resolve_for_session` (Task 2).
- Produces:
  - `step_through(ir, fs, channel_names, chunks, *, skip_warmup: bool, on_before_chunk: Callable[[int, Evaluator], None] | None = None) -> ReplayResult`. `ReplayResult` has `streams: dict[str, np.ndarray]` (per sample, concatenated), `events: list[dict]` (`{"t_sample": int, "channel": str, "kind": str, "value": float}`), `taps_per_chunk: list[dict]`, `applied: list[dict]` and `skipped: list[dict]`.
  - `replay_session(session, ir, channel_names, *, follow_log: bool) -> ReplayResult`.

Rules applied in `on_before_chunk`, for events whose `after_chunk` is the previous chunk, in file order:

| Logged record | `follow_log=True` (session's own protocol) | `follow_log=False` (comparison) |
|---|---|---|
| `control_change` with `engine_value`, source not `warmup_seed` | `set_control(name, engine_value)` | same, if the IR declares the control; otherwise append to `skipped` |
| `control_change` with source `warmup_seed` | append to `applied` as "compared", do not set | ignore |
| `advice_event` kind `"applied"` | `set_control` with its control and value | same rule as above |
| `session_state` pause / resume | `set_clock_frozen(True/False)` | same |
| `phase_change` | if the replay's current phase differs, `advance_phase()` until it matches (with `hold(False)` first) | ignore |
| `phase_change` not yet logged while the replay's phase would end | `hold(True)` while the log still shows the earlier phase | ignore |

Held-output resets: call `reset_held_outputs()` after each applied control change when the session's `manifest` declares layered-texture feedback, and on any gap > 0.5 s between consecutive EEG chunk timestamps.

- [ ] **Step 1: Write the failing tests:** `test_control_change_applies_before_the_next_chunk` (the threshold or control value read from `taps_per_chunk` changes at the chunk after the marker); `test_warmup_seed_is_compared_not_applied` (`applied` holds a "compared" entry and no `set_control` call happens for it); `test_logged_phase_change_is_followed` (protocol with a 1 s warmup phase, log shows the advance at 2 s: the replay's phase changes at the 2 s chunk); `test_compare_skips_unknown_controls`; `test_measure_envelopes_unchanged` (an existing `tests/test_measure_envelopes.py` run, kept green).
- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Implement.** Protocols for the tests are small inline `.refrain` texts written to `tmp_path`, resolved with `amp=None` where they use literal channels.
- [ ] **Step 4: Run and see them pass**, plus `tests/test_measure_envelopes.py`.
- [ ] **Step 5: Commit** — `"Replay a session through refrain, following its log"`

### Task 4: Reconciliation

**Files:**
- Create: `tools/session_report/reconcile.py`
- Test: `tests/test_session_reconcile.py`

**Interfaces:**
- Consumes: `ReplayResult` (Task 3), `Session` (Task 2).
- Produces: `reconcile(session, replay, chunk_len: int) -> Reconciliation`, a dataclass with `events_matched: float`, `outputs_within_1pct: float`, `telemetry_agree: float`, `reconciled: bool` (thresholds from Global Constraints) and `notes: list[str]`.
  - Logged `reward_event` records carry refrain's timestamp; convert to samples with `round(timestamp_s * fs)`. They match a replay event of the same channel and kind within `chunk_len` samples.
  - Output-channel values (`audio_gain` and the feedback channels) are compared at the logged refrain timestamps.
  - Telemetry booleans (`reward_event_holds`, `muted`, each inhibit) are compared against the replay's per-chunk taps at the chunk nearest each frame's position.

- [ ] **Step 1: Write the failing tests:** `test_identical_replay_reconciles` (the log built from a replay of the same protocol gives `reconciled is True` and all three scores at 1.0); `test_shifted_events_fail_reconciliation` (events shifted by 3 chunks give `events_matched < 0.99` and `reconciled is False`).
- [ ] **Step 2–4: Fail, implement, pass.**
- [ ] **Step 5: Commit** — `"Reconcile a replay with what the session logged"`

### Task 5: Truth model: true target episodes for any protocol

**Files:**
- Create: `tools/session_report/truth.py`
- Test: `tests/test_session_truth.py`

**Interfaces:**
- Consumes: IR JSON (`ir_to_json_obj`), `ReplayResult.streams` (input streams and threshold streams), `reference_envelope` from `tools/measure_envelopes.py`.
- Produces:
  - `truth_streams(ir_json, replay) -> tuple[dict[str, np.ndarray], list[str]]`: the truth value per derive, plus the names of derives it cannot reproduce. Rules:
    - envelope shapes (four-stage, `band_envelope`, `band_envelope`+`smooth`, centre+ratio): `reference_envelope` of the derive's source stream over its band;
    - binary arithmetic or `ratio` over derives: the same arithmetic on their truth streams;
    - `coherence`: scipy magnitude-squared coherence on a centred window of the declared length;
    - anything else: unreproducible.
  - `true_episodes(ir_json, truth, replay, fs) -> TruthResult`. It evaluates the reward event's `dwell` condition (supports `above`, `below`, `at_or_above`, `inside`, `all_of`, `any_of`), using the replay's per-sample threshold streams for threshold operands. Episodes are stretches where the condition holds for ≥ the dwell duration, each `(start_sample, end_sample)`. `TruthResult` has `episodes: list[tuple[int, int]]`, `judged: bool` (False when the condition reads an unreproducible derive) and `unreproducible: list[str]`.

- [ ] **Step 1: Write the failing tests:**
  - `test_planted_bursts_are_found_as_episodes`: SMR-like protocol (one `above(smr_envelope, smr_t)` with `dwell 250 ms`, absolute threshold). Synthetic EEG with 13.5 Hz bursts of 0.6 s at known times over noise; each planted burst yields one episode whose start is within 60 ms of the planted start.
  - `test_ratio_condition_episodes`: an alpha-theta-style `above(theta/alpha ratio, 1.0)` with dwell 1 s; a planted stretch where theta exceeds alpha yields one episode.
  - `test_unreproducible_derive_is_named_not_judged`: a derive using `autocorr` makes `judged is False` and names it.
- [ ] **Step 2–4: Fail, implement, pass.**
- [ ] **Step 5: Commit** — `"Find true target episodes for any protocol's reward condition"`

### Task 6: Muscle index, metrics, report and CLI

**Files:**
- Create: `tools/session_report/muscle.py`, `tools/session_report/metrics.py`, `tools/session_report/__main__.py`
- Test: `tests/test_session_metrics.py`, `tests/test_session_report_cli.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `muscle_episodes(raw: np.ndarray, fs: float) -> list[tuple[int, int]]`. Band 70 Hz to min(120 Hz, 0.45·fs) power on 100 ms windows; an episode is ≥ 100 ms above 3× the session median. The band and factor are stated in the report.
  - `session_metrics(session, replay, truth, muscle, fs) -> dict` with:
    - `reward_share_of_unmuted`
    - `rewards_per_min`
    - `episodes_per_min`
    - `episode_len_ms` {median, p90}
    - `rewarded_in_episode`
    - `rewarded_by_end_plus_250`
    - `latency_from_episode_ms` {median, p90}
    - `latency_from_condition_true_ms` {median, p90}
    - `deadline_curve` {200, 300, 400, 500, 1000}
    - `continuous_rise_ms` {median}
    - `stray_rewards_per_min`
    - `mute_share` {artifact, phase, pause, audio}
    - `muscle_time_muted`
    - `muted_without_muscle`
    - `episodes_lost_to_mute` {by source}
    - `thresholds_per_block`
    - `derive_lag_r` {derive: (lag_ms, r)}
    - `ding_decided_vs_rendered` {decided, rendered}
    - per-phase/block copies of the rate and share fields
    - `protocol_views`: when the protocol declares `review_ratio_stream` / `review_target_control`, the ratio trajectory and share above target (60 s buckets); for layered-texture sessions, time in each logged `feedback_state`

    Every rate or share with a zero denominator is `None`.
  - CLI: `python -m tools.session_report <session_folder> [--protocol PATH | --protocols-ref REF] [--compare PATH ...] [--json OUT]`. It prints, in order:
    1. the reconciliation verdict (first line);
    2. which protocol file ran (path, sha256, equals HEAD or not), the replay's refrain version, and "live refrain version: not recorded" until REC-26;
    3. then per protocol: reward, true episodes and latency, mutes and muscle, thresholds, unreproducible derives, and skipped control changes for comparisons.

    `--json` writes the same content.

- [ ] **Step 1: Write the failing tests:**
  - `test_muscle_episodes_found` (planted 80 Hz bursts are found; pure EEG-band signal gives none).
  - `test_metrics_on_planted_session` (synthetic session, one protocol: values within tolerance of the known answers: `episodes_per_min`, `rewarded_in_episode == 1.0` for strong bursts, latency median within 100 ms of the cFIR model).
  - `test_empty_session_metrics_are_defined` (no bursts, no rewards: rates 0, latencies `None`, no exception).
  - `test_cli_prints_reconciliation_first_and_writes_json` (run `python -m tools.session_report <fixture> --json out.json`; exit 0; first line starts with "Reconciliation:"; the JSON has the per-protocol keys above).
- [ ] **Step 2–4: Fail, implement, pass.**
- [ ] **Step 5: Commit** — `"Report how a session's protocol behaved: rewards, true episodes, latency, muting"`

### Task 7: Real-session smoke run, docs, gates

**Files:**
- Modify: `docs/superpowers/specs/2026-10-21-protocol-feedback-roadmap-design.md` (add Stage 1b: session report, done; link the spec)
- Add: `docs/superpowers/specs/2026-10-22-session-report-design.md`, this plan
- Modify: `CHANGELOG.md` (an "Unreleased" section, Added: session report tool)

- [ ] **Step 1: Smoke run on the one real session on disk (local only, nothing committed).** Command: `<venv>/bin/python -m tools.session_report "<the local session folder>" --json <scratchpad>/session_report.json`. Expected: exit 0 and a reconciliation verdict. If it does not reconcile, the report's notes must say which check failed. Record the verdict and the top-line numbers for the user; do not tune code to force agreement without a ruling.
- [ ] **Step 2: Full suite** — `<venv>/bin/python -m pytest tests/; echo $?`. Expected: exit 0. Catalog unchanged (`tools/build_catalog.py` and `git diff --exit-code main -- catalog.json`).
- [ ] **Step 3: Docs and changelog; commit** — `"Add the session report to the roadmap and changelog"`
