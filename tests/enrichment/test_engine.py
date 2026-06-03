import pytest
from pathlib import Path
from pipeline.enrichment.engine import EngineConfig, EngineState, is_runnable, run_engine
from pipeline.enrichment.entity import make_entity
from pipeline.enrichment.entity_pool import EntityPool
from pipeline.enrichment.adapter import AdapterConfig, AdapterResult, Signal, EnrichmentAdapter

TS = "2026-06-02T21:00:00Z"
YT_ID = "UCxyz1234567890123456789"   # valid 24-char UC* id


class FakeYouTubeAdapter(EnrichmentAdapter):
    adapter_id = "youtube_test"; display_name = "YouTube Test"
    requires = ["youtube_channel_id"]; produces = []
    tier = "fast"; priority = 10; cost_usd = 0.0; timeout_s = 10
    retry_max = 1; rate_limit_rpm = 0; ttl_hours = 24
    min_confidence = 0.6; max_instances = 3; osint_risk = False
    secrets_required = []; gdpr_basis = "LEGITIMATE_INTERESTS"
    data_category = "PUBLIC_API"; tos_compliant = True

    def run(self, seed_entities, config):
        return AdapterResult(adapter_id=self.adapter_id, entities=[], signals=[
            Signal(key="youtube_subscriber_count", value=100, unit="count",
                   confidence=1.0, method="api", source=self.adapter_id, osint_risk=False)
        ], error=None, cached=False, ran_at=TS, cost_usd=0.0, duration_s=0.1)


def _pool_with(*entities):
    pool = EntityPool()
    for e in entities: pool.add(e)
    return pool

def _state(config=None, run_counts=None, total_runs=0, total_cost=0.0):
    cfg = config or EngineConfig()
    s = EngineState(config=cfg)
    s.run_counts = run_counts or {}
    s.total_runs = total_runs
    s.total_cost = total_cost
    return s

def _yt_entity(confidence=1.0, depth=1):
    return make_entity("youtube_channel_id", YT_ID,
                       source="linktree", confidence=confidence, depth=depth, discovered_at=TS)


class TestIsRunnable:
    def test_runnable_when_entity_present(self):
        pool = _pool_with(_yt_entity())
        assert is_runnable(FakeYouTubeAdapter(), pool, _state()) is True

    def test_not_runnable_when_no_matching_entity(self):
        pool = EntityPool()
        assert is_runnable(FakeYouTubeAdapter(), pool, _state()) is False

    def test_not_runnable_when_disabled(self):
        class Disabled(FakeYouTubeAdapter):
            adapter_id = "yt_disabled"
            enabled = False
        assert is_runnable(Disabled(), _pool_with(_yt_entity()), _state()) is False

    def test_not_runnable_below_adapter_confidence(self):
        pool = _pool_with(_yt_entity(confidence=0.4))
        # adapter.min_confidence=0.6, global=0.5 → effective=0.6 → 0.4 blocked
        assert is_runnable(FakeYouTubeAdapter(), pool, _state()) is False

    def test_global_floor_overrides_adapter_floor(self):
        """Global floor 0.8 > adapter floor 0.6 → entity at 0.7 is blocked."""
        pool = _pool_with(_yt_entity(confidence=0.7))
        cfg = EngineConfig(min_confidence_global=0.8)
        assert is_runnable(FakeYouTubeAdapter(), pool, _state(config=cfg)) is False

    def test_global_floor_below_adapter_floor_uses_adapter(self):
        """Global floor 0.3 < adapter floor 0.6 → entity at 0.65 is allowed."""
        pool = _pool_with(_yt_entity(confidence=0.65))
        cfg = EngineConfig(min_confidence_global=0.3)
        assert is_runnable(FakeYouTubeAdapter(), pool, _state(config=cfg)) is True

    def test_not_runnable_when_depth_exceeds_max(self):
        pool = _pool_with(_yt_entity(depth=3))
        cfg = EngineConfig(max_depth=2)
        assert is_runnable(FakeYouTubeAdapter(), pool, _state(config=cfg)) is False

    def test_not_runnable_when_max_adapter_runs_hit(self):
        pool = _pool_with(_yt_entity())
        cfg = EngineConfig(max_adapter_runs=0)
        assert is_runnable(FakeYouTubeAdapter(), pool, _state(config=cfg)) is False

    def test_not_runnable_when_max_cost_hit(self):
        pool = _pool_with(_yt_entity())
        cfg = EngineConfig(max_cost_usd=0.0)
        s = _state(config=cfg, total_cost=0.01)
        assert is_runnable(FakeYouTubeAdapter(), pool, s) is False

    def test_not_runnable_when_max_instances_exhausted(self):
        pool = _pool_with(_yt_entity())
        run_counts = {("youtube_test", "youtube_channel_id", YT_ID): 3}
        assert is_runnable(FakeYouTubeAdapter(), pool, _state(run_counts=run_counts)) is False


class TestEngineConfig:
    def test_defaults(self):
        cfg = EngineConfig()
        assert cfg.max_depth == 2
        assert cfg.max_adapter_runs == 20
        assert cfg.max_cost_usd == 0.50
        assert cfg.min_confidence_global == 0.5
        assert cfg.parallel_workers == 8


class TestRunEngine:
    def test_seeds_extracted(self, tmp_path):
        pool, state, _ = run_engine(
            {"handle": "filipe", "display_name": "Filipe", "website": None},
            adapters=[], config=EngineConfig(), cache_dir=tmp_path,
        )
        assert pool.get("handle", "filipe") is not None
        assert pool.get("display_name", "Filipe") is not None

    def test_fast_adapter_runs(self, tmp_path):
        class FakeFast(EnrichmentAdapter):
            adapter_id = "fake_fast"; display_name = "Fake"
            requires = ["handle"]; produces = []
            tier = "fast"; priority = 1; cost_usd = 0.0; timeout_s = 5
            retry_max = 0; rate_limit_rpm = 0; ttl_hours = 0
            min_confidence = 0.5; max_instances = 1; osint_risk = False
            secrets_required = []; gdpr_basis = "LEGITIMATE_INTERESTS"
            data_category = "PUBLIC_API"; tos_compliant = True
            def run(self, seeds, cfg):
                return AdapterResult(adapter_id=self.adapter_id, entities=[], signals=[
                    Signal(key="test_signal", value=42, unit=None, confidence=1.0,
                           method="api", source=self.adapter_id, osint_risk=False)
                ], error=None, cached=False, ran_at=TS, cost_usd=0.0)

        pool, state, results = run_engine(
            {"handle": "filipe"}, adapters=[FakeFast()],
            config=EngineConfig(), cache_dir=tmp_path,
        )
        assert state.total_runs == 1
        assert any(s.key == "test_signal" for r in results for s in r.signals)

    def test_max_adapter_runs_respected(self, tmp_path):
        class FakeFast2(EnrichmentAdapter):
            adapter_id = "fake2"; display_name = "Fake2"
            requires = ["handle"]; produces = []
            tier = "fast"; priority = 1; cost_usd = 0.0; timeout_s = 5
            retry_max = 0; rate_limit_rpm = 0; ttl_hours = 0
            min_confidence = 0.5; max_instances = 10; osint_risk = False
            secrets_required = []; gdpr_basis = "LEGITIMATE_INTERESTS"
            data_category = "PUBLIC_API"; tos_compliant = True
            def run(self, seeds, cfg):
                return AdapterResult(adapter_id=self.adapter_id, entities=[], signals=[],
                                     error=None, cached=False, ran_at=TS, cost_usd=0.0)

        cfg = EngineConfig(max_adapter_runs=0)
        pool, state, results = run_engine(
            {"handle": "filipe"}, adapters=[FakeFast2()],
            config=cfg, cache_dir=tmp_path,
        )
        assert state.total_runs == 0

    def test_run_engine_with_no_adapters(self, tmp_path):
        pool, state, results = run_engine(
            {"handle": "foo"}, adapters=[],
            config=EngineConfig(), cache_dir=tmp_path,
        )
        assert len(results) == 0
        assert pool.get("handle", "foo") is not None
