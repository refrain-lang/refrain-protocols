# Copyright 2026 Refrain Language Authors. Apache-2.0.
"""CI gates for the reference library.

- Every protocol PARSES (the draft gate — so the picker can always list it).
- Every protocol's meta satisfies the tag schema (required fields, enum values).
- catalog.json is current (rebuild == committed).
- `citation` is present once status graduates past draft/roadmap.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from refrain.parser import parse

ROOT = Path(__file__).resolve().parents[1]
# rglob: retired/legacy protocols live in a subfolder (protocols/eeg/legacy/)
ALL = sorted((ROOT / "protocols").rglob("*.refrain")) + sorted((ROOT / "drafts").rglob("*.refrain"))
SCHEMA = json.loads((ROOT / "schema" / "protocol-meta.schema.json").read_text())


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
def test_parses(path):
    parse(path.read_text())  # raises on failure


@pytest.mark.parametrize("path", ALL, ids=lambda p: p.name)
def test_meta_schema(path):
    m = _meta(path)
    for req in ("description", "status", "goals"):
        assert req in m, f"{path.name}: missing required meta `{req}`"
    assert m["status"] in SCHEMA["properties"]["status"]["enum"], f"{path.name}: bad status"
    goal_vocab = SCHEMA["properties"]["goals"]["items"]["enum"]
    for g in m["goals"]:
        assert g in goal_vocab, f"{path.name}: unknown goal {g!r}"
    if m["status"] not in ("draft", "roadmap"):
        assert m.get("citation"), f"{path.name}: status>{m['status']} requires a citation"


def test_catalog_current():
    subprocess.run([sys.executable, "tools/build_catalog.py"], cwd=ROOT, check=True)
    # If this changed catalog.json, CI's git-diff check will flag it.
    cat = json.loads((ROOT / "catalog.json").read_text())
    assert cat["count"] == len(ALL)
