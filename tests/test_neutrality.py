# Copyright 2026 Refrain Language Authors. Apache-2.0.
"""A distributed protocol makes no diagnostic or therapeutic claim.

The library ships general-wellness signal-training building blocks. Provenance
(`evidence`, `citation`) is kept and is honest about where a technique comes
from. What is NOT shipped is any statement about what a protocol is for,
medically, or who should receive it.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from refrain.parser import parse

ROOT = Path(__file__).resolve().parents[1]
ALL = sorted((ROOT / "protocols").rglob("*.refrain")) + sorted(
    (ROOT / "drafts").rglob("*.refrain")
)

# Dropped from the distributed contract. A host app that needs these keeps
# them host-side; a neutral library ships no indications.
# `control_ref` is deliberately NOT here: a pointer to a matching sham
# protocol is study design, not a health claim.
FORBIDDEN_FIELDS = (
    "indication",
    "population",
    "safety_monitoring",
    "outcome_measures",
)


def _meta(path: Path) -> dict:
    f = parse(path.read_text())
    out: dict = {}
    for stmt in f.protocol.body:
        if getattr(stmt, "keyword", None) == "meta":
            for a in stmt.body:
                v = a.value
                out[a.target] = (
                    [getattr(e, "value", None) for e in v.elements]
                    if hasattr(v, "elements") else getattr(v, "value", None)
                )
    return out


@pytest.mark.parametrize("path", ALL, ids=lambda p: p.name)
def test_no_indication_fields(path):
    m = _meta(path)
    present = [f for f in FORBIDDEN_FIELDS if f in m]
    assert not present, (
        f"{path.name}: {present} dropped from the distributed contract — "
        f"a neutral library ships no indications. Keep them host-side."
    )


# Words that name a condition or a medical role. A distributed file may cite a
# paper whose TITLE contains them -- provenance is honest -- but must not use
# them in its own prose.
INDICATION_WORDS = (
    "depression", "depressive", "trauma", "ptsd", "anxiety", "anxious",
    "adhd", "patient", "diagnos", "clinician", "clinical",
)

PROSE_FIELDS = ("description", "title", "summary")


def _citation_spans(text: str) -> list[str]:
    """Lines that ARE a citation -- exempt: a reference keeps its real title."""
    return [ln for ln in text.splitlines() if ln.lstrip().startswith("citation")]


@pytest.mark.parametrize("path", ALL, ids=lambda p: p.name)
def test_no_indication_language_in_prose(path):
    text = path.read_text(encoding="utf-8")
    exempt = set(_citation_spans(text))
    offenders = []
    for i, line in enumerate(text.splitlines(), 1):
        if line in exempt:
            continue
        low = line.lower()
        for w in INDICATION_WORDS:
            if w in low:
                offenders.append(f"{i}: {w!r} in {line.strip()[:80]}")
    assert not offenders, (
        f"{path.name}: indication language in distributed prose:\n  "
        + "\n  ".join(offenders)
    )


@pytest.mark.parametrize("path", ALL, ids=lambda p: p.name)
def test_prose_fields_present(path):
    # The scrub must not leave a file with an empty label.
    m = _meta(path)
    for field in PROSE_FIELDS:
        if field in m:
            assert (m[field] or "").strip(), f"{path.name}: {field} emptied by the scrub"
