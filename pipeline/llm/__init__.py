"""Pluggable Stage 3 LLM backends (spec 0003 §4.0).

``get_llm_backend(name)`` returns an :class:`LLMBackend` (``anthropic`` | ``ollama``).
Both emit feature lists that validate against the unchanged ``03-features.schema.json``.
"""
from pipeline.llm.base import (
    ContentAnalysisRequest,
    FeatureRequest,
    FeatureResponse,
    LLMBackend,
    get_llm_backend,
)
from pipeline.llm.ollama_client import OllamaClient, OllamaError

__all__ = [
    "ContentAnalysisRequest",
    "FeatureRequest",
    "FeatureResponse",
    "LLMBackend",
    "get_llm_backend",
    "OllamaClient",
    "OllamaError",
]
