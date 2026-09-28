# Copyright 2026 Refrain Language Authors. Apache-2.0.
"""Whole-schema validation of every distributed protocol.

tests/test_catalog.py hand-checks a few fields. This validates the entire
`meta` block against protocol-meta.schema.json, which is what catches a tier
or enum value nobody declared -- the hole that let `evidence = "demo"` sit in
19 files unnoticed.
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from refrain.parser import parse

ROOT = Path(__file__).resolve().parents[1]
ALL = sorted((ROOT / "protocols").rglob("*.refrain")) + sorted(
    (ROOT / "drafts").rglob("*.refrain")
)
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
def test_whole_meta_validates(path):
    jsonschema.validate(_meta(path), SCHEMA)


def test_unknown_evidence_tier_rejected():
    # Review Focus 5: the gate must reject ANY unknown tier, not just the two
    # bad values that happened to be in the corpus.
    doc = {"description": "d", "status": "draft", "goals": ["focus_attention"],
           "evidence": "definitely_not_a_tier"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(doc, SCHEMA)


PLACEHOLDER_CITATIONS = ("clinical convention", "convention", "n/a", "tbd", "")


@pytest.mark.parametrize("path", ALL, ids=lambda p: p.name)
def test_citation_is_a_real_reference(path):
    m = _meta(path)
    cite = (m.get("citation") or "").strip()

    # A draft may not have a citation yet; anything past draft must.
    if m.get("status") not in ("draft", "roadmap"):
        assert cite, f"{path.name}: status>{m['status']} requires a citation"
        assert cite.lower() not in PLACEHOLDER_CITATIONS, (
            f"{path.name}: citation {cite!r} is a placeholder, not a reference"
        )

    # But a citation that EXISTS must never frame provenance clinically,
    # whatever the file's maturity -- that is the neutralization, not a
    # maturity question.
    if cite:
        assert "clinical convention" not in cite.lower(), (
            f"{path.name}: citation {cite!r} still frames provenance clinically"
        )


EEG_DIR = ROOT / "protocols" / "eeg"
EEG_FILES = sorted(EEG_DIR.rglob("*.refrain")) + [ROOT / "drafts" / "scp_cz.refrain"]


@pytest.mark.parametrize("path", EEG_FILES, ids=lambda p: p.name)
def test_eeg_protocols_declare_modality(path):
    # Explicit beats implicit: a host app filtering by modality should not have
    # to know the default to find every EEG protocol.
    assert _meta(path).get("modality") == "eeg", (
        f"{path.name}: EEG protocols declare modality = \"eeg\" explicitly"
    )


def _load_build_catalog():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "build_catalog", ROOT / "tools" / "build_catalog.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_missing_modality_still_defaults_to_eeg(tmp_path):
    """Review Focus 2: a user's own EEG file omits `modality`.

    Declaring a default in the schema is not enough -- jsonschema does not
    apply defaults, so a host that filters on meta["modality"] would drop
    every user-authored EEG protocol. The READ PATH has to supply it.
    """
    assert SCHEMA["properties"]["modality"]["default"] == "eeg"
    doc = {"description": "d", "status": "draft", "goals": ["focus_attention"]}
    jsonschema.validate(doc, SCHEMA)  # valid without modality

    f = tmp_path / "mine.refrain"
    f.write_text(
        'protocol "mine" {\n'
        '  meta {\n'
        '    description = "my own thing"\n'
        '    status      = "draft"\n'
        '    goals       = ["focus_attention"]\n'
        '  }\n'
        '}\n'
    )
    meta = _load_build_catalog().read_meta(f)
    assert meta["modality"] == "eeg", (
        "a file with no modality line must read back as eeg, or a host "
        "filtering by modality drops every user-authored EEG protocol"
    )


def test_declared_modality_is_not_overwritten(tmp_path):
    f = tmp_path / "hrv.refrain"
    f.write_text(
        'protocol "hrv" {\n'
        '  meta {\n'
        '    description = "mine"\n'
        '    status      = "draft"\n'
        '    goals       = ["interoception"]\n'
        '    modality    = "hrv"\n'
        '  }\n'
        '}\n'
    )
    assert _load_build_catalog().read_meta(f)["modality"] == "hrv"


def test_no_clinical_amp_hardware():
    for path in ALL:
        assert _meta(path).get("hardware") != "clinical_amp", (
            f"{path.name}: hardware 'clinical_amp' renamed to 'research_amp'"
        )


def test_catalog_lists_a_protocol_with_an_unknown_goal(tmp_path):
    """A user's own file with a goal outside the eight buckets still LISTS.

    Closing the schema enum must not make the picker strict: the host buckets
    an unknown value into "Other" rather than dropping the protocol.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "build_catalog", ROOT / "tools" / "build_catalog.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    f = tmp_path / "mine.refrain"
    f.write_text(
        'protocol "mine" {\n'
        '  meta {\n'
        '    description = "my own thing"\n'
        '    status      = "draft"\n'
        '    goals       = ["my_own_goal"]\n'
        '  }\n'
        '}\n'
    )
    meta = mod.read_meta(f)
    assert meta["goals"] == ["my_own_goal"], "the builder must not filter goals"
    assert "_error" not in meta, "an unknown goal is not a parse failure"
