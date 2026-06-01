"""End-to-end test: --stage 5 over the committed cohort produces schema-valid 05-graph.json
(spec 0012 T24). Tests idempotency and Stage 6 associations block surfacing.
"""
import json
from pathlib import Path

import jsonschema
import pytest

PROJECTS_ROOT = Path(__file__).parent.parent.parent / "projects"
SCHEMA_PATH = Path(__file__).parent.parent.parent / "schemas" / "05-graph.schema.json"
HANDLE = "sample_creator"
PROJECT_DIR = PROJECTS_ROOT / HANDLE


def test_stage5_produces_schema_valid_output():
    from pipeline.stage5_associations import run

    out = run(HANDLE, PROJECT_DIR)
    assert out.exists()

    with open(out) as f:
        doc = json.load(f)

    with open(SCHEMA_PATH) as f:
        schema = json.load(f)

    jsonschema.validate(doc, schema)
    assert doc["handle"] == HANDLE
    assert doc["method_version"] == "v2a"
    assert doc["cohort_size"] >= 2
    assert doc["community_method"] in {"leiden", "louvain"}


def test_stage5_ego_has_required_keys():
    from pipeline.stage5_associations import run

    run(HANDLE, PROJECT_DIR)
    with open(PROJECT_DIR / "05-graph.json") as f:
        doc = json.load(f)

    ego = doc["ego"]
    assert "community_id" in ego
    assert "community_size" in ego
    centrality = ego["centrality"]
    assert "degree" in centrality
    assert "pagerank" in centrality
    assert "betweenness" in centrality


def test_stage5_communities_summary_present():
    from pipeline.stage5_associations import run

    run(HANDLE, PROJECT_DIR)
    with open(PROJECT_DIR / "05-graph.json") as f:
        doc = json.load(f)

    assert isinstance(doc["communities_summary"], list)
    for comm in doc["communities_summary"]:
        assert "community_id" in comm
        assert "art9_risk" in comm
        assert isinstance(comm["art9_risk"], bool)


def test_stage5_idempotent():
    from pipeline.stage5_associations import run

    run(HANDLE, PROJECT_DIR)
    with open(PROJECT_DIR / "05-graph.json") as f:
        doc1 = json.load(f)

    run(HANDLE, PROJECT_DIR)
    with open(PROJECT_DIR / "05-graph.json") as f:
        doc2 = json.load(f)

    doc1.pop("computed_at", None)
    doc2.pop("computed_at", None)
    assert doc1 == doc2


def test_stage5_associations_block_in_stage6(tmp_path):
    """Stage 6 associations block is populated when 05-graph.json exists."""
    from pipeline.stage5_associations import run as run5
    from pipeline.stage6_dossier import _load_associations_block

    run5(HANDLE, PROJECT_DIR)
    block = _load_associations_block(PROJECT_DIR)
    assert block["status"] == "complete"
    assert block["graph_summary"] is not None
    assert "ego" in block["graph_summary"]


def test_stage5_absent_graph_keeps_deferred(tmp_path):
    from pipeline.stage6_dossier import _load_associations_block

    block = _load_associations_block(tmp_path)
    assert block["status"] == "deferred"
    assert block["graph_summary"] is None
