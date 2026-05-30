"""Stage 8 EMBED — idempotent embedding backfill onto Neo4j (spec 0005 §5 / Track D).

Reads ``Creator`` and ``Media`` nodes from the 0002 graph, computes local
embeddings via Ollama (``OllamaEmbedder``), and upserts ``embedding``,
``embedding_model_version``, and ``text_hash`` onto each node.

Idempotency: a node is re-embedded **only** when its stored ``text_hash`` or
``embedding_model_version`` differs from the current values. Re-running on
unchanged data is a no-op (zero writes, manifest records ``reembedded: 0``).

All embeddings run on-host; ``data_egress: local-only`` is recorded in the manifest.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import jsonschema

from pipeline.graph.connection import GraphSession
from pipeline.llm.ollama_embed import OllamaEmbedder
from pipeline.rag.indexes import ensure_rag_indexes, DimensionMismatchError, Neo4jVersionError

_MANIFEST_SCHEMA = Path(__file__).parent.parent / "schemas" / "09-embed.schema.json"
_BATCH_SIZE = 32
_DEFAULT_SIMILARITY = "cosine"


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]


def _resolve_config() -> dict[str, Any]:
    return {
        "model": os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text"),
        "dimensions": int(os.environ.get("EMBED_DIMENSIONS", 768)),
        "similarity": _DEFAULT_SIMILARITY,
    }


class Stage8EmbedProcessor:
    """Idempotent embedding backfill for Creator and Media nodes.

    Args:
        embedder: Pre-built ``OllamaEmbedder``. When None, constructed from env.
        session: Pre-built ``GraphSession``. When None, constructed from env.
    """

    def __init__(
        self,
        embedder: OllamaEmbedder | None = None,
        session: GraphSession | None = None,
    ) -> None:
        self._embedder = embedder
        self._session = session

    def process(self, handle: str, project_dir: Path) -> Path:
        """Run the embedding backfill for *handle*. Returns the manifest path.

        Raises:
            OllamaError: if Ollama is unreachable.
            Neo4jVersionError: if Neo4j < 5.13.
            DimensionMismatchError: if EMBED_DIMENSIONS ≠ model dimension.
        """
        cfg = _resolve_config()
        model = cfg["model"]
        dimensions = cfg["dimensions"]
        similarity = cfg["similarity"]

        started = time.monotonic()

        embedder = self._embedder or OllamaEmbedder(model=model)
        model_version = f"{model}@dim{dimensions}"

        # Verify model dimension matches config before creating/using indexes.
        probed_dim = embedder.get_dimension()

        own_session = self._session is None
        session = self._session or GraphSession()
        if own_session:
            session.__enter__()

        try:
            ensure_rag_indexes(session, dimensions=dimensions, similarity=similarity,
                               probed_dimension=probed_dim)
            creator_counts = self._embed_creators(session, embedder, model_version, dimensions)
            media_counts = self._embed_media(session, embedder, model_version, dimensions)
        finally:
            if own_session:
                session.__exit__(None, None, None)

        manifest = {
            "handle": handle,
            "embedded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "embedding_model": model,
            "embedding_model_version": model_version,
            "dimensions": dimensions,
            "similarity_function": similarity,
            "counts": {
                "creator": creator_counts,
                "media": media_counts,
            },
            "data_egress": "local-only",
        }

        with open(_MANIFEST_SCHEMA) as fh:
            schema = json.load(fh)
        jsonschema.validate(manifest, schema)

        manifest_path = project_dir / "08-embed-manifest.json"
        tmp = manifest_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(manifest, indent=2))
        os.replace(tmp, manifest_path)

        return manifest_path

    def _embed_creators(
        self,
        session: GraphSession,
        embedder: OllamaEmbedder,
        model_version: str,
        dimensions: int,
    ) -> dict[str, int]:
        counts = {"embedded": 0, "skipped": 0, "reembedded": 0}

        # Fetch only governance-gate-passed creators (tos_compliant_at_ingest is True)
        rows = session.read(
            """
            MATCH (c:Creator)
            WHERE c.tos_compliant_at_ingest = true
            RETURN c.user_id        AS user_id,
                   c.username       AS username,
                   c.display_name   AS display_name,
                   c.bio            AS bio,
                   c.embedding_model_version AS stored_version,
                   c.text_hash      AS stored_hash
            """
        )

        to_embed: list[dict] = []
        for row in rows:
            parts = [
                row.get("username") or "",
                row.get("display_name") or "",
                row.get("bio") or "",
            ]
            text = " ".join(p for p in parts if p).strip()
            if not text:
                counts["skipped"] += 1
                continue
            h = _text_hash(text)
            if row.get("stored_version") == model_version and row.get("stored_hash") == h:
                counts["skipped"] += 1
                continue
            reembed = row.get("stored_version") is not None
            to_embed.append({
                "user_id": row["user_id"],
                "text": text,
                "hash": h,
                "reembed": reembed,
            })

        for batch_start in range(0, len(to_embed), _BATCH_SIZE):
            batch = to_embed[batch_start: batch_start + _BATCH_SIZE]
            texts = [item["text"] for item in batch]
            vectors = embedder.embed(texts)

            rows_payload = [
                {
                    "user_id": item["user_id"],
                    "embedding": vec if isinstance(vec, list) else vec,
                    "model_version": model_version,
                    "text_hash": item["hash"],
                }
                for item, vec in zip(batch, vectors)
            ]
            session.write(
                """
                UNWIND $rows AS row
                MATCH (c:Creator {user_id: row.user_id})
                SET c.embedding               = row.embedding,
                    c.embedding_model_version = row.model_version,
                    c.text_hash               = row.text_hash
                """,
                rows=rows_payload,
            )
            for item in batch:
                if item["reembed"]:
                    counts["reembedded"] += 1
                else:
                    counts["embedded"] += 1

        return counts

    def _embed_media(
        self,
        session: GraphSession,
        embedder: OllamaEmbedder,
        model_version: str,
        dimensions: int,
    ) -> dict[str, int]:
        counts = {"embedded": 0, "skipped": 0, "reembedded": 0}

        rows = session.read(
            """
            MATCH (c:Creator)-[:HAS_MEDIA]->(m:Media)
            WHERE c.tos_compliant_at_ingest = true
            RETURN m.media_id    AS media_id,
                   m.caption_text AS caption_text,
                   m.embedding_model_version AS stored_version,
                   m.text_hash   AS stored_hash
            """
        )

        to_embed: list[dict] = []
        for row in rows:
            text = (row.get("caption_text") or "").strip()
            if not text:
                counts["skipped"] += 1
                continue
            h = _text_hash(text)
            if row.get("stored_version") == model_version and row.get("stored_hash") == h:
                counts["skipped"] += 1
                continue
            reembed = row.get("stored_version") is not None
            to_embed.append({
                "media_id": row["media_id"],
                "text": text,
                "hash": h,
                "reembed": reembed,
            })

        for batch_start in range(0, len(to_embed), _BATCH_SIZE):
            batch = to_embed[batch_start: batch_start + _BATCH_SIZE]
            texts = [item["text"] for item in batch]
            vectors = embedder.embed(texts)

            rows_payload = [
                {
                    "media_id": item["media_id"],
                    "embedding": vec if isinstance(vec, list) else vec,
                    "model_version": model_version,
                    "text_hash": item["hash"],
                }
                for item, vec in zip(batch, vectors)
            ]
            session.write(
                """
                UNWIND $rows AS row
                MATCH (m:Media {media_id: row.media_id})
                SET m.embedding               = row.embedding,
                    m.embedding_model_version = row.model_version,
                    m.text_hash               = row.text_hash
                """,
                rows=rows_payload,
            )
            for item in batch:
                if item["reembed"]:
                    counts["reembedded"] += 1
                else:
                    counts["embedded"] += 1

        return counts


def run(handle: str, project_dir: Path) -> Path:
    """Entry point called by ``profile_analyst.py --stage 8``."""
    processor = Stage8EmbedProcessor()
    return processor.process(handle, project_dir)
