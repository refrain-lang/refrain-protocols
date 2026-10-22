# Copyright 2026 Refrain Protocols Authors.
"""The scoring inside tools/measure_envelopes.py: delay and accuracy of an envelope.

The tool itself replays clinical EEG that does not ship with this repo, so CI
cannot run it end to end. These tests pin the parts that decide its numbers:
the alignment search that reports delay and correlation, and the parser that
finds which derives are envelopes and in which shape.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("scipy")
refrain = pytest.importorskip("refrain")
from refrain.amp_profile import load_amp_profile  # noqa: E402
from refrain.ir_json import ir_to_json_obj  # noqa: E402
from refrain.resolver import resolve  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from measure_envelopes import envelopes, lag_and_r, reference_envelope  # noqa: E402

FS = 250.0


def _burst_signal(fs: float, seconds: float) -> np.ndarray:
    """A 13.5 Hz carrier switched on in random half-second bursts, over weak noise."""
    rng = np.random.default_rng(7)
    t = np.arange(int(seconds * fs)) / fs
    gate = np.zeros_like(t)
    for onset in rng.uniform(0, seconds - 0.5, size=int(seconds)):
        gate[(t >= onset) & (t < onset + 0.5)] = 1.0
    return gate * np.sin(2 * np.pi * 13.5 * t) + 0.1 * rng.standard_normal(t.size)


def _resolve(rel: str) -> dict:
    amp = load_amp_profile(Path(refrain.__file__).parent / "amp_profiles" / "q21.json")
    return ir_to_json_obj(resolve(refrain.parse_file(str(ROOT / rel)), amp))


def test_lag_and_r_identity():
    ref = reference_envelope(_burst_signal(FS, 30), FS, (12.0, 15.0))
    lag, r = lag_and_r(ref, ref, FS)
    assert lag == 0.0 and r > 0.999


def test_lag_and_r_recovers_a_known_delay():
    ref = reference_envelope(_burst_signal(FS, 30), FS, (12.0, 15.0))
    delayed = np.concatenate([np.full(50, ref[0]), ref[:-50]])  # 50 samples = 200 ms
    lag, r = lag_and_r(delayed, ref, FS)
    assert lag == pytest.approx(200.0, abs=4.0) and r > 0.99


def test_envelopes_finds_four_stage_and_band_envelope_in_shipped_smr():
    found = {e["derive"]: (e["shape"], e["band"]) for e in envelopes(_resolve("protocols/eeg/smr.refrain"))}
    assert found["smr_envelope"] == ("four-stage", (12.0, 15.0))
    assert found["theta_envelope"][0] == "four-stage"
    assert found["high_beta_envelope"][0] == "four-stage"
