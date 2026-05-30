"""Stage 9 GDS manifest schema tests — A10 (no database)."""
import json
from pathlib import Path

import jsonschema
import pytest

SCHEMA_PATH = Path(__file__).parent.parent.parent / "schemas" / "11-gds.schema.json"


def _schema():
    return json.loads(SCHEMA_PATH.read_text())


def _valid_manifest():
    return {
        "run_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "handle": "sample_creator",
        "graph_name": "profile-analyst",
        "gds_version": "2.6.0",
        "computed_at": "2026-05-30T20:00:00Z",
        "scope": "whole-graph",
        "algorithms": ["louvain", "degree_centrality", "betweenness_centrality",
                       "node_similarity", "link_prediction"],
        "counts": {
            "signals": {"community_id": 2, "degree_centrality": 2, "betweenness_centrality": 2},
            "edges": {"SHARES_AUDIENCE": 1, "COLLABORATED_WITH": 0},
            "scores": 2,
        },
        "fraud": {
            "model_version": "gds-fraud-v1",
            "weights": {"pod": 0.5, "btw": 0.3, "deg": 0.2},
            "normalization": "min-max",
        },
        "superseded": {"signals": 0, "scores": 0, "edges": 0},
        "art9_proxy_warning": "community_id must not be used as a proxy for a protected attribute.",
        "data_egress": "none",
    }


def test_schema_is_valid_draft7():
    jsonschema.Draft7Validator.check_schema(_schema())


def test_valid_manifest_passes():
    jsonschema.validate(_valid_manifest(), _schema())


def test_missing_run_id_fails():
    m = _valid_manifest()
    del m["run_id"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(m, _schema())


def test_bad_scope_enum_fails():
    m = _valid_manifest()
    m["scope"] = "single-handle"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(m, _schema())


def test_bad_normalization_enum_fails():
    m = _valid_manifest()
    m["fraud"]["normalization"] = "quantile"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(m, _schema())


def test_bad_data_egress_fails():
    m = _valid_manifest()
    m["data_egress"] = "external"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(m, _schema())


def test_superseded_missing_edges_fails():
    m = _valid_manifest()
    m["superseded"] = {"signals": 0, "scores": 0}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(m, _schema())


def test_counts_negative_fails():
    m = _valid_manifest()
    m["counts"]["scores"] = -1
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(m, _schema())
