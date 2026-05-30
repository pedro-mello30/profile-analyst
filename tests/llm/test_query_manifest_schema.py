"""Query-manifest schema tests — spec 0003 §7 C1 (A1, A10). No DB.

Named to avoid collision with tests/graph/test_manifest_schema.py (Stage-7 load manifest).
"""
import json
from pathlib import Path

import jsonschema
import pytest

SCHEMA_PATH = Path(__file__).parent.parent.parent / "schemas" / "08-query.schema.json"


def _schema():
    return json.loads(SCHEMA_PATH.read_text())


def _valid_manifest():
    return {
        "question": "list undisclosed sponsored posts for sample_creator",
        "cypher": "MATCH (c:Creator)-[:HAS_MEDIA]->(m:Media) RETURN m.media_id AS media_id\nLIMIT 200",
        "params": {"user_id": "sample_creator"},
        "model": "qwen2.5-coder:32b",
        "model_role": "cypher",
        "ollama_host": "http://localhost:11434",
        "validation": {"passed": True, "reasons": []},
        "row_count": 3,
        "latency_ms": 1234,
        "answer": "Three undisclosed sponsored posts were found.",
        "asked_at": "2026-05-30T18:00:00Z",
        "read_only": True,
        "data_egress": "local-only",
    }


def test_schema_is_valid_draft7():
    jsonschema.Draft7Validator.check_schema(_schema())


def test_valid_manifest_passes():
    jsonschema.validate(_valid_manifest(), _schema())


def test_rejection_manifest_with_reasons_passes():
    m = _valid_manifest()
    m["cypher"] = None
    m["validation"] = {"passed": False,
                       "reasons": [{"reason_code": "WRITE_KEYWORD", "message": "DELETE not allowed"}]}
    m["row_count"] = 0
    jsonschema.validate(m, _schema())


@pytest.mark.parametrize("field", [
    "question", "cypher", "params", "model", "model_role", "ollama_host",
    "validation", "row_count", "latency_ms", "answer", "asked_at", "read_only", "data_egress",
])
def test_missing_required_field_fails(field):
    m = _valid_manifest()
    del m[field]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(m, _schema())


def test_read_only_must_be_true():
    m = _valid_manifest()
    m["read_only"] = False
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(m, _schema())


def test_data_egress_enum_enforced():
    m = _valid_manifest()
    m["data_egress"] = "somewhere-else"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(m, _schema())


def test_validation_reason_requires_code_and_message():
    m = _valid_manifest()
    m["validation"] = {"passed": False, "reasons": [{"message": "missing code"}]}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(m, _schema())
