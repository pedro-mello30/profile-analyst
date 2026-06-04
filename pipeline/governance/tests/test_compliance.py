"""Contract validation tests — AC1, AC2, AC9, AC10 (spec-0020 §6, §11)."""
from __future__ import annotations

import ast
import pathlib

import pytest

from pipeline.governance import (
    AdapterContractError,
    ProvenanceError,
    assert_provenance_chain,
    validate_adapter_contract,
    validate_discovery_adapter_contract,
    validate_enricher_contract,
)
from pipeline.governance.tests.conftest import (
    FakeEntity,
    make_valid_discovery_adapter,
    make_valid_enricher,
    make_valid_enrichment_adapter,
)

_GOV_DIR = pathlib.Path(__file__).parent.parent


class TestEnrichmentAdapterContract:
    def test_valid_passes(self):
        validate_adapter_contract(make_valid_enrichment_adapter())

    def test_missing_adapter_id_raises(self):  # AC1
        a = make_valid_enrichment_adapter()
        del a.adapter_id
        with pytest.raises(AdapterContractError, match="adapter_id"):
            validate_adapter_contract(a)

    def test_missing_gdpr_basis_raises(self):  # AC1
        a = make_valid_enrichment_adapter()
        del a.gdpr_basis
        with pytest.raises(AdapterContractError, match="gdpr_basis"):
            validate_adapter_contract(a)

    def test_invalid_data_category_raises(self):
        a = make_valid_enrichment_adapter(data_category="INTERNAL")
        with pytest.raises(AdapterContractError, match="data_category"):
            validate_adapter_contract(a)

    def test_invalid_tier_raises(self):
        a = make_valid_enrichment_adapter(tier="turbo")
        with pytest.raises(AdapterContractError, match="tier"):
            validate_adapter_contract(a)

    def test_invalid_gdpr_basis_raises(self):
        a = make_valid_enrichment_adapter(gdpr_basis="UNKNOWN")
        with pytest.raises(AdapterContractError, match="gdpr_basis"):
            validate_adapter_contract(a)

    def test_invalid_robots_policy_raises(self):
        a = make_valid_enrichment_adapter(robots_txt_policy="FOLLOW")
        with pytest.raises(AdapterContractError, match="robots_txt_policy"):
            validate_adapter_contract(a)

    @pytest.mark.parametrize("cat", ["PUBLIC_API", "PUBLIC_SCRAPE", "OSINT", "OPEN_DATA"])
    def test_valid_data_categories_pass(self, cat):
        a = make_valid_enrichment_adapter(data_category=cat)
        validate_adapter_contract(a)

    @pytest.mark.parametrize("tier", ["seed", "fast", "medium", "slow"])
    def test_valid_tiers_pass(self, tier):
        a = make_valid_enrichment_adapter(tier=tier)
        validate_adapter_contract(a)


class TestDiscoveryAdapterContract:
    def test_valid_passes(self):
        validate_discovery_adapter_contract(make_valid_discovery_adapter())

    def test_missing_field_raises(self):  # AC1
        a = make_valid_discovery_adapter()
        del a.requires
        with pytest.raises(AdapterContractError, match="requires"):
            validate_discovery_adapter_contract(a)

    def test_invalid_robots_policy_raises(self):
        a = make_valid_discovery_adapter(robots_txt_policy="MAYBE")
        with pytest.raises(AdapterContractError, match="robots_txt_policy"):
            validate_discovery_adapter_contract(a)

    @pytest.mark.parametrize("policy", ["RESPECT", "N/A"])
    def test_valid_robots_policies_pass(self, policy):
        a = make_valid_discovery_adapter(robots_txt_policy=policy)
        validate_discovery_adapter_contract(a)


class TestEnricherContract:
    def test_valid_passes(self):
        validate_enricher_contract(make_valid_enricher())

    def test_missing_enricher_id_raises(self):
        e = make_valid_enricher()
        del e.enricher_id
        with pytest.raises(AdapterContractError):
            validate_enricher_contract(e)

    def test_missing_adapter_id_raises(self):
        e = make_valid_enricher()
        del e.adapter_id
        with pytest.raises(AdapterContractError, match="adapter_id"):
            validate_enricher_contract(e)

    def test_min_confidence_above_one_raises(self):
        e = make_valid_enricher(min_confidence=1.5)
        with pytest.raises(AdapterContractError, match="min_confidence"):
            validate_enricher_contract(e)

    def test_min_confidence_below_zero_raises(self):
        e = make_valid_enricher(min_confidence=-0.1)
        with pytest.raises(AdapterContractError, match="min_confidence"):
            validate_enricher_contract(e)

    @pytest.mark.parametrize("mc", [0.0, 0.5, 1.0])
    def test_valid_min_confidence_passes(self, mc):
        validate_enricher_contract(make_valid_enricher(min_confidence=mc))


class TestProvenanceChain:
    def test_empty_chain_raises(self):  # AC2
        entity = FakeEntity("handle", attribution_chain=[])
        with pytest.raises(ProvenanceError, match="attribution_chain"):
            assert_provenance_chain(entity)

    def test_none_chain_raises(self):  # AC2
        entity = FakeEntity("handle")
        entity.attribution_chain = None
        with pytest.raises(ProvenanceError):
            assert_provenance_chain(entity)

    def test_non_empty_chain_passes(self):
        entity = FakeEntity("handle", attribution_chain=["bio_parser"])
        assert_provenance_chain(entity)


class TestCrossModuleValidation:
    def test_same_engine_validates_both_types(self):  # AC9
        """validate_adapter_contract works for both Discovery and Enrichment instances."""
        # Discovery adapter passes its own validation
        discovery = make_valid_discovery_adapter()
        validate_discovery_adapter_contract(discovery)

        # Enrichment adapter passes its own validation
        enrichment = make_valid_enrichment_adapter()
        validate_adapter_contract(enrichment)

        # Enrichment adapter missing discovery-required field also fails discovery validation
        bad = make_valid_discovery_adapter()
        del bad.display_name
        with pytest.raises(AdapterContractError):
            validate_discovery_adapter_contract(bad)


class TestNoImportsFromPipeline:
    _FORBIDDEN_PREFIXES = (
        "pipeline.compliance",
        "pipeline.enrichment",
        "pipeline.account_discovery",
        "pipeline.graph",
        "pipeline.linkage",
        "pipeline.associations",
        "pipeline.scoring",
        "pipeline.llm",
        "pipeline.rag",
        "pipeline.stage",
    )

    def test_no_cross_imports(self):  # AC10
        """pipeline/governance/ module files must not import from other pipeline subpackages."""
        violations = []
        for py_file in sorted(_GOV_DIR.glob("*.py")):
            source = py_file.read_text()
            try:
                tree = ast.parse(source, filename=str(py_file))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        for prefix in self._FORBIDDEN_PREFIXES:
                            if alias.name.startswith(prefix):
                                violations.append(
                                    f"{py_file.name}: import {alias.name!r}"
                                )
                elif isinstance(node, ast.ImportFrom) and node.module:
                    for prefix in self._FORBIDDEN_PREFIXES:
                        if node.module.startswith(prefix):
                            violations.append(
                                f"{py_file.name}: from {node.module!r}"
                            )
        assert not violations, (
            "Cross-module import violations in pipeline/governance/:\n"
            + "\n".join(violations)
        )
