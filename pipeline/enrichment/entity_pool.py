"""Thread-safe entity pool for the enrichment engine (spec 0014 §3.2)."""
from __future__ import annotations

import threading
from dataclasses import asdict
from pipeline.enrichment.entity import Entity


class EntityPool:
    """Keyed by (type, value). Higher confidence wins on duplicate. Thread-safe."""

    def __init__(self):
        self._store: dict[tuple[str, str], Entity] = {}
        self._provenance: dict[tuple[str, str], list[str]] = {}
        self._lock = threading.Lock()

    def add(self, entity: Entity) -> bool:
        """Insert or update. Returns True if the pool changed (new or higher-confidence)."""
        key = (entity.type, entity.value)
        with self._lock:
            self._provenance.setdefault(key, []).append(entity.source)
            existing = self._store.get(key)
            if existing is None or entity.confidence > existing.confidence:
                self._store[key] = entity
                return True
            return False

    def get(self, entity_type: str, entity_value: str) -> Entity | None:
        with self._lock:
            return self._store.get((entity_type, entity_value))

    def by_type(self, entity_type: str) -> list[Entity]:
        with self._lock:
            return [e for e in self._store.values() if e.type == entity_type]

    def by_type_any(self, entity_types: list[str]) -> list[Entity]:
        if not entity_types:
            return []
        types = set(entity_types)
        with self._lock:
            return [e for e in self._store.values() if e.type in types]

    def provenance(self, entity_type: str, entity_value: str) -> list[str]:
        """All adapter_ids that contributed to this entity (including losers)."""
        with self._lock:
            return list(self._provenance.get((entity_type, entity_value), []))

    def snapshot(self) -> list[dict]:
        """JSON-serializable list of all entities with all_sources provenance."""
        with self._lock:
            result = []
            for e in sorted(self._store.values(), key=lambda x: (x.type, x.value)):
                d = asdict(e)
                d["all_sources"] = list(self._provenance.get((e.type, e.value), []))
                result.append(d)
            return result

    def all_entities(self) -> list[Entity]:
        with self._lock:
            return list(self._store.values())

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)
