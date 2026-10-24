"""Decide whether the replay did what the live session did.

Three comparisons, each against what the recorder logged:

* dings: ``reward_event`` records of kind "event" against the replay's events,
* output values: ``reward_event`` records of kind "value" against the replay's values,
* telemetry: the 10 Hz frames' booleans against the replay's per-chunk taps.

The replay is "reconciled" only if all three clear their thresholds. A failed
check is a result, not an error: ``reconcile`` always returns, and ``notes``
says which check fell short and by how much.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from statistics import median

EVENTS_MIN = 0.99          # share of dings matched within the tolerance
OUTPUTS_MIN = 0.99         # share of output values within OUTPUT_REL_TOL
TELEMETRY_MIN = 0.98       # share of telemetry booleans that agree
OUTPUT_REL_TOL = 0.01
COVERAGE_MARGIN_S = 1.0    # a replay may stop this many seconds short of the recording and still reconcile


@dataclass
class Reconciliation:
    """A score is None when its check had nothing to compare; that is not a pass.

    ``evaluated`` says which of "events", "outputs", "telemetry" were actually checked.
    ``reconciled`` means the replay covered the recording (to within COVERAGE_MARGIN_S), at least one check ran
    and none that ran fell short. ``coverage`` is the share of samples replayed.
    """
    events_matched: float | None
    outputs_within_1pct: float | None
    telemetry_agree: float | None
    reconciled: bool
    notes: list[str] = field(default_factory=list)
    evaluated: dict[str, bool] = field(default_factory=dict)
    coverage: float | None = None      # share of the recording's samples the replay stepped through


def _ratio(good: int, total: int) -> float | None:
    return good / total if total else None


def _by_channel(records, key) -> dict[str, list]:
    out: dict[str, list] = {}
    for r in records:
        out.setdefault(r["channel"], []).append(key(r))
    return out


def _match_events(logged: list[dict], replayed: list[dict], tol: int) -> int:
    """Dings matched one-to-one on channel, within ``tol`` samples."""
    mine = _by_channel(replayed, lambda e: e["t_sample"])
    matched = 0
    for ch, times in _by_channel(logged, lambda r: r["_sample"]).items():
        pool = sorted(mine.get(ch, []))
        for t in sorted(times):
            i = bisect_left(pool, t)
            cands = [j for j in (i - 1, i) if 0 <= j < len(pool) and abs(pool[j] - t) <= tol]
            if cands:
                pool.pop(min(cands, key=lambda j: abs(pool[j] - t)))
                matched += 1
    return matched


def _close(logged: float, replayed: float) -> bool:
    # the log is the reference; the replay is what is under test
    return abs(logged - replayed) <= OUTPUT_REL_TOL * abs(logged) + 1e-12


def _output_scores(logged: list[dict], replayed: list[dict], tol: int, notes: list[str]) -> tuple[int, int]:
    pool: dict[str, tuple[list[int], list[float]]] = {}
    for ch, rows in _by_channel(replayed, lambda e: (e["t_sample"], e["value"])).items():
        rows.sort()
        pool[ch] = ([t for t, _ in rows], [v for _, v in rows])
    good, no_counterpart = 0, 0
    absent = set()
    for r in logged:
        times, values = pool.get(r["channel"], ([], []))
        if r["channel"] not in pool:
            absent.add(r["channel"])
        i = bisect_left(times, r["_sample"])
        cands = [j for j in (i - 1, i) if 0 <= j < len(times) and abs(times[j] - r["_sample"]) <= tol]
        if not cands:
            no_counterpart += 1
            continue
        j = min(cands, key=lambda j: abs(times[j] - r["_sample"]))
        good += _close(float(r["value"]), values[j])
    if absent:
        notes.append(f"output channel(s) in the log but never produced by the replay: {', '.join(sorted(absent))}")
    if no_counterpart:
        notes.append(f"{no_counterpart} logged output value(s) had no replay value within {tol} samples")
    return good, len(logged)


def _frame_positions(session, notes: list[str]) -> list[tuple[dict, float]]:
    """(telemetry frame, its time on refrain's clock in seconds), mapped by file position.

    Telemetry t_s is wall-clock and drifts from refrain's sample clock; reward_event
    records in the same file carry refrain's clock, so a frame sits between its
    neighbouring reward_event records (by line number).
    """
    anchors = [(i, float(r["t_s"])) for i, r in enumerate(session.history)
               if r.get("type") == "reward_event" and isinstance(r.get("t_s"), (int, float))]
    idx = [i for i, _ in anchors]
    out, drifts, fallback = [], [], 0
    for i, r in enumerate(session.history):
        if r.get("type") != "telemetry":
            continue
        wall = r.get("t_s")
        p = bisect_left(idx, i) - 1            # last anchor before the frame
        q = bisect_right(idx, i)               # first anchor after it
        before = anchors[p] if p >= 0 else None
        after = anchors[q] if q < len(anchors) else None
        if before and after:
            frac = (i - before[0]) / (after[0] - before[0])
            t = before[1] + frac * (after[1] - before[1])
        elif before or after:
            t = (before or after)[1]
        elif isinstance(wall, (int, float)):
            t, fallback = float(wall), fallback + 1
        else:
            continue
        if (before or after) and isinstance(wall, (int, float)):
            drifts.append(float(wall) - t)
        out.append((r, t))
    if fallback:
        notes.append(f"{fallback} telemetry frame(s) had no reward_event record to place them; "
                     "their own wall-clock t_s was used")
    if drifts:
        head, tail = median(drifts[:50]), median(drifts[-50:])
        notes.append(f"telemetry wall clock minus refrain clock: {head:+.2f} s at the start, "
                     f"{tail:+.2f} s at the end (largest {max(drifts, key=abs):+.2f} s over {len(drifts)} frames); "
                     "frames were placed by file position, not by their own t_s")
    return out


def _telemetry_scores(session, replay, replay_end: int, notes: list[str]) -> tuple[int, int]:
    """(frames agreeing, frames compared). A frame agrees only if every non-null field does.

    Frames past the end of the replay are not compared (they are reported as coverage).
    """
    offsets = replay.chunk_sample_offsets
    good = total = beyond = missing = 0
    per_field: dict[str, list[int]] = {}
    for frame, t in _frame_positions(session, notes):
        fields = {k: frame.get(k) for k in ("reward_event_holds", "muted")}
        fields.update({f"inhibit/{k}": v for k, v in (frame.get("inhibits") or {}).items()})
        fields = {k: v for k, v in fields.items() if v is not None}     # null: not reported, not compared
        if not fields:
            continue
        sample = int(round(t * session.fs))
        if sample >= replay_end:
            beyond += 1
            continue
        tap = replay.taps_per_chunk[max(bisect_right(offsets, sample) - 1, 0)]
        agree = True
        for k, v in fields.items():
            key = {"reward_event_holds": "reward/event.holds", "muted": "muted"}.get(k, k)
            tally = per_field.setdefault(k, [0, 0])
            tally[1] += 1
            if key not in tap:
                missing += 1
                agree = False
            elif bool(v) == bool(tap[key]):
                tally[0] += 1
            else:
                agree = False
        total += 1
        good += agree
    if beyond:
        notes.append(f"{beyond} telemetry frame(s) lie past the end of the replay and were not compared")
    if missing:
        notes.append(f"{missing} logged telemetry value(s) have no matching tap in the replay and count as disagreements")
    if per_field:
        notes.append("telemetry by state, frames agreeing: " + "; ".join(
            f"{k} {g}/{n}" for k, (g, n) in sorted(per_field.items())))
    return good, total


def reconcile(session, replay, chunk_len: int) -> Reconciliation:
    """Compare ``replay`` with what ``session`` logged.

    ``chunk_len`` is the match tolerance in samples ("within one chunk"); real
    recordings have no single chunk size, so chunks are located through
    ``replay.chunk_sample_offsets``.
    """
    fs = session.fs
    notes = [f"match tolerance: {chunk_len} sample(s) ({chunk_len / fs * 1000:.0f} ms at {fs:g} Hz)"]
    # Only the part of the recording the replay stepped through can be compared. Records and
    # frames past its end are reported as coverage, never scored as disagreement.
    total_samples = sum(len(c) for c in session.chunks)
    n = len(replay.chunk_sample_offsets)
    replay_end = replay.chunk_sample_offsets[-1] + len(session.chunks[n - 1]) if n and len(session.chunks) >= n else 0
    coverage = replay_end / total_samples if total_samples else None
    logged_all = [dict(r, _sample=int(round(r["t_s"] * fs))) for r in session.history
                  if r.get("type") == "reward_event" and isinstance(r.get("t_s"), (int, float))]
    logged = [r for r in logged_all if r["_sample"] < replay_end]
    uncovered = len(logged_all) - len(logged)
    dings = [r for r in logged if r.get("kind") == "event"]
    values = [r for r in logged if r.get("kind") == "value" and isinstance(r.get("value"), (int, float))]
    replay_dings = [e for e in replay.events if e["kind"] == "event"]
    replay_values = [e for e in replay.events if e["kind"] == "value"]

    ding_hits = _match_events(dings, replay_dings, chunk_len)
    # Denominator is the larger of logged and replayed dings, not just logged: dividing by
    # logged alone would let a replay that fires many spurious dings still score 1.0, the
    # silently-differing replay this check exists to catch. Do not "simplify" it.
    ding_total = max(len(dings), len(replay_dings))
    out_good, out_total = _output_scores(values, replay_values, chunk_len, notes)
    tel_good, tel_total = _telemetry_scores(session, replay, replay_end, notes)
    events, outputs, telemetry = _ratio(ding_hits, ding_total), _ratio(out_good, out_total), _ratio(tel_good, tel_total)

    notes.append(f"dings: {ding_hits} matched, out of {ding_total} (the larger of {len(dings)} logged "
                 f"and {len(replay_dings)} replayed)")
    notes.append(f"output values: {out_good} within {OUTPUT_REL_TOL:.0%} of {out_total} logged")
    notes.append(f"telemetry: {tel_good} of {tel_total} frames agree on every state they report")
    scores = (("dings", events, EVENTS_MIN), ("output values", outputs, OUTPUTS_MIN),
              ("telemetry", telemetry, TELEMETRY_MIN))
    for name, got, need in scores:
        if got is None:
            notes.append(f"NOT EVALUATED {name}: nothing to compare, so this check says nothing either way")
        elif got < need:
            notes.append(f"FAILED {name}: {got:.1%} against a required {need:.0%} (short by {(need - got) * 100:.1f} points)")
    ran = [got is not None for _, got, _ in scores]
    if not any(ran):
        notes.append("no check could be evaluated, so the replay is not reported as reconciled")
    short = total_samples - replay_end
    complete = short <= COVERAGE_MARGIN_S * fs
    if uncovered:
        notes.append(f"{uncovered} logged reward record(s) lie past the end of the replayed samples and were not compared")
    if short > 0:
        gap = f"{short} sample(s) ({short / fs:.3f} s) short of the end, covering {coverage:.4%} of the recording"
        if complete:
            notes.append(f"coverage: the replay stopped {gap}, within the {COVERAGE_MARGIN_S:g} s margin")
        else:
            notes.append(f"FAILED coverage: the replay stopped {gap}, beyond the {COVERAGE_MARGIN_S:g} s margin. "
                         "The scores above describe only the covered part, so this is not a protocol "
                         "disagreement but an incomplete replay")
    passed = complete and any(ran) and all(got >= need for _, got, need in scores if got is not None)
    if replay.mismatches:
        notes.append("replay reported mismatches, so the protocol replayed may not be the one that ran: "
                     + "; ".join(replay.mismatches))
    if replay.chunks_unreplayed:
        notes.append(f"{replay.chunks_unreplayed} chunk(s) were never replayed because the phase plan ended first")
    return Reconciliation(events, outputs, telemetry, passed, notes,
                          dict(zip(("events", "outputs", "telemetry"), ran)), coverage)
