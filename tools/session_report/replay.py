"""Step recorded EEG through refrain's evaluator, optionally following the session's log.

``step_through`` is the shared stepping loop (also used by tools/measure_envelopes.py).
``replay_session`` wraps it with the rules that make the replay do what the live run did:
the clinician's control changes, phase changes and pauses are applied at the chunk
where the log shows them.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

import numpy as np

from refrain.eval_ import Evaluator, control_defaults

GAP_RESET_S = 0.5     # a longer hole between EEG chunks invalidates held feedback streaks


@dataclass
class ReplayResult:
    streams: dict[str, np.ndarray] = field(default_factory=dict)   # per sample, concatenated
    events: list[dict] = field(default_factory=list)               # {t_sample, channel, kind, value}
    taps_per_chunk: list[dict] = field(default_factory=list)
    applied: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    control_timeline: dict[str, list[tuple[int, float]]] = field(default_factory=dict)
    chunk_sample_offsets: list[int] = field(default_factory=list)  # index of each chunk's first sample
    # follow_log=True only. Facts that mean the protocol replayed is probably not the one
    # that ran (a logged control it does not declare; a phase the replay is far from).
    mismatches: list[str] = field(default_factory=list)
    # one per logged phase_change: {t_s, logged_index, replay_index, agrees}
    phase_checks: list[dict] = field(default_factory=list)
    # chunks never stepped because the evaluator went terminal (the phase plan ended first)
    chunks_unreplayed: int = 0


def step_through(ir, fs: float, channel_names: Sequence[str], chunks: Iterable[np.ndarray], *,
                 skip_warmup: bool,
                 on_before_chunk: Callable[[int, Evaluator], None] | None = None,
                 keep_streams: Iterable[str] | None = None) -> ReplayResult:
    """Push ``chunks`` (samples x channel_names) through a live evaluator.

    ``on_before_chunk(k, ev)`` runs before chunk ``k`` is stepped. ``keep_streams``
    names the per-sample streams to accumulate (default: all of them).
    """
    ev = Evaluator.live(ir, sample_rate_hz=fs, channel_names=tuple(channel_names), record_streams=True)
    ev.start(skip_warmup=skip_warmup)
    keep = None if keep_streams is None else list(keep_streams)
    parts: dict[str, list[np.ndarray]] = {k: [] for k in keep} if keep is not None else {}
    res = ReplayResult()
    pos = 0
    it = iter(chunks)
    for k, chunk in enumerate(it):
        if on_before_chunk is not None and ev.state != "stopped":
            on_before_chunk(k, ev)
        if ev.state == "stopped":
            # The phase plan ended before the recording did. Stepping now would raise;
            # record how much of the recording went unreplayed instead.
            res.chunks_unreplayed = 1 + sum(1 for _ in it)
            break
        res.chunk_sample_offsets.append(pos)
        pos += len(chunk)
        for e in ev.step_chunk(chunk):
            res.events.append({"t_sample": int(round(e.timestamp_s * fs)), "channel": e.channel,
                               "kind": e.kind, "value": float("nan") if e.value is None else float(e.value)})
        res.taps_per_chunk.append(dict(ev.last_taps()))
        streams = ev.last_streams()
        for key in (streams if keep is None else keep):
            if key in streams:
                parts.setdefault(key, []).append(np.asarray(streams[key], dtype=float))
    res.streams = {k: np.concatenate(v) for k, v in parts.items() if v}
    return res


def _is_layered_texture(session, ir) -> bool:
    style = (session.meta.get("audio") or {}).get("feedback_style")
    if style is None:
        node = getattr(getattr(ir, "meta", None), "fields", {}).get("feedback_style")
        style = getattr(node, "value", None)
    return style == "layered_texture"


def _control_record(rec: dict) -> tuple[str, float] | None:
    """(control name, value in refrain units) for a record that sets a control, else None."""
    t, kind = rec.get("type"), rec.get("kind")
    if t == "control_change" and rec.get("source") != "warmup_seed" and "engine_value" in rec:
        return rec["name"], float(rec["engine_value"])
    if t == "advice_event" and kind == "applied":
        # refrain's advisor emits applied(control=<name>, from=<old>, to=<new>) in engine units
        if rec.get("control") is not None and rec.get("to") is not None:
            return rec["control"], float(rec["to"])
    return None


def _starting_values(session, defaults: dict[str, float]) -> tuple[dict[str, float], list[dict]]:
    """Control values the session began with, where the log shows they differ from the IR default.

    The first logged change for a control records `previous_value` in display units;
    that record's own value <-> engine_value ratio converts it to refrain units.
    """
    start: dict[str, float] = {}
    skipped: list[dict] = []
    seen: set[str] = set()
    for te in session.events:
        r = te.record
        if r.get("type") != "control_change" or r.get("source") == "warmup_seed" or "engine_value" not in r:
            continue
        name = r["name"]
        if name in seen:
            continue
        seen.add(name)
        if name not in defaults or r.get("previous_value") is None:
            continue
        value, engine = float(r["value"]), float(r["engine_value"])
        if value == 0.0:
            skipped.append({"name": name, "reason": "cannot derive the units of a control logged at 0", "record": r})
            continue
        prev = float(r["previous_value"]) * engine / value
        if abs(prev - defaults[name]) > 1e-9 * max(1.0, abs(prev)):
            start[name] = prev
    return start, skipped


def replay_session(session, ir, channel_names: Sequence[str], *, follow_log: bool) -> ReplayResult:
    """Replay the session's EEG through ``ir``.

    ``follow_log=True`` (the session's own protocol) applies every logged control
    change, pause and phase change where it happened. ``follow_log=False`` (a
    comparison protocol) applies only the control changes the protocol declares and
    lets its own phase clock run.
    """
    chans = tuple(channel_names)
    index = {c.upper(): i for i, c in enumerate(session.channel_names)}
    cols = [index.get(c.upper()) for c in chans]
    matrices = [np.column_stack([c[:, j] if j is not None else np.zeros(len(c)) for j in cols])
                for c in session.chunks]

    mismatches: list[str] = []
    # control_defaults keys are "control/<name>"; the log and set_control use the bare name
    defaults = {k.removeprefix("control/"): v for k, v in control_defaults(ir).items()}
    layered = _is_layered_texture(session, ir)
    if follow_log and len(ir.session.phases) > 1 and not any(
            te.record.get("type") == "phase_change" for te in session.events):
        mismatches.append("the log has no phase_change record, so the replay holds its first phase "
                          "as long as it can; phase markers may have been lost")
    by_chunk: dict[int, list[dict]] = {}
    for te in session.events:
        by_chunk.setdefault(te.after_chunk, []).append(te.record)

    phase_checks: list[dict] = []
    applied: list[dict] = []
    skipped: list[dict] = []
    timeline: dict[str, list[tuple[int, float]]] = {n: [(0, v)] for n, v in defaults.items()}
    state = {"logged_phase": 0}

    def set_control(ev, k, rec, name, value):
        if name not in defaults:
            skipped.append({"name": name, "value": value, "after_chunk": k - 1,
                            "reason": "control not declared by this protocol", "record": rec})
            if follow_log:
                mismatches.append(f"the log changes control {name!r}, which this protocol does not declare "
                                  f"(t_s {rec.get('t_s')}); the protocol file replayed may not be the one that ran")
            return
        ev.set_control(name, value)
        timeline[name].append((k, value))
        applied.append({"name": name, "value": value, "after_chunk": k - 1, "status": "applied", "record": rec})
        if layered:
            ev.reset_held_outputs()

    def before(k, ev):
        if k == 0:
            start, bad = _starting_values(session, defaults)
            skipped.extend(bad)
            for name, value in start.items():
                ev.set_control(name, value)
                timeline[name][0] = (0, value)
                applied.append({"name": name, "value": value, "after_chunk": -1, "status": "initial"})
        starts = session.chunk_starts
        if k > 0 and len(starts) > k and len(session.chunks[k - 1]):
            hole = starts[k] - (starts[k - 1] + len(session.chunks[k - 1]) / session.fs)
            if hole > GAP_RESET_S:
                ev.reset_held_outputs()
        for rec in by_chunk.get(k - 1, []):
            t = rec.get("type")
            if (t == "control_change" and rec.get("source") != "warmup_seed" and "engine_value" not in rec):
                skipped.append({"name": rec.get("name"), "after_chunk": k - 1,
                                "reason": "control_change carries no engine_value", "record": rec})
                continue
            ctl = _control_record(rec)
            if ctl is not None:
                set_control(ev, k, rec, *ctl)
            elif t == "control_change" and rec.get("source") == "warmup_seed":
                if follow_log:
                    applied.append({"name": rec.get("name"), "value": rec.get("value"),
                                    "after_chunk": k - 1, "status": "compared", "record": rec})
            elif t == "session_state" and rec.get("action") in ("pause", "resume"):
                ev.set_clock_frozen(rec["action"] == "pause")
            elif t == "phase_change" and follow_log:
                target = int(rec["phase_index"])
                # Wall-clock drift (seconds over a session) moves a phase edge by seconds, so the
                # replay may sit one phase behind the log (its timer not yet fired) or one ahead
                # (an unholdable `timed` phase fired first). Only a gap of more than one phase
                # either way is a real disagreement.
                here = ev.current_phase()["index"]
                agrees = target - 1 <= here <= target + 1
                phase_checks.append({"t_s": rec.get("t_s"), "logged_index": target,
                                     "replay_index": here, "agrees": agrees})
                if not agrees:
                    mismatches.append(f"log enters phase {target} at t_s {rec.get('t_s')} but the replay "
                                      f"is in phase {here}")
                # never advance past the last phase: that stops the evaluator
                last = len(ir.session.phases) - 1
                state["logged_phase"] = min(target, last)
                while 0 <= ev.current_phase()["index"] < min(target, last):
                    ev.hold(False)
                    if not ev.advance_phase():
                        break
        if follow_log:
            # Don't let the replay's phase end before the log shows it ending.
            ph = ev.current_phase()
            if ph["index"] == state["logged_phase"] and ph["mode"] == "timed_with_floor" and not ph["held"]:
                ev.hold(True)

    res = step_through(ir, session.fs, chans, matrices, skip_warmup=False, on_before_chunk=before)
    res.applied, res.skipped, res.control_timeline = applied, skipped, timeline
    res.mismatches, res.phase_checks = mismatches, phase_checks
    return res
