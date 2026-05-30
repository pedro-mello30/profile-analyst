"""Reciprocal Rank Fusion for Hybrid RAG (spec 0005 §7.1 / Track F).

Pure, deterministic, no I/O. Fully unit-testable.

``RRFFusion.fuse`` takes per-mode ranked candidate lists and returns a single
fused ranking by combining reciprocal ranks across modes. Media-level matches
are rolled up to the owning ``Creator`` by taking the **max** per-creator score
before fusion (OQ4 default).

Named constants (parameterizable in tests, per 0001 convention):
    RRF_K = 60
    RAG_MODE_WEIGHTS: per-mode multipliers (all 1.0 by default)
    RAG_FUSED_TOP_K = 20
"""
from __future__ import annotations

import os
from collections import defaultdict
from typing import Any

# Named constants — overridable via env for tests and config
RRF_K: int = int(os.environ.get("RAG_RRF_K", 60))
RAG_FUSED_TOP_K: int = int(os.environ.get("RAG_FUSED_TOP_K", 20))


def _parse_weights(raw: str) -> dict[str, float]:
    """Parse 'vector:1.0,graph:1.5,keyword:0.8' → {'vector': 1.0, ...}."""
    result: dict[str, float] = {}
    for part in raw.split(","):
        part = part.strip()
        if ":" in part:
            k, _, v = part.partition(":")
            try:
                result[k.strip()] = float(v.strip())
            except ValueError:
                pass
    return result


_DEFAULT_WEIGHTS_RAW = "vector:1.0,graph:1.0,keyword:1.0"
RAG_MODE_WEIGHTS: dict[str, float] = _parse_weights(
    os.environ.get("RAG_MODE_WEIGHTS", _DEFAULT_WEIGHTS_RAW)
)


class RRFFusion:
    """Reciprocal Rank Fusion across retrieval modes.

    Args:
        rrf_k: The RRF constant k (default ``RRF_K``).
        weights: Per-mode weight multipliers (default ``RAG_MODE_WEIGHTS``).
        top_k: Max candidates to return (default ``RAG_FUSED_TOP_K``).
    """

    def __init__(
        self,
        rrf_k: int | None = None,
        weights: dict[str, float] | None = None,
        top_k: int | None = None,
    ) -> None:
        self.rrf_k = rrf_k if rrf_k is not None else RRF_K
        self.weights = weights if weights is not None else dict(RAG_MODE_WEIGHTS)
        self.top_k = top_k if top_k is not None else RAG_FUSED_TOP_K

    def fuse(
        self,
        mode_results: dict[str, list[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        """Fuse per-mode ranked candidate lists into a single ranking.

        Each mode's list is ordered best-first. Each item must have:
        - ``user_id`` (str): canonical Creator key (per 0002 §5.1)
        - ``username`` (str): human-readable label
        - ``score`` (float): per-mode similarity / BM25 / graph score
        - ``source`` (str): the mode name

        Media-level items (with ``media_id`` but no ``user_id``) are rolled up
        to their owning Creator by taking the max score per creator.

        Returns:
            A list of ``{user_id, username, fused_score, sources}`` dicts,
            sorted by ``fused_score`` descending, truncated to ``top_k``.
        """
        # Roll-up: aggregate each mode's list to creator level (max score per creator)
        per_mode_creator: dict[str, dict[str, dict]] = {}
        for mode, candidates in mode_results.items():
            creator_map: dict[str, dict] = {}
            for cand in candidates:
                uid = cand.get("user_id") or cand.get("creator_user_id", "")
                if not uid:
                    continue
                existing = creator_map.get(uid)
                if existing is None or cand.get("score", 0) > existing.get("score", 0):
                    creator_map[uid] = {
                        "user_id": uid,
                        "username": cand.get("username", ""),
                        "score": cand.get("score", 0.0),
                        "source": mode,
                    }
            per_mode_creator[mode] = creator_map

        # RRF — score[uid] += weight_mode * 1 / (rrf_k + rank)
        fused: dict[str, float] = defaultdict(float)
        meta: dict[str, dict] = {}
        sources: dict[str, set] = defaultdict(set)

        for mode, creator_map in per_mode_creator.items():
            w = self.weights.get(mode, 1.0)
            ranked = sorted(creator_map.values(), key=lambda x: x["score"], reverse=True)
            for rank, item in enumerate(ranked, start=1):
                uid = item["user_id"]
                fused[uid] += w * (1.0 / (self.rrf_k + rank))
                sources[uid].add(mode)
                if uid not in meta:
                    meta[uid] = {"user_id": uid, "username": item["username"]}

        results = [
            {
                "user_id": uid,
                "username": meta[uid]["username"],
                "fused_score": score,
                "sources": sorted(sources[uid]),
            }
            for uid, score in sorted(fused.items(), key=lambda kv: kv[1], reverse=True)
        ]
        return results[: self.top_k]

    def fusion_manifest(
        self,
        mode_results: dict[str, list[dict]],
        fused: list[dict],
    ) -> dict:
        """Return the fusion block for the RAG manifest (spec §4.4)."""
        return {
            "method": "RRF",
            "rrf_k": self.rrf_k,
            "weights": dict(self.weights),
            "fused_candidates": len(fused),
        }
