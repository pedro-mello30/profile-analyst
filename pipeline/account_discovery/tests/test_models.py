"""Tests for account discovery models (spec-0018 §4)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from pipeline.account_discovery.models import (
    AccountRelationship,
    AttributionStep,
    DiscoveredAccount,
    DiscoveryManifest,
    DiscoveryStats,
)


def _utc(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def _make_attribution_step() -> AttributionStep:
    return AttributionStep(
        adapter_id="test_adapter",
        from_entity_type="instagram_handle",
        from_entity_value="filipelauar",
        relationship="tagged_in",
    )


def _make_discovered_account(*, verified: bool = False) -> DiscoveredAccount:
    return DiscoveredAccount(
        account_id="acc-001",
        platform="youtube",
        handle="@filipelauar",
        profile_url="https://youtube.com/@filipelauar",
        confidence=0.9,
        method="bio_url_match",
        source_adapter_id="test_adapter",
        attribution_chain=[_make_attribution_step()],
        discovered_at=_utc("2026-06-04T12:00:00+00:00"),
        verified=verified,
    )


def _make_stats() -> DiscoveryStats:
    return DiscoveryStats(
        adapters_run=2,
        accounts_found=5,
        relationships_found=3,
        depth_reached=1,
        elapsed_s=1.23,
    )


def _make_manifest(*, limit_reached: bool = False, governance=None) -> DiscoveryManifest:
    return DiscoveryManifest(
        seed_handle="filipelauar",
        seed_platform="instagram",
        run_id="run-abc-123",
        started_at=_utc("2026-06-04T12:00:00+00:00"),
        completed_at=_utc("2026-06-04T12:00:01+00:00"),
        discovered_accounts=[_make_discovered_account()],
        relationships=[
            AccountRelationship(
                from_account_id="acc-001",
                to_account_id="acc-002",
                relationship_type="collab",
                confidence=0.8,
                source_adapter_id="test_adapter",
            )
        ],
        stats=_make_stats(),
        limit_reached=limit_reached,
        governance=governance,
    )


class TestAttributionStep:
    def test_to_dict_fields(self):
        step = _make_attribution_step()
        d = step.to_dict()
        assert d["adapter_id"] == "test_adapter"
        assert d["from_entity_type"] == "instagram_handle"
        assert d["from_entity_value"] == "filipelauar"
        assert d["relationship"] == "tagged_in"

    def test_to_dict_keys(self):
        d = _make_attribution_step().to_dict()
        assert set(d.keys()) == {"adapter_id", "from_entity_type", "from_entity_value", "relationship"}


class TestDiscoveredAccount:
    def test_to_dict_datetime_is_iso_string(self):
        d = _make_discovered_account().to_dict()
        assert isinstance(d["discovered_at"], str)
        parsed = datetime.fromisoformat(d["discovered_at"])
        assert parsed.year == 2026

    def test_to_dict_attribution_chain_serialised(self):
        d = _make_discovered_account().to_dict()
        assert isinstance(d["attribution_chain"], list)
        assert len(d["attribution_chain"]) == 1
        step = d["attribution_chain"][0]
        assert step["adapter_id"] == "test_adapter"
        assert step["relationship"] == "tagged_in"

    def test_to_dict_verified_default_false(self):
        d = _make_discovered_account().to_dict()
        assert d["verified"] is False

    def test_to_dict_verified_true(self):
        d = _make_discovered_account(verified=True).to_dict()
        assert d["verified"] is True

    def test_to_dict_scalar_fields(self):
        d = _make_discovered_account().to_dict()
        assert d["account_id"] == "acc-001"
        assert d["platform"] == "youtube"
        assert d["handle"] == "@filipelauar"
        assert d["profile_url"] == "https://youtube.com/@filipelauar"
        assert d["confidence"] == 0.9
        assert d["method"] == "bio_url_match"
        assert d["source_adapter_id"] == "test_adapter"


class TestDiscoveryManifest:
    def test_to_dict_limit_reached_false(self):
        d = _make_manifest(limit_reached=False).to_dict()
        assert d["limit_reached"] is False

    def test_to_dict_limit_reached_true(self):
        d = _make_manifest(limit_reached=True).to_dict()
        assert d["limit_reached"] is True

    def test_to_dict_governance_none_by_default(self):
        d = _make_manifest().to_dict()
        assert d["governance"] is None

    def test_to_dict_governance_passthrough(self):
        gov = {"run_id": "gov-001", "module": "account_discovery"}
        d = _make_manifest(governance=gov).to_dict()
        assert d["governance"] == gov

    def test_to_dict_datetime_fields_are_iso_strings(self):
        d = _make_manifest().to_dict()
        assert isinstance(d["started_at"], str)
        assert isinstance(d["completed_at"], str)
        datetime.fromisoformat(d["started_at"])
        datetime.fromisoformat(d["completed_at"])

    def test_to_dict_nested_accounts_serialised(self):
        d = _make_manifest().to_dict()
        assert isinstance(d["discovered_accounts"], list)
        assert len(d["discovered_accounts"]) == 1
        acc = d["discovered_accounts"][0]
        assert acc["account_id"] == "acc-001"
        assert isinstance(acc["discovered_at"], str)
        assert isinstance(acc["attribution_chain"], list)

    def test_to_dict_nested_relationships_serialised(self):
        d = _make_manifest().to_dict()
        assert isinstance(d["relationships"], list)
        assert len(d["relationships"]) == 1
        rel = d["relationships"][0]
        assert rel["from_account_id"] == "acc-001"
        assert rel["to_account_id"] == "acc-002"
        assert rel["relationship_type"] == "collab"

    def test_to_dict_stats_serialised(self):
        d = _make_manifest().to_dict()
        stats = d["stats"]
        assert stats["adapters_run"] == 2
        assert stats["accounts_found"] == 5
        assert stats["relationships_found"] == 3
        assert stats["depth_reached"] == 1
        assert stats["elapsed_s"] == 1.23

    def test_to_dict_seed_fields(self):
        d = _make_manifest().to_dict()
        assert d["seed_handle"] == "filipelauar"
        assert d["seed_platform"] == "instagram"
        assert d["run_id"] == "run-abc-123"
