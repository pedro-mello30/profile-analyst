"""Tests for AdapterContext and its integration into AdapterConfig (spec 0017 §3)."""
from pipeline.enrichment.adapter import AdapterConfig, AdapterContext


def test_adapter_config_accepts_context():
    ctx = AdapterContext(
        raw_profile={"handle": "filipelauar", "bio": "contato@x.com"},
        raw_media=[],
        source_platform="instagram",
    )
    cfg = AdapterConfig(
        profile_id="filipelauar", run_id="r1", max_depth=2,
        max_cost_usd=0.5, max_runtime_s=600, secrets={},
        osint_enabled=True, cache_enabled=True, dry_run=False,
        context=ctx,
    )
    assert cfg.context.raw_profile["bio"] == "contato@x.com"
    assert cfg.context.source_platform == "instagram"


def test_adapter_config_context_is_optional():
    cfg = AdapterConfig(
        profile_id="x", run_id="r1", max_depth=2,
        max_cost_usd=0.5, max_runtime_s=600, secrets={},
        osint_enabled=True, cache_enabled=True, dry_run=False,
    )
    assert cfg.context is None


def test_adapter_context_raw_media_defaults_to_none():
    ctx = AdapterContext(raw_profile={"handle": "x"})
    assert ctx.raw_media is None
    assert ctx.source_platform is None
