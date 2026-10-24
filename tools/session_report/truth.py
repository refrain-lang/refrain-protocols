"""When did the behaviour a protocol rewards actually happen?

A protocol's own envelopes are causal, laggy filters, so scoring its feedback
against them is circular: the feedback would always look on time. This module
rebuilds the protocol's reward condition offline with filters that are allowed to
look forwards in time -- same bands, same thresholds, same arithmetic -- and
reports the stretches where the target behaviour genuinely occurred. Task 6 then
measures how much of the feedback landed on those stretches, and how late.

What a derive's truth stream is:

* an envelope (any of the shapes ``tools/measure_envelopes.py`` recognises, whether
  its band is written as a pair of edges or as a centre and a width ratio) becomes
  ``reference_envelope`` of the stream it reads, over the same band. That is a
  zero-phase Butterworth plus a Hilbert magnitude, with none of the protocol's own
  smoothing: the question is when the band amplitude was there, not when the
  protocol's smoother caught up with it;
* binary arithmetic over other derives becomes the same arithmetic on their truth
  streams (``ratio(x)`` is refrain's dimensionless-number constructor, not a
  division; a division is a ``binop``);
* ``coherence`` becomes Welch magnitude-squared coherence over a window centred on
  each sample rather than trailing it;
* anything else -- a conditional, an autocorrelation, a filter shape not listed
  above -- is named as unreproducible and left out.

A reward condition reads four kinds of operand and all four have to be resolved
per sample, not collapsed to a constant: a derive (its truth stream), a threshold
(the replay's own per-sample threshold stream, adaptive or not), a control (its
value over replay time, because a clinician moves a target mid-session and the
truth has to follow), and a plain number.

Edge effects: ``reference_envelope`` filters forwards and backwards, so the first
and last samples of a recording are filter transient, not signal. Episodes are
therefore looked for only inside the same trusted window ``measure_envelopes``
scores on (``SKIP_HEAD_S`` in, ``SKIP_TAIL_S`` from the end). ``TruthResult.window``
says which samples that was, so a report can print what it covers, and an episode
that reaches a window edge is reported clipped to it rather than extrapolated.
"""
from __future__ import annotations

import operator
from dataclasses import dataclass, field

import numpy as np
import scipy.signal as ss

from measure_envelopes import SKIP_HEAD_S, SKIP_TAIL_S, envelopes, reference_envelope

# how refrain's own condition primitives compare a signal with a threshold
COMPARISONS = {"above": operator.gt, "at_or_above": operator.ge, "below": operator.lt}
ARITHMETIC = {"+": operator.add, "-": operator.sub, "*": operator.mul, "/": operator.truediv}
# argument order each condition primitive declares, so a named and a positional IR read alike
CONDITION_PARAMS = {"above": ("signal", "threshold"), "at_or_above": ("signal", "threshold"),
                    "below": ("signal", "threshold"), "inside": ("signal", "low", "high")}
SECONDS_PER_UNIT = {"ms": 1e-3, "s": 1.0, "min": 60.0}


@dataclass
class TruthResult:
    """Where the target behaviour genuinely occurred, and whether that could be decided.

    ``episodes`` are half-open ``[start_sample, end_sample)`` spans: every sample on
    which the reward condition held, in runs that lasted at least the dwell. An
    episode starts where the behaviour started, not where the dwell was satisfied --
    the dwell decides which runs count, not when they began.

    ``judged`` is False only when the reward condition itself reads something the
    truth model cannot reproduce. A protocol with unreproducible derives elsewhere is
    still judged; those derives are named in ``unreproducible`` either way.

    ``window`` is the half-open sample range the zero-phase filters can be trusted on.
    """
    episodes: list[tuple[int, int]]
    judged: bool
    unreproducible: list[str]
    window: tuple[int, int] = (0, 0)
    notes: list[str] = field(default_factory=list)


def _bare(target: str) -> str:
    return target.split("/", 1)[-1]


def _describe(node: dict) -> str:
    """What to call an IR node that could not be reproduced."""
    kind = node.get("node", "?")
    return f"{kind} {node['callee']}" if kind == "call" else str(node.get("target") or kind)


def _by_position(node: dict, names: tuple[str, ...]) -> list[dict] | None:
    """A call's argument values in declared order, whether the IR wrote them named or not."""
    named = {a["name"]: a["value"] for a in node["args"] if a.get("name")}
    loose = [a["value"] for a in node["args"] if not a.get("name")]
    out = []
    for name in names:
        if name in named:
            out.append(named[name])
        elif loose:
            out.append(loose.pop(0))
        else:
            return None
    return out


def _number(node: dict) -> float | None:
    """A compile-time number: a literal, or the default the IR baked into a reference.

    Unlike ``measure_envelopes._num`` this answers None rather than raising, because a
    band edge the truth model cannot read makes one derive unreproducible -- which the
    report says out loud -- and must not take the whole report down with it.
    """
    for key in ("value", "default"):
        if isinstance(node.get(key), (int, float)):
            return float(node[key])
    return None


def _span(replay) -> int:
    """How many samples every one of the replay's streams covers."""
    return min((len(v) for v in replay.streams.values()), default=0)


def _runs(flags: np.ndarray) -> list[tuple[int, int]]:
    """Half-open [start, end) spans of consecutive True samples."""
    edges = np.diff(flags.astype(np.int8))
    starts = [int(i) + 1 for i in np.flatnonzero(edges == 1)]
    ends = [int(i) + 1 for i in np.flatnonzero(edges == -1)]
    if flags.size and flags[0]:
        starts.insert(0, 0)
    if flags.size and flags[-1]:
        ends.append(int(flags.size))
    return list(zip(starts, ends))


class _Operands:
    """Per-sample values for the things an IR expression can read.

    Every lookup returns an array of ``n`` samples or None, and a None is recorded in
    ``missing`` under the name that could not be resolved, so a caller can say what it
    could not reproduce instead of substituting a plausible number for it.
    """

    def __init__(self, replay, truth: dict[str, np.ndarray], n: int, fs: float):
        self.replay, self.truth, self.n, self.fs = replay, truth, n, fs
        self.missing: list[str] = []

    def _fail(self, name: str) -> None:
        if name not in self.missing:
            self.missing.append(name)
        return None

    def _fit(self, stream, name: str) -> np.ndarray | None:
        if stream is None:
            return self._fail(name)
        values = np.asarray(stream, dtype=float)
        if values.shape[0] < self.n:
            return self._fail(f"{name} (covers {values.shape[0]} of {self.n} samples)")
        return values[:self.n]

    def control(self, name: str, default) -> np.ndarray | None:
        """A control's value over replay time, stepping where the replay applied a change."""
        changes = self.replay.control_timeline.get(name) or []
        if not changes and default is None:
            return self._fail(f"control/{name}")
        out = np.full(self.n, float(default if default is not None else changes[0][1]))
        offsets = self.replay.chunk_sample_offsets
        for chunk, value in changes:
            if chunk < len(offsets):      # a change in a chunk the replay never reached did nothing
                out[offsets[chunk]:] = float(value)
        return out

    def value(self, node: dict) -> np.ndarray | None:
        kind = node.get("node")
        if kind == "number":
            return np.full(self.n, float(node["value"]))
        if kind == "control_ref":
            return self.control(_bare(node["target"]), node.get("default"))
        if kind == "threshold_ref":
            return self._fit(self.replay.streams.get(_bare(node["target"])), node["target"])
        if kind == "stream_ref":
            name = _bare(node["target"])
            source = self.truth if node["target"].startswith("derive/") else self.replay.streams
            return self._fit(source.get(name), node["target"])
        if kind == "binop" and node.get("op") in ARITHMETIC:
            left, right = self.value(node["left"]), self.value(node["right"])
            return None if left is None or right is None else ARITHMETIC[node["op"]](left, right)
        if kind == "call" and node["callee"] == "ratio" and len(node["args"]) == 1:
            return self.value(node["args"][0]["value"])     # dimensionless-number constructor
        return self._fail(_describe(node))

    def condition(self, node: dict) -> np.ndarray | None:
        """A reward condition as a boolean per sample."""
        if node.get("node") != "call":
            return self._fail(_describe(node))
        callee = node["callee"]
        if callee in CONDITION_PARAMS:
            nodes = _by_position(node, CONDITION_PARAMS[callee])
            if nodes is None:
                return self._fail(f"{callee} (missing arguments)")
            parts = [self.value(v) for v in nodes]
            if any(p is None for p in parts):
                return None
            if callee == "inside":
                signal, low, high = parts
                return (signal >= low) & (signal <= high)
            return COMPARISONS[callee](parts[0], parts[1])
        if callee in ("all_of", "any_of"):
            parts = [self.condition(c) for c in _condition_list(node)]
            if not parts:
                return self._fail(f"{callee} (no conditions)")
            if any(part is None for part in parts):
                return None
            stacked = np.stack(parts)
            return np.all(stacked, axis=0) if callee == "all_of" else np.any(stacked, axis=0)
        return self._fail(f"condition {callee}")


def _condition_list(node: dict) -> list[dict]:
    """The conditions an all_of/any_of call combines, written as an array or loose."""
    values = [a["value"] for a in node["args"]]
    if len(values) == 1 and values[0].get("node") in ("array", "tuple"):
        return values[0]["elements"]
    return values


def _source_stream(name: str, replay, truth: dict[str, np.ndarray], n: int) -> np.ndarray | None:
    """The truth stream a derive reads: another derive's truth, else the replay's own input."""
    for found in (truth.get(name), replay.streams.get(name)):
        if found is not None and len(found) >= n:
            return np.asarray(found, dtype=float)[:n]
    return None


def _centred_coherence(a: np.ndarray, b: np.ndarray, fs: float, band: tuple[float, float],
                       window: int, nperseg: int, noverlap: int) -> np.ndarray | None:
    """Band-averaged magnitude-squared coherence over a window centred on each sample.

    The live primitive runs Welch over the window *trailing* each chunk; centring the
    window reports a coherent stretch where it happened rather than a window later.
    Welch resolves no faster than one segment step, so the estimate is computed every
    ``nperseg - noverlap`` samples and interpolated onto the sample grid; the leading
    and trailing half-window hold the nearest estimate and sit inside the edge guard.
    """
    n = len(a)
    half = window // 2
    if n < window or nperseg < 1:
        return None
    hop = max(1, nperseg - noverlap)
    centres = np.arange(half, n - window + half + 1, hop)
    if centres[-1] != n - window + half:
        centres = np.append(centres, n - window + half)
    keep = None
    values = []
    for centre in centres:
        start = int(centre) - half
        freqs, msc = ss.coherence(a[start:start + window], b[start:start + window], fs=fs,
                                  nperseg=nperseg, noverlap=noverlap)
        if keep is None:
            keep = (freqs >= band[0]) & (freqs <= band[1])
            if not keep.any():
                return None
        values.append(float(np.mean(msc[keep])))
    return np.interp(np.arange(n), centres, values)


def _truth_coherence(node: dict, replay, truth: dict[str, np.ndarray], n: int,
                     fs: float) -> np.ndarray | None:
    nodes = _by_position(node, ("input_a", "input_b", "band", "window"))
    coeffs = node.get("coeffs") or {}
    if nodes is None or not coeffs.get("window_samples") or not coeffs.get("nperseg"):
        return None
    a_node, b_node, band_node, _ = nodes
    if a_node.get("node") != "stream_ref" or b_node.get("node") != "stream_ref":
        return None
    a = _source_stream(_bare(a_node["target"]), replay, truth, n)
    b = _source_stream(_bare(b_node["target"]), replay, truth, n)
    if a is None or b is None:
        return None
    edges = [_number(e) for e in band_node.get("elements", ())]
    if len(edges) != 2 or None in edges:
        return None
    return _centred_coherence(a, b, fs, (edges[0], edges[1]), int(coeffs["window_samples"]),
                              int(coeffs["nperseg"]), int(coeffs.get("noverlap", 0)))


def _derive_order(ir_json: dict) -> list[str]:
    """Derive names in dependency order, so a derive sees the truth of what it reads."""
    order = [_bare(k) for k in ir_json.get("topological_order", ()) if k.startswith("derive/")]
    known = [name for name in order if name in ir_json["derives"]]
    return known + [name for name in ir_json["derives"] if name not in known]


def truth_streams(ir_json: dict, replay) -> tuple[dict[str, np.ndarray], list[str]]:
    """The truth value per derive, plus the names of the derives it cannot reproduce."""
    fs = float(ir_json["sample_rate_hz"])
    n = _span(replay)
    truth: dict[str, np.ndarray] = {}
    unreproducible: list[str] = []
    shapes = {e["derive"]: e for e in envelopes(ir_json)}
    arithmetic = _Operands(replay, truth, n, fs)
    for name in _derive_order(ir_json):
        node = ir_json["derives"][name]["expression"]
        shape = shapes.get(name)
        if shape is not None:
            source = _source_stream(shape["source"], replay, truth, n)
            found = None if source is None else reference_envelope(source, fs, shape["band"])
        elif node.get("node") == "call" and node["callee"] == "coherence":
            found = _truth_coherence(node, replay, truth, n, fs)
        else:
            found = arithmetic.value(node)
        if found is None:
            unreproducible.append(name)
        else:
            truth[name] = found
    return truth, unreproducible


def _dwell_samples(event: dict, fs: float) -> int | None:
    """How long the condition must hold, in samples, as the live evaluator counted it."""
    baked = (event.get("coeffs") or {}).get("dwell_samples")
    if baked:
        return int(baked)
    duration = _by_position(event, ("condition", "duration"))
    node = None if duration is None else duration[1]
    if node is None or node.get("node") != "number":
        return None
    scale = SECONDS_PER_UNIT.get(node.get("unit"))
    return max(1, int(round(float(node["value"]) * scale * fs))) if scale else None


def true_episodes(ir_json: dict, truth: dict[str, np.ndarray], replay, fs: float) -> TruthResult:
    """Find the stretches where the protocol's reward condition genuinely held."""
    n = _span(replay)
    head = min(int(round(SKIP_HEAD_S * fs)), n)
    window = (head, max(n - int(round(SKIP_TAIL_S * fs)), head))
    notes = [f"zero-phase filters are unreliable at a recording's edges, so episodes are looked for "
             f"only from {SKIP_HEAD_S:g} s in to {SKIP_TAIL_S:g} s before the end: "
             f"samples {window[0]} to {window[1]} of {n}"]
    if window[0] == window[1]:
        notes.append(f"the replay covers {n / fs:.1f} s, too short to leave any trustworthy window, "
                     "so no episode can be found in it")
    unreproducible = [name for name in _derive_order(ir_json) if name not in truth]
    if unreproducible:
        notes.append("derives the truth model cannot reproduce: " + ", ".join(unreproducible))

    event = (ir_json.get("reward") or {}).get("event")
    args = None if event is None or event.get("node") != "call" else _by_position(event, ("condition",))
    if args is None:
        notes.append("this protocol has no reward event with a condition, so there is nothing to judge")
        return TruthResult([], False, unreproducible, window, notes)
    dwell = _dwell_samples(event, fs)
    if dwell is None:
        notes.append(f"the reward event's {event['callee']} does not say how long its condition "
                     "must hold, so episodes cannot be bounded")
        return TruthResult([], False, unreproducible, window, notes)

    operands = _Operands(replay, truth, n, fs)
    holding = operands.condition(args[0])
    if holding is None:
        notes.append("the reward condition reads what the truth model cannot reproduce ("
                     + ", ".join(operands.missing) + "), so this session cannot be judged")
        return TruthResult([], False, unreproducible, window, notes)

    trusted = np.zeros(n, dtype=bool)
    trusted[window[0]:window[1]] = holding[window[0]:window[1]]
    episodes = [span for span in _runs(trusted) if span[1] - span[0] >= dwell]
    notes.append(f"{len(episodes)} episode(s) where the reward condition held for at least "
                 f"{dwell} sample(s) ({dwell / fs * 1000:.0f} ms), covering "
                 f"{sum(b - a for a, b in episodes) / fs:.1f} s")
    return TruthResult(episodes, True, unreproducible, window, notes)
