"""Tests for AccountPool dedup + attribution merge (spec-0018 AC7)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from pipeline.account_discovery.models import AttributionStep, DiscoveredAccount
from pipeline.account_discovery.pool import AccountPool


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_DISCOVERED_AT = datetime(2026, 6, 4, 12, 0, 0, tzinfo=timezone.utc)


def _step(adapter_id: str, from_entity_value: str, relationship: str = "tagged_in") -> AttributionStep:
    return AttributionStep(
        adapter_id=adapter_id,
        from_entity_type="instagram_handle",
        from_entity_value=from_entity_value,
        relationship=relationship,
    )


def _account(
    *,
    platform: str = "youtube",
    handle: str = "creator",
    confidence: float = 0.8,
    adapter_id: str = "adapter_a",
    steps: list[AttributionStep] | None = None,
) -> DiscoveredAccount:
    if steps is None:
        steps = [_step(adapter_id, handle)]
    return DiscoveredAccount(
        account_id=f"{platform}-{handle}",
        platform=platform,
        handle=handle,
        profile_url=f"https://{platform}.com/{handle}",
        confidence=confidence,
        method="bio_url_match",
        source_adapter_id=adapter_id,
        attribution_chain=steps,
        discovered_at=_DISCOVERED_AT,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAccountPoolAdd:
    def test_add_returns_true_for_new_account(self):
        pool = AccountPool()
        acc = _account()
        assert pool.add(acc) is True

    def test_add_returns_false_for_duplicate_lower_confidence(self):
        """Duplicate with lower confidence: pool unchanged (returns False) but chain merged."""
        pool = AccountPool()
        high = _account(confidence=0.9, adapter_id="adapter_a", handle="creator")
        low = _account(confidence=0.5, adapter_id="adapter_b", handle="creator")
        pool.add(high)
        result = pool.add(low)
        assert result is False

    def test_add_returns_true_for_duplicate_higher_confidence(self):
        pool = AccountPool()
        low = _account(confidence=0.5, adapter_id="adapter_a", handle="creator")
        high = _account(confidence=0.9, adapter_id="adapter_b", handle="creator")
        pool.add(low)
        result = pool.add(high)
        assert result is True

    def test_pool_size_unchanged_on_duplicate(self):
        pool = AccountPool()
        pool.add(_account(confidence=0.8, handle="creator"))
        pool.add(_account(confidence=0.6, handle="creator"))
        assert len(pool) == 1


class TestAccountPoolDedup:
    def test_higher_confidence_wins_ac7(self):
        """AC7: the entry with higher confidence dominates core fields."""
        pool = AccountPool()
        low = _account(
            confidence=0.4,
            adapter_id="adapter_a",
            handle="creator",
        )
        high = _account(
            confidence=0.95,
            adapter_id="adapter_b",
            handle="creator",
        )
        pool.add(low)
        pool.add(high)

        stored = pool.get("youtube", "creator")
        assert stored is not None
        assert stored.confidence == 0.95
        assert stored.source_adapter_id == "adapter_b"

    def test_existing_wins_when_incoming_has_lower_confidence(self):
        pool = AccountPool()
        first = _account(confidence=0.9, adapter_id="adapter_a", handle="creator")
        second = _account(confidence=0.3, adapter_id="adapter_b", handle="creator")
        pool.add(first)
        pool.add(second)

        stored = pool.get("youtube", "creator")
        assert stored is not None
        assert stored.confidence == 0.9
        assert stored.source_adapter_id == "adapter_a"


class TestAttributionMerge:
    def test_attribution_chain_merged_both_adapters_present_ac7(self):
        """AC7: attribution_chain contains steps from both entries."""
        pool = AccountPool()
        step_a = _step("adapter_a", "creator")
        step_b = _step("adapter_b", "creator_alias")
        acc_high = _account(confidence=0.9, adapter_id="adapter_a", handle="creator", steps=[step_a])
        acc_low = _account(confidence=0.5, adapter_id="adapter_b", handle="creator", steps=[step_b])

        pool.add(acc_high)
        pool.add(acc_low)

        stored = pool.get("youtube", "creator")
        assert stored is not None
        adapter_ids = [s.adapter_id for s in stored.attribution_chain]
        assert "adapter_a" in adapter_ids
        assert "adapter_b" in adapter_ids

    def test_attribution_chain_no_duplicate_steps(self):
        """Duplicate steps (same adapter_id + from_entity_value) are not duplicated."""
        pool = AccountPool()
        shared_step = _step("adapter_a", "creator")
        acc1 = _account(confidence=0.8, steps=[shared_step])
        # Second account carries the exact same step
        acc2 = _account(confidence=0.5, steps=[shared_step])

        pool.add(acc1)
        pool.add(acc2)

        stored = pool.get("youtube", "creator")
        assert stored is not None
        # Only one copy of the shared step should be in the chain
        dedup_keys = [(s.adapter_id, s.from_entity_value) for s in stored.attribution_chain]
        assert len(dedup_keys) == len(set(dedup_keys))

    def test_lower_confidence_wins_attribution_still_merged(self):
        """Even when incoming loses on confidence, its attribution step is still merged."""
        pool = AccountPool()
        step_a = _step("adapter_a", "creator")
        step_b = _step("adapter_b", "creator_alias")
        acc_high = _account(confidence=0.9, steps=[step_a])
        acc_low = _account(confidence=0.3, steps=[step_b])

        pool.add(acc_high)
        pool.add(acc_low)

        stored = pool.get("youtube", "creator")
        assert stored is not None
        adapter_ids = [s.adapter_id for s in stored.attribution_chain]
        assert "adapter_a" in adapter_ids
        assert "adapter_b" in adapter_ids


class TestAllAccounts:
    def test_all_accounts_returns_all_entries(self):
        pool = AccountPool()
        pool.add(_account(platform="youtube", handle="creator_a"))
        pool.add(_account(platform="youtube", handle="creator_b"))
        pool.add(_account(platform="twitter", handle="creator_c"))

        all_acc = pool.all_accounts()
        assert len(all_acc) == 3

    def test_all_accounts_empty_pool(self):
        pool = AccountPool()
        assert pool.all_accounts() == []


class TestCaseInsensitivity:
    def test_handle_case_insensitive_same_account(self):
        """'Creator' and 'creator' must be treated as the same account."""
        pool = AccountPool()
        acc_upper = _account(handle="Creator", confidence=0.8)
        acc_lower = _account(handle="creator", confidence=0.6)

        pool.add(acc_upper)
        pool.add(acc_lower)

        assert len(pool) == 1

    def test_get_is_case_insensitive(self):
        pool = AccountPool()
        pool.add(_account(handle="MyHandle", confidence=0.9))

        assert pool.get("youtube", "myhandle") is not None
        assert pool.get("youtube", "MYHANDLE") is not None
        assert pool.get("youtube", "MyHandle") is not None

    def test_platform_case_normalised(self):
        pool = AccountPool()
        pool.add(_account(platform="YouTube", handle="creator"))
        # Same platform, different casing
        found = pool.get("youtube", "creator")
        assert found is not None


class TestByTypeAny:
    def test_by_type_any_matches_platform(self):
        pool = AccountPool()
        pool.add(_account(platform="youtube", handle="creator_a"))
        pool.add(_account(platform="twitter", handle="creator_b"))

        results = pool.by_type_any(["youtube"])
        assert len(results) == 1
        assert results[0].platform == "youtube"

    def test_by_type_any_matches_platform_handle(self):
        pool = AccountPool()
        pool.add(_account(platform="youtube", handle="creator"))

        results = pool.by_type_any(["youtube_handle"])
        assert len(results) == 1

    def test_by_type_any_multiple_types(self):
        pool = AccountPool()
        pool.add(_account(platform="youtube", handle="c1"))
        pool.add(_account(platform="twitter", handle="c2"))
        pool.add(_account(platform="instagram", handle="c3"))

        results = pool.by_type_any(["youtube", "twitter"])
        assert len(results) == 2

    def test_by_type_any_empty_list_returns_empty(self):
        pool = AccountPool()
        pool.add(_account())
        assert pool.by_type_any([]) == []

    def test_by_type_any_no_match_returns_empty(self):
        pool = AccountPool()
        pool.add(_account(platform="youtube", handle="creator"))
        assert pool.by_type_any(["spotify"]) == []


class TestLen:
    def test_len_empty(self):
        assert len(AccountPool()) == 0

    def test_len_after_adds(self):
        pool = AccountPool()
        pool.add(_account(platform="youtube", handle="a"))
        pool.add(_account(platform="youtube", handle="b"))
        pool.add(_account(platform="twitter", handle="a"))
        assert len(pool) == 3
