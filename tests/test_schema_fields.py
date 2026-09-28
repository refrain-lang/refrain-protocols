import json
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schema" / "protocol-meta.schema.json").read_text())

_VALID = {
    "description": "SMR/THETA up-train at Cz",
    "status": "draft",
    "goals": ["focus_attention"],
    "title": "Steady focus — boost SMR (top of head)",
    "summary": "Rewards a calm-but-alert rhythm; the bar can adapt to you or hold fixed.",
    "family": "smr_theta_cz",
    "feedback_style": "discrete",
    "session_shape": "staged",
    "threshold_style": "selectable",
}


def test_new_meta_fields_validate():
    jsonschema.validate(_VALID, SCHEMA)  # must not raise


def test_selectable_threshold_style_allowed():
    doc = {"description": "d", "status": "draft", "goals": ["focus_attention"],
           "threshold_style": "selectable"}
    jsonschema.validate(doc, SCHEMA)


def test_bad_feedback_style_rejected():
    doc = {"description": "d", "status": "draft", "goals": ["focus_attention"],
           "feedback_style": "loud"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(doc, SCHEMA)


def test_required_fields_still_enforced():
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"status": "draft", "goals": ["focus_attention"]}, SCHEMA)


def test_legacy_status_allowed():
    # "legacy" marks a protocol superseded by a newer one: still runnable,
    # hidden from the default picker.
    doc = {"description": "d", "status": "legacy", "goals": ["focus_attention"]}
    jsonschema.validate(doc, SCHEMA)  # must not raise


def test_unknown_status_still_rejected():
    doc = {"description": "d", "status": "retired", "goals": ["focus_attention"]}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(doc, SCHEMA)


def test_empty_goals_rejected():
    # The trauma_recovery drop must never leave a file with no goal at all.
    doc = {"description": "d", "status": "draft", "goals": []}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(doc, SCHEMA)
