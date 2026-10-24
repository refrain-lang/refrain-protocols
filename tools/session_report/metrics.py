"""Every number the report prints, assembled from one replay of one protocol.

The arithmetic is the easy part; the denominators are the whole job. Three rules
run through this module:

* **A rate over elapsed time with no events is zero. A share or a latency whose
  own denominator is zero is None.** No rewards in a minute is a well-defined
  nothing per minute; "the share of episodes that were rewarded" when there were
  no episodes is not a number at all, and reporting it as 0 % would read as a
  protocol that missed everything. Nothing here divides without checking.
* **What could not be measured is named, not filled in.** When the truth model
  could not judge the session, every episode-derived figure is None rather than
  zero, and ``notes`` says why. Degradations are recorded, never swallowed.
* **Each figure's denominator is the time it belongs to.** Reward share is over
  *unmuted* time, because muted reward reached nobody; episode rates are over
  the *trusted window*, because that is the only stretch the truth model could
  look at; mute shares are over the replayed recording after warmup.

Everything is measured **after warmup**. A protocol's warmup is its first phase
when that phase is output-muted (refrain's own rule, and the window its
percentile thresholds and filters fill in), and during it the trainee is
getting no feedback at all -- so counting it would dilute every rate in the
report. The span is taken from the live telemetry's ``state`` field where the
log has one and from the protocol's own first phase otherwise, both figures are
reported, and a disagreement between them is noted rather than resolved
silently. A phase that is entirely warmup comes back with None figures, not
zeroes: nothing was measured there, which is not the same as nothing happening.

Resolutions differ by source and the report says so: refrain's artifact mute and
the phase's output mute are read from the replay's per-chunk taps (one chunk of
resolution, 16 ms on a real session), the clinician's pause from the log's own
records, and the recorder's audio mute from the 10 Hz telemetry.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from measure_envelopes import envelopes, lag_and_r, reference_envelope
from session_report.muscle import MUSCLE_FACTOR, WINDOW_MS as MUSCLE_WINDOW_MS, muscle_band
from session_report.reconcile import frame_positions

GRACE_MS = 250.0                 # "late but still useful": a reward by episode end + this
DEADLINES_MS = (200, 300, 400, 500, 1000)
RISE_FRACTION = 0.5              # the continuous output's half-rise, as its rise time
BUCKET_S = 60.0                  # protocol_views trajectory buckets
MIN_LAG_S = 10.0                 # lag_and_r needs at least this much signal to search over
FLAT_STD = 1e-9
MUTE_SOURCES = ("artifact", "phase", "pause", "audio")
WARMUP_DISAGREE_S = 1.0          # log and protocol further apart than this is worth saying


def _share(part, whole) -> float | None:
    """A share, or None when there is nothing to take a share of."""
    return float(part) / float(whole) if whole else None


def _per_min(count, seconds) -> float | None:
    """A rate; zero events over real time is 0.0, but no time at all is None."""
    return 60.0 * float(count) / float(seconds) if seconds and seconds > 0 else None


def _median_p90(values) -> dict[str, float | None]:
    if not values:
        return {"median": None, "p90": None}
    a = np.asarray(values, dtype=float)
    return {"median": float(np.median(a)), "p90": float(np.percentile(a, 90))}


def _span(replay) -> int:
    """How many samples every one of the replay's streams covers."""
    return min((len(v) for v in replay.streams.values()), default=0)


def _expand_tap(replay, key: str, n: int, default: float = 0.0) -> np.ndarray:
    """A per-chunk tap as one value per sample.

    A tap is the value at its chunk's *last* sample, so holding it across the
    chunk dates any change from the chunk's start -- one chunk of resolution.
    """
    offsets = list(replay.chunk_sample_offsets)
    if not offsets or n <= 0:
        return np.full(max(n, 0), default, dtype=float)
    values = np.array([default if t.get(key) is None else float(t[key])
                       for t in replay.taps_per_chunk[:len(offsets)]], dtype=float)
    lengths = np.diff(np.clip(np.asarray(offsets + [n]), 0, n))
    keep = min(len(values), len(lengths))             # a chunk with no taps holds no value
    out = np.repeat(values[:keep], lengths[:keep])
    if len(out) < n:                                  # the taps did not reach the end
        out = np.concatenate([out, np.full(n - len(out), default)])
    return out


def _mask_from_spans(spans, n: int) -> np.ndarray:
    mask = np.zeros(max(n, 0), dtype=bool)
    for start, end in spans:
        mask[max(int(start), 0):min(int(end), n)] = True
    return mask


def _onsets(stream) -> np.ndarray:
    """Sample indices where an event stream rises."""
    if stream is None or not len(stream):
        return np.zeros(0, dtype=int)
    on = np.asarray(stream, dtype=float) > 0.5
    rising = np.flatnonzero(on[1:] & ~on[:-1]) + 1
    return np.concatenate(([0], rising)) if on[0] else rising


def _run_lengths(flags: np.ndarray, lo: int) -> list[int]:
    """Length in samples of every run of True that starts at or after ``lo``."""
    if not flags.size:
        return []
    edges = np.diff(np.concatenate(([False], flags, [False])).astype(np.int8))
    starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    return [int(end - start) for start, end in zip(starts, ends) if start >= lo]


def _pause_mask(session, replay, n: int, notes: list[str]) -> np.ndarray:
    """When the clinician had the session paused, from the log's own records."""
    mask = np.zeros(max(n, 0), dtype=bool)
    offsets = list(replay.chunk_sample_offsets)

    def position(after_chunk: int) -> int:
        chunk = after_chunk + 1                       # it takes effect before the next chunk
        if chunk <= 0:
            return 0
        return offsets[chunk] if chunk < len(offsets) else n

    frozen: int | None = None
    for event in session.events:
        record = event.record
        if record.get("type") != "session_state" or record.get("action") not in ("pause", "resume"):
            continue
        at = position(event.after_chunk)
        if record["action"] == "pause":
            frozen = at if frozen is None else frozen
        elif frozen is not None:
            mask[frozen:at] = True
            frozen = None
    if frozen is not None:
        mask[frozen:] = True
        notes.append("the log shows a pause that it never resumes; every sample from it on "
                     "counts as paused")
    return mask


def _audio_mask(frames, n: int, fs: float, notes: list[str]) -> np.ndarray:
    """When the recorder had the audio muted, from the 10 Hz telemetry."""
    mask = np.zeros(max(n, 0), dtype=bool)
    if not frames:
        notes.append("the log carries no telemetry, so nothing says when the audio was muted; "
                     "audio mute is reported as never")
        return mask
    notes.append(f"{len(frames)} telemetry frame(s) placed on refrain's clock by their position "
                 "in the log (the reconciliation reports the wall-clock drift); the audio mute is "
                 "therefore known to about one frame")
    rows = [(int(round(t * fs)), frame.get("audio_muted")) for frame, t in frames]
    if all(value is None for _, value in rows):
        notes.append("no telemetry frame reports audio_muted; audio mute is reported as never")
    for i, (at, value) in enumerate(rows):
        end = rows[i + 1][0] if i + 1 < len(rows) else n
        if value:
            mask[max(at, 0):min(end, n)] = True
    return mask


def _declared_warmup(ir_json, fs: float) -> int | None:
    """The warmup the protocol itself declares, in samples.

    refrain's rule: the first session phase is the warmup window when that phase is
    output-muted, and nothing is warmup otherwise. This is the replay's own view, and
    it needs no state the replay does not already expose.
    """
    phases = ((ir_json or {}).get("session") or {}).get("phases") or []
    if not phases:
        return None
    first = phases[0]
    if not first.get("output_muted"):
        return 0
    return int(round(float(first.get("duration_ms") or 0.0) / 1000.0 * fs))


def _logged_warmup(frames, n: int, fs: float) -> int | None:
    """Where the live telemetry says warmup ended, in samples, or None if it never says.

    Warmup ends where the first frame that is not in it begins. A log that never reports
    the warmup state describes a session that never had one -- and that is not the same as
    "warmup ended when telemetry started", which would quietly drop the first frames of
    every session that had no warmup at all. A log whose frames are *all* warmup describes
    a session that never left it, so the whole replay is warmup.
    """
    states = [(int(round(t * fs)), frame.get("state")) for frame, t in frames
              if frame.get("state") is not None]
    if not states:
        return None
    if not any(state == "warmup" for _, state in states):
        return 0
    running = [at for at, state in states if state != "warmup"]
    return min(running) if running else n


def _warmup_span(frames, ir_json, n: int, fs: float, notes: list[str]) -> dict:
    """The span excluded from every figure, and where that span was read from."""
    declared, logged = _declared_warmup(ir_json, fs), _logged_warmup(frames, n, fs)
    if logged is not None:
        end, source = logged, "the live telemetry's state field"
    elif declared is not None:
        end, source = declared, ("the protocol's own first phase, which is output_muted"
                                 if declared else "the protocol's own first phase, which is "
                                                  "not output_muted, so it has no warmup")
    else:
        end, source = 0, "nothing: neither the log nor a protocol IR says where warmup ended"
    reached, end = int(end), max(0, min(int(end), max(n, 0)))
    if end:
        notes.append(f"metrics are measured after warmup: samples 0 to {end} "
                     f"({end / fs:.1f} s) are excluded, read from {source}")
    else:
        notes.append(f"no warmup was excluded, according to {source}")
    if n and end >= n:
        notes.append(f"warmup covers the whole replay (it runs to {reached / fs:.1f} s of the "
                     f"{n / fs:.1f} s replayed), so there is no time after it to measure and "
                     "every figure is reported as unmeasured rather than as zero")
    if declared is not None and logged is not None and abs(declared - logged) > WARMUP_DISAGREE_S * fs:
        notes.append(f"the log says warmup ended at {logged / fs:.1f} s but the protocol declares "
                     f"{declared / fs:.1f} s; the log is what actually ran, so it was used, and "
                     "the difference is reported rather than resolved")
    return {"end_sample": end, "end_s": end / fs, "source": source,
            "logged_end_sample": logged, "declared_end_sample": declared}


def _condition_node(event) -> dict | None:
    """The condition expression a ``dwell(...)`` reward event tests."""
    if not isinstance(event, dict) or event.get("node") != "call":
        return None
    for arg in event["args"]:
        if arg.get("name") == "condition":
            return arg["value"]
    loose = [arg["value"] for arg in event["args"] if not arg.get("name")]
    return loose[0] if loose else None


def _condition_mask(replay, ir_json, n: int, notes: list[str]) -> np.ndarray | None:
    """When the protocol's own reward condition held, from its sub-condition taps.

    refrain taps each element of an ``all_of``/``any_of`` separately, so the
    protocol's own combination has to be read from the IR to put them back
    together: anding an ``any_of`` would report a condition that never held.
    """
    if ir_json is None:
        notes.append("no protocol IR was given, so the moment the reward condition became true "
                     "could not be read")
        return None
    if not replay.taps_per_chunk:
        notes.append("the replay stepped no chunk, so nothing says when the reward condition held")
        return None
    keys = sorted(k for k in replay.taps_per_chunk[0] if k.startswith("reward/condition["))
    if not keys:
        notes.append("the replay taps no reward condition, so the filter's own delay could not "
                     "be separated from the dwell")
        return None
    node = _condition_node((ir_json.get("reward") or {}).get("event"))
    callee = node.get("callee") if isinstance(node, dict) and node.get("node") == "call" else None
    parts = np.stack([_expand_tap(replay, k, n) > 0.5 for k in keys])
    if callee == "any_of":
        return np.any(parts, axis=0)
    if callee == "all_of" or len(keys) == 1:
        return np.all(parts, axis=0)
    notes.append(f"the reward condition is a {callee or 'bare'} expression with {len(keys)} tapped "
                 "parts, which this report cannot recombine; the filter's own delay is not reported")
    return None


@dataclass
class _Tracks:
    """One value per replayed sample for everything the metrics divide up."""
    n: int
    fs: float
    window: tuple[int, int]
    grace: int
    mutes: dict[str, np.ndarray]
    muted: np.ndarray
    unmuted: np.ndarray
    holds: np.ndarray
    muscle: np.ndarray
    onsets: np.ndarray
    episodes: list[tuple[int, int]] | None            # None when the session was not judged
    condition: np.ndarray | None = None
    continuous: np.ndarray | None = None
    strays: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=int))


def _episode_rows(tracks: _Tracks) -> list[dict]:
    """Per true episode: when feedback arrived, how late, and whether it was muted.

    ``condition_ms`` -- how long after the behaviour truly started the protocol's own
    condition first held, which is the filter's delay without the dwell -- is measured
    only for episodes that did get a reward, so that it and ``ding_ms`` describe the
    same episodes and the gap between them is the protocol's hold and nothing else.

    An episode whose live condition was *already* holding when the behaviour truly
    started gets ``condition_ms = None`` and ``condition_at_start = True``, not 0 ms.
    The real delay there is negative and unmeasurable from this side: the condition
    began before the episode did, so the search would have to look backwards into the
    previous episode. Recording it as zero would drag the median down and make the
    filter look faster than it is, and would break the decomposition the report prints
    (experienced latency = filter delay + hold). The count of such episodes is reported
    beside the latency instead.
    """
    rows = []
    for start, end in (tracks.episodes or []):
        stop = min(end + tracks.grace, tracks.n)
        after = int(np.searchsorted(tracks.onsets, start, "left"))
        in_episode = after < int(np.searchsorted(tracks.onsets, end, "left"))
        by_grace = after < int(np.searchsorted(tracks.onsets, stop, "left"))
        row = {
            "start": int(start), "end": int(end),
            "rewarded_in_episode": in_episode,
            "rewarded_by_grace": by_grace,
            "ding_ms": (int(tracks.onsets[after]) - start) / tracks.fs * 1000.0 if by_grace else None,
            "condition_ms": None,
            "condition_at_start": False,
            "rise_ms": None,
            "lost": {},
        }
        if by_grace and tracks.condition is not None:
            if tracks.condition[start]:
                row["condition_at_start"] = True          # began before the episode did
            else:
                held = np.flatnonzero(tracks.condition[start:stop])
                row["condition_ms"] = float(held[0]) / tracks.fs * 1000.0 if held.size else None
        if tracks.continuous is not None:
            risen = np.flatnonzero(tracks.continuous[start:stop] >= RISE_FRACTION)
            row["rise_ms"] = float(risen[0]) / tracks.fs * 1000.0 if risen.size else None
        row["lost"] = {source: bool(mask[start:stop].all()) for source, mask in tracks.mutes.items()}
        row["lost"]["any"] = bool(tracks.muted[start:stop].all())
        rows.append(row)
    return rows


def _span_metrics(tracks: _Tracks, rows: list[dict], lo: int, hi: int) -> dict:
    """The rate and share fields over one stretch of the replay.

    Exactly these fields are what the report repeats per phase, so anything that
    only makes sense for a whole session belongs in ``session_metrics``, not here.
    """
    width = max(hi - lo, 0)
    elapsed = width / tracks.fs
    unmuted = int(tracks.unmuted[lo:hi].sum())
    held = int((tracks.holds & tracks.unmuted)[lo:hi].sum())
    onsets = int(np.searchsorted(tracks.onsets, hi, "left") - np.searchsorted(tracks.onsets, lo, "left"))
    trusted = max(min(hi, tracks.window[1]) - max(lo, tracks.window[0]), 0)
    judged = tracks.episodes is not None
    mine = [r for r in rows if lo <= r["start"] < hi]
    strays = int(((tracks.strays >= lo) & (tracks.strays < hi)).sum())
    muscle = int(tracks.muscle[lo:hi].sum())
    muted = int(tracks.muted[lo:hi].sum())
    return {
        "elapsed_s": elapsed,
        "unmuted_s": unmuted / tracks.fs,
        "window_s": trusted / tracks.fs,
        # A span with no time in it -- a phase that is entirely warmup -- counted nothing,
        # which is not the same as having counted none, so even the counts are None there.
        "episodes": len(mine) if judged and width else None,
        "reward_onsets": onsets if width else None,
        "reward_share_of_unmuted": _share(held, unmuted),
        "rewards_per_min": _per_min(onsets, elapsed),
        "episodes_per_min": _per_min(len(mine), trusted / tracks.fs) if judged else None,
        "rewarded_in_episode": _share(sum(r["rewarded_in_episode"] for r in mine), len(mine))
                               if judged else None,
        "rewarded_by_end_plus_250": _share(sum(r["rewarded_by_grace"] for r in mine), len(mine))
                                    if judged else None,
        "stray_rewards_per_min": _per_min(strays, trusted / tracks.fs) if judged else None,
        "mute_share": {source: _share(int(mask[lo:hi].sum()), width)
                       for source, mask in tracks.mutes.items()},
        "muscle_time_muted": _share(int((tracks.muscle & tracks.muted)[lo:hi].sum()), muscle),
        "muted_without_muscle": _share(int((tracks.muted & ~tracks.muscle)[lo:hi].sum()), muted),
    }


def _phase_blocks(replay, ir_json, n: int) -> list[dict]:
    """The phases the replay went through, as sample spans with their declared names."""
    if n <= 0:
        return []
    declared = ((ir_json or {}).get("session") or {}).get("phases") or []
    index = _expand_tap(replay, "phase/index", n, default=-1.0).astype(int)
    edges = np.flatnonzero(np.diff(index)) + 1
    bounds = [0, *edges.tolist(), n]
    out = []
    for lo, hi in zip(bounds, bounds[1:]):
        i = int(index[lo])
        phase = declared[i] if 0 <= i < len(declared) else {}
        out.append({"index": i, "name": phase.get("name"), "block": phase.get("block"),
                    "start": int(lo), "end": int(hi)})
    return out


def _thresholds_per_block(replay, blocks: list[dict], notes: list[str]) -> dict:
    """Each threshold's start, end and drift in every block, from the replay's own streams."""
    if not replay.taps_per_chunk:
        return {}
    names = sorted(k.removeprefix("threshold/") for k in replay.taps_per_chunk[0]
                   if k.startswith("threshold/"))
    if not names:
        notes.append("this protocol declares no threshold, so there is no threshold drift to report")
        return {}
    out: dict[str, list[dict]] = {}
    for name in names:
        stream = replay.streams.get(name)
        if stream is None or not len(stream):
            notes.append(f"threshold {name!r} has no per-sample stream in the replay, so its drift "
                         "is not reported")
            continue
        rows = []
        for block in blocks:
            lo, hi = block["start"], min(block["end"], len(stream))
            if hi <= lo:
                continue
            start, end = float(stream[lo]), float(stream[hi - 1])
            rows.append({"block": block["name"], "index": block["index"], "start": start,
                         "end": end, "drift": end - start})
        out[name] = rows
    return out


def _derive_lag_r(replay, ir_json, fs: float, window: tuple[int, int],
                  notes: list[str]) -> dict[str, list[float]]:
    """Per envelope derive, how far the live filter lags an accurate one, and how well it tracks."""
    lo, hi = window
    if ir_json is None:
        return {}
    if hi - lo < MIN_LAG_S * fs:
        notes.append(f"the trusted window is {(hi - lo) / fs:.1f} s, under the {MIN_LAG_S:g} s "
                     "lag_and_r searches over, so no envelope lag was measured")
        return {}
    out: dict[str, list[float]] = {}
    for shape in envelopes(ir_json):
        name, band = shape["derive"], shape["band"]
        live, source = replay.streams.get(name), replay.streams.get(shape["source"])
        if live is None or source is None or len(live) < hi or len(source) < hi:
            notes.append(f"derive {name} has no replayed stream over the trusted window, so its "
                         "lag was not measured")
            continue
        if not 0 < band[0] < band[1] < fs / 2:
            notes.append(f"derive {name}'s {band[0]:g}-{band[1]:g} Hz band does not fit under "
                         f"{fs / 2:g} Hz, so no accurate envelope could be built to compare it with")
            continue
        if float(np.std(np.asarray(source[lo:hi], dtype=float))) < FLAT_STD:
            notes.append(f"derive {name} reads a stream that does not vary over the trusted "
                         "window, so its lag means nothing and is not reported")
            continue
        reference = reference_envelope(np.asarray(source, dtype=float), fs, band)
        lag, r = lag_and_r(np.asarray(live[lo:hi], dtype=float), reference[lo:hi], fs)
        out[name] = [float(lag), float(r)]
    return out


def _dings(session, replay, own: bool) -> dict:
    """The dings this replay's output channels fired, against what the recorder logged.

    ``decided`` counts the ding events the output channels emitted -- which is what the
    recorder logs a ``reward_event`` for, and what the audio layer was asked to play --
    not the pre-mute reward decision, which ``reward_onsets`` carries. The two differ
    whenever a mute was on, and the report prints both.
    """
    decided: dict[str, int] = {}
    for event in replay.events:
        if event["kind"] == "event":
            decided[event["channel"]] = decided.get(event["channel"], 0) + 1
    by_channel = {channel: {"decided": count, "logged": None, "rendered": None}
                  for channel, count in sorted(decided.items())}
    logged = rendered = None
    if own:
        counts: dict[str, int] = {}
        heard: dict[str, int] = {}
        for record in session.history:
            if record.get("type") != "reward_event" or record.get("kind") != "event":
                continue
            channel = record.get("channel")
            counts[channel] = counts.get(channel, 0) + 1
            if record.get("rendered_sound"):
                heard[channel] = heard.get(channel, 0) + 1
        logged, rendered = sum(counts.values()), sum(heard.values())
        for channel in sorted(set(counts) | set(by_channel)):
            row = by_channel.setdefault(channel, {"decided": 0, "logged": None, "rendered": None})
            row["logged"] = counts.get(channel, 0)
            row["rendered"] = heard.get(channel, 0)
    return {"decided": sum(decided.values()), "rendered": rendered, "logged": logged,
            "by_channel": by_channel}


def _review_contract(session, ir_json) -> tuple[dict, str] | tuple[None, None]:
    """The ratio and target a protocol declares for review, and where that was read."""
    meta = (ir_json or {}).get("meta") or {}

    def declared(key):
        node = meta.get(key)
        return node.get("value") if isinstance(node, dict) else node

    ratio, target = declared("review_ratio_stream"), declared("review_target_control")
    if ratio:
        return ({"ratio_stream": ratio, "target_control": target,
                 "literal_threshold": declared("review_literal_threshold")},
                "the protocol's own meta")
    contract = (session.meta.get("manifest") or {}).get("review_contract") or {}
    if contract.get("ratio_stream"):
        return ({"ratio_stream": contract.get("ratio_stream"),
                 "target_control": contract.get("target_control"),
                 "literal_threshold": contract.get("literal_threshold")},
                "the session manifest's review contract")
    return None, None


def _control_track(replay, name: str | None, n: int) -> np.ndarray | None:
    """A control's value over replay time, stepping where the replay applied a change."""
    changes = (replay.control_timeline or {}).get(name) if name else None
    if not changes:
        return None
    offsets = list(replay.chunk_sample_offsets)
    out = np.full(max(n, 0), float(changes[0][1]))
    for chunk, value in changes:
        if 0 <= chunk < len(offsets):
            out[offsets[chunk]:] = float(value)
    return out


def _ratio_view(session, replay, ir_json, fs: float, n: int, begin: int,
                notes: list[str]) -> dict | None:
    """The review ratio's trajectory, and how much of the time it was above target.

    The buckets run from the start of the recording, each labelled with its own seconds,
    because the trajectory through warmup is part of what a reviewer is looking at. The
    single share figure is measured after warmup like every other share.
    """
    contract, source = _review_contract(session, ir_json)
    if contract is None:
        return None
    name = contract["ratio_stream"]
    stream = replay.streams.get(name)
    if stream is None or len(stream) < n:
        notes.append(f"the protocol declares {name!r} as its review ratio, but the replay has no "
                     "such stream, so no ratio trajectory is reported")
        return None
    ratio = np.asarray(stream[:n], dtype=float)
    target = _control_track(replay, contract["target_control"], n)
    against = contract["target_control"]
    if target is None and contract["literal_threshold"] is not None:
        target = np.full(n, float(contract["literal_threshold"]))
        against = f"the declared literal threshold {contract['literal_threshold']:g}"
        notes.append(f"control {contract['target_control']!r} is not one this protocol declares, so "
                     "the ratio is scored against its declared literal threshold instead")
    if target is None:
        notes.append(f"neither control {contract['target_control']!r} nor a literal threshold is "
                     f"available, so {name!r} is reported without a target")
    above = None if target is None else ratio > target
    buckets = []
    for k in range(max(math.ceil(n / (BUCKET_S * fs)), 0)):
        lo = int(k * BUCKET_S * fs)
        hi = min(int((k + 1) * BUCKET_S * fs), n)
        if hi <= lo:
            continue
        buckets.append({"start_s": lo / fs, "end_s": hi / fs,
                        "ratio_median": float(np.median(ratio[lo:hi])),
                        "target_median": None if target is None else float(np.median(target[lo:hi])),
                        "share_above_target": None if above is None
                        else float(above[lo:hi].mean())})
    return {"ratio_stream": name, "target_control": contract["target_control"],
            "scored_against": against, "declared_in": source,
            "literal_threshold": contract["literal_threshold"],
            "share_above_target": (None if above is None or n <= begin
                                   else float(above[begin:].mean())),
            "share_measured_from_s": begin / fs,
            "buckets": buckets}


def _layered(session, ir_json) -> bool:
    style = (session.meta.get("audio") or {}).get("feedback_style")
    if style is None:
        node = ((ir_json or {}).get("meta") or {}).get("feedback_style")
        style = node.get("value") if isinstance(node, dict) else node
    return style == "layered_texture"


def _feedback_state_view(frames, begin: int, fs: float) -> dict | None:
    """Time in each logged feedback state, for a session whose audio is layered texture.

    Counted over the frames after warmup, like every other share here.
    """
    counts: dict[str, int] = {}
    after = [frame for frame, t in frames if int(round(t * fs)) >= begin]
    for frame in after:
        state = frame.get("feedback_state")
        if state is not None:
            counts[str(state)] = counts.get(str(state), 0) + 1
    reported = sum(counts.values())
    return {"frames": dict(sorted(counts.items())), "reported_frames": reported,
            "telemetry_frames": len(after), "measured_from_s": begin / fs,
            "share": {k: _share(v, reported) for k, v in sorted(counts.items())}}


def session_metrics(session, replay, truth, muscle, fs, *, ir_json=None, own: bool = True) -> dict:
    """Assemble every reported figure for one replay.

    ``truth`` is the ``TruthResult`` for this replay and ``muscle`` the muscle
    episodes found in the recording's own samples. ``ir_json`` is the replayed
    protocol's IR as JSON, which names its phases, its envelopes, the review view
    it declares, and the warmup to exclude when the log does not say; without it
    those sections are reported as unavailable. ``own`` is False for a comparison
    design, which never ran live, so nothing the recorder logged about rendering
    describes it.
    """
    notes: list[str] = []
    fs = float(fs)
    n = _span(replay)
    if n <= 0:
        notes.append("the replay stepped no samples, so nothing could be measured")

    # The telemetry's clock mapping (ruling R15) is wanted by three things below, so it
    # runs once; the reconciliation reports its drift, which is why the notes are dropped.
    frames = frame_positions(session, [])
    mutes = {"artifact": _expand_tap(replay, "muted", n) > 0.5,
             "phase": _expand_tap(replay, "phase/output_muted", n) > 0.5,
             "pause": _pause_mask(session, replay, n, notes),
             "audio": _audio_mask(frames, n, fs, notes)}
    muted = np.zeros(max(n, 0), dtype=bool)
    for mask in mutes.values():
        muted |= mask

    holds = replay.streams.get("reward.event.holds")
    if holds is None:
        notes.append("the replay has no reward hold stream, so the reward share of unmuted time "
                     "is reported as zero")
    continuous = replay.streams.get("reward.continuous")
    if continuous is None:
        notes.append("this protocol declares no continuous reward, so there is no rise time to report")

    window = (int(truth.window[0]), int(truth.window[1]))
    tracks = _Tracks(
        n=n, fs=fs, window=window, grace=int(round(GRACE_MS * fs / 1000.0)),
        mutes=mutes, muted=muted, unmuted=~muted,
        holds=(np.asarray(holds[:n], dtype=float) > 0.5 if holds is not None
               else np.zeros(max(n, 0), dtype=bool)),
        muscle=_mask_from_spans(muscle, n),
        onsets=_onsets(None if replay.streams.get("reward.event") is None
                       else replay.streams["reward.event"][:n]),
        episodes=[(int(a), int(b)) for a, b in truth.episodes] if truth.judged else None,
        condition=_condition_mask(replay, ir_json, n, notes),
        continuous=None if continuous is None else np.asarray(continuous[:n], dtype=float),
    )
    if not truth.judged:
        notes.append("the truth model could not judge this session, so every figure that counts "
                     "true target episodes is reported as unavailable, not as zero")

    rows = _episode_rows(tracks)
    covered = _mask_from_spans([(r["start"], min(r["end"] + tracks.grace, n)) for r in rows], n)
    in_window = (tracks.onsets >= window[0]) & (tracks.onsets < window[1])
    tracks.strays = tracks.onsets[in_window & ~covered[tracks.onsets]] if n else tracks.onsets

    warmup = _warmup_span(frames, ir_json, n, fs, notes)
    begin = warmup["end_sample"]
    blocks = _phase_blocks(replay, ir_json, n)
    judged = truth.judged
    # Every figure below is measured after warmup, so the episodes counted are the ones
    # that began after it. A phase entirely inside warmup gets an empty span, hence Nones.
    mine = [r for r in rows if r["start"] >= begin]
    rewarded = [r for r in mine if r["ding_ms"] is not None]
    out = dict(_span_metrics(tracks, rows, begin, n))
    out.update({
        "samples": n,
        "warmup": warmup,
        "judged": bool(judged),
        "window": list(window),
        "unreproducible": list(truth.unreproducible),
        "truth_notes": list(truth.notes),
        "episode_len_ms": _median_p90([(r["end"] - r["start"]) / fs * 1000.0 for r in mine]),
        "reward_hold_len_ms": _median_p90(
            [length / fs * 1000.0 for length in _run_lengths(tracks.holds, begin)]),
        "latency_from_episode_ms": _median_p90([r["ding_ms"] for r in rewarded]),
        "latency_from_condition_true_ms": _median_p90(
            [r["condition_ms"] for r in rewarded if r["condition_ms"] is not None]),
        "condition_already_true_at_start": (sum(r["condition_at_start"] for r in rewarded)
                                            if judged else None),
        "deadline_curve": {
            int(deadline): (_share(sum(r["ding_ms"] is not None and r["ding_ms"] <= deadline
                                       for r in mine), len(mine)) if judged else None)
            for deadline in DEADLINES_MS},
        "continuous_rise_ms": {"median": _median_p90(
            [r["rise_ms"] for r in mine if r["rise_ms"] is not None])["median"]},
        "episodes_lost_to_mute": ({source: sum(r["lost"][source] for r in mine)
                                   for source in (*MUTE_SOURCES, "any")} if judged
                                  else {source: None for source in (*MUTE_SOURCES, "any")}),
        # A threshold's value at a block's edges is not a rate warmup can dilute, so it is
        # reported over the whole block -- including a block that is all warmup, where the
        # seeding of an adaptive threshold is the interesting part.
        "thresholds_per_block": _thresholds_per_block(replay, blocks, notes),
        "derive_lag_r": _derive_lag_r(replay, ir_json, fs, (max(window[0], begin), window[1]),
                                      notes),
        "ding_decided_vs_rendered": _dings(session, replay, own),
        "per_phase": [{"index": b["index"], "name": b["name"], "block": b["block"],
                       "start_s": b["start"] / fs, "end_s": b["end"] / fs,
                       **_span_metrics(tracks, rows, max(b["start"], begin), b["end"])}
                      for b in blocks],
        "settings": {
            "muscle_band_hz": list(muscle_band(fs)) if muscle_band(fs) else None,
            "muscle_factor": MUSCLE_FACTOR,
            "muscle_window_ms": MUSCLE_WINDOW_MS,
            "grace_ms": GRACE_MS,
            "deadlines_ms": list(DEADLINES_MS),
            "continuous_rise_fraction": RISE_FRACTION,
            "bucket_s": BUCKET_S,
            "trusted_window_samples": list(window),
            "measured_from_sample": begin,
        },
        "notes": notes,
    })
    views = {}
    ratio = _ratio_view(session, replay, ir_json, fs, n, begin, notes)
    if ratio is not None:
        views["ratio"] = ratio
    if _layered(session, ir_json):
        views["feedback_state"] = _feedback_state_view(frames, begin, fs)
    out["protocol_views"] = views
    return out
