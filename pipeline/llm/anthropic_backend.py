"""Anthropic Stage 3 backend (spec 0003 §4.0).

The existing Stage 3 Anthropic call, moved behind :class:`LLMBackend` with no semantic change —
output is byte-identical to the pre-refactor path for a fixed input (regression-tested).
"""
from __future__ import annotations

import json
import os
from typing import Any

from pipeline.llm.base import (
    ContentAnalysisRequest,
    FeatureRequest,
    FeatureResponse,
    LLMBackend,
    build_content_analysis_payload,
    build_feature_payload,
    load_content_analysis_prompt,
    load_feature_prompt,
    parse_structured_output,
)

_MODEL = "claude-sonnet-4-6"


class AnthropicBackend(LLMBackend):
    def __init__(self, client: Any = None) -> None:
        self._client = client

    def name(self) -> str:
        return "anthropic"

    def _ensure_client(self) -> Any:
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
        return self._client

    def extract_features(self, req: FeatureRequest) -> FeatureResponse:
        client = self._ensure_client()
        system_prompt = load_feature_prompt()
        user_payload = build_feature_payload(req.normalized)

        messages = [
            {
                "role": "user",
                "content": json.dumps(user_payload, ensure_ascii=False),
            }
        ]
        if req.retry_context is not None:
            messages.append({"role": "user", "content": req.retry_context})

        response = client.messages.create(
            model=_MODEL,
            max_tokens=4096,
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=messages,
        )

        text = response.content[0].text.strip()
        features = parse_structured_output(text)
        return FeatureResponse(
            features=features,
            model=_MODEL,
            backend="anthropic",
            data_egress="anthropic-api",
            raw_text=text,
        )

    def extract_content_features(self, req: ContentAnalysisRequest) -> FeatureResponse:
        client = self._ensure_client()
        system_prompt = load_content_analysis_prompt()
        user_payload = build_content_analysis_payload(req.posts)

        messages = [{"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)}]
        if req.retry_context is not None:
            messages.append({"role": "user", "content": req.retry_context})

        response = client.messages.create(
            model=_MODEL,
            max_tokens=2048,
            system=[{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
            messages=messages,
        )

        text = response.content[0].text.strip()
        features = parse_structured_output(text)
        return FeatureResponse(
            features=features,
            model=_MODEL,
            backend="anthropic",
            data_egress="anthropic-api",
            raw_text=text,
        )
