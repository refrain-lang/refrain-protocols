# Copyright 2026 Refrain Protocols Authors.
"""Amp-neutral protocols (those that read `amp.*`) must resolve on more than one
amp from one source — the working-slice proof. Full-amp coverage is WOR-163."""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pytest

refrain = pytest.importorskip("refrain")
from refrain.amp_profile import load_amp_profile  # noqa: E402
from refrain.ir_json import ir_to_json_obj  # noqa: E402
from refrain.primitive_impls import ReferentialImpl  # noqa: E402
from refrain.resolver import ResolveError, resolve  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PROF = Path(refrain.__file__).parent / "amp_profiles"
BRAINBIT = load_amp_profile(PROF / "brainbit_flex.json")
Q21 = load_amp_profile(PROF / "q21.json")

# Amp-reading protocols: source references the `amp` namespace.
AMP_READERS = [
    p for p in sorted(ROOT.glob("protocols/**/*.refrain"))
    if re.search(r'\bamp\.', p.read_text())
]


def _ref_arg(ir: dict) -> str:
    m = ir["inputs"]["raw"]["montage"]
    return next(a for a in m["args"] if a["name"] == "reference")["value"]["value"]


def test_there_is_at_least_one_amp_reader():
    assert AMP_READERS, "no amp-reading protocol found — did the slice land?"


@pytest.mark.parametrize("path", AMP_READERS, ids=lambda p: p.name)
def test_amp_reader_fails_closed_without_profile(path: Path):
    with pytest.raises(ResolveError):
        resolve(refrain.parse(path.read_text()))


@pytest.mark.parametrize("path", AMP_READERS, ids=lambda p: p.name)
def test_amp_reader_resolves_on_q21(path: Path):
    # A clinical amp declares every standard site + A1/A2, so every amp-neutral
    # protocol resolves on it and folds the reference to linked_ears.
    q = ir_to_json_obj(resolve(refrain.parse(path.read_text()), amp=Q21))
    assert _ref_arg(q) == "linked_ears"


@pytest.mark.parametrize("path", AMP_READERS, ids=lambda p: p.name)
def test_amp_reader_on_brainbit_device_or_fail_closed(path: Path):
    # BrainBit exposes only 4 electrodes (Cz/F3/F4/Pz). A protocol whose site is
    # among them folds the reference to `device`; one whose site is not (e.g. Fz,
    # C3, C4) fails closed on the requires-channel check — a genuine hardware
    # incapacity, the correct behaviour, not a defect. (Full-amp matrix: WOR-163.)
    src = path.read_text()
    needed = ir_to_json_obj(resolve(refrain.parse(src), amp=Q21))["requires"]["channels"]
    hostable = all(BRAINBIT.has_channel(c) for c in needed)
    if hostable:
        bb = ir_to_json_obj(resolve(refrain.parse(src), amp=BRAINBIT))
        assert _ref_arg(bb) == "device"
    else:
        with pytest.raises(ResolveError):
            resolve(refrain.parse(src), amp=BRAINBIT)


def test_montage_is_live_not_a_flatline_on_brainbit():
    # The pre-abstraction linked_ears form flatlines on a BrainBit (mean of one
    # channel minus itself = 0). The device fold must produce a live stream.
    rng = np.random.default_rng(1)
    chunk = rng.standard_normal((64, 4)) + np.arange(4)  # Cz/F3/F4/Pz
    out = ReferentialImpl(active="Cz", reference="device",
                          channel_names=("Cz", "F3", "F4", "Pz")).step(chunk)
    assert not np.allclose(out, 0.0)
