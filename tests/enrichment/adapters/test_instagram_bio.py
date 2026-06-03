"""Tests for InstagramBioAdapter (spec-0017 §5) — 9 acceptance criteria."""
import pytest

from pipeline.enrichment.adapter import AdapterConfig, AdapterContext
from pipeline.enrichment.adapters.instagram_bio import InstagramBioAdapter
from pipeline.enrichment.entity import make_entity

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = "2026-06-03T00:00:00Z"


def _make_config(
    *,
    dry_run: bool = False,
    context: AdapterContext | None = None,
) -> AdapterConfig:
    return AdapterConfig(
        profile_id="test-profile",
        run_id="test-run",
        max_depth=3,
        max_cost_usd=1.0,
        max_runtime_s=30,
        secrets={},
        osint_enabled=True,
        cache_enabled=False,
        dry_run=dry_run,
        context=context,
    )


def _seed_handle() -> list:
    return [
        make_entity(
            "handle", "testhandle",
            source="test", confidence=1.0, depth=0, discovered_at=_NOW,
        )
    ]


# ---------------------------------------------------------------------------
# AC 1 — Adapter contract validated at import time (no AdapterContractError)
# ---------------------------------------------------------------------------

def test_adapter_imports_cleanly():
    """Import must not raise AdapterContractError."""
    # If import failed the module would not be loaded; just verify the class exists.
    assert InstagramBioAdapter.adapter_id == "instagram_bio"


# ---------------------------------------------------------------------------
# AC 2 — run() extracts email from config.context.raw_profile["bio"]
# ---------------------------------------------------------------------------

def test_extracts_email_from_bio():
    ctx = AdapterContext(raw_profile={"bio": "Contact me at hello@example.com"})
    config = _make_config(context=ctx)
    result = InstagramBioAdapter().run(_seed_handle(), config)
    types = {e.type for e in result.entities}
    assert "email" in types
    emails = [e.value for e in result.entities if e.type == "email"]
    assert "hello@example.com" in emails


# ---------------------------------------------------------------------------
# AC 3 — run() extracts domain from config.context.raw_profile["website"]
# ---------------------------------------------------------------------------

def test_extracts_domain_from_website_field():
    ctx = AdapterContext(raw_profile={"bio": "", "website": "https://vidacomia.com.br"})
    config = _make_config(context=ctx)
    result = InstagramBioAdapter().run(_seed_handle(), config)
    domains = [e.value for e in result.entities if e.type == "domain"]
    assert "vidacomia.com.br" in domains


# ---------------------------------------------------------------------------
# AC 4 — run() extracts CNPJ from bio text
# ---------------------------------------------------------------------------

def test_extracts_cnpj_from_bio():
    ctx = AdapterContext(raw_profile={"bio": "Empresa: 12.345.678/0001-90 | NF disponível"})
    config = _make_config(context=ctx)
    result = InstagramBioAdapter().run(_seed_handle(), config)
    cnpjs = [e.value for e in result.entities if e.type == "cnpj"]
    assert "12345678000190" in cnpjs


# ---------------------------------------------------------------------------
# AC 5 — run() returns empty result when config.context is None
# ---------------------------------------------------------------------------

def test_returns_empty_when_context_is_none():
    config = _make_config(context=None)
    result = InstagramBioAdapter().run(_seed_handle(), config)
    assert result.entities == []
    assert result.error is None


# ---------------------------------------------------------------------------
# AC 6 — run() returns empty result when config.dry_run is True
# ---------------------------------------------------------------------------

def test_returns_empty_when_dry_run():
    ctx = AdapterContext(raw_profile={"bio": "hello@example.com"})
    config = _make_config(dry_run=True, context=ctx)
    result = InstagramBioAdapter().run(_seed_handle(), config)
    assert result.entities == []
    assert result.error is None


# ---------------------------------------------------------------------------
# AC 7 — run() returns empty result when bio is None or ""
# ---------------------------------------------------------------------------

def test_returns_empty_when_bio_is_empty():
    ctx = AdapterContext(raw_profile={"bio": ""})
    config = _make_config(context=ctx)
    result = InstagramBioAdapter().run(_seed_handle(), config)
    assert result.entities == []


def test_returns_empty_when_bio_is_none():
    ctx = AdapterContext(raw_profile={"bio": None})
    config = _make_config(context=ctx)
    result = InstagramBioAdapter().run(_seed_handle(), config)
    assert result.entities == []


# ---------------------------------------------------------------------------
# AC 8 — result.cost_usd == 0.0 always
# ---------------------------------------------------------------------------

def test_cost_is_always_zero():
    ctx = AdapterContext(raw_profile={"bio": "hello@example.com"})
    config = _make_config(context=ctx)
    result = InstagramBioAdapter().run(_seed_handle(), config)
    assert result.cost_usd == 0.0


# ---------------------------------------------------------------------------
# AC 9a — All entities have source == "instagram_bio"
# ---------------------------------------------------------------------------

def test_all_entities_have_correct_source():
    ctx = AdapterContext(
        raw_profile={"bio": "Contact: info@brand.com | CNPJ: 12.345.678/0001-90"}
    )
    config = _make_config(context=ctx)
    result = InstagramBioAdapter().run(_seed_handle(), config)
    assert len(result.entities) > 0
    for ent in result.entities:
        assert ent.source == "instagram_bio"


# ---------------------------------------------------------------------------
# AC 9b — bio_entity_count signal present in result.signals
# ---------------------------------------------------------------------------

def test_bio_entity_count_signal_present():
    ctx = AdapterContext(raw_profile={"bio": "hello@example.com"})
    config = _make_config(context=ctx)
    result = InstagramBioAdapter().run(_seed_handle(), config)
    signal_keys = [s.key for s in result.signals]
    assert "bio_entity_count" in signal_keys
    count_signal = next(s for s in result.signals if s.key == "bio_entity_count")
    assert count_signal.value == len(result.entities)
