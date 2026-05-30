"""Ollama Stage 3 backend (spec 0003 §4.0, §7 C6).

Runs Stage 3 LLM feature extraction against a local Ollama model. Strips code fences, parses
JSON, validates every feature against the ``03-features.schema.json`` item schema, and forces
``method = "llm"`` (C6). **Never silently repairs**: invalid JSON or a schema violation raises
``ValueError`` (which does NOT trigger the Stage 3 Anthropic fallback — only an unreachable host,
surfaced as ``OllamaError``, does).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import jsonschema

from pipeline.llm.base import (
    FeatureRequest,
    FeatureResponse,
    LLMBackend,
    build_feature_payload,
    load_feature_prompt,
    parse_structured_output,
)
from pipeline.llm.ollama_client import OllamaClient

_SCHEMA_PATH = Path(__file__).parent.parent.parent / "schemas" / "03-features.schema.json"
_DEFAULT_MODEL = "qwen2.5:14b"


def _feature_item_schema() -> dict:
    with open(_SCHEMA_PATH) as fh:
        schema = json.load(fh)
    return schema["properties"]["features"]["items"]


class OllamaBackend(LLMBackend):
    def __init__(self, client: OllamaClient | None = None, model: str | None = None) -> None:
        self._client = client or OllamaClient()
        self._model = model or os.environ.get("OLLAMA_FEATURES_MODEL", _DEFAULT_MODEL)

    def name(self) -> str:
        return "ollama"

    def extract_features(self, req: FeatureRequest) -> FeatureResponse:
        system_prompt = load_feature_prompt()
        user_payload = build_feature_payload(req.normalized)

        # OllamaError (unreachable host / non-2xx) propagates to Stage 3 for fallback handling.
        text = self._client.chat(
            self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            options={"temperature": 0, "seed": 0},  # determinism (OQ4)
            fmt="json",
        )

        try:
            features = parse_structured_output(text)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Ollama model {self._model} returned non-JSON Stage 3 output: {exc}"
            ) from exc
        if not isinstance(features, list):
            raise ValueError(
                f"Ollama model {self._model} returned {type(features).__name__}, expected a JSON array of features."
            )

        item_schema = _feature_item_schema()
        validated: list[dict] = []
        for feat in features:
            feat = dict(feat)
            feat["method"] = "llm"  # C6 — Ollama-derived features are always method=llm
            try:
                jsonschema.validate(feat, item_schema)
            except jsonschema.ValidationError as exc:
                raise ValueError(
                    f"Ollama Stage 3 feature failed schema validation "
                    f"({feat.get('feature_id', '<no id>')}): {exc.message}"
                ) from exc
            validated.append(feat)

        return FeatureResponse(
            features=validated,
            model=self._model,
            backend="ollama",
            data_egress="local-only",
            raw_text=text,
        )
