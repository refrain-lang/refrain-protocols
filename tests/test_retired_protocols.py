# Copyright 2026 Refrain Protocols Authors.
"""Retirement of composite_smr_theta_cz and smr_up_c4 (both top-level/BrainBit
copies of each), 2026-07: a product decision to drop rather than merge the
fork pairs the audit found in docs/fork-audit-2026-07.md.

composite_smr_theta_cz (both copies) is a weighted composite that rewards on
fixed uV midpoints rather than adaptively — it sits at 0% forever and the
session coach's reward-rate advice cannot address its weight knobs. Retired
on its own merits.

smr_up_c4 (both copies) is SMR up-training at C4, reproduced by the
forthcoming configurable SMR template purely by setting its site knob.

This is the proof: all four files are still parseable/runnable (a subject
already assigned one is unaffected) but clearly marked `status = "legacy"`,
moved into protocols/eeg/legacy/, and gone from their old paths.
"""
from __future__ import annotations

from pathlib import Path

import pytest

refrain = pytest.importorskip("refrain")
from refrain.parser import parse  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

RETIRED_COMPOSITE = ROOT / "protocols" / "eeg" / "legacy" / "composite_smr_theta_cz.refrain"
RETIRED_COMPOSITE_BRAINBIT = (
    ROOT / "protocols" / "eeg" / "legacy" / "composite_smr_theta_cz_brainbit.refrain"
)
RETIRED_SMR_C4 = ROOT / "protocols" / "eeg" / "legacy" / "smr_up_c4.refrain"
RETIRED_SMR_C4_BRAINBIT = ROOT / "protocols" / "eeg" / "legacy" / "smr_up_c4_brainbit.refrain"

ALL_RETIRED = [
    RETIRED_COMPOSITE,
    RETIRED_COMPOSITE_BRAINBIT,
    RETIRED_SMR_C4,
    RETIRED_SMR_C4_BRAINBIT,
]

OLD_COMPOSITE_PATH = ROOT / "protocols" / "composite_smr_theta_cz.refrain"
OLD_COMPOSITE_BRAINBIT_PATH = ROOT / "protocols" / "brainbit" / "composite_smr_theta_cz_brainbit.refrain"
OLD_SMR_C4_PATH = ROOT / "protocols" / "smr_up_c4.refrain"
OLD_SMR_C4_BRAINBIT_PATH = ROOT / "protocols" / "brainbit" / "smr_up_c4_brainbit.refrain"

ALL_OLD_PATHS = [
    OLD_COMPOSITE_PATH,
    OLD_COMPOSITE_BRAINBIT_PATH,
    OLD_SMR_C4_PATH,
    OLD_SMR_C4_BRAINBIT_PATH,
]


def _meta(src: str) -> dict:
    f = parse(src)
    out: dict = {}
    for stmt in f.protocol.body:
        if getattr(stmt, "keyword", None) == "meta":
            for a in stmt.body:
                v = a.value
                out[a.target] = getattr(v, "value", None)
    return out


@pytest.mark.parametrize("path", ALL_RETIRED)
def test_retired_file_exists_at_new_path(path: Path):
    assert path.exists(), f"expected {path} to exist under protocols/eeg/legacy/"


@pytest.mark.parametrize("path", ALL_RETIRED)
def test_retired_files_still_parse(path: Path):
    parse(path.read_text())  # hidden from the picker, not broken


@pytest.mark.parametrize("path", ALL_RETIRED)
def test_retired_files_are_marked_legacy(path: Path):
    meta = _meta(path.read_text())
    assert meta["status"] == "legacy"


@pytest.mark.parametrize("path", ALL_OLD_PATHS)
def test_old_paths_no_longer_exist(path: Path):
    assert not path.exists(), f"expected {path} to be gone (moved via git mv)"
