"""Schema validation tests for both RAG manifests (T37 / A1, A8, A12)."""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

SCHEMAS_DIR = Path(__file__).parent.parent.parent / "schemas"


def _load_schema(name: str) -> dict:
    return json.loads((SCHEMAS_DIR / name).read_text())


class TestEmbedManifestSchema:
    _schema = None

    @property
    def schema(self):
        if self._schema is None:
            TestEmbedManifestSchema._schema = _load_schema("09-embed.schema.json")
        return self._schema

    def _valid(self):
        return {
            "handle": "test_creator",
            "embedded_at": "2026-01-01T00:00:00Z",
            "embedding_model": "nomic-embed-text",
            "embedding_model_version": "nomic-embed-text@dim768",
            "dimensions": 768,
            "similarity_function": "cosine",
            "counts": {
                "creator": {"embedded": 1, "skipped": 0, "reembedded": 0},
                "media": {"embedded": 5, "skipped": 2, "reembedded": 1},
            },
            "data_egress": "local-only",
        }

    def test_valid_manifest_passes(self):
        jsonschema.validate(self._valid(), self.schema)

    def test_missing_handle_fails(self):
        m = self._valid()
        del m["handle"]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(m, self.schema)

    def test_wrong_data_egress_fails(self):
        m = self._valid()
        m["data_egress"] = "cloud"
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(m, self.schema)

    def test_missing_counts_creator_fails(self):
        m = self._valid()
        del m["counts"]["creator"]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(m, self.schema)

    def test_negative_embedded_count_fails(self):
        m = self._valid()
        m["counts"]["creator"]["embedded"] = -1
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(m, self.schema)

    def test_idempotent_manifest_zero_reembedded(self):
        m = self._valid()
        m["counts"]["creator"]["embedded"] = 0
        m["counts"]["creator"]["skipped"] = 10
        m["counts"]["creator"]["reembedded"] = 0
        jsonschema.validate(m, self.schema)


class TestRagManifestSchema:
    _schema = None

    @property
    def schema(self):
        if self._schema is None:
            TestRagManifestSchema._schema = _load_schema("10-rag.schema.json")
        return self._schema

    def _valid(self):
        return {
            "question": "Which creators post about sustainable fitness?",
            "handle": None,
            "modes_run": ["vector", "keyword", "graph"],
            "retrievers": {
                "vector": {"k": 50, "candidates": 10, "latency_ms": 45, "error": None,
                           "index": "creator_embeddings", "cypher": None, "safety_gates_passed": None},
                "keyword": {"k": 50, "candidates": 5, "latency_ms": 20, "error": None,
                            "index": "creator_fulltext", "cypher": None, "safety_gates_passed": None},
                "graph": {"k": 50, "candidates": 3, "latency_ms": 150, "error": None,
                          "index": None, "cypher": "MATCH ...", "safety_gates_passed": True},
            },
            "fusion": {"method": "RRF", "rrf_k": 60,
                       "weights": {"vector": 1.0, "keyword": 1.0, "graph": 1.0},
                       "fused_candidates": 15},
            "rerank": {"enabled": False, "model": None},
            "generation": {"model": "qwen2.5:14b", "latency_ms": 800},
            "answer": "Based on retrieved data, creator @fitnessguru matches best.",
            "citations": [{"type": "creator", "user_id": "u_42", "handle": "fitnessguru",
                           "media_id": None, "caption_snippet": None, "signal_name": None}],
            "row_counts": {"vector": 10, "keyword": 5, "graph": 3},
            "latency_ms": 1100,
            "data_egress": "local-only",
            "asked_at": "2026-01-01T12:00:00Z",
        }

    def test_valid_manifest_passes(self):
        jsonschema.validate(self._valid(), self.schema)

    def test_missing_question_fails(self):
        m = self._valid()
        del m["question"]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(m, self.schema)

    def test_empty_modes_run_fails(self):
        m = self._valid()
        m["modes_run"] = []
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(m, self.schema)

    def test_invalid_mode_name_fails(self):
        m = self._valid()
        m["modes_run"] = ["vector", "unknown_mode"]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(m, self.schema)

    def test_wrong_data_egress_fails(self):
        m = self._valid()
        m["data_egress"] = "remote"
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(m, self.schema)

    def test_invalid_citation_type_fails(self):
        m = self._valid()
        m["citations"][0]["type"] = "invalid_type"
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(m, self.schema)
