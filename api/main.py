"""FastAPI service — read-only query surface for the profile-analyst pipeline.

Spec 0007 §4.3. Two endpoints delegate entirely to existing tool functions:
  POST /ask  → tools.ask.ask()   (spec 0003 NL→Cypher, inherits S1–S6 + read-only txn)
  POST /rag  → tools.rag.run()   (spec 0005 hybrid RAG, inherits fusion/safety)
  GET  /healthz                  → 200 when Neo4j + Ollama reachable, else 503

No new analytics, no new safety logic, no write path.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from api.deps import check_dependencies, shutdown, startup
from api.models import AskRequest, AskResponse, HealthResponse, RagRequest, RagResponse

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Observability init (no-op when OBSERVABILITY_ENABLED is falsy — spec 0006 D4/D8).
    try:
        from observability import init_tracing
        init_tracing()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Observability init failed (continuing without tracing): %s", exc)

    await startup()
    yield
    await shutdown()


app = FastAPI(
    title="profile-analyst API",
    description="Read-only query surface: NL→Cypher (/ask) and Hybrid RAG (/rag).",
    version="0.1.0",
    lifespan=lifespan,
)


@app.post("/ask", response_model=AskResponse)
async def ask_endpoint(req: AskRequest) -> AskResponse:
    """NL→Cypher query (spec 0003). Inherits S1–S6 read-only safety gates."""
    from tools.ask import ask

    if not req.handle:
        raise HTTPException(status_code=422, detail="handle is required for /ask")

    result = ask(req.handle, req.question)

    if result.exit_code != 0:
        manifest = result.manifest or {}
        reasons = manifest.get("validation", {}).get("reasons", [])
        raise HTTPException(
            status_code=422,
            detail={"error": "Query rejected or failed", "reasons": reasons},
        )

    manifest = result.manifest or {}
    return AskResponse(
        answer=manifest.get("answer", ""),
        manifest_path=str(result.manifest_path or ""),
        cypher=manifest.get("cypher"),
        row_count=manifest.get("row_count"),
    )


@app.post("/rag", response_model=RagResponse)
async def rag_endpoint(req: RagRequest) -> RagResponse:
    """Hybrid RAG query (spec 0005). Inherits fusion/safety unchanged."""
    from tools.rag import run

    manifest = run(req.question, handle=req.handle, modes=req.modes)

    return RagResponse(
        answer=manifest.get("answer", ""),
        citations=manifest.get("citations", []),
        manifest_path=str(manifest.get("manifest_path", "")),
        modes_run=manifest.get("modes_run"),
    )


@app.get("/healthz", response_model=HealthResponse)
async def healthz() -> HealthResponse:
    """Readiness check. Returns 503 if Neo4j or Ollama is unreachable."""
    deps = await check_dependencies()
    all_ok = all(v == "ok" for v in deps.values())
    if not all_ok:
        raise HTTPException(
            status_code=503,
            detail=HealthResponse(status="degraded", **deps).model_dump(),
        )
    return HealthResponse(status="ok", **deps)
