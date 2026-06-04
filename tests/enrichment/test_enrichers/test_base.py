"""Tests for EnrichmentEnricher ABC (spec-0019 §5.3)."""
import pytest

from pipeline.enrichment.enrichers.base import EnrichmentEnricher, EnricherContractError


# ---------------------------------------------------------------------------
# Helpers: valid concrete enricher
# ---------------------------------------------------------------------------

class ValidEnricher(EnrichmentEnricher):
    enricher_id = "valid_enricher"
    adapter_id = "some_adapter"
    min_confidence = 0.7

    def extract(self, raw_data: dict) -> list:
        return [{"value": raw_data.get("name")}]


# ---------------------------------------------------------------------------
# Test 1: Valid enricher registers without error
# ---------------------------------------------------------------------------

def test_valid_enricher_registers_without_error():
    """Defining a valid enricher (all 3 required attrs) must not raise."""
    # The class was already defined above; if no exception occurred, it passes.
    enricher = ValidEnricher()
    assert enricher is not None


# ---------------------------------------------------------------------------
# Test 2: Missing enricher_id raises EnricherContractError
# ---------------------------------------------------------------------------

def test_missing_enricher_id_raises_contract_error():
    with pytest.raises(EnricherContractError) as exc_info:
        class MissingEnricherId(EnrichmentEnricher):
            adapter_id = "some_adapter"
            min_confidence = 0.5

            def extract(self, raw_data: dict) -> list:
                return []

    assert "enricher_id" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Test 3: Missing adapter_id raises EnricherContractError
# ---------------------------------------------------------------------------

def test_missing_adapter_id_raises_contract_error():
    with pytest.raises(EnricherContractError) as exc_info:
        class MissingAdapterId(EnrichmentEnricher):
            enricher_id = "some_enricher"
            min_confidence = 0.5

            def extract(self, raw_data: dict) -> list:
                return []

    assert "adapter_id" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Test 4: min_confidence > 1.0 raises EnricherContractError
# ---------------------------------------------------------------------------

def test_min_confidence_above_one_raises_contract_error():
    with pytest.raises(EnricherContractError) as exc_info:
        class ConfidenceTooHigh(EnrichmentEnricher):
            enricher_id = "high_conf_enricher"
            adapter_id = "some_adapter"
            min_confidence = 1.5

            def extract(self, raw_data: dict) -> list:
                return []

    assert "min_confidence" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Test 5: safe_extract() returns [] when extract() raises
# ---------------------------------------------------------------------------

def test_safe_extract_returns_empty_list_on_exception():
    class BrokenEnricher(EnrichmentEnricher):
        enricher_id = "broken_enricher"
        adapter_id = "some_adapter"
        min_confidence = 0.5

        def extract(self, raw_data: dict) -> list:
            raise ValueError("something went wrong")

    enricher = BrokenEnricher()
    result = enricher.safe_extract({"name": "test"})
    assert result == []


# ---------------------------------------------------------------------------
# Test 6: extract() is abstract — cannot instantiate without implementing it
# ---------------------------------------------------------------------------

def test_extract_is_abstract_cannot_instantiate():
    class AbstractEnricher(EnrichmentEnricher):
        enricher_id = "abstract_enricher"
        adapter_id = "some_adapter"
        min_confidence = 0.5
        # extract() intentionally NOT implemented

    with pytest.raises(TypeError):
        AbstractEnricher()
