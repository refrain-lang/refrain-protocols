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


def _match_events(logged: list[dict], replayed: list[dict], tol, offsets: list[int] | None = None) -> int:
    """Dings matched one-to-one on channel, each within ``tol`` samples of its logged sample.

    ``tol`` is an int or a function of the logged sample. The distance of every match is
    appended to ``offsets`` when given.
    """
    tol_at = tol if callable(tol) else (lambda _t: tol)
    mine = _by_channel(replayed, lambda e: e["t_sample"])
    matched = 0
    for ch, times in _by_channel(logged, lambda r: r["_sample"]).items():
        pool = sorted(mine.get(ch, []))
        for t in sorted(times):
            i = bisect_left(pool, t)
            cands = [j for j in (i - 1, i) if 0 <= j < len(pool) and abs(pool[j] - t) <= tol_at(t)]
            if cands:
                j = min(cands, key=lambda j: abs(pool[j] - t))
                if offsets is not None:
                    offsets.append(abs(pool[j] - t))
                pool.pop(j)
                matched += 1
    return matched


def _offset_note(what: str, offsets: list[int], fs: float, verb: str = "matched") -> str:
    """How far apart the matches were: a 100 % at median 0 is not a 100 % at median 25."""
    if not offsets:
        return f"{what} {verb} at offset: no {verb} pairs, so no offsets to report"
    med, top = median(offsets), max(offsets)
    return (f"{what} {verb} at offset: median {med:g} sample(s) ({med / fs * 1000:.0f} ms), "
            f"maximum {top} sample(s) ({top / fs * 1000:.0f} ms), over {len(offsets)} match(es)")


def _close(logged: float, replayed: float) -> bool:
    # the log is the reference; the replay is what is under test
    return abs(logged - replayed) <= OUTPUT_REL_TOL * abs(logged) + 1e-12


def _output_scores(logged: list[dict], replayed: list[dict], tol, notes: list[str],
                   offsets: list[int] | None = None) -> tuple[int, int]:
    """(values agreeing, values compared).

    The denominator is the logged values, plus every value on a channel the replay produced and
    the log never mentions. Unlike dings, output values are not enumerated events: the recorder
    logs them on a coarse clock (about every 50 ms) while the replay produces them per chunk, so
    on a channel the log does track the replay is expected to hold more values than the log, and
    that thinning must not count against the score (dividing by max(logged, replayed) here scored
    a real session 31 % for exactly this reason). A channel the log never mentions is different:
    it is the sign that the protocol replayed is not the one that ran, and it counts as
    disagreement. Do not "simplify" either half.
    """
    tol_at = tol if callable(tol) else (lambda _t: tol)
    pool: dict[str, tuple[list[int], list[float]]] = {}
    for ch, rows in _by_channel(replayed, lambda e: (e["t_sample"], e["value"])).items():
        rows.sort()
        pool[ch] = ([t for t, _ in rows], [v for _, v in rows])
    n_logged: dict[str, int] = {}
    good, no_counterpart = 0, 0
    absent = set()
    for r in logged:
        n_logged[r["channel"]] = n_logged.get(r["channel"], 0) + 1
        times, values = pool.get(r["channel"], ([], []))
        if r["channel"] not in pool:
            absent.add(r["channel"])
        i = bisect_left(times, r["_sample"])
        cands = [j for j in (i - 1, i) if 0 <= j < len(times) and abs(times[j] - r["_sample"]) <= tol_at(r["_sample"])]
        if not cands:
            no_counterpart += 1
            continue
        j = min(cands, key=lambda j: abs(times[j] - r["_sample"]))
        if offsets is not None:
            offsets.append(abs(times[j] - r["_sample"]))
        good += _close(float(r["value"]), values[j])
    if absent:
        notes.append(f"output channel(s) in the log but never produced by the replay: {', '.join(sorted(absent))}")
    if no_counterpart:
        notes.append(f"{no_counterpart} logged output value(s) had no replay value within tolerance")
    total = len(logged)
    thinned, replay_only = 0, {}
    for ch, (times, _) in pool.items():
        if ch not in n_logged:
            replay_only[ch] = len(times)
        elif len(times) > n_logged[ch]:
            thinned += len(times) - n_logged[ch]
    if replay_only:
        total += sum(replay_only.values())
        notes.append("output channel(s) the replay produced with no logged counterpart (the log never recorded "
                     "them, so the protocol replayed may not be the one that ran); their values count against "
                     "the output score: " + ", ".join(f"{c} ({n} values)" for c, n in sorted(replay_only.items())))
    if thinned:
        notes.append(f"information only: the replay holds {thinned} more output value(s) than the log on channels "
                     "the log does track (the recorder logs values on a coarser clock); not counted as disagreement")
    return good, total


def frame_positions(session, notes: list[str]) -> list[tuple[dict, float]]:
    """(telemetry frame, its time on refrain's clock in seconds), mapped by file position.

    Telemetry t_s is wall-clock and drifts from refrain's sample clock; reward_event
    records in the same file carry refrain's clock, so a frame sits between its
    neighbouring reward_event records (by line number).
    """
    anchors = [(i, float(r["t_s"])) for i, r in enumerate(session.history)
               if r.get("type") == "reward_event" and isinstance(r.get("t_s"), (int, float))]
    idx = [i for i, _ in anchors]
    placed: list[tuple[int, dict, float | None]] = []     # (history index, frame, t if bracketed else None)
    for i, r in enumerate(session.history):
        if r.get("type") != "telemetry":
            continue
        p = bisect_left(idx, i) - 1            # last anchor before the frame
        q = bisect_right(idx, i)               # first anchor after it
        before = anchors[p] if p >= 0 else None
        after = anchors[q] if q < len(anchors) else None
        t = None
        if before and after:
            t = before[1] + (i - before[0]) / (after[0] - before[0]) * (after[1] - before[1])
        placed.append((i, r, t))

    def wall_of(r):
        w = r.get("t_s")
        return float(w) if isinstance(w, (int, float)) else None

    drifts = [(i, wall_of(r) - t) for i, r, t in placed if t is not None and wall_of(r) is not None]
    # Frames before the first anchor or after the last cannot be bracketed (a warmup phase that
    # mutes its output logs no reward_event records at all). Place them by their own wall clock
    # minus the drift measured at the nearest bracketed frame: still refrain's clock, and exact
    # if the drift is locally constant, which over a stretch of seconds it is.
    out, edge, unanchored = [], 0, 0
    for i, r, t in placed:
        if t is None:
            w = wall_of(r)
            if w is None:
                continue
            if drifts:
                nearest = drifts[0] if i < drifts[0][0] else drifts[-1]
                t, edge = w - nearest[1], edge + 1
            else:
                t, unanchored = w, unanchored + 1
        out.append((r, t))
    if edge:
        notes.append(f"{edge} telemetry frame(s) lay before the first or after the last reward_event record; "
                     "they were placed by their own wall-clock t_s corrected by the drift measured at the "
                     "nearest frame that could be bracketed")
    if unanchored:
        notes.append(f"{unanchored} telemetry frame(s) had no bracketing reward_event records; "
                     "their own wall-clock t_s was used uncorrected")
    if drifts:
        ds = [d for _, d in drifts]
        head, tail = median(ds[:50]), median(ds[-50:])
        notes.append(f"telemetry wall clock minus refrain clock: {head:+.2f} s at the start, "
                     f"{tail:+.2f} s at the end (largest {max(ds, key=abs):+.2f} s over {len(ds)} frames); "
                     "frames were placed by file position, not by their own t_s")
    return out


def _telemetry_scores(session, replay, replay_end: int, notes: list[str]) -> tuple[int, int]:
    """(frames agreeing, frames compared). A frame agrees only if every non-null field does.

    Frames past the end of the replay are not compared (they are reported as coverage).
    """
    offsets = replay.chunk_sample_offsets
    good = total = beyond = missing = 0
    per_field: dict[str, list[int]] = {}
    for frame, t in frame_positions(session, notes):
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

    Real recordings have no single chunk size (they run 1 to 32 samples), so each logged
    event is matched within the length of the chunk that contains it, found through
    ``replay.chunk_sample_offsets``. ``chunk_len`` is an upper bound on that tolerance
    (and the tolerance outright where the chunk cannot be located).
    """
    fs = session.fs
    chunk_offsets = list(replay.chunk_sample_offsets)

    def tol_at(sample: int) -> int:
        k = bisect_right(chunk_offsets, sample) - 1      # an event exactly on a chunk boundary takes the later chunk
        if 0 <= k < len(session.chunks):
            return max(1, min(chunk_len, len(session.chunks[k])))   # never 0, even for an empty chunk
        return chunk_len

    notes = [f"match tolerance: {chunk_len} sample(s) ({chunk_len / fs * 1000:.0f} ms at {fs:g} Hz) at most; "
             "each event is matched within the length of its own containing chunk, capped at that"]
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

    ding_offsets: list[int] = []
    out_offsets: list[int] = []
    ding_hits = _match_events(dings, replay_dings, tol_at, ding_offsets)
    # Denominator is the larger of logged and replayed dings, not just logged: dividing by
    # logged alone would let a replay that fires many spurious dings still score 1.0, the
    # silently-differing replay this check exists to catch. Do not "simplify" it.
    ding_total = max(len(dings), len(replay_dings))
    out_good, out_total = _output_scores(values, replay_values, tol_at, notes, out_offsets)
    tel_good, tel_total = _telemetry_scores(session, replay, replay_end, notes)
    events, outputs, telemetry = _ratio(ding_hits, ding_total), _ratio(out_good, out_total), _ratio(tel_good, tel_total)

    notes.append(f"dings: {ding_hits} matched, out of {ding_total} (the larger of {len(dings)} logged "
                 f"and {len(replay_dings)} replayed)")
    notes.append(f"output values: {out_good} within {OUTPUT_REL_TOL:.0%}, out of {out_total} "
                 "(logged values, plus any channel only the replay produced)")
    notes.append(_offset_note("dings", ding_offsets, fs))
    notes.append(_offset_note("output values", out_offsets, fs, "paired"))   # compared, not necessarily within 1 %
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
