"""Score a protocol's onset trigger against non-causal ground truth.

Answers one question: of the spindles that actually happened, how many did the
protocol's `audio_chime` commit to, how many of its commitments went nowhere,
and how far ahead of the published criterion did it fire?

    caught   per spindle: did any fire match it
    fizzled  per commitment: did it land in or near a real spindle
    lead     per spindle: how long before the 500 ms criterion would have fired

Ground truth is allowed to be non-causal -- a zero-phase envelope of the SAME
montaged input the protocol trains on, above that recording's 80th percentile,
held 500 ms with 200 ms tolerance. Both of those words are load-bearing:

  - *same montaged input*. The protocol trains a montage (a channel
    DIFFERENCE for `referential`), not a raw electrode. Scoring against a raw
    channel picked by name compares two different signals, which silently
    halved the catch rate until it was fixed.
  - *tolerance*. A dip-intolerant hold finds almost no spindles, so ground
    truth built on one is not a reference, it is an artifact of the criterion.

One replay scores BOTH triggers, which is the arrangement the design asked
for: `audio_chime` carries the onset trigger while `reward.event` still
carries the published criterion, so the ratio between them is the fizzle rate
recorded for free in every session.

Rough edges, named rather than hidden. The per-subject bar goes in as a
literal via a `__BAR__` placeholder in a template protocol, because a voltage
control cannot be bound at resolve time ("voltage controls are session
controls") -- in a real session that value comes from the control's `seed`
block during warmup. And the refractory is applied HERE, not in the protocol:
`dwell_rearm`'s `rearm` wants a continuous false interval, which an
oscillating condition never provides, so it is not a refractory. The
declarative one is `min_interval` on a `feedback` event entry, enforced by the
host renderer.

Not run in CI: needs `mne` and a replay corpus that does not ship with the
repository. Supersedes the ad-hoc script that produced the design doc's first
trigger table, which survived only because a scratchpad had not been cleared.

Usage: score_onset_trigger.py <template.refrain> [backend] [minutes]
       ONSET_K=0.8 sets the bar as a fraction of each recording's median peak.
"""

from __future__ import annotations

import os
import statistics
import sys
import tempfile

import pathlib

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import refrain  # noqa: E402
from measure_envelopes import (  # noqa: E402
    SKIP_HEAD_S,
    SKIP_TAIL_S,
    load_amp_profile,
    load_recordings,
    reference_envelope,
    resolve,
)
from session_report.replay import step_through  # noqa: E402

# Read from argv only when run as a script, so the module can be IMPORTED:
# tools/burst_reference.py reuses `ground_truth`, and the importing script's
# own arguments are not this one's.
_ARGV = sys.argv if __name__ == "__main__" else []
PROTOCOL = _ARGV[1] if len(_ARGV) > 1 else None
BACKEND = _ARGV[2] if len(_ARGV) > 2 else "python"
MINUTES = float(_ARGV[3]) if len(_ARGV) > 3 else 4.0

BAND = (12.0, 16.0)
CRITERION_MS = 500.0
GT_TOLERANCE_MS = 200.0
GT_PCT = 80.0
LOOKAHEAD_MS = 500.0
# Every figure in the design doc and the ledger was taken at 1 s. Override
# with ONSET_REFRACTORY_MS to ask what the trigger does unthrottled --
# which is the question of whether a refractory is a prerequisite or a
# refinement, since the host renderer does not enforce one today.
REFRACTORY_MS = float(os.environ.get("ONSET_REFRACTORY_MS", "1000"))
# Override with ONSET_CORPUS. The default is one developer's local path and
# is useless to anyone else; it stays only so the tool runs with no argument
# on the machine the measurements in the design doc were taken on.
CORPUS = os.environ.get("ONSET_CORPUS", "/Users/jcroall/tmp/file_io_corpus")
MIN_BAR_UV = 0.5
SP_DIR = os.environ.get("ONSET_WORKDIR", "")
TEMPLATE = ""


def runs(mask):
    d = np.diff(np.concatenate(([0], mask.view(np.int8), [0])))
    return list(zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)))


def tolerant_hold(cond, fs, duration_ms, tolerance_ms):
    need = max(1, int(round(duration_ms / 1000.0 * fs)))
    tol = int(round(tolerance_ms / 1000.0 * fs))
    holds = np.zeros(len(cond), dtype=bool)
    streak = gap = 0
    for i, c in enumerate(cond):
        if c:
            gap = 0
            streak += 1
        else:
            gap += 1
            if gap > tol:
                streak = 0
            else:
                streak += 1
        holds[i] = streak >= need
    return holds


def refract(mask, fs, ms):
    """Suppress fires within `ms` of the previous one -- a minimum GAP.

    Not the same as `dwell_rearm`'s `rearm`, which requires a continuous FALSE
    interval. The trigger condition is true 49% of samples and its longest
    not-rising run across a 224 s window is 784 ms, so a 1 s rearm never
    elapses: the first declared form fired three times in four minutes.
    """
    out = np.zeros_like(mask)
    gap = int(round(ms / 1000.0 * fs))
    last = -gap - 1
    for i in np.flatnonzero(mask):
        if i - last > gap:
            out[i] = True
            last = i
    return out


def ground_truth(ref, fs):
    thr = np.percentile(ref, GT_PCT)
    holds = tolerant_hold(ref > thr, fs, CRITERION_MS, GT_TOLERANCE_MS)
    spindles = []
    need = int(round(CRITERION_MS / 1000.0 * fs))
    for a, b in runs(holds):
        spindles.append((max(0, a - need), b))
    peaks = [float(ref[a:b].max()) for a, b in spindles if b > a]
    return spindles, (float(np.median(peaks)) if peaks else None)


def score(fires, spindles, fs):
    look = int(round(LOOKAHEAD_MS / 1000.0 * fs))
    need = int(round(CRITERION_MS / 1000.0 * fs))
    starts = np.array([a for a, _ in spindles])
    idxs = np.flatnonzero(fires)
    n = len(idxs)
    hits = 0
    for c in idxs:
        inside = any(a <= c < b for a, b in spindles)
        near = bool(len(starts)) and bool(np.any((starts >= c - look) & (starts <= c + look)))
        if inside or near:
            hits += 1
    caught, leads = 0, []
    for a, b in spindles:
        m = idxs[((idxs >= a - look) & (idxs <= a + look)) | ((idxs >= a) & (idxs < b))]
        if len(m):
            caught += 1
            leads.append((a + need - int(m.min())) / fs * 1000.0)
    return dict(
        n=n,
        caught=100.0 * caught / len(spindles) if spindles else None,
        fizzle=100.0 * (n - hits) / n if n else None,
        lead=float(statistics.median(leads)) if leads else None,
        per_min=None,
    )


def agg(rows, key):
    vals = [r[key] for r in rows if r.get(key) is not None]
    return statistics.median(vals) if vals else None


def fmt(v, suffix=""):
    return "   --" if v is None else f"{v:5.1f}{suffix}"


def main() -> int:
    global SP_DIR, TEMPLATE
    if PROTOCOL is None:
        print(__doc__)
        return 2
    SP_DIR = SP_DIR or tempfile.mkdtemp(prefix="onset-")
    os.makedirs(f"{SP_DIR}/variants", exist_ok=True)
    TEMPLATE = pathlib.Path(PROTOCOL).read_text()
    amp_path = os.path.join(os.path.dirname(refrain.__file__), "amp_profiles", "brainbit_flex.json")
    amp = load_amp_profile(amp_path)
    # The template still carries its placeholder, so this first resolve -- which
    # exists only to read the chosen sample rate -- uses a stand-in value.
    probe_file = f"{SP_DIR}/variants/_fs_probe.refrain"
    pathlib.Path(probe_file).write_text(TEMPLATE.replace("__BAR__", "4.5"))
    ir = resolve(refrain.parse_file(probe_file), amp)
    fs = float(ir.requires.sample_rate_chosen_hz)
    K = float(os.environ.get("ONSET_K", "0.8"))
    chans = tuple(sorted(amp.channel_names()))
    recordings = list(load_recordings(CORPUS, fs, MINUTES))

    grad_rows, crit_rows, spindle_counts, peaks, bars = [], [], [], [], []
    excluded: list[tuple[str, str]] = []
    for case, rec in recordings:
        n = len(next(iter(rec.values())))
        X = np.column_stack([rec.get(c.upper(), np.zeros(n)) for c in chans])
        lo0, hi0 = int(SKIP_HEAD_S * fs), n - int(SKIP_TAIL_S * fs)
        # Two passes: the first reads the montaged input the protocol actually
        # trains on, so ground truth and the trigger see the same signal.
        pre = step_through(ir, fs, chans,
                           (X[k : k + int(round(0.05 * fs))]
                            for k in range(0, n - int(round(0.05 * fs)) + 1,
                                           int(round(0.05 * fs)))),
                           skip_warmup=True, keep_streams={"raw"})
        src = pre.streams.get("raw")
        if src is None:
            print(f"  {case}: no montaged input stream; have {sorted(pre.streams)[:6]}", flush=True)
            continue
        ref0 = reference_envelope(np.asarray(src), fs, BAND)[lo0:hi0]
        sp0, peak0 = ground_truth(ref0, fs)
        if not sp0 or peak0 is None:
            continue
        bar = K * peak0
        # A degenerate recording produces a bar of ~0, which makes the level
        # condition always true and the trigger fire at whatever rate the
        # refractory allows. The predecessor harness excluded these by crest
        # factor and flat envelope and reported them separately; dropping that
        # check let one recording through with a 0.00 uV bar. Medians are
        # robust enough that it cannot distort a comparison, but it has no
        # business in the absolute figures.
        if bar < MIN_BAR_UV:
            excluded.append((case, f"degenerate bar {bar:.3f} uV"))
            continue
        # A voltage control cannot be bound at resolve time ("voltage controls
        # are session controls"), so the per-subject bar goes in as a literal.
        # In a real session this is what the control's `seed` block computes
        # from the subject's own signal during warmup.
        case_file = f"{SP_DIR}/variants/_case_{case}.refrain"
        pathlib.Path(case_file).write_text(TEMPLATE.replace("__BAR__", f"{bar:.3f}"))
        ir_case = resolve(refrain.parse_file(case_file), amp)
        bars.append(bar)
        cn = max(1, int(round(0.05 * fs)))
        keep = {"smr_envelope", "reward.event.holds"}
        res = step_through(
            ir_case, fs, chans,
            (X[k : k + cn] for k in range(0, n - cn + 1, cn)),
            skip_warmup=True, keep_streams=keep,
        )
        env = res.streams.get("smr_envelope")
        holds = res.streams.get("reward.event.holds")
        if env is None or holds is None:
            # Loudly, not silently: a missing stream skipped every recording
            # on the first run and the table printed "--" as if measured.
            print(f"  {case}: missing streams; have {sorted(res.streams)[:6]}", flush=True)
            continue

        lo, hi = int(SKIP_HEAD_S * fs), n - int(SKIP_TAIL_S * fs)
        src = X[:, 0] if X.shape[1] else None
        # Ground truth is allowed to be non-causal: zero-phase envelope of the
        # same site the protocol trains, on the same window.
        ref, spindles, peak = ref0, sp0, peak0
        if not spindles:
            print(f"  {case}: ground truth found no spindle", flush=True)
            continue
        spindle_counts.append(len(spindles) / (len(ref) / fs / 60.0))
        if peak is not None:
            peaks.append(peak)

        # The gradient trigger: the engine's own audio_chime events.
        fires = np.zeros(hi - lo, dtype=bool)
        for e in res.events:
            if e.get("channel") == "audio_chime":
                t = int(e["t_sample"]) - lo
                if 0 <= t < fires.size:
                    fires[t] = True
        fires = refract(fires, fs, REFRACTORY_MS)
        g = score(fires, spindles, fs)
        g["per_min"] = fires.sum() / (fires.size / fs / 60.0)
        grad_rows.append(g)

        # The published criterion, from the same replay: rising edges of holds.
        h = holds[lo:hi] > 0.5
        edges = np.zeros_like(h)
        edges[1:] = h[1:] & ~h[:-1]
        c = score(edges, spindles, fs)
        c["per_min"] = edges.sum() / (edges.size / fs / 60.0)
        crit_rows.append(c)

    for case_name, why in excluded:
        print(f"excluded {case_name}: {why}")
    if bars:
        print(f"per-subject bar: median {statistics.median(bars):.2f} uV, "
              f"range {min(bars):.2f}-{max(bars):.2f} uV (k={K:g} x each recording's median peak)")
    print(
        f"{os.path.basename(PROTOCOL)} on {BACKEND}, n={len(grad_rows)} recordings, "
        f"{MINUTES:g} min each"
    )
    print(
        f"ground truth: {statistics.median(spindle_counts):.1f} spindles/min, "
        f"median peak {statistics.median(peaks):.2f} uV"
        if spindle_counts else "ground truth: none found"
    )
    print(f"\n{'trigger':<26} {'caught':>8} {'fizzled':>9} {'lead':>10} {'fires/min':>10}")
    print("-" * 66)
    for label, rows in (("declared gradient", grad_rows), ("500 ms criterion", crit_rows)):
        print(
            f"{label:<26} {fmt(agg(rows, 'caught'), '%')} {fmt(agg(rows, 'fizzle'), '%')} "
            f"{fmt(agg(rows, 'lead'), ' ms')} {fmt(agg(rows, 'per_min'))}"
        )
    print("\nsection 12.5, hand-assembled, for comparison:")
    print(f"{'hand-set k=0.8':<26} {87.5:5.1f}% {38.7:5.1f}% {119:5.1f} ms")
    print(f"{'wait out 500 ms':<26} {60.7:5.1f}% {68.5:5.1f}% {296:5.1f} ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
