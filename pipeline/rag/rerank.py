"""Optional cross-encoder reranker for Hybrid RAG (spec 0005 §7.2 / Track F).

Off by default (``RAG_RERANK=false``). When enabled, re-scores the fused top-K
candidates against the original query using a local cross-encoder model behind
the ``[rag]`` optional extra (``pip install profile-analyst[rag]``).

The reranker is **local-only** — it must never call a hosted API. Model is
resolved from ``RAG_RERANK_MODEL`` (default ``bge-reranker-v2-m3``).
"""
from __future__ import annotations

import os
from typing import Any

_DEFAULT_RERANK_MODEL = "bge-reranker-v2-m3"
_DEFAULT_RERANK_INPUT = 50
_DEFAULT_RERANK_OUTPUT = 5


class CrossEncoderReranker:
    """Re-rank fused candidates with a local cross-encoder.

    When ``enabled=False`` (default), :meth:`rerank` is a no-op that returns its
    input unchanged. This keeps the happy-path zero-dependency and zero-latency.

    Args:
        enabled: If False, rerank() is a no-op. Defaults to ``RAG_RERANK`` env var.
        model: Local cross-encoder model name. Defaults to ``RAG_RERANK_MODEL``.
        input_k: How many fused candidates to feed to the reranker.
                 Defaults to ``RAG_RERANK_INPUT``.
        output_n: How many to return after reranking. Defaults to ``RAG_RERANK_OUTPUT``.
    """

    def __init__(
        self,
        enabled: bool | None = None,
        model: str | None = None,
        input_k: int | None = None,
        output_n: int | None = None,
    ) -> None:
        if enabled is None:
            raw = os.environ.get("RAG_RERANK", "false").lower()
            enabled = raw in ("true", "1", "yes")
        self.enabled = enabled
        self.model = model or os.environ.get("RAG_RERANK_MODEL", _DEFAULT_RERANK_MODEL)
        self.input_k = input_k or int(os.environ.get("RAG_RERANK_INPUT", _DEFAULT_RERANK_INPUT))
        self.output_n = output_n or int(os.environ.get("RAG_RERANK_OUTPUT", _DEFAULT_RERANK_OUTPUT))
        self._encoder = None  # lazy-loaded when first used

    def rerank(
        self,
        query: str,
        candidates: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Re-rank *candidates* by cross-encoder score against *query*.

        If ``self.enabled`` is False, returns *candidates* unchanged.

        Raises:
            ImportError: if ``sentence-transformers`` is not installed (``pip install
                profile-analyst[rag]``).
            RuntimeError: if the model cannot be loaded.
        """
        if not self.enabled:
            return candidates

        top = candidates[: self.input_k]
        encoder = self._get_encoder()
        texts = [(query, c.get("username", "") + " " + c.get("bio_snippet", "")) for c in top]
        scores = encoder.predict(texts)
        ranked = sorted(zip(top, scores), key=lambda x: x[1], reverse=True)
        reranked = [cand for cand, _ in ranked[: self.output_n]]
        for i, (cand, score) in enumerate(ranked[: self.output_n]):
            reranked[i] = dict(cand, rerank_score=float(score))
        return reranked

    def _get_encoder(self):
        if self._encoder is None:
            try:
                from sentence_transformers import CrossEncoder  # type: ignore[import]
            except ImportError as exc:
                raise ImportError(
                    "The cross-encoder reranker requires the 'sentence-transformers' package. "
                    "Install it with: pip install 'profile-analyst[rag]'"
                ) from exc
            self._encoder = CrossEncoder(self.model)
        return self._encoder

    def manifest_block(self) -> dict:
        """Return the rerank block for the RAG manifest (spec §4.4)."""
        return {
            "enabled": self.enabled,
            "model": self.model if self.enabled else None,
        }
