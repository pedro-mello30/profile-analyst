"""Unit tests for OllamaEmbedder (Track C, T12) — mocked transport."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from pipeline.llm.ollama_embed import OllamaEmbedder
from pipeline.llm.ollama_client import OllamaError


def _make_embedder(response_body: dict | None = None, raise_error: Exception | None = None):
    """Return an OllamaEmbedder whose HTTP transport is mocked."""
    embedder = OllamaEmbedder(host="http://mock-ollama:11434", model="nomic-embed-text")

    if raise_error is not None:
        embedder._client._post = MagicMock(side_effect=raise_error)
    else:
        embedder._client._post = MagicMock(return_value=response_body or {})
    return embedder


_FAKE_VECTOR = [0.1] * 768


class TestEmbedSingle:
    def test_returns_vector_for_string(self):
        embedder = _make_embedder({"embedding": _FAKE_VECTOR})
        result = embedder.embed("hello")
        assert isinstance(result, list)
        assert len(result) == 768
        assert result[0] == pytest.approx(0.1)

    def test_posts_to_correct_endpoint(self):
        embedder = _make_embedder({"embedding": _FAKE_VECTOR})
        embedder.embed("hello")
        call_args = embedder._client._post.call_args
        assert call_args[0][0] == "/api/embeddings"

    def test_payload_contains_model_and_prompt(self):
        embedder = _make_embedder({"embedding": _FAKE_VECTOR})
        embedder.embed("test text")
        payload = embedder._client._post.call_args[0][1]
        assert payload["model"] == "nomic-embed-text"
        assert payload["prompt"] == "test text"


class TestEmbedBatch:
    def test_returns_list_of_vectors_for_list(self):
        embedder = _make_embedder({"embedding": _FAKE_VECTOR})
        results = embedder.embed(["a", "b", "c"])
        assert isinstance(results, list)
        assert len(results) == 3
        assert all(isinstance(v, list) and len(v) == 768 for v in results)

    def test_calls_post_once_per_item(self):
        embedder = _make_embedder({"embedding": _FAKE_VECTOR})
        embedder.embed(["x", "y"])
        assert embedder._client._post.call_count == 2


class TestGetDimension:
    def test_returns_vector_length(self):
        embedder = _make_embedder({"embedding": _FAKE_VECTOR})
        assert embedder.get_dimension() == 768

    def test_works_with_smaller_model(self):
        embedder = _make_embedder({"embedding": [0.0] * 384})
        assert embedder.get_dimension() == 384


class TestConnectionError:
    def test_raises_ollama_error_on_connection_failure(self):
        embedder = _make_embedder(raise_error=OllamaError("Ollama unreachable at http://mock-ollama:11434"))
        with pytest.raises(OllamaError, match="Ollama unreachable"):
            embedder.embed("hi")

    def test_raises_ollama_error_on_bad_response(self):
        embedder = _make_embedder({"embedding": None})
        with pytest.raises(OllamaError, match="unexpected body"):
            embedder.embed("hi")

    def test_raises_ollama_error_on_empty_embedding(self):
        embedder = _make_embedder({"embedding": []})
        with pytest.raises(OllamaError, match="unexpected body"):
            embedder.embed("hi")
