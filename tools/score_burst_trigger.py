"""Score a protocol's reward and chime against references that are not its own rule.

For each protocol, the engine replays every recording TWICE: once as recorded,
once as a phase-randomised surrogate with the identical power spectrum and no
burst structure. Two fire trains come out of each replay:

    chime   the engine's own `audio_chime` events
    onset   rising edges of `reward.event.holds`

and three kinds of answer are printed:

    reward time     share of scored samples with `reward.event.holds` true.
                    NOT time above threshold, and not what the trainee hears.
    real / noise    fires per minute on the recording over fires per minute on
                    its surrogate. A percentile bar is crossed equally often
                    on anything, so a percentile trigger sits near 1.0 here by
                    construction. Above 1 means the trigger responds to
                    structure that noise with this spectrum does not have.
    vs reference    recall, precision, chance and lift against each reference
                    in tools/burst_reference.py, at every match window. A fire
                    matches a burst (a, b) when a - w <= fire < b + w.
                    `in-burst` is the share of caught bursts whose first fire
                    arrived before the burst ENDED, at w = 0 on the far side -
                    the direct test of "lands while it is still happening".
                    `lag` is that first fire minus the burst's start, ms.

The session block is replaced by one long phase in a temporary copy, because
these recordings outlast `block1` and a rest phase mutes every output. Nothing
else in the protocol is touched. The first 130 s are not scored: a 2 min
percentile window is still filling.

    BURST_CORPUS=/path/to/ds003478 python tools/score_burst_trigger.py \\
        protocols/eeg/smr_burst.refrain protocols/eeg/smr_consolidated.refrain

    BURST_MIN_GAP_MS   apply a minimum gap between fires IN PYTHON (default 0:
                       score what the protocol itself declares)
    BURST_REFS         comma list (default ridge3,ridge5,amp2.5,circular)
    BURST_WINDOWS      comma list of ms (default 500,300,200,100)
    BURST_SUBST        NAME=value,... for a template's __NAME__ placeholders
    BURST_JOBS         recordings replayed in parallel (default 6)

Not run in CI: needs mne, statsmodels and a corpus that does not ship here.
"""
from __future__ import annotations

import os
import pathlib
import re
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import refrain  # noqa: E402
from burst_reference import FS, REFERENCES, bids_subjects, load_bids_rest, surrogate  # noqa: E402
from measure_envelopes import load_amp_profile, resolve  # noqa: E402
from session_report.replay import step_through  # noqa: E402

HEAD_S, TAIL_S = 130.0, 6.0
ONE_PHASE = '  session {\n    phases = [ phase { name = "run"; duration = 60 min } ]\n  }\n'


def one_phase(text: str) -> str:
    m = re.search(r"^  session \{\n.*?^  \}\n", text, flags=re.S | re.M)
    if m is None:
        raise SystemExit("no `session { }` block at two-space indent; cannot make a one-phase copy")
    return text[: m.start()] + ONE_PHASE + text[m.end():]


def min_gap(fires: np.ndarray, gap: int) -> np.ndarray:
    out, last = [], -gap - 1
    for i in fires:
        if i - last > gap:
            out.append(i)
            last = i
    return np.array(out, dtype=int)


def trains(res, lo: int, hi: int, gap: int) -> tuple[dict[str, np.ndarray], float]:
    holds = res.streams["reward.event.holds"] > 0.5
    onset = np.flatnonzero(holds[1:] & ~holds[:-1]) + 1
    chime = np.array(sorted(int(e["t_sample"]) for e in res.events if e["channel"] == "audio_chime"), dtype=int)
    out = {}
    for name, f in (("chime", chime), ("onset", onset)):
        f = f[(f >= lo) & (f < hi)]
        out[name] = min_gap(f, gap) if gap else f
    return out, float(holds[lo:hi].mean())


def score(fires: np.ndarray, events: list, lo: int, hi: int, w: int) -> dict:
    near = np.zeros(hi, dtype=bool)
    for a, b in events:
        near[max(0, a - w): b + w] = True
    events = [(a, b) for a, b in events if a >= lo and b < hi]
    caught = inside = 0
    lags = []
    for a, b in events:
        m = fires[(fires >= a - w) & (fires < b + w)]
        if len(m):
            caught += 1
            inside += int(m.min() < b)
            lags.append((int(m.min()) - a) / FS * 1000.0)
    return dict(fires=len(fires), hits=int(near[fires].sum()) if len(fires) else 0, events=len(events),
                caught=caught, inside=inside, lags=lags, chance=float(near[lo:hi].mean()))


def _prepare(protocols: list[str], subst: dict, work: str) -> dict:
    amp = load_amp_profile(os.path.join(os.path.dirname(refrain.__file__), "amp_profiles", "brainbit_flex.json"))
    irs = {}
    for p in protocols:
        text = one_phase(pathlib.Path(p).read_text())
        for k, v in subst.items():
            text = text.replace(f"__{k}__", v)
        tmp = os.path.join(work, os.path.basename(p))
        pathlib.Path(tmp).write_text(text)
        irs[p] = resolve(refrain.parse_file(tmp), amp)
        if float(irs[p].requires.sample_rate_chosen_hz) != FS:
            raise SystemExit(f"{p}: resolves to {irs[p].requires.sample_rate_chosen_hz} Hz, the references assume {FS}")
    return irs, tuple(sorted(amp.channel_names()))


def _one(job) -> dict:
    """One recording, every protocol, as recorded and as its surrogate."""
    root, sub, index, protocols, refs, windows, gap, subst, work = job
    irs, chans = _prepare(protocols, subst, work)
    (_, x, _), = list(load_bids_rest(root, only=sub))
    s = surrogate(x, np.random.default_rng(42 + index))  # per recording, so the order of work cannot change it
    lo, hi = int(HEAD_S * FS), len(x) - int(TAIL_S * FS)
    mins = (hi - lo) / FS / 60.0
    truth = {r: REFERENCES[r](x) for r in refs}
    cz = [c.upper() for c in chans].index("CZ")
    cn = int(round(0.05 * FS))
    out = {}
    for p in protocols:
        got, o = {}, {"rate": {}, "sc": {}}
        for tag, sig in (("real", x), ("noise", s)):
            X = np.zeros((len(sig), len(chans)))
            X[:, cz] = sig  # the BrainBit profile's reference is "device": the montage is the channel
            res = step_through(irs[p], FS, chans, (X[k: k + cn] for k in range(0, len(sig) - cn + 1, cn)),
                               skip_warmup=True, keep_streams={"reward.event.holds"})
            got[tag], rt = trains(res, lo, hi, gap)
            if tag == "real":
                o["rt"] = 100.0 * rt
        for name in ("chime", "onset"):
            o["rate"][name] = (len(got["real"][name]) / mins, len(got["noise"][name]) / mins)
            for r in refs:
                for w in windows:
                    o["sc"][(name, r, w)] = score(got["real"][name], truth[r], lo, hi, int(round(w / 1000.0 * FS)))
        out[p] = o
    return out


def main() -> int:
    from concurrent.futures import ProcessPoolExecutor

    protocols = sys.argv[1:]
    root = os.environ.get("BURST_CORPUS", "")
    if not protocols or not root:
        print(__doc__)
        return 2
    refs = os.environ.get("BURST_REFS", "ridge3,ridge5,amp2.5,circular").split(",")
    windows = [float(v) for v in os.environ.get("BURST_WINDOWS", "500,300,200,100").split(",")]
    gap = int(round(float(os.environ.get("BURST_MIN_GAP_MS", "0")) / 1000.0 * FS))
    subst = dict(kv.split("=", 1) for kv in os.environ.get("BURST_SUBST", "").split(",") if kv)
    work = tempfile.mkdtemp(prefix="burst-")
    _prepare(protocols, subst, work)  # fail on a bad protocol before any replay starts
    subs = bids_subjects(root)
    jobs = [(root, sub, i, protocols, refs, windows, gap, subst, work) for i, sub in enumerate(subs)]
    acc: dict = {p: {"rt": [], "rate": {"chime": [], "onset": []}, "sc": {}} for p in protocols}
    # The engine's rolling percentile is O(window) per sample, so one replay of
    # eight minutes takes most of a minute; recordings are independent.
    with ProcessPoolExecutor(max_workers=int(os.environ.get("BURST_JOBS", "6"))) as pool:
        for sub, got in zip(subs, pool.map(_one, jobs)):
            for p in protocols:
                acc[p]["rt"].append(got[p]["rt"])
                for name in ("chime", "onset"):
                    acc[p]["rate"][name].append(got[p]["rate"][name])
                for key, val in got[p]["sc"].items():
                    acc[p]["sc"].setdefault(key, []).append(val)
            print(f"  {sub} done", flush=True)
    n_rec = len(subs)

    print(f"\nn={n_rec} recordings, refrain {refrain.__version__}, "
          f"min gap applied in Python: {gap / FS * 1000:.0f} ms")
    for p in protocols:
        a = acc[p]
        print(f"\n=== {os.path.basename(p)} ===")
        print(f"reward time: median {np.median(a['rt']):.1f}%  (range {min(a['rt']):.1f}-{max(a['rt']):.1f})")
        for name in ("chime", "onset"):
            r = np.array(a["rate"][name])
            if r[:, 0].sum() == 0:
                print(f"{name}: none")
                continue
            print(f"{name}: {np.median(r[:, 0]):.1f}/min on the recording, {np.median(r[:, 1]):.1f}/min on its noise "
                  f"surrogate; pooled real/noise {r[:, 0].sum() / max(r[:, 1].sum(), 1e-9):.2f}, "
                  f"real > noise in {int((r[:, 0] > r[:, 1]).sum())}/{len(r)}")
            print(f"  {'reference':<10}{'window':>7}{'events':>8}{'recall':>8}{'precis.':>9}{'chance':>8}{'lift':>6}{'in-burst':>10}{'lag ms':>8}")
            for ref in refs:
                for w in windows:
                    rows = a["sc"][(name, ref, w)]
                    ev, ca = sum(x["events"] for x in rows), sum(x["caught"] for x in rows)
                    fi, hi_ = sum(x["fires"] for x in rows), sum(x["hits"] for x in rows)
                    ins = sum(x["inside"] for x in rows)
                    lags = [v for x in rows for v in x["lags"]]
                    ch = float(np.mean([x["chance"] for x in rows]))
                    pr = hi_ / fi if fi else float("nan")
                    print(f"  {ref:<10}{w:>6.0f} {ev:>8d}{100 * ca / max(ev, 1):>7.1f}%{100 * pr:>8.1f}%{100 * ch:>7.1f}%"
                          f"{pr / ch if ch else float('nan'):>6.2f}{100 * ins / max(ca, 1):>9.1f}%"
                          f"{np.median(lags) if lags else float('nan'):>8.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
