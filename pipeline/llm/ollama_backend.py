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


def _array_format(item_schema: dict) -> dict:
    """Ollama structured-output schema — a top-level array whose items match the feature item schema.

    ``format:"json"`` only guarantees *some* JSON value, so small local models emit a single object
    instead of the required array. Constraining the grammar to ``array`` fixes that; and because
    Ollama enforces JSON-Schema ``required`` in its grammar, each object is forced to carry the
    mandatory fields (``confidence``, ``method`` …) rather than relying on the model to remember.

    We also tighten ``value`` to non-object types: every legitimate Stage 3 value is a string (niche,
    sentiment, status) or an array (lists, brand objects) — never a bare object. The permissive
    ``value: {}`` in the real schema otherwise lets the grammar emit maps like ``{"Sports": 0.9}``
    that pass validation but are semantically wrong downstream. The deep copy keeps the *validation*
    schema (still ``value: {}``) untouched.
    """
    item = json.loads(json.dumps(item_schema))  # deep copy — don't mutate the validation schema
    item.setdefault("properties", {})["value"] = {
        "type": ["string", "array", "number", "boolean", "null"]
    }
    return {"type": "array", "items": item}


def _coerce_to_feature_list(parsed: object, *, model: str) -> list:
    """Normalize the model's top-level *container* to a list of feature dicts.

    Small local models sometimes wrap the array in an object (``{"features": [...]}``) or return a
    single feature object instead of a one-element array. We normalize the **container shape only** —
    individual feature *content* is still validated strictly downstream and never repaired (C6).
    """
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        for key in ("features", "feature_list", "items", "result", "results", "data"):
            if isinstance(parsed.get(key), list):
                return parsed[key]
        list_values = [v for v in parsed.values() if isinstance(v, list)]
        if len(list_values) == 1:
            return list_values[0]
        if "feature_id" in parsed:  # a single feature object → wrap it
            return [parsed]
    raise ValueError(
        f"Ollama model {model} returned {type(parsed).__name__}, expected a JSON array of features."
    )


class OllamaBackend(LLMBackend):
    def __init__(self, client: OllamaClient | None = None, model: str | None = None) -> None:
        self._client = client or OllamaClient()
        self._model = model or os.environ.get("OLLAMA_FEATURES_MODEL", _DEFAULT_MODEL)

    def name(self) -> str:
        return "ollama"

    def extract_features(self, req: FeatureRequest) -> FeatureResponse:
        system_prompt = load_feature_prompt()
        user_payload = build_feature_payload(req.normalized)
        item_schema = _feature_item_schema()

        # OllamaError (unreachable host / non-2xx) propagates to Stage 3 for fallback handling.
        text = self._client.chat(
            self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            options={"temperature": 0, "seed": 0},  # determinism (OQ4)
            fmt=_array_format(item_schema),
        )

        try:
            parsed = parse_structured_output(text)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Ollama model {self._model} returned non-JSON Stage 3 output: {exc}"
            ) from exc
        features = _coerce_to_feature_list(parsed, model=self._model)

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
