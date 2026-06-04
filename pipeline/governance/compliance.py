"""Adapter and enricher contract validation (spec-0020 §6)."""
from __future__ import annotations

_VALID_DATA_CATS = frozenset({"PUBLIC_API", "PUBLIC_SCRAPE", "OSINT", "OPEN_DATA"})
_VALID_ROBOTS = frozenset({"RESPECT", "N/A"})
_VALID_GDPR = frozenset({"LEGITIMATE_INTERESTS", "CONSENT", "NONE"})
_VALID_TIERS = frozenset({"seed", "fast", "medium", "slow"})

_SHARED_REQUIRED: tuple = (
    ("adapter_id", str),
    ("display_name", str),
    ("requires", (list, tuple)),
    ("produces", (list, tuple)),
    ("data_category", str),
    ("tos_compliant", bool),
    ("robots_txt_policy", str),
)

_ENRICHMENT_EXTRA: tuple = (
    ("gdpr_basis", str),
    ("osint_risk", bool),
    ("tier", str),
    ("rate_limit_rpm", int),
    ("timeout_s", (int, float)),
)

_ENRICHER_REQUIRED: tuple = (
    ("enricher_id", str),
    ("adapter_id", str),
    ("min_confidence", (int, float)),
)


class AdapterContractError(RuntimeError):
    pass


class ProvenanceError(RuntimeError):
    pass


def _validate_attrs(obj, required: tuple, id_attr: str = "adapter_id") -> list:
    from pipeline.governance.models import ContractViolation
    adapter_id = str(getattr(obj, id_attr, repr(obj)))
    violations = []
    for attr, expected_type in required:
        if not hasattr(obj, attr):
            violations.append(ContractViolation(
                adapter_id=adapter_id, field=attr,
                expected=str(expected_type), got="missing",
                message=f"missing required attribute: {attr!r}",
            ))
            continue
        val = getattr(obj, attr)
        if not isinstance(val, expected_type):
            violations.append(ContractViolation(
                adapter_id=adapter_id, field=attr,
                expected=str(expected_type), got=type(val).__name__,
                message=f"{attr}={val!r} has wrong type (expected {expected_type})",
            ))
    return violations


def _validate_vocab(obj, field: str, valid: frozenset, adapter_id: str) -> list:
    from pipeline.governance.models import ContractViolation
    if not hasattr(obj, field):
        return []
    val = getattr(obj, field)
    if val not in valid:
        return [ContractViolation(
            adapter_id=adapter_id, field=field,
            expected=str(valid), got=repr(val),
            message=f"{field}={val!r} not in valid vocabulary {valid}",
        )]
    return []


def validate_adapter_contract(adapter) -> None:
    """Validate an EnrichmentAdapter contract at registration time. Raises AdapterContractError."""
    adapter_id = str(getattr(adapter, "adapter_id", repr(adapter)))
    violations = []
    violations += _validate_attrs(adapter, _SHARED_REQUIRED)
    violations += _validate_attrs(adapter, _ENRICHMENT_EXTRA)
    violations += _validate_vocab(adapter, "data_category", _VALID_DATA_CATS, adapter_id)
    violations += _validate_vocab(adapter, "robots_txt_policy", _VALID_ROBOTS, adapter_id)
    violations += _validate_vocab(adapter, "gdpr_basis", _VALID_GDPR, adapter_id)
    violations += _validate_vocab(adapter, "tier", _VALID_TIERS, adapter_id)
    if violations:
        raise AdapterContractError(
            f"Adapter {adapter_id!r} has {len(violations)} contract violation(s):\n"
            + "\n".join(f"  • {v.message}" for v in violations)
        )


def validate_discovery_adapter_contract(adapter) -> None:
    """Validate a DiscoveryAdapter contract at registration time. Raises AdapterContractError."""
    adapter_id = str(getattr(adapter, "adapter_id", repr(adapter)))
    violations = []
    violations += _validate_attrs(adapter, _SHARED_REQUIRED)
    violations += _validate_vocab(adapter, "data_category", _VALID_DATA_CATS, adapter_id)
    violations += _validate_vocab(adapter, "robots_txt_policy", _VALID_ROBOTS, adapter_id)
    if violations:
        raise AdapterContractError(
            f"Discovery adapter {adapter_id!r} has {len(violations)} contract violation(s):\n"
            + "\n".join(f"  • {v.message}" for v in violations)
        )


def validate_enricher_contract(enricher) -> None:
    """Validate an Enricher contract at registration time. Raises AdapterContractError."""
    enricher_id = str(getattr(enricher, "enricher_id", repr(enricher)))
    violations = _validate_attrs(enricher, _ENRICHER_REQUIRED, id_attr="enricher_id")
    if hasattr(enricher, "min_confidence"):
        mc = enricher.min_confidence
        if isinstance(mc, (int, float)) and not (0.0 <= mc <= 1.0):
            from pipeline.governance.models import ContractViolation
            violations.append(ContractViolation(
                adapter_id=enricher_id, field="min_confidence",
                expected="float in [0.0, 1.0]", got=repr(mc),
                message=f"min_confidence={mc!r} out of [0.0, 1.0]",
            ))
    if violations:
        raise AdapterContractError(
            f"Enricher {enricher_id!r} has {len(violations)} contract violation(s):\n"
            + "\n".join(f"  • {v.message}" for v in violations)
        )


def assert_provenance_chain(entity) -> None:
    """Assert that entity has a non-empty attribution_chain. Raises ProvenanceError."""
    chain = getattr(entity, "attribution_chain", None)
    if not chain:
        raise ProvenanceError(
            f"attribution_chain must be non-empty for entity {entity!r}"
        )
