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

# Amp-reading protocols: source references an `amp.<field>` namespace member.
# The trailing identifier class is load-bearing — a bare `\bamp\.` would also
# match English prose like "...a DC-coupled clinical amp." in a summary/comment.
AMP_READERS = [
    p for p in sorted(ROOT.glob("protocols/**/*.refrain"))
    if re.search(r'\bamp\.[a-z_]', p.read_text())
]


def _ref_args(ir: dict) -> list[str]:
    """The `reference` arg of every input's montage. Most protocols have a
    single input named "raw"; multi-input ones (e.g. coherence over a pair
    of sites) have more than one, and each must independently agree with
    the amp fold — so this checks all of them, not just one input's worth."""
    out = []
    for inp in ir["inputs"].values():
        m = inp["montage"]
        out.append(next(a for a in m["args"] if a["name"] == "reference")["value"]["value"])
    return out


def test_there_is_at_least_one_amp_reader():
    assert AMP_READERS, "no amp-reading protocol found — did the slice land?"


def test_brainbit_folder_is_gone():
    # 2026-07 library reorg: forking a protocol for the BrainBit meant
    # hardcoding its montage reference (killing portability) and relaxing the
    # sample-rate gate — undone across the library by reverting to
    # amp.reference (AMP_READERS above picks up every one of them
    # automatically), so the device-specific folder is no longer needed.
    assert not (ROOT / "protocols" / "brainbit").exists()


@pytest.mark.parametrize("path", AMP_READERS, ids=lambda p: p.name)
def test_amp_reader_fails_closed_without_profile(path: Path):
    with pytest.raises(ResolveError):
        resolve(refrain.parse(path.read_text()))


@pytest.mark.parametrize("path", AMP_READERS, ids=lambda p: p.name)
def test_amp_reader_resolves_on_q21(path: Path):
    # A clinical amp declares every standard site + A1/A2, so every amp-neutral
    # protocol resolves on it and folds the reference to linked_ears.
    q = ir_to_json_obj(resolve(refrain.parse(path.read_text()), amp=Q21))
    refs = _ref_args(q)
    assert refs, "no montage inputs found — did the IR shape change?"
    assert all(r == "linked_ears" for r in refs)


@pytest.mark.parametrize("path", AMP_READERS, ids=lambda p: p.name)
def test_amp_reader_on_brainbit_device_or_fail_closed(path: Path):
    # BrainBit exposes only 4 electrodes (Cz/F3/F4/Pz) and a single 250 Hz
    # sample rate. A protocol whose site is among them AND whose sample-rate
    # floor is satisfiable (<= 250 Hz) folds the reference to `device`; one
    # that needs a site BrainBit doesn't have (e.g. Fz, C3, C4) OR a rate it
    # can't offer (e.g. critical_fluctuation.refrain's deliberate >= 256 Hz
    # floor — see its header) fails closed on the requires check — a genuine
    # hardware incapacity, the correct behaviour, not a defect. (Full-amp
    # matrix: WOR-163.)
    src = path.read_text()
    needed_ir = ir_to_json_obj(resolve(refrain.parse(src), amp=Q21))["requires"]
    channels_ok = all(BRAINBIT.has_channel(c) for c in needed_ir["channels"])
    rate_ok = BRAINBIT.best_sample_rate_at_least(needed_ir["sample_rate_min_hz"]) is not None
    hostable = channels_ok and rate_ok
    if hostable:
        bb = ir_to_json_obj(resolve(refrain.parse(src), amp=BRAINBIT))
        refs = _ref_args(bb)
        assert refs, "no montage inputs found — did the IR shape change?"
        assert all(r == "device" for r in refs)
    else:
        with pytest.raises(ResolveError):
            resolve(refrain.parse(src), amp=BRAINBIT)


def test_placement_smr_bipolar_resolves_on_both_amps():
    # protocols/eeg/placement_smr_bipolar.refrain (relocated 2026-07, was
    # protocols/brainbit/placement_smr_bipolar_brainbit.refrain) uses a
    # `bipolar(pair: ...)` montage, which has no separate `reference` field to
    # hardcode — it was already portable and needed no amp.reference edit, so
    # it does not show up in AMP_READERS above. It is still one of the newly-
    # relocated protocols this reorg made portable-by-location, so prove it
    # resolves against both profiles from the one source, same as the
    # AMP_READERS proof does for reference-folding protocols.
    path = ROOT / "protocols" / "eeg" / "placement_smr_bipolar.refrain"
    src = path.read_text()
    for amp in (BRAINBIT, Q21):
        ir = ir_to_json_obj(resolve(refrain.parse(src), amp=amp))
        assert ir["inputs"]["raw"]["montage"]["callee"] == "bipolar"


def test_montage_is_live_not_a_flatline_on_brainbit():
    # The pre-abstraction linked_ears form flatlines on a BrainBit (mean of one
    # channel minus itself = 0). The device fold must produce a live stream.
    rng = np.random.default_rng(1)
    chunk = rng.standard_normal((64, 4)) + np.arange(4)  # Cz/F3/F4/Pz
    out = ReferentialImpl(active="Cz", reference="device",
                          channel_names=("Cz", "F3", "F4", "Pz")).step(chunk)
    assert not np.allclose(out, 0.0)
