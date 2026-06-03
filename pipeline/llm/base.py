"""LLM backend ABC + factory + shared Stage 3 helpers (spec 0003 §4.0).

The ABC has one job: turn a normalized profile into the *LLM* slice of the Stage 3 feature
catalog (niche, sentiment, brand affinity, undisclosed-sponsorship inference). The deterministic
features and the schema/compliance gates remain in ``pipeline.stage3_features`` and run identically
regardless of which backend produced the LLM features (spec §7 C6).
"""
from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

_PROMPT_PATH = Path(__file__).parent.parent.parent / "prompts" / "stage3-features.md"
_CONTENT_PROMPT_PATH = Path(__file__).parent.parent.parent / "prompts" / "stage3-content-analysis.md"


# ── request / response ─────────────────────────────────────────────────────────

@dataclass
class FeatureRequest:
    """Input to a backend: the Stage 2 normalized profile."""
    normalized: dict
    retry_context: str | None = None  # injected on retry (spec 0013)


@dataclass
class ContentAnalysisRequest:
    """Input to Stage 3B: windowed post list with full engagement payload."""
    posts: list[dict]   # already-sliced to the content window
    window: int         # len(posts) — for provenance
    retry_context: str | None = None


@dataclass
class FeatureResponse:
    """Output of a backend: the LLM-derived feature objects + provenance."""
    features: list[dict]
    model: str
    backend: str
    data_egress: str  # local-only | anthropic-api
    raw_text: str = ""
    extra: dict = field(default_factory=dict)


# ── shared helpers (used by both backends) ─────────────────────────────────────

def load_feature_prompt() -> str:
    """The Stage 3A system prompt (niche + sponsored detection)."""
    with open(_PROMPT_PATH) as fh:
        return fh.read()


def load_content_analysis_prompt() -> str:
    """The Stage 3B system prompt (content themes, topics, editorial consistency)."""
    with open(_CONTENT_PROMPT_PATH) as fh:
        return fh.read()


def build_content_analysis_payload(posts: list[dict]) -> dict:
    """Compact post list sent to Stage 3B. Captions truncated at 400 chars to bound token cost."""
    return {
        "post_count": len(posts),
        "posts": [
            {
                "index": i + 1,
                "caption": (p.get("caption") or "")[:400],
                "hashtags": p.get("hashtags") or [],
                "likes": p.get("likes") or 0,
                "comments": p.get("comments") or 0,
                "media_type": p.get("media_type") or "IMAGE",
                "timestamp": (p.get("posted_at") or "")[:10],
            }
            for i, p in enumerate(posts)
        ],
    }


def build_feature_payload(normalized: dict) -> dict:
    """Minimized user payload sent to the model (data minimization — same fields for both backends)."""
    return {
        "handle": normalized.get("handle"),
        "bio": normalized.get("bio"),
        "followers": normalized.get("followers"),
        "media": [
            {
                "media_id": m.get("media_id"),
                "media_type": m.get("media_type"),
                "caption": m.get("caption"),
                "hashtags": m.get("hashtags", []),
                "mentions": m.get("mentions", []),
                "is_paid_partnership": m.get("is_paid_partnership", False),
                "paid_partner_handle": m.get("paid_partner_handle"),
            }
            for m in (normalized.get("media") or [])
        ],
    }


def parse_structured_output(text: str) -> list[dict]:
    """Strip markdown code fences and parse the model's JSON feature list.

    Never repairs — a malformed payload raises ``json.JSONDecodeError`` for the caller to surface.
    """
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return json.loads(text)


# ── backend ABC + factory ──────────────────────────────────────────────────────

class LLMBackend(ABC):
    """A pluggable Stage 3 LLM provider."""

    @abstractmethod
    def extract_features(self, req: FeatureRequest) -> FeatureResponse:
        """Stage 3A — niche, sentiment, brand affinity, sponsorship inference."""

    @abstractmethod
    def extract_content_features(self, req: ContentAnalysisRequest) -> FeatureResponse:
        """Stage 3B — content themes, top-performing topics, editorial consistency."""

    @abstractmethod
    def name(self) -> str:
        """Backend identifier (``anthropic`` | ``ollama``)."""


def get_llm_backend(name: str | None, *, anthropic_client=None) -> LLMBackend:
    """Factory: resolve a backend by name (spec §4.0).

    Backends are imported lazily so this module loads without the anthropic SDK / httpx installed.
    """
    resolved = (name or "anthropic").strip().lower()
    if resolved == "anthropic":
        from pipeline.llm.anthropic_backend import AnthropicBackend

        return AnthropicBackend(client=anthropic_client)
    if resolved == "ollama":
        from pipeline.llm.ollama_backend import OllamaBackend

        return OllamaBackend()
    raise ValueError(f"Unknown LLM_BACKEND {name!r} (expected 'anthropic' or 'ollama')")
