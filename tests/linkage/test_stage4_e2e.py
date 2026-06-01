"""Integration test: --stage 4 over committed fixture emits schema-valid 04-linkage.json (spec 0011 T20, T23)."""
import json
import os
import socket
from pathlib import Path

import jsonschema
import pytest

PROJECTS_ROOT = Path(__file__).parent.parent.parent / "projects"
SCHEMA_PATH = Path(__file__).parent.parent.parent / "schemas" / "04-linkage.schema.json"
HANDLE = "sample_creator"
PROJECT_DIR = PROJECTS_ROOT / HANDLE


@pytest.fixture(autouse=True)
def lia_env(monkeypatch):
    monkeypatch.setenv("LIA_FILE_PATH", "/docs/lia.pdf")


def test_stage4_produces_schema_valid_output(tmp_path):
    """Run Stage 4 over the committed fixture and validate the output."""
    from pipeline.stage4_linkage import run

    out = run(HANDLE, PROJECT_DIR)
    assert out.exists()

    with open(out) as f:
        doc = json.load(f)

    with open(SCHEMA_PATH) as f:
        schema = json.load(f)

    jsonschema.validate(doc, schema)
    assert doc["handle"] == HANDLE
    assert doc["method_version"] == "v3a"
    assert isinstance(doc["candidates"], list)


def test_stage4_candidates_have_required_fields():
    from pipeline.stage4_linkage import run

    run(HANDLE, PROJECT_DIR)
    with open(PROJECT_DIR / "04-linkage.json") as f:
        doc = json.load(f)

    for cand in doc["candidates"]:
        assert "confidence" in cand
        assert "likelihood_ratio" in cand
        assert len(cand["feature_evidence"]) >= 1
        assert cand["classification"] in {"link", "possible_link", "non_link"}


def test_stage4_no_network_reached(monkeypatch):
    """Confirm Stage 4 with SampleUILAdapter opens no socket."""
    def _no_connect(*a, **kw):
        raise AssertionError("Stage 4 must not open a network socket")

    monkeypatch.setattr(socket, "getaddrinfo", _no_connect)

    from pipeline.stage4_linkage import run
    run(HANDLE, PROJECT_DIR)  # must not raise


def test_stage4_idempotent():
    from pipeline.stage4_linkage import run

    out1 = run(HANDLE, PROJECT_DIR)
    with open(out1) as f:
        doc1 = json.load(f)

    out2 = run(HANDLE, PROJECT_DIR)
    with open(out2) as f:
        doc2 = json.load(f)

    # Same candidates (computed_at will differ — exclude from comparison)
    doc1.pop("computed_at", None)
    doc2.pop("computed_at", None)
    assert doc1["candidates"] == doc2["candidates"]


def test_stage4_raises_without_lia(monkeypatch):
    monkeypatch.delenv("LIA_FILE_PATH", raising=False)
    from pipeline.stage4_linkage import run
    from pipeline.compliance.tos import UilLiaError

    with pytest.raises(UilLiaError):
        run(HANDLE, PROJECT_DIR)
