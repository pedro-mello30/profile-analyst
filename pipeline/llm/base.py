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


# ── request / response ─────────────────────────────────────────────────────────

@dataclass
class FeatureRequest:
    """Input to a backend: the Stage 2 normalized profile."""
    normalized: dict
    retry_context: str | None = None  # injected on retry (spec 0013)


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
    """The Stage 3 system prompt (niche + sponsored detection)."""
    with open(_PROMPT_PATH) as fh:
        return fh.read()


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
        """Return the LLM-derived feature objects for *req*."""

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
