"""Request / response models for the profile-analyst query API (spec 0007 §4.3)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(..., description="Natural-language question (0003 NL→Cypher).")
    handle: str | None = Field(None, description="Creator handle to scope the query.")


class AskResponse(BaseModel):
    answer: str
    manifest_path: str
    cypher: str | None = None
    row_count: int | None = None


class RagRequest(BaseModel):
    question: str = Field(..., description="Natural-language question (0005 hybrid RAG).")
    handle: str | None = Field(None, description="Optional handle filter; None = whole graph.")
    modes: list[str] | None = Field(
        None, description="Retrieval modes: vector, graph, keyword. None = all three."
    )


class RagResponse(BaseModel):
    answer: str
    citations: list[str]
    manifest_path: str
    modes_run: list[str] | None = None


class HealthResponse(BaseModel):
    status: str
    neo4j: str
    ollama: str
