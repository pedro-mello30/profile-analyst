"""AccountPool: dedup, confidence merge, delta tracking (spec-0018 §3.2)."""
from __future__ import annotations

import dataclasses
import threading
from pipeline.account_discovery.models import AttributionStep, DiscoveredAccount


class AccountPool:
    """Keyed by (platform, handle.lower()). Higher confidence wins on duplicate.

    Dedup invariant (AC7): when the same (platform, handle) is added twice,
    only one entry survives. The entry with the higher confidence dominates
    core fields. Attribution chains from both entries are merged with no
    duplicate steps (deduped by (adapter_id, from_entity_value)).
    """

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], DiscoveredAccount] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _key(platform: str, handle: str) -> tuple[str, str]:
        return (platform.lower(), handle.lower())

    @staticmethod
    def _merge_attribution(
        base: list[AttributionStep],
        incoming: list[AttributionStep],
    ) -> list[AttributionStep]:
        """Return a deduplicated union of both lists.

        Uniqueness key: (adapter_id, from_entity_value).
        Order: base steps first, then new steps from incoming.
        """
        seen: set[tuple[str, str]] = set()
        merged: list[AttributionStep] = []
        for step in base:
            dedup_key = (step.adapter_id, step.from_entity_value)
            if dedup_key not in seen:
                seen.add(dedup_key)
                merged.append(step)
        for step in incoming:
            dedup_key = (step.adapter_id, step.from_entity_value)
            if dedup_key not in seen:
                seen.add(dedup_key)
                merged.append(step)
        return merged

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add(self, account: DiscoveredAccount) -> bool:
        """Insert or update. Returns True if the pool changed (new or higher-confidence).

        Regardless of confidence comparison, attribution chains are always
        merged so no adapter's provenance is lost.
        """
        key = self._key(account.platform, account.handle)
        with self._lock:
            existing = self._store.get(key)
            if existing is None:
                self._store[key] = account
                return True

            # Merge attribution chains regardless of who wins on confidence.
            merged_chain = self._merge_attribution(
                existing.attribution_chain, account.attribution_chain
            )

            if account.confidence > existing.confidence:
                # Incoming wins core fields; store a new instance with merged chain.
                updated = dataclasses.replace(account, attribution_chain=merged_chain)
                self._store[key] = updated
                return True

            # Existing wins core fields; store a new instance with merged chain.
            updated = dataclasses.replace(existing, attribution_chain=merged_chain)
            self._store[key] = updated
            return False

    def get(self, platform: str, handle: str) -> DiscoveredAccount | None:
        with self._lock:
            return self._store.get(self._key(platform, handle))

    def all_accounts(self) -> list[DiscoveredAccount]:
        with self._lock:
            return list(self._store.values())

    def by_type_any(self, entity_types: list[str]) -> list[DiscoveredAccount]:
        """Return accounts whose platform or '{platform}_handle' is in entity_types."""
        if not entity_types:
            return []
        types = set(entity_types)
        results = []
        with self._lock:
            for acc in self._store.values():
                platform_lower = acc.platform.lower()
                if platform_lower in types or f"{platform_lower}_handle" in types:
                    results.append(acc)
        return results

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)
