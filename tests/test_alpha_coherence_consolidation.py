# Copyright 2026 Refrain Protocols Authors.
"""Consolidation of three overlapping alpha-coherence protocols down to one
canonical file (2026-07): the amplitude-symmetry stand-in
(protocols/eeg/legacy/alpha_symmetry_c3c4_brainbit.refrain) and the fixed-C3/C4
coherence draft (protocols/eeg/legacy/alpha_coherence_c3c4.refrain) are retired
in favor of protocols/eeg/alpha_coherence.refrain, which uses the real
coherence() primitive over a clinician-selectable site pair.

This is the proof: the survivor is the one with true phase coherence, it
resolves on more than one amp from one source (follows the pattern in
test_amp_neutral.py), and the retired files are still parseable/runnable but
clearly marked `status = "legacy"` and gone from their old paths.
"""
from __future__ import annotations

from pathlib import Path

import pytest

refrain = pytest.importorskip("refrain")
from refrain.amp_profile import load_amp_profile  # noqa: E402
from refrain.parser import parse  # noqa: E402
from refrain.resolver import resolve  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PROF = Path(refrain.__file__).parent / "amp_profiles"
BRAINBIT = load_amp_profile(PROF / "brainbit_flex.json")
Q21 = load_amp_profile(PROF / "q21.json")

SURVIVOR = ROOT / "protocols" / "eeg" / "alpha_coherence.refrain"
RETIRED_SYMMETRY = ROOT / "protocols" / "eeg" / "legacy" / "alpha_symmetry_c3c4_brainbit.refrain"
RETIRED_C3C4 = ROOT / "protocols" / "eeg" / "legacy" / "alpha_coherence_c3c4.refrain"

OLD_C3C4_PATH = ROOT / "protocols" / "alpha_coherence_c3c4.refrain"
OLD_SYMMETRY_PATH = ROOT / "protocols" / "brainbit" / "alpha_symmetry_c3c4_brainbit.refrain"


def _meta(src: str) -> dict:
    f = parse(src)
    out: dict = {}
    for stmt in f.protocol.body:
        if getattr(stmt, "keyword", None) == "meta":
            for a in stmt.body:
                v = a.value
                out[a.target] = getattr(v, "value", None)
    return out


def test_survivor_exists_and_parses():
    assert SURVIVOR.exists(), "canonical alpha_coherence.refrain is missing"
    parse(SURVIVOR.read_text())  # must not raise


def test_survivor_uses_true_coherence_not_amplitude_stand_in():
    src = SURVIVOR.read_text()
    assert "coherence(" in src, "survivor must use the real coherence() primitive"
    # The retired amplitude-symmetry stand-in computed |a - b| directly; the
    # survivor must not regress to that shape.
    assert "rectify(" not in src


@pytest.mark.parametrize(
    "amp,name,expected_reference",
    [(Q21, "Q21", "linked_ears"), (BRAINBIT, "BrainBit", "device")],
)
def test_survivor_resolves_on_both_amps(amp, name, expected_reference):
    # Follows the pattern in test_amp_neutral.py: an amp-neutral protocol
    # (reads `amp.reference`) must resolve on more than one amp profile from
    # the same source. The `coh` placement control needs a pair binding —
    # F3/F4 is in `allowed` and is present on both amp profiles.
    src = SURVIVOR.read_text()
    ir = resolve(parse(src), amp=amp, bindings={"coh": ("F3", "F4")})
    for inp_name in ("a", "b"):
        montage = ir.inputs[inp_name].montage
        ref_arg = next(a for a in montage.args if a.name == "reference")
        ref_value = ref_arg.value.value
        assert ref_value == expected_reference, (
            f"{name}: input {inp_name!r} reference resolved to {ref_value!r}, "
            f"expected {expected_reference!r}"
        )


def test_survivor_keeps_placement_pair_control_and_defaults():
    meta = _meta(SURVIVOR.read_text())
    src = SURVIVOR.read_text()
    assert 'kind    = "pair"' in src or 'kind = "pair"' in src
    assert 'default = ("F3", "F4")' in src
    assert '("C3", "C4")' in src
    assert "coh_reward_pct" in src
    assert meta["status"] == "reviewed"


def test_survivor_carries_window_from_retired_c3c4_variant():
    # `window` on coherence() is required=False/default=None upstream (folds
    # to 1000 ms if omitted) — carrying the fixed-C3/C4 file's explicit
    # `window: 2 s` is a real, non-cosmetic behavior change, not a no-op.
    src = SURVIVOR.read_text()
    assert "window: 2 s" in src


@pytest.mark.parametrize("path", [RETIRED_SYMMETRY, RETIRED_C3C4])
def test_retired_files_still_parse(path: Path):
    assert path.exists()
    parse(path.read_text())  # hidden from the picker, not broken


@pytest.mark.parametrize("path", [RETIRED_SYMMETRY, RETIRED_C3C4])
def test_retired_files_are_marked_legacy(path: Path):
    meta = _meta(path.read_text())
    assert meta["status"] == "legacy"


def test_old_paths_no_longer_exist():
    assert not OLD_C3C4_PATH.exists()
    assert not OLD_SYMMETRY_PATH.exists()
