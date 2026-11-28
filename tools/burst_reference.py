"""References for a 12-16 Hz burst that are NOT the protocol's own rule.

`score_onset_trigger.py` builds its ground truth from the band the protocol
trains and the rule shape the protocol uses (80th percentile, held 500 ms),
computed non-causally. That validates latency and filter fidelity. It cannot
validate the burst definition, because a detector and a reference built from
one rule share their blind spots. This module holds the references that do not
share it, and one that deliberately does, for comparison.

No public recording of WAKING EEG carries expert-scored bursts (searched
2026-11-28: Zenodo, OpenNeuro, PhysioNet; DREAMS, MASS and MODA are sleep), so
"expert-scored" is not on offer and nothing here is one. What is here:

  null        Phase-randomised surrogate of the same recording: identical
              power spectrum, no burst structure. Label-free. A trigger that
              fires as often on this as on the recording is not detecting
              events, whatever its catch rate says.
  ridge       Rhythmic episodes after BOSC/eBOSC (Whitten 2011; Kosciessa
              2020): Morlet power above the 95th chi-square(2) percentile of a
              robustly fitted aperiodic background, AT A LOCAL SPECTRAL
              MAXIMUM inside the band, for >= N cycles. A REIMPLEMENTATION of
              the published rule, not the eBOSC toolbox; not validated against
              it. The local-maximum step matters here: without it the 8-12 Hz
              skirt puts 12 Hz above background for a fifth of the session.
  bycycle     Cole & Voytek 2019, cycle-by-cycle on the broadband waveform:
              amplitude and period consistency, monotonicity, >= N cycles.
              Code defaults. `inband` additionally requires every cycle's own
              frequency to lie in the band - without it 62% of the "12-16 Hz"
              burst cycles on resting EEG are under 12 Hz (alpha).
  yasa        yasa.spindles_detect, the A7-derived SLEEP spindle detector,
              unmodified. Its thresholds were set on N2 sleep and it has never
              been validated on waking EEG; it is here as a second opinion on
              the word "spindle", and it finds almost none.
  amp         Envelope above k x its own median, no minimum duration - the
              waking-burst definition of Ossadtchi 2017 (k=2) and Belinskaia
              2020 (k=2.5). SAME RULE FAMILY as a median-relative trigger, so
              like the circular reference it measures timing, not definition.
  circular    The old ground truth, re-exported for side-by-side columns.

Needs numpy, scipy, statsmodels; mne for the loader; yasa / bycycle only for
the references that bear their names. Not run in CI: no recording ships here.
"""
from __future__ import annotations

import glob
import os
import warnings

import numpy as np
import scipy.signal as ss
import scipy.stats as st

from measure_envelopes import reference_envelope

FS = 250.0
BAND = (12.0, 16.0)


# --------------------------------------------------------------------------
# recordings
# --------------------------------------------------------------------------
def bids_subjects(root: str) -> list[str]:
    return sorted(os.path.basename(p).split("_")[0]
                  for p in glob.glob(os.path.join(root, "sub-*", "eeg", "*_eeg.set")))


def load_bids_rest(root: str, site: str = "CZ", reference=("M1", "M2"), fs: float = FS, only: str | None = None):
    """Yield (subject, x_uV, state) from a BIDS tree of EEGLAB `.set` files.

    `x` is `site` minus the mean of `reference`, anti-alias resampled to `fs`.
    `state` is 1 eyes-open, 2 eyes-closed, 0 unlabelled, from `events.tsv`
    rows whose `trial_type` starts "Eyes Open"/"Eyes Closed" (OpenNeuro
    ds003478; other trees simply yield all zeros). The tail is cut one second
    after the last labelled sample: ds003478 ends most files with a 2.5 s
    amplifier excursion of a quarter of a volt.
    """
    import mne

    mne.set_log_level("ERROR")
    for path in sorted(glob.glob(os.path.join(root, "sub-*", "eeg", "*_eeg.set"))):
        if only is not None and os.path.basename(path).split("_")[0] != only:
            continue
        raw = mne.io.read_raw_eeglab(path, preload=True)
        up = {n.upper(): n for n in raw.ch_names}
        if site not in up or any(r not in up for r in reference):
            continue
        get = lambda n: raw.get_data(picks=[up[n]])[0] * 1e6  # noqa: E731
        x = get(site) - np.mean([get(r) for r in reference], axis=0)
        q = raw.info["sfreq"] / fs
        if abs(q - round(q)) > 1e-9:
            continue
        x = ss.resample_poly(x, 1, int(round(q)))
        state = np.zeros(len(x), dtype=np.int8)
        ev_path = path.replace("_eeg.set", "_events.tsv")
        if os.path.exists(ev_path):
            t, k = [], []
            with open(ev_path) as fh:
                cols = fh.readline().rstrip("\n").split("\t")
                io, it = cols.index("onset"), cols.index("trial_type")
                for line in fh:
                    f = line.rstrip("\n").split("\t")
                    if f[it].startswith("Eyes Open"):
                        t.append(float(f[io])); k.append(1)
                    elif f[it].startswith("Eyes Closed"):
                        t.append(float(f[io])); k.append(2)
            for i in range(len(t) - 1):
                if k[i] == k[i + 1] and t[i + 1] - t[i] < 3.0:
                    state[int(t[i] * fs): int(t[i + 1] * fs)] = k[i]
        if state.any():
            n = min(len(x), int(np.flatnonzero(state).max() + fs))
            x, state = x[:n], state[:n]
        n = len(x) // 2 * 2
        yield os.path.basename(path).split("_")[0], x[:n].astype(float), state[:n]


def surrogate(x: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Same amplitude spectrum, uniformly random phases."""
    X = np.fft.rfft(x)
    ph = rng.uniform(0, 2 * np.pi, len(X))
    ph[0] = 0.0
    return np.fft.irfft(np.abs(X) * np.exp(1j * ph), n=len(x))


def runs(mask: np.ndarray) -> list[tuple[int, int]]:
    d = np.diff(np.concatenate(([0], mask.astype(np.int8), [0])))
    return list(zip(np.flatnonzero(d == 1).tolist(), np.flatnonzero(d == -1).tolist()))


# --------------------------------------------------------------------------
# references
# --------------------------------------------------------------------------
_F = 2 ** np.arange(1.5, 5.4, 0.0625)  # 2.8-41 Hz, 1/16 octave


def _tfr(x: np.ndarray, fs: float, wavenumber: int = 6) -> np.ndarray:
    """Morlet power, built as `ebosc.BOSC.BOSC_tf` builds it, FFT-convolved."""
    B = np.empty((len(_F), len(x)))
    for i, f in enumerate(_F):
        sd = 1.0 / (2 * np.pi * (f / wavenumber))
        t = np.arange(-3.6 * sd, 3.6 * sd, 1.0 / fs)
        m = (1.0 / np.sqrt(sd * np.sqrt(np.pi))) * np.exp(-t**2 / (2 * sd**2)) * np.exp(2j * np.pi * f * t)
        B[i] = np.abs(ss.fftconvolve(x, m, mode="same")) ** 2
    return B


def ridge_episodes(x, fs=FS, band=BAND, min_cycles=3, pct=0.95, exclude=(7.0, 16.0), ridge=True):
    import statsmodels.api as sm

    B = _tfr(x, fs)
    e = int(2 * fs)
    mp, lf = np.log10(B[:, e:-e].mean(1)), np.log10(_F)
    fit = (_F < exclude[0]) | (_F > exclude[1])
    rl = sm.RLM(mp[fit], sm.add_constant(lf[fit])).fit()
    bg = 10 ** (rl.params[0] + rl.params[1] * lf)
    over = B > (bg * st.chi2.ppf(pct, 2) / 2.0)[:, None]
    if ridge:
        lm = np.zeros_like(over)
        lm[1:-1] = (B[1:-1] >= B[:-2]) & (B[1:-1] >= B[2:])
        over &= lm
    inb = (_F >= band[0]) & (_F <= band[1])
    need = int(round(min_cycles / np.mean(band) * fs))
    return [(a, b) for a, b in runs(over[inb].any(0)) if b - a >= need]


def bycycle_bursts(x, fs=FS, band=BAND, min_cycles=3, inband=False, **thresholds):
    import pandas as pd
    from bycycle.features import compute_burst_features, compute_shape_features

    kw = dict(amp_fraction_threshold=0.0, amp_consistency_threshold=0.5,
              period_consistency_threshold=0.5, monotonicity_threshold=0.8)
    kw.update(thresholds)
    xl = ss.sosfiltfilt(ss.butter(4, 40 / (fs / 2), btype="low", output="sos"), x)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        sh = compute_shape_features(xl, fs, band)
        df = pd.concat((compute_burst_features(sh, xl), sh), axis=1)
    # bycycle 1.2's detect_bursts_cycles assigns into a read-only array under
    # numpy >= 2.3; this is its rule, on a writable copy.
    ib = ((df.amp_fraction > kw["amp_fraction_threshold"])
          & (df.amp_consistency > kw["amp_consistency_threshold"])
          & (df.period_consistency > kw["period_consistency_threshold"])
          & (df.monotonicity > kw["monotonicity_threshold"])).to_numpy().copy()
    ib[0] = ib[-1] = False
    if inband:
        f = fs / df.period.to_numpy()
        ib &= (f >= band[0]) & (f <= band[1])
    a0, b0 = df.sample_last_trough.to_numpy(), df.sample_next_trough.to_numpy()
    return [(int(a0[i]), int(b0[j - 1])) for i, j in runs(ib) if j - i >= min_cycles]


def yasa_spindles(x, fs=FS, band=(12.0, 15.0), duration=(0.5, 2.0)):
    import logging

    import yasa

    logging.disable(logging.CRITICAL)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            sp = yasa.spindles_detect(x, fs, freq_sp=band, duration=duration)
    finally:
        logging.disable(logging.NOTSET)
    if sp is None:
        return []
    df = sp.summary()
    return [(int(round(s * fs)), int(round(e * fs))) for s, e in zip(df.Start, df.End)]


def amp_bursts(x, fs=FS, band=BAND, k=2.5):
    env = reference_envelope(x, fs, band)
    return runs(env > k * np.median(env))


def circular(x, fs=FS, band=BAND):
    """score_onset_trigger.ground_truth, on the same zero-phase envelope."""
    from score_onset_trigger import ground_truth

    return [(int(a), int(b)) for a, b in ground_truth(reference_envelope(x, fs, band), fs)[0]]


REFERENCES = {
    "ridge3": lambda x: ridge_episodes(x, min_cycles=3),
    "ridge5": lambda x: ridge_episodes(x, min_cycles=5),
    "bycycle3": lambda x: bycycle_bursts(x, min_cycles=3),
    "bycycle3_inband": lambda x: bycycle_bursts(x, min_cycles=3, inband=True),
    "bycycle7": lambda x: bycycle_bursts(x, min_cycles=7),
    "yasa": yasa_spindles,
    "amp2.5": amp_bursts,
    "circular": circular,
}


def main() -> int:
    """Every reference on every recording AND on its surrogate.

    The surrogate column is the point: a reference that finds as many events
    in spectrum-matched noise as in the recording is not a reference.
    """
    root = os.environ.get("BURST_CORPUS", "")
    if not root:
        print("set BURST_CORPUS to a BIDS root (OpenNeuro ds003478 is what the figures were taken on)")
        return 2
    rng = np.random.default_rng(42)
    rows: dict[str, list] = {k: [] for k in REFERENCES}
    for sub, x, _ in load_bids_rest(root):
        s, mins = surrogate(x, rng), len(x) / FS / 60
        for name, fn in REFERENCES.items():
            real, null = fn(x), fn(s)
            dur = np.median([(b - a) / FS * 1000 for a, b in real]) if real else np.nan
            rows[name].append((len(real) / mins, len(null) / mins, dur, 100 * sum(b - a for a, b in real) / len(x)))
        print(f"  {sub} done", flush=True)
    print(f"\n{'reference':<18}{'events/min':>11}{'on noise':>10}{'real>noise':>12}{'median ms':>11}{'% of time':>11}")
    for name, r in rows.items():
        a = np.array(r)
        print(f"{name:<18}{np.median(a[:, 0]):>11.2f}{np.median(a[:, 1]):>10.2f}"
              f"{int((a[:, 0] > a[:, 1]).sum()):>9d}/{len(a):<2d}{np.nanmedian(a[:, 2]):>11.0f}{np.median(a[:, 3]):>11.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
