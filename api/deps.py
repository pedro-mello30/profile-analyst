"""Shared dependency lifetimes for the FastAPI service (spec 0007 §4.3).

Neo4j driver and Ollama client are created once at startup and closed on shutdown.
``check_dependencies()`` is used by GET /healthz to confirm both are reachable.
"""
from __future__ import annotations

import logging

import httpx

from pipeline.graph.connection import graph_config
from pipeline.llm.ollama_client import OllamaClient

logger = logging.getLogger(__name__)

_driver = None
_ollama: OllamaClient | None = None


def get_driver():
    return _driver


def get_ollama() -> OllamaClient | None:
    return _ollama


async def startup() -> None:
    global _driver, _ollama
    try:
        from neo4j import GraphDatabase

        cfg = graph_config()
        _driver = GraphDatabase.driver(cfg["uri"], auth=(cfg["user"], cfg["password"]))
        logger.info("Neo4j driver connected: %s", cfg["uri"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("Neo4j driver init failed (healthz will report unhealthy): %s", exc)
        _driver = None

    try:
        _ollama = OllamaClient()
        logger.info("Ollama client ready: %s", _ollama.host)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Ollama client init failed: %s", exc)
        _ollama = None


async def shutdown() -> None:
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None


async def check_dependencies() -> dict[str, str]:
    """Return {neo4j: ok|error, ollama: ok|error}. Used by /healthz."""
    results: dict[str, str] = {}

    # Neo4j
    if _driver is None:
        results["neo4j"] = "unavailable"
    else:
        try:
            with _driver.session() as s:
                s.run("RETURN 1").consume()
            results["neo4j"] = "ok"
        except Exception as exc:  # noqa: BLE001
            results["neo4j"] = f"error: {exc}"

    # Ollama — hit /api/tags
    if _ollama is None:
        results["ollama"] = "unavailable"
    else:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                r = await client.get(f"{_ollama.host}/api/tags")
                results["ollama"] = "ok" if r.status_code == 200 else f"http {r.status_code}"
        except Exception as exc:  # noqa: BLE001
            results["ollama"] = f"error: {exc}"

    return results
