"""Tests for discovery scheduler next_runnable (spec-0018 §6)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from pipeline.account_discovery.scheduler import DiscoveryConfig, next_runnable


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _adapter(
    adapter_id: str = "adapter_v1",
    requires: frozenset[str] | None = None,
    priority: int = 10,
    tos_compliant: bool = True,
) -> SimpleNamespace:
    """Build a duck-typed adapter for testing (no DiscoveryAdapter subclass needed)."""
    return SimpleNamespace(
        adapter_id=adapter_id,
        requires=requires if requires is not None else frozenset(),
        priority=priority,
        tos_compliant=tos_compliant,
    )


_DEFAULT_CONFIG = DiscoveryConfig()


# ---------------------------------------------------------------------------
# AC1 — Adapter with satisfied requires is in runnable list
# ---------------------------------------------------------------------------


class TestSatisfiedRequiresIsRunnable:
    def test_empty_requires_always_eligible(self):
        a = _adapter(requires=frozenset())
        result = next_runnable([a], set(), {}, _DEFAULT_CONFIG)
        assert a in result

    def test_single_require_satisfied(self):
        a = _adapter(requires=frozenset({"instagram_handle"}))
        pool = {"instagram_handle"}
        result = next_runnable([a], pool, {}, _DEFAULT_CONFIG)
        assert a in result

    def test_multiple_requires_all_satisfied(self):
        a = _adapter(requires=frozenset({"instagram_handle", "domain"}))
        pool = {"instagram_handle", "domain", "url"}
        result = next_runnable([a], pool, {}, _DEFAULT_CONFIG)
        assert a in result

    def test_pool_superset_of_requires_eligible(self):
        """Pool may contain more types than required — adapter is still eligible."""
        a = _adapter(requires=frozenset({"email"}))
        pool = {"instagram_handle", "domain", "email", "url"}
        result = next_runnable([a], pool, {}, _DEFAULT_CONFIG)
        assert a in result


# ---------------------------------------------------------------------------
# AC2 — Adapter with unsatisfied requires is NOT in runnable list
# ---------------------------------------------------------------------------


class TestUnsatisfiedRequiresNotRunnable:
    def test_single_require_missing(self):
        a = _adapter(requires=frozenset({"youtube_handle"}))
        pool = {"instagram_handle"}
        result = next_runnable([a], pool, {}, _DEFAULT_CONFIG)
        assert a not in result

    def test_partial_requires_still_not_eligible(self):
        a = _adapter(requires=frozenset({"instagram_handle", "domain"}))
        pool = {"instagram_handle"}  # domain is missing
        result = next_runnable([a], pool, {}, _DEFAULT_CONFIG)
        assert a not in result

    def test_empty_pool_blocks_adapter_with_requires(self):
        a = _adapter(requires=frozenset({"instagram_handle"}))
        result = next_runnable([a], set(), {}, _DEFAULT_CONFIG)
        assert a not in result

    def test_empty_pool_allows_adapter_with_no_requires(self):
        a = _adapter(requires=frozenset())
        result = next_runnable([a], set(), {}, _DEFAULT_CONFIG)
        assert a in result


# ---------------------------------------------------------------------------
# AC3 — Adapter already in ran_set as "ran" is NOT in runnable list
# ---------------------------------------------------------------------------


class TestRanStatusExcluded:
    def test_ran_status_excluded(self):
        a = _adapter(adapter_id="x")
        ran = {"x": "ran"}
        result = next_runnable([a], set(), ran, _DEFAULT_CONFIG)
        assert a not in result

    def test_ran_status_excludes_only_that_adapter(self):
        a1 = _adapter(adapter_id="a1")
        a2 = _adapter(adapter_id="a2")
        ran = {"a1": "ran"}
        result = next_runnable([a1, a2], set(), ran, _DEFAULT_CONFIG)
        assert a1 not in result
        assert a2 in result

    def test_adapter_not_in_ran_set_is_eligible(self):
        a = _adapter(adapter_id="new_adapter")
        ran = {"other_adapter": "ran"}
        result = next_runnable([a], set(), ran, _DEFAULT_CONFIG)
        assert a in result


# ---------------------------------------------------------------------------
# AC4 — Adapter already in ran_set as "skipped" is NOT in runnable list
# ---------------------------------------------------------------------------


class TestSkippedStatusExcluded:
    def test_skipped_status_excluded(self):
        a = _adapter(adapter_id="skip_me")
        ran = {"skip_me": "skipped"}
        result = next_runnable([a], set(), ran, _DEFAULT_CONFIG)
        assert a not in result

    def test_skipped_does_not_affect_other_adapters(self):
        a1 = _adapter(adapter_id="a1")
        a2 = _adapter(adapter_id="a2")
        ran = {"a2": "skipped"}
        result = next_runnable([a1, a2], set(), ran, _DEFAULT_CONFIG)
        assert a1 in result
        assert a2 not in result


class TestFailedStatusExcluded:
    """Also verify 'failed' is a terminal status (boundary of AC3/AC4)."""

    def test_failed_status_excluded(self):
        a = _adapter(adapter_id="failed_adapter")
        ran = {"failed_adapter": "failed"}
        result = next_runnable([a], set(), ran, _DEFAULT_CONFIG)
        assert a not in result

    def test_pending_status_not_excluded(self):
        """A non-terminal status like 'pending' should not exclude the adapter."""
        a = _adapter(adapter_id="pending_adapter")
        ran = {"pending_adapter": "pending"}
        result = next_runnable([a], set(), ran, _DEFAULT_CONFIG)
        assert a in result


# ---------------------------------------------------------------------------
# AC5 — Adapter with tos_compliant=False + allow_noncompliant=False → NOT runnable
# ---------------------------------------------------------------------------


class TestTosComplianceGate:
    def test_noncompliant_excluded_by_default(self):
        a = _adapter(tos_compliant=False)
        config = DiscoveryConfig(allow_noncompliant=False)
        result = next_runnable([a], set(), {}, config)
        assert a not in result

    def test_noncompliant_excluded_when_flag_is_false(self):
        a = _adapter(tos_compliant=False)
        result = next_runnable([a], set(), {}, _DEFAULT_CONFIG)
        assert a not in result

    def test_compliant_adapter_included(self):
        a = _adapter(tos_compliant=True)
        result = next_runnable([a], set(), {}, _DEFAULT_CONFIG)
        assert a in result

    def test_noncompliant_mix_only_removes_noncompliant(self):
        compliant = _adapter(adapter_id="ok", tos_compliant=True)
        noncompliant = _adapter(adapter_id="bad", tos_compliant=False)
        result = next_runnable([compliant, noncompliant], set(), {}, _DEFAULT_CONFIG)
        assert compliant in result
        assert noncompliant not in result


# ---------------------------------------------------------------------------
# AC6 — Adapter with tos_compliant=False + allow_noncompliant=True → IS runnable
# ---------------------------------------------------------------------------


class TestAllowNoncompliantFlag:
    def test_noncompliant_allowed_when_flag_true(self):
        a = _adapter(tos_compliant=False)
        config = DiscoveryConfig(allow_noncompliant=True)
        result = next_runnable([a], set(), {}, config)
        assert a in result

    def test_both_compliant_and_noncompliant_included_when_flag_true(self):
        compliant = _adapter(adapter_id="ok", tos_compliant=True)
        noncompliant = _adapter(adapter_id="bad", tos_compliant=False)
        config = DiscoveryConfig(allow_noncompliant=True)
        result = next_runnable([compliant, noncompliant], set(), {}, config)
        assert compliant in result
        assert noncompliant in result

    def test_allow_noncompliant_does_not_bypass_ran_set(self):
        """allow_noncompliant=True still respects terminal ran_set statuses."""
        a = _adapter(adapter_id="was_ran", tos_compliant=False)
        config = DiscoveryConfig(allow_noncompliant=True)
        ran = {"was_ran": "ran"}
        result = next_runnable([a], set(), ran, config)
        assert a not in result

    def test_allow_noncompliant_does_not_bypass_requires(self):
        """allow_noncompliant=True still respects unsatisfied requires."""
        a = _adapter(tos_compliant=False, requires=frozenset({"domain"}))
        config = DiscoveryConfig(allow_noncompliant=True)
        result = next_runnable([a], set(), {}, config)
        assert a not in result


# ---------------------------------------------------------------------------
# AC7 — Results sorted by priority ascending
# ---------------------------------------------------------------------------


class TestSortedByPriorityAscending:
    def test_two_adapters_sorted_ascending(self):
        low = _adapter(adapter_id="low", priority=1)
        high = _adapter(adapter_id="high", priority=100)
        result = next_runnable([high, low], set(), {}, _DEFAULT_CONFIG)
        assert result == [low, high]

    def test_three_adapters_sorted_ascending(self):
        a1 = _adapter(adapter_id="a1", priority=30)
        a2 = _adapter(adapter_id="a2", priority=10)
        a3 = _adapter(adapter_id="a3", priority=20)
        result = next_runnable([a1, a2, a3], set(), {}, _DEFAULT_CONFIG)
        priorities = [a.priority for a in result]
        assert priorities == sorted(priorities)

    def test_single_adapter_trivially_sorted(self):
        a = _adapter(priority=42)
        result = next_runnable([a], set(), {}, _DEFAULT_CONFIG)
        assert len(result) == 1
        assert result[0].priority == 42

    def test_equal_priorities_all_returned(self):
        """Adapters with identical priority must all be present (stable order not enforced)."""
        a1 = _adapter(adapter_id="a1", priority=5)
        a2 = _adapter(adapter_id="a2", priority=5)
        result = next_runnable([a1, a2], set(), {}, _DEFAULT_CONFIG)
        assert len(result) == 2

    def test_empty_adapters_returns_empty(self):
        result = next_runnable([], set(), {}, _DEFAULT_CONFIG)
        assert result == []

    def test_all_excluded_returns_empty(self):
        a = _adapter(tos_compliant=False)
        result = next_runnable([a], set(), {}, _DEFAULT_CONFIG)
        assert result == []
