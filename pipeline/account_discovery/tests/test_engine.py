"""Tests for DiscoveryEngine (spec-0018 §6)."""
from pipeline.account_discovery.engine import DiscoveryEngine, DiscoveryEngineState
from pipeline.account_discovery.scheduler import DiscoveryConfig
from pipeline.account_discovery.pool import AccountPool
from pipeline.account_discovery.contracts import DiscoveryAdapter
from pipeline.account_discovery.models import AttributionStep, DiscoveredAccount
from datetime import datetime, timezone

NOW = datetime.now(timezone.utc)


def _account(platform, handle):
    return DiscoveredAccount(
        account_id=f"{platform}-{handle}", platform=platform, handle=handle,
        profile_url=f"https://{platform}.com/{handle}",
        confidence=0.9, method="test", source_adapter_id="bio_parser",
        attribution_chain=[AttributionStep("bio_parser", "instagram_handle", "seed", "bio")],
        discovered_at=NOW,
    )


class FakeBioParser(DiscoveryAdapter):
    adapter_id = "bio_parser_test"; display_name = "Bio"
    requires = ["instagram_handle"]; produces = ["platform_handle"]
    priority = 1; timeout_s = 1.0; retry_max = 0
    data_category = "PUBLIC_API"; tos_compliant = True; robots_txt_policy = "N/A"

    def run(self, seed_entities, config):
        return [_account("youtube", "creator123")]


def _seed():
    class E:
        pass
    e = E()
    e.type = "instagram_handle"
    e.value = "creator"
    return [e]


def test_engine_runs_adapter_adds_to_pool():
    pool = AccountPool()
    state = DiscoveryEngineState()
    engine = DiscoveryEngine(adapters=[FakeBioParser()], config=DiscoveryConfig())
    engine.run(pool, _seed(), state)
    assert pool.get("youtube", "creator123") is not None


def test_limit_reached_on_max_adapters_zero():  # AC6
    pool = AccountPool()
    state = DiscoveryEngineState()
    engine = DiscoveryEngine(adapters=[FakeBioParser()], config=DiscoveryConfig(max_adapters=0))
    engine.run(pool, _seed(), state)
    assert state.limit_reached is True


def test_governance_report_populated():
    pool = AccountPool()
    state = DiscoveryEngineState()
    engine = DiscoveryEngine(adapters=[FakeBioParser()], config=DiscoveryConfig())
    engine.run(pool, _seed(), state)
    assert state.governance_report is not None
    assert state.governance_report.module == "account_discovery"


def test_invalid_adapter_filtered_at_startup():
    from types import SimpleNamespace
    bad = SimpleNamespace(adapter_id="bad", display_name="Bad")  # missing most fields
    pool = AccountPool()
    state = DiscoveryEngineState()
    engine = DiscoveryEngine(adapters=[bad, FakeBioParser()], config=DiscoveryConfig())
    engine.run(pool, _seed(), state)
    assert any(e["adapter_id"] == "bad" for e in state.adapter_errors)
    assert pool.get("youtube", "creator123") is not None  # FakeBioParser still ran
