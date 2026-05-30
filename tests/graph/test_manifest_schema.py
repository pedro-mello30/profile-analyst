"""Stage 7 load-manifest schema tests — A1, A8 (no database)."""
import json
from pathlib import Path

import jsonschema
import pytest

SCHEMA_PATH = Path(__file__).parent.parent.parent / "schemas" / "07-graph-load.schema.json"


def _schema():
    return json.loads(SCHEMA_PATH.read_text())


def _valid_manifest():
    return {
        "run_id": "11111111-1111-1111-1111-111111111111",
        "handle": "sample_creator",
        "loaded_at": "2026-05-30T18:00:00Z",
        "neo4j_database": "neo4j",
        "counts": {
            "nodes": {"Creator": 1, "Media": 12, "Signal": 20, "Score": 4},
            "relationships": {"HAS_MEDIA": 12, "HAS_SIGNAL": 20, "CONTRIBUTED_TO": 4},
        },
        "associations": "deferred",
        "superseded": {"signals": 0, "scores": 0},
    }


def test_schema_is_valid_draft7():
    jsonschema.Draft7Validator.check_schema(_schema())


def test_valid_manifest_passes():
    jsonschema.validate(_valid_manifest(), _schema())


def test_missing_required_field_fails():
    m = _valid_manifest()
    del m["run_id"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(m, _schema())


def test_bad_associations_enum_fails():
    m = _valid_manifest()
    m["associations"] = "partial"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(m, _schema())


def test_superseded_requires_signals_and_scores():
    m = _valid_manifest()
    m["superseded"] = {"signals": 1}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(m, _schema())
