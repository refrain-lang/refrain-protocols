"""Muscle activity in the raw EEG, measured independently of the protocol.

The protocol's own artifact inhibit is not evidence that muting matched muscle:
it is the thing under test. So this reads the recording's own samples -- before
any montage, band or threshold the protocol declares -- and asks one question:
when was there high-frequency power that EEG does not produce?

The choices, which the report states:

* **band** 70 Hz to min(120 Hz, 0.45 x sample rate). 70 Hz is above every EEG
  band a protocol in this library trains (the highest is high-beta, to 30 Hz),
  and 0.45 x the sample rate keeps the upper edge clear of the anti-alias
  rolloff. At 250 Hz that is 70-112.5 Hz. Below ~156 Hz there is no such band at
  all, and ``muscle_band`` answers None rather than filtering at a made-up edge.
* **level** 3x the recording's own median window power. A relative level,
  because what counts as high-frequency power depends on the amplifier, the
  electrode and the subject -- an absolute uV^2 figure would be a different
  detector on every recording.
* **length** at least 100 ms. Windows are 100 ms long and step 50 ms, and an
  episode is a run of at least two consecutive windows over the level, so the
  excess has to persist across 100 ms rather than appear in one window. Even so,
  a 100 ms window is a noisy power estimate: on pure white noise this finds
  about one 100 ms "episode" per two minutes at 250 Hz. That is the floor of
  what this measure can tell, and it is why the report gives muscle as a share
  of time rather than as a count of events.

Two guards keep arithmetic from being read as signal:

* the first and last 500 ms are dropped, because a zero-phase filter's output
  there is its own edge transient (``sosfiltfilt`` pads the signal, and the
  ringing from that padding outlives the pad);
* a window must also clear a billionth of the recording's mean square power.
  Without it, a synthetic or flat signal with no high-frequency content at all
  has a median of nothing, and every rounding error in the band is "3x the
  median". Real recordings carry orders of magnitude more than this floor in
  70-112.5 Hz, so it never decides anything on real data.
"""
from __future__ import annotations

import numpy as np
import scipy.signal as ss

MUSCLE_LOW_HZ = 70.0
MUSCLE_HIGH_HZ = 120.0
NYQUIST_SHARE = 0.45        # the upper edge never goes above this share of the sample rate
MUSCLE_FACTOR = 3.0         # a window is hot above this multiple of the recording's median
WINDOW_MS = 100.0
HOP_MS = 50.0
MIN_WINDOWS = 2             # two overlapping windows = 100 ms of sustained excess
EDGE_GUARD_S = 0.5          # the zero-phase filter's own transient, dropped at both ends
SILENT_SHARE = 1e-9         # band power below this share of mean square power is arithmetic
FILTER_ORDER = 4


def muscle_band(fs: float) -> tuple[float, float] | None:
    """The band the muscle index is measured over, or None if the rate leaves none."""
    high = min(MUSCLE_HIGH_HZ, NYQUIST_SHARE * float(fs))
    return (MUSCLE_LOW_HZ, high) if high > MUSCLE_LOW_HZ else None


def _window_power(x: np.ndarray, sos: np.ndarray, window: int, starts: np.ndarray) -> np.ndarray:
    """Mean squared band-passed amplitude over each window, by cumulative sum."""
    squared = np.square(ss.sosfiltfilt(sos, x))
    cumulative = np.concatenate(([0.0], np.cumsum(squared)))
    return (cumulative[starts + window] - cumulative[starts]) / window


def _runs(hot: np.ndarray) -> list[tuple[int, int]]:
    """Half-open [first, last) window-index spans of consecutive hot windows."""
    edges = np.diff(hot.astype(np.int8))
    first = [int(i) + 1 for i in np.flatnonzero(edges == 1)]
    last = [int(i) + 1 for i in np.flatnonzero(edges == -1)]
    if hot[0]:
        first.insert(0, 0)
    if hot[-1]:
        last.append(int(hot.size))
    return list(zip(first, last))


def muscle_episodes(raw: np.ndarray, fs: float) -> list[tuple[int, int]]:
    """Half-open ``[start, end)`` sample spans of muscle activity in ``raw``.

    ``raw`` is one channel or samples x channels; with several channels the index
    is the worst channel's power in each window, since muscle at one electrode is
    muscle whether or not the others saw it.
    """
    band = muscle_band(fs)
    x = np.asarray(raw, dtype=float)
    if x.ndim == 1:
        x = x[:, None]
    if band is None or x.ndim != 2 or x.shape[1] == 0:
        return []
    window = max(1, int(round(WINDOW_MS * fs / 1000.0)))
    hop = max(1, int(round(HOP_MS * fs / 1000.0)))
    guard = int(round(EDGE_GUARD_S * fs))
    sos = ss.butter(FILTER_ORDER, [band[0] / (fs / 2), band[1] / (fs / 2)], btype="band",
                    output="sos")
    if x.shape[0] <= max(3 * (2 * len(sos) + 1), 2 * guard + window * MIN_WINDOWS):
        return []

    starts = np.arange(guard, x.shape[0] - guard - window + 1, hop)
    if starts.size < MIN_WINDOWS:
        return []
    power = np.max([_window_power(x[:, j], sos, window, starts) for j in range(x.shape[1])],
                   axis=0)
    floor = SILENT_SHARE * float(np.mean(np.square(x)))
    level = max(MUSCLE_FACTOR * float(np.median(power)), floor)
    if not np.isfinite(level):
        return []

    hot = power > level
    return [(int(starts[a]), int(starts[b - 1]) + window)
            for a, b in _runs(hot) if b - a >= MIN_WINDOWS]
