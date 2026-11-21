"""Measure the front end a spindle-contingent SMR protocol would need.

Two questions, both answerable offline and both independent of any protocol
file, pin bump or reward-rule redesign (see
docs/superpowers/specs/2026-11-21-smr-spindle-protocol-design.md §10):

  band      -- what declared `band_envelope` latency each candidate band needs
               to match the accuracy of the shipped four-stage chain.
  gradient  -- how the envelope's slope behaves, which is what an onset
               ("waxing phase") trigger would fire on.

Run it before writing the protocol. The band answer decides the protocol's
band and its one declared latency, which bake at resolve time and cannot be
live controls.

    python tools/measure_spindle_front_end.py --corpus ~/tmp/file_io_corpus \\
        --section band --json band.json

Needs `mne`, `scipy` and refrain. Not run in CI: the corpus does not ship with
this repo.


Each band is scored against ITS OWN zero-phase reference
---------------------------------------------------------
The accuracy bar for 12-17 Hz is a zero-phase 12-17 Hz envelope, not the
12-15 Hz one. This is deliberate and it is the whole measurement, so it is
worth being explicit: the question is "how well does a filter track the band
it claims to track", because 12-17 Hz is the intended target signal for a
spindle protocol, not a cheap proxy for 12-15 Hz. Scoring a 12-17 Hz filter
against a 12-15 Hz reference would answer whether the wider band substitutes
for the narrower one, which is a different question and not the one being
asked.

The consequence to keep in mind when reading the numbers: the two bands' `r`
values are accuracies against different ground truths and are not a ranking
of signal quality. Only the LATENCY column compares across bands.


Primitives are driven directly, not through the evaluator
----------------------------------------------------------
There is no protocol file here. `BandEnvelopeImpl` and friends are fed chunks
straight from the recording, which is what makes this measurement runnable
today: it needs nothing from REC-15 and nothing from a pin bump. Every
primitive it uses is present in refrain v0.24.0, the version the recorder and
this repo's CI both run.

The shipped chain is reproduced from the same impls the engine uses
(`BandpassImpl -> HilbertFirImpl -> magnitude -> SmoothImpl`) rather than
re-implemented in scipy, so the bar is what the engine actually delivers.


Where this sits next to the other tools
----------------------------------------
`measure_envelopes.py` measures a protocol file's declared envelopes on corpus
recordings; this is its sibling, measuring candidate front ends that no protocol
file declares yet. `tools/session_report/` is the other half and the better tool
once a real session exists: it replays a saved session, reconciles the replay
against what ran live, and already reports true target episodes, run lengths and
envelope lag. So the division is — this tool for "what should the protocol
declare", `session_report` for "what did it then do on a person". Anything here
that needs ground truth about real spindles belongs there, not here.


Degenerate recordings are reported, not dropped
------------------------------------------------
The file-I/O corpus holds recordings that are unusable for this measurement
(a flat trace, a derivative montage whose numbers are physically impossible).
An earlier pass over this corpus silently excluded two of fourteen. Silent
exclusion hides whether a result rests on two recordings or twelve, so this
tool reports them in a `degenerate` list with the reason and leaves them out
of the medians only.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from measure_envelopes import (  # noqa: E402  (after sys.path setup)
    SKIP_HEAD_S,
    SKIP_TAIL_S,
    lag_and_r,
    load_recordings,
    reference_envelope,
)

from refrain.primitive_impls import (  # noqa: E402
    BandEnvelopeImpl,
    BandpassImpl,
    DifferentiateImpl,
    HilbertFirImpl,
    SmoothImpl,
)

# The site SMR trains at, in order of preference. A recording with none of
# these is skipped rather than substituted: mapping by position instead of by
# name is what made an earlier measurement of this kind evaluate synthetic
# noise and report plausible-looking numbers.
SITE_PREFERENCE = ("CZ", "C3", "C4")

# 12-15 Hz is what `smr.refrain` trains today and the bar every candidate is
# measured against. 12-17 Hz is the spindle protocol's proposal (§7.1): the
# same 5 Hz of bandwidth as the sleep literature's 11-16 Hz sigma band, but
# placed upward, where Cz's fast centroparietal spindles live and where the
# contaminant admitted is high beta the protocol already vetoes.
CANDIDATE_BANDS = ((12.0, 15.0), (12.0, 17.0), (11.0, 16.0))
SHIPPED_BAND = (12.0, 15.0)

# The shipped chain's shape, read off protocols/eeg/smr.refrain.
SHIPPED_ORDER = 4
SHIPPED_SMOOTH_TAU_MS = 250.0

# Sweep bounds for the declared latency. The ~1/bandwidth floor is 333 ms at
# 3 Hz and 200 ms at 5 Hz, and the shipped chain measures 500-600 ms, so this
# brackets every plausible answer.
SWEEP_LO_MS, SWEEP_HI_MS, SWEEP_STEP_MS = 80.0, 620.0, 20.0

FS = 250.0
MINUTES = 4.0
CHUNK_S = 0.05
# A recording whose band has essentially no signal cannot rank a filter.
MIN_SHIPPED_R = 0.50


def _chunks(x: np.ndarray, fs: float, chunk_s: float):
    n = max(1, int(round(chunk_s * fs)))
    for i in range(0, len(x), n):
        yield x[i : i + n]


def _run(impls, x: np.ndarray, fs: float) -> np.ndarray:
    """Stream `x` through a list of primitive impls, chunk by chunk."""
    out = []
    for chunk in _chunks(x, fs, CHUNK_S):
        buf = chunk
        for impl in impls:
            buf = impl.step(buf)
            if isinstance(buf, np.ndarray) and buf.dtype == complex:
                buf = np.abs(buf)
        out.append(np.asarray(buf, dtype=float))
    return np.concatenate(out)


def shipped_chain(x: np.ndarray, fs: float, band) -> np.ndarray:
    """`bandpass(order: 4) -> hilbert() -> magnitude() -> smooth(tau: 250 ms)`."""
    return _run(
        [
            BandpassImpl(band=band, order=SHIPPED_ORDER, sample_rate_hz=fs),
            HilbertFirImpl(sample_rate_hz=fs),
            SmoothImpl(tau_ms=SHIPPED_SMOOTH_TAU_MS, sample_rate_hz=fs),
        ],
        x,
        fs,
    )


def one_stage(x: np.ndarray, fs: float, band, latency_ms: float) -> np.ndarray:
    """`band_envelope(band: ..., latency: ...)` — one filter, delay declared."""
    return _run(
        [BandEnvelopeImpl(band=band, latency_ms=latency_ms, sample_rate_hz=fs)], x, fs
    )


def _score(est: np.ndarray, ref: np.ndarray, fs: float) -> tuple[float, float]:
    head, tail = int(SKIP_HEAD_S * fs), int(SKIP_TAIL_S * fs)
    n = min(len(est), len(ref))
    return lag_and_r(est[head : n - tail], ref[head : n - tail], fs, max_lag_ms=900.0)


def _pick_site(channels: dict) -> str | None:
    for name in SITE_PREFERENCE:
        if name in channels:
            return name
    return None


def section_band(recordings: list, fs: float) -> dict:
    """Matched-accuracy declared latency, per candidate band, per recording."""
    rows: list[dict] = []
    degenerate: list[dict] = []
    sweep = np.arange(SWEEP_LO_MS, SWEEP_HI_MS + 1, SWEEP_STEP_MS)

    for case, channels in recordings:
        site = _pick_site(channels)
        if site is None:
            degenerate.append({"case": case, "reason": "no Cz/C3/C4 channel by name"})
            continue
        x = channels[site]

        # The bar: the shipped chain on the band it ships with.
        ref_shipped = reference_envelope(x, fs, SHIPPED_BAND)
        bar_lag, bar_r = _score(shipped_chain(x, fs, SHIPPED_BAND), ref_shipped, fs)
        if not np.isfinite(bar_r) or bar_r < MIN_SHIPPED_R:
            degenerate.append(
                {"case": case, "site": site, "reason": f"shipped-chain r={bar_r:.3f} below {MIN_SHIPPED_R}"}
            )
            continue

        row = {"case": case, "site": site, "shipped_lag_ms": bar_lag, "shipped_r": bar_r, "bands": {}}
        for band in CANDIDATE_BANDS:
            ref = reference_envelope(x, fs, band)
            matched_ms, matched_r = None, None
            for latency_ms in sweep:
                _, r = _score(one_stage(x, fs, band, float(latency_ms)), ref, fs)
                if r >= bar_r:
                    matched_ms, matched_r = float(latency_ms), r
                    break
            row["bands"][f"{band[0]:g}-{band[1]:g}"] = {
                "matched_latency_ms": matched_ms,
                "r_at_match": matched_r,
                "saved_vs_shipped_ms": (bar_lag - matched_ms) if matched_ms else None,
            }
        rows.append(row)

    return {"recordings": rows, "degenerate": degenerate, "summary": _summarise_band(rows)}


def _summarise_band(rows: list[dict]) -> dict:
    out: dict = {"n": len(rows)}
    if not rows:
        return out
    out["shipped_lag_ms_median"] = statistics.median(r["shipped_lag_ms"] for r in rows)
    for key in (f"{b[0]:g}-{b[1]:g}" for b in CANDIDATE_BANDS):
        vals = [r["bands"][key]["matched_latency_ms"] for r in rows if r["bands"][key]["matched_latency_ms"]]
        unmatched = sum(1 for r in rows if not r["bands"][key]["matched_latency_ms"])
        out[key] = {
            "matched_latency_ms_median": statistics.median(vals) if vals else None,
            "matched_latency_ms_min": min(vals) if vals else None,
            "matched_latency_ms_max": max(vals) if vals else None,
            "never_matched": unmatched,
        }
    return out


def section_gradient(recordings: list, fs: float, band, latency_ms: float) -> dict:
    """The envelope's slope distribution — what an onset trigger fires on.

    Reported as percentiles of the positive slope, in microvolts per second,
    alongside the envelope's own amplitude percentiles so the two can be read
    together. This characterises the trigger; it cannot validate it. On
    recordings of people not performing the task there is no ground truth for
    what was a spindle, which is why the design gives the kill decision to a
    live session (§9.4).
    """
    rows: list[dict] = []
    degenerate: list[dict] = []

    for case, channels in recordings:
        site = _pick_site(channels)
        if site is None:
            degenerate.append({"case": case, "reason": "no Cz/C3/C4 channel by name"})
            continue
        x = channels[site]
        env = one_stage(x, fs, band, latency_ms)
        head, tail = int(SKIP_HEAD_S * fs), int(SKIP_TAIL_S * fs)
        env = env[head : len(env) - tail]
        if env.std() < 1e-9:
            degenerate.append({"case": case, "site": site, "reason": "flat envelope"})
            continue

        slope = _run([DifferentiateImpl(sample_rate_hz=fs)], env, fs)
        pos = slope[slope > 0]
        rows.append(
            {
                "case": case,
                "site": site,
                "env_uv_p50": float(np.percentile(env, 50)),
                "env_uv_p90": float(np.percentile(env, 90)),
                "slope_uv_per_s_p50": float(np.percentile(pos, 50)) if pos.size else None,
                "slope_uv_per_s_p90": float(np.percentile(pos, 90)) if pos.size else None,
                "slope_uv_per_s_p99": float(np.percentile(pos, 99)) if pos.size else None,
                "rising_fraction": float((slope > 0).mean()),
            }
        )

    summary: dict = {"n": len(rows), "band": list(band), "latency_ms": latency_ms}
    for key in ("slope_uv_per_s_p90", "slope_uv_per_s_p99", "rising_fraction", "env_uv_p50"):
        vals = [r[key] for r in rows if r[key] is not None]
        summary[f"{key}_median"] = statistics.median(vals) if vals else None
    return {"recordings": rows, "degenerate": degenerate, "summary": summary}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--corpus", required=True, help="file-I/O corpus root")
    ap.add_argument("--section", choices=("band", "gradient", "all"), default="all")
    ap.add_argument("--json", help="write results here")
    ap.add_argument("--minutes", type=float, default=MINUTES)
    ap.add_argument(
        "--gradient-band",
        default="12-17",
        help="band for the gradient section, as LO-HI in Hz (default 12-17)",
    )
    ap.add_argument(
        "--gradient-latency-ms",
        type=float,
        default=200.0,
        help="declared latency for the gradient section (default 200, the 5 Hz floor)",
    )
    args = ap.parse_args(argv)

    recordings = list(load_recordings(args.corpus, FS, args.minutes))
    if not recordings:
        print(f"no usable recordings under {args.corpus}", file=sys.stderr)
        return 1
    print(f"loaded {len(recordings)} recordings at {FS:g} Hz, {args.minutes:g} min each\n")

    out: dict = {"fs_hz": FS, "minutes": args.minutes, "n_loaded": len(recordings)}

    if args.section in ("band", "all"):
        out["band"] = section_band(recordings, FS)
        s = out["band"]["summary"]
        print("=== matched-accuracy declared latency ===")
        print(f"recordings kept: {s['n']}   degenerate: {len(out['band']['degenerate'])}")
        if s.get("shipped_lag_ms_median") is not None:
            print(f"shipped four-stage chain at 12-15 Hz: {s['shipped_lag_ms_median']:.0f} ms median\n")
        print(f"{'band':<10} {'median':>8} {'min':>7} {'max':>7} {'unmatched':>10}")
        for band in CANDIDATE_BANDS:
            key = f"{band[0]:g}-{band[1]:g}"
            b = s.get(key, {})
            med = b.get("matched_latency_ms_median")
            print(
                f"{key + ' Hz':<10} {('%.0f' % med) if med else '--':>8} "
                f"{('%.0f' % b['matched_latency_ms_min']) if b.get('matched_latency_ms_min') else '--':>7} "
                f"{('%.0f' % b['matched_latency_ms_max']) if b.get('matched_latency_ms_max') else '--':>7} "
                f"{b.get('never_matched', '--'):>10}"
            )
        for d in out["band"]["degenerate"]:
            print(f"  excluded {d['case']}: {d['reason']}")
        print()

    if args.section in ("gradient", "all"):
        lo, hi = (float(v) for v in args.gradient_band.split("-"))
        out["gradient"] = section_gradient(recordings, FS, (lo, hi), args.gradient_latency_ms)
        s = out["gradient"]["summary"]
        print(f"=== envelope slope at {lo:g}-{hi:g} Hz, {s['latency_ms']:g} ms declared ===")
        print(f"recordings kept: {s['n']}   degenerate: {len(out['gradient']['degenerate'])}")
        for key in ("env_uv_p50", "slope_uv_per_s_p90", "slope_uv_per_s_p99", "rising_fraction"):
            v = s.get(f"{key}_median")
            print(f"  {key + ' (median)':<32} {('%.3f' % v) if v is not None else '--'}")
        print()

    if args.json:
        Path(args.json).write_text(json.dumps(out, indent=2))
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
