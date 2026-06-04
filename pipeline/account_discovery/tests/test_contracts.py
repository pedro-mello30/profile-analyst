"""Tests for DiscoveryAdapter contract (spec-0018 §5)."""
from __future__ import annotations

import ast
import importlib
import textwrap
from pathlib import Path

import pytest

from pipeline.account_discovery.contracts import (
    ENTITY_TYPES,
    AdapterContractError,
    DiscoveryAdapter,
    DiscoveryContractError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_valid_adapter(name: str = "ValidAdapter", **overrides):
    """Dynamically create a concrete DiscoveryAdapter subclass with all required attrs."""
    attrs = dict(
        adapter_id="test_adapter_v1",
        display_name="Test Adapter",
        requires=frozenset({"instagram_handle"}),
        produces=frozenset({"youtube_handle", "domain"}),
        priority=10,
        timeout_s=30,
        retry_max=3,
        data_category="PUBLIC_API",
        tos_compliant=True,
        robots_txt_policy="RESPECT",
    )
    attrs.update(overrides)

    def run(self, seed_entities, config):
        return []

    return type(name, (DiscoveryAdapter,), {**attrs, "run": run})


# ---------------------------------------------------------------------------
# AC1 — valid adapter registers without error
# ---------------------------------------------------------------------------

class TestValidAdapterRegisters:
    def test_valid_adapter_no_error(self):
        """A fully compliant adapter class definition must not raise."""
        adapter_cls = _make_valid_adapter()
        assert adapter_cls is not None

    def test_valid_adapter_is_subclass_of_discovery_adapter(self):
        adapter_cls = _make_valid_adapter()
        assert issubclass(adapter_cls, DiscoveryAdapter)

    def test_valid_adapter_can_be_instantiated(self):
        adapter_cls = _make_valid_adapter()
        obj = adapter_cls()
        assert hasattr(obj, "run")

    def test_valid_adapter_can_call_run(self):
        adapter_cls = _make_valid_adapter()
        obj = adapter_cls()
        result = obj.run([], None)
        assert result == []

    def test_valid_adapter_with_na_robots_policy(self):
        """'N/A' is a valid robots_txt_policy value."""
        adapter_cls = _make_valid_adapter(robots_txt_policy="N/A")
        assert adapter_cls is not None

    def test_valid_adapter_all_data_categories_accepted(self):
        for cat in ("PUBLIC_API", "PUBLIC_SCRAPE", "OSINT", "OPEN_DATA"):
            adapter_cls = _make_valid_adapter(data_category=cat)
            assert adapter_cls is not None, f"Category {cat!r} should be accepted"


# ---------------------------------------------------------------------------
# AC2 — missing robots_txt_policy raises AdapterContractError
# ---------------------------------------------------------------------------

class TestMissingRobotsTxtPolicy:
    def test_missing_raises_adapter_contract_error(self):
        attrs = dict(
            adapter_id="bad_adapter",
            display_name="Bad Adapter",
            requires=frozenset({"instagram_handle"}),
            produces=frozenset({"domain"}),
            priority=5,
            timeout_s=30,
            retry_max=3,
            data_category="PUBLIC_API",
            tos_compliant=True,
            # robots_txt_policy intentionally omitted
        )

        def run(self, seed_entities, config):
            return []

        with pytest.raises(AdapterContractError) as exc_info:
            type("MissingRobotsAdapter", (DiscoveryAdapter,), {**attrs, "run": run})

        assert "robots_txt_policy" in str(exc_info.value)

    def test_error_message_names_the_field(self):
        """The error message must explicitly mention 'robots_txt_policy'."""
        with pytest.raises(AdapterContractError) as exc_info:
            _make_valid_adapter.__module__  # just to touch imports

            class _BadAdapter(DiscoveryAdapter):
                adapter_id = "x"
                display_name = "X"
                requires: frozenset = frozenset()
                produces: frozenset = frozenset()
                priority = 1
                timeout_s = 10
                retry_max = 1
                data_category = "PUBLIC_API"
                tos_compliant = True
                # robots_txt_policy missing

                def run(self, seed_entities, config):
                    return []

        assert "robots_txt_policy" in str(exc_info.value)


# ---------------------------------------------------------------------------
# AC3 — invalid data_category raises AdapterContractError
# ---------------------------------------------------------------------------

class TestInvalidDataCategory:
    def test_invalid_category_raises(self):
        with pytest.raises(AdapterContractError) as exc_info:
            _make_valid_adapter(data_category="PRIVATE_SCRAPE")

        assert "data_category" in str(exc_info.value)
        assert "PRIVATE_SCRAPE" in str(exc_info.value)

    def test_empty_string_category_raises(self):
        with pytest.raises(AdapterContractError):
            _make_valid_adapter(data_category="")

    def test_lowercase_valid_name_raises(self):
        """Vocabulary is case-sensitive; 'public_api' is not valid."""
        with pytest.raises(AdapterContractError):
            _make_valid_adapter(data_category="public_api")

    def test_all_valid_categories_accepted(self):
        for cat in ("PUBLIC_API", "PUBLIC_SCRAPE", "OSINT", "OPEN_DATA"):
            # Should not raise
            _make_valid_adapter(data_category=cat)


# ---------------------------------------------------------------------------
# AC4 — unknown entity type in requires raises AdapterContractError
# ---------------------------------------------------------------------------

class TestUnknownEntityTypeInRequires:
    def test_unknown_require_raises(self):
        with pytest.raises(AdapterContractError) as exc_info:
            _make_valid_adapter(requires=frozenset({"instagram_handle", "nonexistent_type"}))

        assert "nonexistent_type" in str(exc_info.value)

    def test_unknown_produces_raises(self):
        with pytest.raises(AdapterContractError) as exc_info:
            _make_valid_adapter(produces=frozenset({"domain", "made_up_entity"}))

        assert "made_up_entity" in str(exc_info.value)

    def test_all_entity_types_accepted_in_requires(self):
        """Every member of ENTITY_TYPES must be valid in requires."""
        adapter_cls = _make_valid_adapter(requires=frozenset(ENTITY_TYPES))
        assert adapter_cls is not None

    def test_all_entity_types_accepted_in_produces(self):
        """Every member of ENTITY_TYPES must be valid in produces."""
        adapter_cls = _make_valid_adapter(produces=frozenset(ENTITY_TYPES))
        assert adapter_cls is not None

    def test_empty_requires_is_valid(self):
        adapter_cls = _make_valid_adapter(requires=frozenset())
        assert adapter_cls is not None

    def test_empty_produces_is_valid(self):
        adapter_cls = _make_valid_adapter(produces=frozenset())
        assert adapter_cls is not None

    def test_unknown_requires_message_mentions_field(self):
        with pytest.raises(AdapterContractError) as exc_info:
            _make_valid_adapter(requires=frozenset({"bad_type_xyz"}))
        assert "requires" in str(exc_info.value)

    def test_unknown_produces_message_mentions_field(self):
        with pytest.raises(AdapterContractError) as exc_info:
            _make_valid_adapter(produces=frozenset({"bad_type_xyz"}))
        assert "produces" in str(exc_info.value)


# ---------------------------------------------------------------------------
# AC5 — AST check: contracts.py has zero forbidden imports
# ---------------------------------------------------------------------------

class TestNoForbiddenImports:
    """Static analysis: contracts.py must not import from banned modules."""

    CONTRACTS_PATH = (
        Path(__file__).parent.parent / "contracts.py"
    )

    FORBIDDEN_PREFIXES = (
        "pipeline.enrichment",
        "pipeline.compliance",
        "pipeline.graph",
        "pipeline.stage",
    )

    def _collect_imports(self, source: str) -> list[str]:
        """Return all imported module names from an AST parse of source."""
        tree = ast.parse(source)
        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module)
        return imports

    def test_contracts_py_exists(self):
        assert self.CONTRACTS_PATH.exists(), (
            f"contracts.py not found at {self.CONTRACTS_PATH}"
        )

    def test_no_pipeline_enrichment_import(self):
        source = self.CONTRACTS_PATH.read_text()
        imports = self._collect_imports(source)
        forbidden = [m for m in imports if m.startswith("pipeline.enrichment")]
        assert forbidden == [], (
            f"contracts.py must not import from pipeline.enrichment; found: {forbidden}"
        )

    def test_no_pipeline_compliance_import(self):
        source = self.CONTRACTS_PATH.read_text()
        imports = self._collect_imports(source)
        forbidden = [m for m in imports if m.startswith("pipeline.compliance")]
        assert forbidden == [], (
            f"contracts.py must not import from pipeline.compliance; found: {forbidden}"
        )

    def test_no_pipeline_graph_import(self):
        source = self.CONTRACTS_PATH.read_text()
        imports = self._collect_imports(source)
        forbidden = [m for m in imports if m.startswith("pipeline.graph")]
        assert forbidden == [], (
            f"contracts.py must not import from pipeline.graph; found: {forbidden}"
        )

    def test_no_pipeline_stage_import(self):
        source = self.CONTRACTS_PATH.read_text()
        imports = self._collect_imports(source)
        forbidden = [m for m in imports if m.startswith("pipeline.stage")]
        assert forbidden == [], (
            f"contracts.py must not import from pipeline.stage*; found: {forbidden}"
        )

    def test_all_forbidden_prefixes_absent(self):
        """Consolidated check across all forbidden prefixes."""
        source = self.CONTRACTS_PATH.read_text()
        imports = self._collect_imports(source)
        violations = [
            m for m in imports
            if any(m.startswith(p) for p in self.FORBIDDEN_PREFIXES)
        ]
        assert violations == [], (
            f"contracts.py imports from forbidden modules: {violations}"
        )

    def test_only_stdlib_imports_present(self):
        """contracts.py should only import from stdlib (abc, __future__, etc.)."""
        source = self.CONTRACTS_PATH.read_text()
        imports = self._collect_imports(source)
        # Allow __future__ and stdlib modules used in this file
        allowed_prefixes = ("__future__", "abc")
        non_stdlib = [
            m for m in imports
            if not any(m.startswith(p) for p in allowed_prefixes)
        ]
        assert non_stdlib == [], (
            f"contracts.py should use only stdlib imports; unexpected: {non_stdlib}"
        )


# ---------------------------------------------------------------------------
# Additional: exception hierarchy
# ---------------------------------------------------------------------------

class TestExceptionHierarchy:
    def test_adapter_contract_error_is_runtime_error(self):
        assert issubclass(AdapterContractError, RuntimeError)

    def test_discovery_contract_error_is_runtime_error(self):
        assert issubclass(DiscoveryContractError, RuntimeError)

    def test_adapter_contract_error_can_be_raised(self):
        with pytest.raises(AdapterContractError):
            raise AdapterContractError("test error")

    def test_discovery_contract_error_can_be_raised(self):
        with pytest.raises(DiscoveryContractError):
            raise DiscoveryContractError("test error")


# ---------------------------------------------------------------------------
# Additional: intermediate abstract classes are not validated
# ---------------------------------------------------------------------------

class TestIntermediateAbstractClassNotValidated:
    def test_abstract_intermediate_not_validated(self):
        """An intermediate abstract subclass (still has abstractmethods) must not be validated."""
        from abc import abstractmethod

        # This should NOT raise even without required attrs, because it's still abstract
        class IntermediateAdapter(DiscoveryAdapter):
            @abstractmethod
            def specialized_setup(self) -> None: ...

        # Concrete subclass with full contract should work
        class ConcreteAdapter(IntermediateAdapter):
            adapter_id = "concrete_v1"
            display_name = "Concrete"
            requires: frozenset = frozenset({"instagram_handle"})
            produces: frozenset = frozenset({"domain"})
            priority = 1
            timeout_s = 10
            retry_max = 1
            data_category = "PUBLIC_API"
            tos_compliant = True
            robots_txt_policy = "RESPECT"

            def run(self, seed_entities, config):
                return []

            def specialized_setup(self) -> None:
                pass

        assert ConcreteAdapter is not None


# ---------------------------------------------------------------------------
# Additional: ENTITY_TYPES completeness
# ---------------------------------------------------------------------------

class TestEntityTypes:
    EXPECTED = {
        "instagram_handle", "bio_text", "url", "platform_handle",
        "youtube_handle", "github_handle", "tiktok_handle",
        "twitter_handle", "twitch_handle", "spotify_handle",
        "reddit_handle", "substack_url", "linkedin_url",
        "facebook_url", "domain", "email",
    }

    def test_entity_types_is_frozenset(self):
        assert isinstance(ENTITY_TYPES, frozenset)

    def test_entity_types_contains_all_expected(self):
        assert ENTITY_TYPES == self.EXPECTED

    def test_entity_types_immutable(self):
        with pytest.raises((TypeError, AttributeError)):
            ENTITY_TYPES.add("new_type")  # type: ignore[attr-defined]
