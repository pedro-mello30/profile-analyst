import pytest
from pipeline.enrichment.adapter import (
    AdapterConfig, AdapterResult, Signal, EnrichmentAdapter, AdapterContractError
)

TS = "2026-06-02T21:00:00Z"
CFG = AdapterConfig(
    profile_id="filipelauar", run_id="test-run-1",
    max_depth=2, max_cost_usd=0.50, max_runtime_s=60,
    secrets={}, osint_enabled=True, cache_enabled=True, dry_run=False,
)


class TestAdapterConfig:
    def test_constructs(self):
        assert CFG.profile_id == "filipelauar"
        assert CFG.dry_run is False
        assert CFG.secrets == {}


class TestAdapterContractValidation:
    def test_missing_attribute_raises_at_import(self):
        with pytest.raises(AdapterContractError, match="missing required"):
            class BadAdapter(EnrichmentAdapter):
                adapter_id = "bad"
                # missing almost everything
                def run(self, seed_entities, config):
                    pass

    def test_unknown_entity_type_in_requires_raises(self):
        with pytest.raises(AdapterContractError, match="unknown entity types"):
            class BadRequires(EnrichmentAdapter):
                adapter_id = "bad2"; display_name = "Bad"
                requires = ["not_a_real_type"]
                produces = ["handle"]
                tier = "fast"; priority = 10
                cost_usd = 0.0; timeout_s = 10; retry_max = 1; rate_limit_rpm = 0
                ttl_hours = 24; min_confidence = 0.5; max_instances = 1
                osint_risk = False; secrets_required = []
                gdpr_basis = "LEGITIMATE_INTERESTS"
                data_category = "PUBLIC_API"; tos_compliant = True
                def run(self, seed_entities, config): pass

    def test_unknown_entity_type_in_produces_raises(self):
        with pytest.raises(AdapterContractError, match="unknown entity types"):
            class BadProduces(EnrichmentAdapter):
                adapter_id = "bad3"; display_name = "Bad"
                requires = ["handle"]
                produces = ["not_real_either"]
                tier = "fast"; priority = 10
                cost_usd = 0.0; timeout_s = 10; retry_max = 1; rate_limit_rpm = 0
                ttl_hours = 24; min_confidence = 0.5; max_instances = 1
                osint_risk = False; secrets_required = []
                gdpr_basis = "LEGITIMATE_INTERESTS"
                data_category = "PUBLIC_API"; tos_compliant = True
                def run(self, seed_entities, config): pass

    def test_invalid_tier_raises(self):
        with pytest.raises(AdapterContractError, match="tier"):
            class BadTier(EnrichmentAdapter):
                adapter_id = "bad4"; display_name = "Bad"
                requires = ["handle"]; produces = []
                tier = "ultra"
                priority = 10; cost_usd = 0.0; timeout_s = 10; retry_max = 1
                rate_limit_rpm = 0; ttl_hours = 24; min_confidence = 0.5
                max_instances = 1; osint_risk = False; secrets_required = []
                gdpr_basis = "LEGITIMATE_INTERESTS"
                data_category = "PUBLIC_API"; tos_compliant = True
                def run(self, seed_entities, config): pass

    def test_invalid_gdpr_basis_raises(self):
        with pytest.raises(AdapterContractError, match="gdpr_basis"):
            class BadGdpr(EnrichmentAdapter):
                adapter_id = "bad5"; display_name = "Bad"
                requires = ["handle"]; produces = []
                tier = "fast"; priority = 10; cost_usd = 0.0; timeout_s = 10
                retry_max = 1; rate_limit_rpm = 0; ttl_hours = 24
                min_confidence = 0.5; max_instances = 1; osint_risk = False
                secrets_required = []; gdpr_basis = "WRONG"
                data_category = "PUBLIC_API"; tos_compliant = True
                def run(self, seed_entities, config): pass

    def test_valid_adapter_registers_cleanly(self):
        class GoodAdapter(EnrichmentAdapter):
            adapter_id = "good"; display_name = "Good"
            requires = ["handle"]; produces = ["youtube_handle"]
            tier = "fast"; priority = 10; cost_usd = 0.0; timeout_s = 10
            retry_max = 1; rate_limit_rpm = 0; ttl_hours = 24
            min_confidence = 0.5; max_instances = 1; osint_risk = False
            secrets_required = []; gdpr_basis = "LEGITIMATE_INTERESTS"
            data_category = "PUBLIC_API"; tos_compliant = True
            def run(self, seed_entities, config):
                return AdapterResult(adapter_id="good", entities=[], signals=[],
                                     error=None, cached=False, ran_at=TS,
                                     cost_usd=0.0, duration_s=0.1)
        result = GoodAdapter().run([], CFG)
        assert result.adapter_id == "good"
        assert result.error is None


class TestSignal:
    def test_constructs(self):
        s = Signal(key="sub_count", value=100, unit="count",
                   confidence=1.0, method="api", source="youtube", osint_risk=False)
        assert s.value == 100
        assert s.osint_risk is False


class TestAdapterResult:
    def test_duration_defaults_to_zero(self):
        r = AdapterResult(adapter_id="x", entities=[], signals=[],
                          error=None, cached=False, ran_at=TS, cost_usd=0.0)
        assert r.duration_s == 0.0
