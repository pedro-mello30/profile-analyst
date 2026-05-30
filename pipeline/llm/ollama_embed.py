"""Ollama local embedding client for Hybrid RAG (spec 0005 Track C).

Wraps the Ollama ``/api/embeddings`` endpoint. Reuses the 0003 ``OllamaClient``
transport (``OLLAMA_HOST``, ``keep_alive``, ``httpx``-based ``_post``) so all
connection errors propagate as ``OllamaError`` with the same actionable message.

Usage::

    from pipeline.llm.ollama_embed import OllamaEmbedder
    embedder = OllamaEmbedder()
    vec = embedder.embed("sustainable activewear creator")  # → List[float]
    dim = embedder.get_dimension()                          # → 768 for nomic-embed-text
"""
from __future__ import annotations

import os
from typing import Union

from pipeline.llm.ollama_client import OllamaClient, OllamaError  # noqa: F401 (re-export)

_DEFAULT_MODEL = "nomic-embed-text"


class OllamaEmbedder:
    """Thin client over Ollama ``/api/embeddings``.

    Args:
        host: Ollama daemon URL. Defaults to ``OLLAMA_HOST`` env var or ``http://localhost:11434``.
        model: Embedding model name. Defaults to ``OLLAMA_EMBED_MODEL`` env var or
               ``nomic-embed-text``.
        keep_alive: How long to hold the model warm (passed to Ollama). Defaults to
                    ``OLLAMA_KEEP_ALIVE`` env var or ``10m``.
    """

    def __init__(
        self,
        host: str | None = None,
        model: str | None = None,
        keep_alive: str | None = None,
    ) -> None:
        self._client = OllamaClient(host=host, keep_alive=keep_alive)
        self.model = model or os.environ.get("OLLAMA_EMBED_MODEL", _DEFAULT_MODEL)
        self.host = self._client.host

    def embed(
        self, texts: Union[str, list[str]]
    ) -> Union[list[float], list[list[float]]]:
        """Embed one or more texts. Returns a single vector for a string, list for a list.

        Raises:
            OllamaError: if Ollama is unreachable or returns a non-2xx response.
        """
        single = isinstance(texts, str)
        items = [texts] if single else texts
        vectors = [self._embed_one(t) for t in items]
        return vectors[0] if single else vectors

    def _embed_one(self, text: str) -> list[float]:
        payload = {
            "model": self.model,
            "prompt": text,
            "keep_alive": self._client.keep_alive,
        }
        data = self._client._post("/api/embeddings", payload)
        embedding = data.get("embedding")
        if not embedding or not isinstance(embedding, list):
            raise OllamaError(
                f"Ollama /api/embeddings returned an unexpected body for model {self.model!r}: "
                f"{str(data)[:200]}"
            )
        return embedding

    def get_dimension(self) -> int:
        """Return the dimension of this model's embeddings by embedding a probe string.

        Raises:
            OllamaError: if Ollama is unreachable (same error as embed()).
        """
        vec = self._embed_one("dimension probe")
        return len(vec)
