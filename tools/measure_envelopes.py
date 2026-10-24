"""Measure every band envelope in a protocol file: delay and accuracy on real EEG.

For each `derive` whose pipeline is an envelope (`bandpass -> hilbert ->
magnitude -> smooth` or `band_envelope`), this runs the protocol file itself
through refrain's evaluator on recorded EEG and scores the derive's output
against a zero-phase reference envelope (order-4 Butterworth, filtfilt,
Hilbert magnitude) of the *same input stream the derive reads*. Two numbers
per envelope per recording:

  lag  -- the shift that best aligns the live envelope with the reference, ms
  r    -- the correlation at that shift

and, per protocol per recording, how the reward behaves -- onsets per minute
and the share of time a reward is held -- because a change that leaves every
envelope accurate can still change how often the protocol rewards.

`held_pct` counts every sample on which `reward.event.holds` is true,
including time an inhibit or a phase has muted the output. It is a property
of the reward rule, not of what the trainee hears.

Run it on a file before and after a change to get a before/after pair that
differs only in the change. It measures the protocol as shipped -- resolved
against an amp profile, control defaults applied, warm start and all -- not a
re-implementation of the filter.

    python tools/measure_envelopes.py protocols/eeg/smr.refrain \\
        --corpus ~/tmp/file_io_corpus --json out.json

Needs `mne` (EDF reading) and `scipy` on top of refrain. Not run in CI: the
corpus is clinical EEG that does not ship with this repo.

Recordings are mapped to the amp's channels BY NAME. A recording that lacks a
channel the protocol's montage reads is skipped, never filled with noise: an
earlier measurement of this kind evaluated synthetic noise for every recording
because it mapped by position, and produced plausible-looking numbers.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import warnings
from pathlib import Path

import numpy as np
import scipy.signal as ss

import refrain
from refrain.amp_profile import load_amp_profile
from refrain.ir_json import ir_to_json_obj
from refrain.resolver import resolve
from session_report.replay import step_through

ENVELOPE_SHAPES = {
    ("bandpass", "hilbert", "magnitude", "smooth"): "four-stage",
    ("band_envelope",): "band_envelope",
    ("band_envelope", "smooth"): "band_env+smooth",
}
SKIP_HEAD_S = 10.0  # filter start-up, excluded from scoring
SKIP_TAIL_S = 6.0  # the zero-phase reference's own edge effect
MAX_LAG_MS = 2000.0


def _chain(expr: dict) -> tuple[list[str], dict, dict | None]:
    """Callee names innermost-first, the call naming the band, and the source ref."""
    names, band_call, node = [], None, expr
    while node.get("node") == "call":
        names.append(node["callee"])
        named = {a.get("name") for a in node["args"]}
        if "band" in named or {"center", "bandwidth"} <= named:
            band_call = node
        node = node["args"][0]["value"]
    return names[::-1], band_call, (node if node.get("node") == "stream_ref" else None)


def _num(v: dict) -> float:
    return float(v["value"] if v["node"] == "number" else v["default"])


def _band(args: dict) -> tuple[float, float] | None:
    """(low, high) edge in Hz, from `band: (lo, hi)` or from `center` + `bandwidth: ratio(r)`.

    `bandwidth` in any other form is refused rather than guessed at: a bandwidth given
    in Hz would mean center +/- w/2, a different band from the same two numbers.
    """
    if "band" in args:
        lo, hi = (_num(e) for e in args["band"]["elements"])
        return lo, hi
    width = args["bandwidth"]
    if width.get("node") != "call" or width["callee"] != "ratio" or len(width["args"]) != 1:
        return None
    root = float(np.sqrt(_num(width["args"][0]["value"])))
    center = _num(args["center"])
    return center / root, center * root


def envelopes(ir_json: dict) -> list[dict]:
    out = []
    for name, d in ir_json["derives"].items():
        names, call, src = _chain(d["expression"])
        shape = ENVELOPE_SHAPES.get(tuple(names))
        if shape is None or call is None or src is None:
            continue
        args = {a["name"]: a["value"] for a in call["args"] if a["name"]}
        band = _band(args)
        if band is None:
            continue
        latency = _num(args["latency"]) if "latency" in args else None
        out.append(dict(derive=name, shape=shape, band=band, latency_ms=latency,
                        source=src["target"].split("/", 1)[-1]))
    return out


def montage_channels(ir_json: dict, known: set[str]) -> set[str]:
    found: set[str] = set()

    def walk(v):
        if isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
        elif isinstance(v, str) and v in known:
            found.add(v)

    for inp in ir_json["inputs"].values():
        walk(inp)
    return found


def reference_envelope(x: np.ndarray, fs: float, band) -> np.ndarray:
    sos = ss.butter(4, [band[0] / (fs / 2), band[1] / (fs / 2)], btype="band", output="sos")
    return np.abs(ss.hilbert(ss.sosfiltfilt(sos, x)))


def lag_and_r(est: np.ndarray, ref: np.ndarray, fs: float) -> tuple[float, float]:
    a = (est - est.mean()) / (est.std() + 1e-12)
    b = (ref - ref.mean()) / (ref.std() + 1e-12)
    best_lag, best_r = 0, -1.0
    for lag in range(int(MAX_LAG_MS / 1000 * fs)):
        n = len(a) - lag
        if n < 10 * fs:
            break
        r = float(np.dot(a[lag:lag + n], b[:n]) / n)
        if r > best_r:
            best_lag, best_r = lag, r
    return best_lag / fs * 1000.0, best_r


def load_recordings(corpus: str, fs: float, minutes: float):
    import mne

    mne.set_log_level("ERROR")
    for path in sorted(glob.glob(os.path.join(corpus, "cases", "*", "input.edf"))):
        case = os.path.basename(os.path.dirname(path))
        try:
            raw = mne.io.read_raw_edf(path, preload=True, verbose=False)
        except Exception:
            continue
        sr = raw.info["sfreq"]
        if sr < 200:
            continue
        names = [c.upper().replace("EEG ", "").split("-")[0].strip() for c in raw.ch_names]
        n = min(int(minutes * 60 * sr), raw.n_times)
        if n < 60 * sr:
            continue
        data = raw.get_data()[:, :n] * 1e6
        if abs(sr - fs) > 1:
            m = int(n * fs / sr)
            grid = np.linspace(0, n - 1, m)
            data = np.vstack([np.interp(grid, np.arange(n), row) for row in data])
        yield case, {nm: data[i] for i, nm in enumerate(names)}


def measure(path: Path, amp, recordings: list, chunk_s: float = 0.05) -> list[dict]:
    ir = resolve(refrain.parse_file(str(path)), amp)
    j = ir_to_json_obj(ir)
    envs = envelopes(j)
    if not envs:
        return []
    fs = float(ir.requires.sample_rate_chosen_hz)
    chans = tuple(sorted(amp.channel_names()))
    needed = montage_channels(j, set(chans))
    rows = []
    for case, rec in recordings:
        if not all(c.upper() in rec for c in needed):
            continue
        n = len(next(iter(rec.values())))
        X = np.column_stack([rec.get(c.upper(), np.zeros(n)) for c in chans])
        cn = max(1, int(round(chunk_s * fs)))
        keep = {k for e in envs for k in (e["derive"], e["source"])} | {"reward.event", "reward.event.holds"}
        streams = step_through(ir, fs, chans, (X[k:k + cn] for k in range(0, n - cn + 1, cn)),
                               skip_warmup=True, keep_streams=keep).streams
        cut = slice(int(SKIP_HEAD_S * fs), -int(SKIP_TAIL_S * fs))
        if "reward.event.holds" in streams:
            held = streams["reward.event.holds"][cut] > 0.5
            onsets = int(np.sum(held[1:] & ~held[:-1]))
            rows.append(dict(protocol=path.name, case=case, fs=fs, derive="(reward)",
                             onsets_per_min=onsets / (len(held) / fs / 60.0),
                             held_pct=100.0 * float(held.mean())))
        for e in envs:
            src = streams[e["source"]]
            if np.std(src[cut]) < 1e-9:
                continue
            ref = reference_envelope(src, fs, e["band"])
            lag, r = lag_and_r(streams[e["derive"]][cut], ref[cut], fs)
            rows.append(dict(protocol=path.name, case=case, fs=fs, lag_ms=lag, r=r, **e))
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("protocols", nargs="+", type=Path)
    ap.add_argument("--corpus", default=os.path.expanduser("~/tmp/file_io_corpus"))
    ap.add_argument("--amp", default="brainbit_flex",
                    help="bundled amp profile name or a path (default: brainbit_flex, 250 Hz)")
    ap.add_argument("--minutes", type=float, default=4.0, help="per recording")
    ap.add_argument("--json", type=Path, help="write every row here")
    a = ap.parse_args(argv)
    warnings.filterwarnings("ignore")

    amp_path = a.amp if os.path.exists(a.amp) else os.path.join(
        os.path.dirname(refrain.__file__), "amp_profiles", f"{a.amp}.json")
    amp = load_amp_profile(amp_path)
    fs = float(resolve(refrain.parse_file(str(a.protocols[0])), amp).requires.sample_rate_chosen_hz)
    recordings = list(load_recordings(a.corpus, fs, a.minutes))
    if not recordings:
        sys.exit(f"no usable recordings under {a.corpus}")

    rows = []
    for p in a.protocols:
        got = measure(p, amp, recordings)
        rows += got
        rw = [r for r in got if r["derive"] == "(reward)"]
        if rw:
            print(f"{p.name:40s} {'(reward)':20s} n={len(rw):2d} onsets median "
                  f"{np.median([r['onsets_per_min'] for r in rw]):5.1f}/min | held median "
                  f"{np.median([r['held_pct'] for r in rw]):5.1f}%")
        got = [r for r in got if r["derive"] != "(reward)"]
        for e in sorted({(r["derive"], r["shape"], r["band"], r["latency_ms"]) for r in got}):
            sel = [r for r in got if r["derive"] == e[0]]
            lat = f"{e[3]:g} ms" if e[3] else "-"
            print(f"{p.name:40s} {e[0]:20s} {e[1]:13s} {e[2][0]:g}-{e[2][1]:g} Hz "
                  f"declared {lat:>7s} | n={len(sel):2d} lag median "
                  f"{np.median([r['lag_ms'] for r in sel]):5.0f} ms | r median "
                  f"{np.median([r['r'] for r in sel]):.3f}")
    if a.json:
        a.json.write_text(json.dumps(rows, indent=1, default=list))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
