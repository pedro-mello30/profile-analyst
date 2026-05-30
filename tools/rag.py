"""Hybrid RAG orchestrator — ``--rag "<question>"`` (spec 0005 §4/§8 / Track G).

Question → embed → [vector | keyword | graph] → RRF fuse → (rerank?) → generate → manifest.

All retrieval and generation run on-host; ``data_egress: local-only`` is always recorded.
The generated answer is grounded *only* in retrieved records; zero-result queries say so
without fabrication (0003 C5).

Art. 9 signals trigger an explicit notice. Art. 22 signal lineage is included for any
ranking answer. The orchestrator is advisory-only; a human confirms campaign selection.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import jsonschema

from pipeline.llm.ollama_client import OllamaClient, OllamaError
from pipeline.llm.ollama_embed import OllamaEmbedder
from pipeline.rag.fusion import RRFFusion
from pipeline.rag.rerank import CrossEncoderReranker
from observability import init_tracing, trace, CHAIN, RETRIEVER

_MANIFEST_SCHEMA = Path(__file__).parent.parent / "schemas" / "10-rag.schema.json"

init_tracing()  # no-op when OBSERVABILITY_ENABLED is falsy


class RAGError(RuntimeError):
    """Raised when all retrievers return zero candidates."""


class HybridRAGOrchestrator:
    """Orchestrate one hybrid RAG query.

    Args:
        embedder: ``OllamaEmbedder`` for question embedding. Defaults from env.
        ollama: ``OllamaClient`` for generation. Defaults from env.
        fusion: ``RRFFusion`` instance. Defaults from env constants.
        reranker: ``CrossEncoderReranker``. Defaults from env (off).
    """

    def __init__(
        self,
        embedder: OllamaEmbedder | None = None,
        ollama: OllamaClient | None = None,
        fusion: RRFFusion | None = None,
        reranker: CrossEncoderReranker | None = None,
    ) -> None:
        self._embedder = embedder or OllamaEmbedder()
        self._ollama = ollama or OllamaClient()
        self._fusion = fusion or RRFFusion()
        self._reranker = reranker or CrossEncoderReranker()

    @trace(CHAIN)
    def query(
        self,
        question: str,
        handle: str | None = None,
        modes: list[str] | None = None,
    ) -> dict[str, Any]:
        """Run one hybrid RAG query.

        Args:
            question: The user's natural-language question.
            handle: Optional graph filter (Creator handle). None = whole-graph corpus.
            modes: Which retrieval modes to run. Defaults to ``RAG_MODES`` env var.

        Returns:
            The full RAG manifest dict (matches ``10-rag.schema.json``).

        Raises:
            OllamaError: if Ollama is unreachable for embedding or generation.
            RAGError: if all modes return zero candidates.
        """
        active_modes = modes or _parse_modes(os.environ.get("RAG_MODES", "vector,graph,keyword"))
        started = time.monotonic()

        # 1. Embed the question once
        question_embedding = self._embedder.embed(question)

        # 2. Run retrievers (graceful degradation)
        retriever_results, retriever_manifest, retriever_errors = self._run_retrievers(
            question=question,
            question_embedding=question_embedding,
            handle=handle,
            active_modes=active_modes,
        )

        if all(len(v) == 0 for v in retriever_results.values()):
            raise RAGError(
                f"All retrievers ({', '.join(active_modes)}) returned zero candidates. "
                "Check that --stage 8 has been run and Neo4j + Ollama are reachable."
            )

        # 3. Fuse
        fused = self._fusion.fuse(retriever_results)
        fusion_manifest = self._fusion.fusion_manifest(retriever_results, fused)

        # 4. Rerank (optional)
        final_candidates = self._reranker.rerank(question, fused)
        rerank_manifest = self._reranker.manifest_block()

        # 5. Expand context + check Art. 9
        context_block, citations, art9_present = self._build_context(final_candidates)

        # 6. Generate answer
        gen_started = time.monotonic()
        gen_model = os.environ.get("OLLAMA_FEATURES_MODEL", "qwen2.5:14b")
        answer = self._generate(
            question=question,
            context=context_block,
            art9_present=art9_present,
            gen_model=gen_model,
        )
        gen_latency = int((time.monotonic() - gen_started) * 1000)

        total_latency = int((time.monotonic() - started) * 1000)

        manifest = {
            "question": question,
            "handle": handle,
            "modes_run": active_modes,
            "retrievers": retriever_manifest,
            "fusion": fusion_manifest,
            "rerank": rerank_manifest,
            "generation": {"model": gen_model, "latency_ms": gen_latency},
            "answer": answer,
            "citations": citations,
            "row_counts": {m: len(v) for m, v in retriever_results.items()},
            "latency_ms": total_latency,
            "data_egress": "local-only",
            "asked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

        with open(_MANIFEST_SCHEMA) as fh:
            schema = json.load(fh)
        jsonschema.validate(manifest, schema)

        return manifest

    @trace(RETRIEVER)
    def _run_retrievers(
        self,
        question: str,
        question_embedding: list[float],
        handle: str | None,
        active_modes: list[str],
    ) -> tuple[dict, dict, dict]:
        """Run each active mode independently; failures are logged, not raised."""
        from pipeline.graph.connection import GraphSession
        from pipeline.rag.retrievers import VectorRetriever, KeywordRetriever, GraphRetriever

        results: dict[str, list] = {m: [] for m in active_modes}
        manifest: dict[str, dict] = {}
        errors: dict[str, str] = {}

        with GraphSession() as session:
            for mode in active_modes:
                mode_start = time.monotonic()
                try:
                    if mode == "vector":
                        retriever = VectorRetriever(session)
                        candidates = retriever.retrieve(question_embedding)
                    elif mode == "keyword":
                        retriever = KeywordRetriever(session)
                        candidates = retriever.retrieve(question)
                    elif mode == "graph":
                        retriever = GraphRetriever(handle=handle)
                        candidates = retriever.retrieve(question)
                    else:
                        candidates = []
                    results[mode] = candidates
                    manifest[mode] = {
                        "k": int(os.environ.get(f"RAG_{mode.upper()}_K", 50)),
                        "candidates": len(candidates),
                        "latency_ms": int((time.monotonic() - mode_start) * 1000),
                        "error": None,
                        "index": _index_name(mode),
                        "cypher": None,
                        "safety_gates_passed": (mode == "graph") or None,
                    }
                except Exception as exc:
                    errors[mode] = str(exc)
                    manifest[mode] = {
                        "k": int(os.environ.get(f"RAG_{mode.upper()}_K", 50)),
                        "candidates": 0,
                        "latency_ms": int((time.monotonic() - mode_start) * 1000),
                        "error": str(exc),
                        "index": None,
                        "cypher": None,
                        "safety_gates_passed": None,
                    }

        return results, manifest, errors

    def _build_context(
        self,
        candidates: list[dict],
    ) -> tuple[str, list[dict], bool]:
        """Expand candidates into a context block and citation list."""
        from pipeline.graph.connection import GraphSession

        citations: list[dict] = []
        art9_present = False
        context_lines: list[str] = []

        if not candidates:
            return "No candidates were retrieved.", citations, art9_present

        with GraphSession() as session:
            for cand in candidates:
                uid = cand.get("user_id", "")
                if not uid:
                    continue

                # Fetch enriched data
                rows = session.read(
                    """
                    MATCH (c:Creator {user_id: $uid})
                    OPTIONAL MATCH (c)-[:HAS_SIGNAL]->(sig:Signal)
                    RETURN c.username          AS username,
                           c.followers_count  AS followers,
                           c.bio              AS bio,
                           collect({
                               name: sig.name,
                               value: sig.value,
                               confidence: sig.confidence,
                               method: sig.method,
                               art9_risk: sig.art9_risk
                           }) AS signals
                    LIMIT 1
                    """,
                    uid=uid,
                )
                if not rows:
                    continue
                row = rows[0]
                username = row.get("username", uid)

                # Art. 9 check
                for sig in row.get("signals", []):
                    if sig.get("art9_risk"):
                        art9_present = True

                context_lines.append(
                    f"Creator @{username} (user_id={uid})\n"
                    f"  Followers: {row.get('followers', 'unknown')}\n"
                    f"  Bio: {(row.get('bio') or 'n/a')[:200]}\n"
                    f"  Signals: {json.dumps(row.get('signals', [])[:5])}"
                )
                citations.append({"type": "creator", "user_id": uid, "handle": username})

        context = "\n\n".join(context_lines) if context_lines else "No enriched data found."
        return context, citations, art9_present

    def _generate(
        self,
        question: str,
        context: str,
        art9_present: bool,
        gen_model: str,
    ) -> str:
        """Generate a grounded, cited answer using the 0003 OllamaClient."""
        art9_notice = (
            "\n\n⚠️ GDPR Art. 9 NOTICE: Some retrieved signals relate to special-category data "
            "(health, religion, political views, sexual orientation). Handle with explicit consent."
            if art9_present
            else ""
        )

        if not context.strip() or context == "No candidates were retrieved.":
            return (
                "No matching creators were found for this query. "
                "Try broadening your search terms or running --stage 8 to ensure embeddings exist."
                + art9_notice
            )

        system_prompt = (
            "You are an influencer marketing analyst. Answer the question using ONLY the "
            "creator data provided below. Do not invent facts. Cite each claim with the "
            "creator handle (@username) or user_id. For any ranking, explain which signals "
            "drove it (GDPR Art. 22 explainability). This analysis is advisory only — "
            "a human must confirm any final campaign selection decision."
        )
        user_message = (
            f"Creator data:\n{context}\n\n"
            f"Question: {question}\n\n"
            "Answer only from the data above. If the data does not contain enough information "
            "to answer, say so explicitly rather than guessing."
            + art9_notice
        )

        try:
            answer = self._ollama.chat(
                model=gen_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                options={"temperature": 0.2},
            )
        except OllamaError:
            answer = (
                "[Generation failed — Ollama unreachable. "
                "Retrieved context is available in the manifest's citations.]"
            )

        return answer.strip() or "No answer generated."


def _parse_modes(raw: str) -> list[str]:
    return [m.strip() for m in raw.split(",") if m.strip()]


def _index_name(mode: str) -> str | None:
    mapping = {
        "vector": "creator_embeddings / media_embeddings",
        "keyword": "creator_fulltext / media_fulltext",
        "graph": None,
    }
    return mapping.get(mode)


def run(
    question: str,
    handle: str | None = None,
    modes: list[str] | None = None,
    project_dir: Path | None = None,
) -> dict[str, Any]:
    """Entry point called by ``profile_analyst.py --rag``."""
    orch = HybridRAGOrchestrator()
    manifest = orch.query(question, handle=handle, modes=modes)

    if project_dir is not None:
        queries_dir = project_dir / "queries"
        queries_dir.mkdir(parents=True, exist_ok=True)
        ts = manifest["asked_at"].replace(":", "").replace("-", "")
        out_path = queries_dir / f"{ts}-rag.json"
        tmp = out_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(manifest, indent=2))
        os.replace(tmp, out_path)

    return manifest
