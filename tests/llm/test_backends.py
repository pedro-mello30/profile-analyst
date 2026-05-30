"""LLM backend tests — Anthropic parity, Ollama schema validity, fallback (A6, A8).

Ollama HTTP is mocked with respx (exercises the real OllamaClient over httpx). No live services.
"""
import json
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import jsonschema
import pytest
import respx
from httpx import Response

from pipeline.llm import FeatureRequest, get_llm_backend
from pipeline.llm.ollama_backend import OllamaBackend
from pipeline.llm.ollama_client import OllamaClient, OllamaError

FIXTURE_ROOT = Path(__file__).parent.parent / "fixtures"

_LLM_FEATURES = [
    {"feature_id": "primary_niche", "value": "Fitness/Health", "unit": None,
     "confidence": 0.88, "method": "llm", "art9_risk": False,
     "signals": ["hashtags FitnessMotivation"], "notes": None},
    {"feature_id": "caption_sentiment", "value": "positive", "unit": None,
     "confidence": 0.82, "method": "llm", "art9_risk": False,
     "signals": ["motivational language"], "notes": None},
]


def _normalized():
    return json.loads((FIXTURE_ROOT / "02-normalized.json").read_text())


# ── factory ─────────────────────────────────────────────────────────────────

def test_factory_returns_named_backends():
    assert get_llm_backend("anthropic").name() == "anthropic"
    assert get_llm_backend("ollama").name() == "ollama"
    assert get_llm_backend(None).name() == "anthropic"


def test_factory_rejects_unknown():
    with pytest.raises(ValueError):
        get_llm_backend("gpt5")


# ── Anthropic parity (A6 reference path unchanged) ──────────────────────────────

def test_anthropic_backend_parses_features():
    client = MagicMock()
    msg = MagicMock()
    msg.content = [MagicMock(text=json.dumps(_LLM_FEATURES))]
    client.messages.create.return_value = msg

    backend = get_llm_backend("anthropic", anthropic_client=client)
    resp = backend.extract_features(FeatureRequest(_normalized()))

    assert resp.data_egress == "anthropic-api"
    assert resp.model == "claude-sonnet-4-6"
    assert [f["feature_id"] for f in resp.features] == ["primary_niche", "caption_sentiment"]
    # the call uses prompt caching on the system block (parity with pre-refactor)
    _, kwargs = client.messages.create.call_args
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}


# ── Ollama backend (A6 — schema-valid output, method forced to llm) ─────────────

@respx.mock
def test_ollama_backend_schema_valid_and_method_llm():
    payload = [
        {"feature_id": "primary_niche", "value": "Fitness", "confidence": 0.8,
         "art9_risk": False, "signals": ["hashtags"]},  # method omitted on purpose
    ]
    respx.post("http://localhost:11434/api/chat").mock(
        return_value=Response(200, json={"message": {"content": json.dumps(payload)}})
    )
    backend = OllamaBackend(client=OllamaClient(host="http://localhost:11434"), model="qwen2.5:14b")
    resp = backend.extract_features(FeatureRequest(_normalized()))

    assert resp.data_egress == "local-only"
    item_schema = json.loads((Path("schemas/03-features.schema.json")).read_text())[
        "properties"]["features"]["items"]
    for feat in resp.features:
        assert feat["method"] == "llm"  # C6
        jsonschema.validate(feat, item_schema)


@respx.mock
def test_ollama_backend_invalid_json_raises_valueerror():
    respx.post("http://localhost:11434/api/chat").mock(
        return_value=Response(200, json={"message": {"content": "not json{"}})
    )
    backend = OllamaBackend(client=OllamaClient(), model="qwen2.5:14b")
    with pytest.raises(ValueError):
        backend.extract_features(FeatureRequest(_normalized()))


@respx.mock
def test_ollama_client_unreachable_raises_ollamaerror():
    import httpx
    respx.post("http://localhost:11434/api/chat").mock(
        side_effect=httpx.ConnectError("refused")
    )
    with pytest.raises(OllamaError) as ei:
        OllamaClient().chat("qwen2.5:14b", [{"role": "user", "content": "hi"}])
    assert "Failed to reach Ollama" in str(ei.value)


@respx.mock
def test_ollama_client_http_error_raises_ollamaerror():
    respx.post("http://localhost:11434/api/chat").mock(return_value=Response(500, text="boom"))
    with pytest.raises(OllamaError) as ei:
        OllamaClient().chat("qwen2.5:14b", [{"role": "user", "content": "hi"}])
    assert "HTTP 500" in str(ei.value)


# ── Stage 3 fallback (A8) ───────────────────────────────────────────────────────

def _anthropic_client():
    client = MagicMock()
    msg = MagicMock()
    msg.content = [MagicMock(text=json.dumps(_LLM_FEATURES))]
    client.messages.create.return_value = msg
    return client


def test_stage3_falls_back_to_anthropic_when_ollama_down(tmp_path, monkeypatch):
    import pipeline.stage3_features as s3

    shutil.copy(FIXTURE_ROOT / "02-normalized.json", tmp_path / "02-normalized.json")
    monkeypatch.setenv("LLM_BACKEND", "ollama")
    monkeypatch.setenv("ASK_FALLBACK", "true")

    def boom(self, req):
        raise OllamaError("Failed to reach Ollama at http://localhost:11434")

    with patch.object(OllamaBackend, "extract_features", boom):
        out = s3.run("sample_creator", tmp_path, anthropic_client=_anthropic_client())
    ids = [f["feature_id"] for f in json.loads(out.read_text())["features"]]
    assert "primary_niche" in ids  # came from the Anthropic fallback


def test_stage3_reraises_when_fallback_disabled(tmp_path, monkeypatch):
    import pipeline.stage3_features as s3

    shutil.copy(FIXTURE_ROOT / "02-normalized.json", tmp_path / "02-normalized.json")
    monkeypatch.setenv("LLM_BACKEND", "ollama")
    monkeypatch.setenv("ASK_FALLBACK", "false")

    def boom(self, req):
        raise OllamaError("down")

    with patch.object(OllamaBackend, "extract_features", boom):
        with pytest.raises(OllamaError):
            s3.run("sample_creator", tmp_path, anthropic_client=_anthropic_client())
