import threading
import pytest
from pipeline.enrichment.entity import make_entity
from pipeline.enrichment.entity_pool import EntityPool

TS = "2026-06-02T21:00:00Z"

def _h(value="foo", *, source="seed", confidence=1.0, depth=0):
    return make_entity("handle", value, source=source, confidence=confidence,
                       depth=depth, discovered_at=TS)

def _e(value="a@b.com", *, source="linktree", confidence=0.9, depth=1):
    return make_entity("email", value, source=source, confidence=confidence,
                       depth=depth, discovered_at=TS)


class TestEntityPoolBasics:
    def test_add_and_get(self):
        pool = EntityPool()
        e = _h()
        pool.add(e)
        assert pool.get("handle", "foo") == e

    def test_higher_confidence_wins(self):
        pool = EntityPool()
        pool.add(_h(confidence=0.5, source="a"))
        pool.add(_h(confidence=0.9, source="b"))
        assert pool.get("handle", "foo").confidence == 0.9
        assert pool.get("handle", "foo").source == "b"

    def test_lower_confidence_does_not_replace(self):
        pool = EntityPool()
        pool.add(_h(confidence=0.9))
        pool.add(_h(confidence=0.5))
        assert pool.get("handle", "foo").confidence == 0.9

    def test_add_returns_true_on_new(self):
        pool = EntityPool()
        assert pool.add(_h()) is True

    def test_add_returns_false_when_not_updated(self):
        pool = EntityPool()
        pool.add(_h(confidence=1.0))
        assert pool.add(_h(confidence=0.5)) is False

    def test_get_returns_none_on_miss(self):
        pool = EntityPool()
        assert pool.get("handle", "missing") is None

    def test_by_type(self):
        pool = EntityPool()
        pool.add(_h("foo"))
        pool.add(_h("bar"))
        pool.add(_e())
        handles = pool.by_type("handle")
        assert len(handles) == 2
        assert all(e.type == "handle" for e in handles)

    def test_by_type_any(self):
        pool = EntityPool()
        pool.add(_h())
        pool.add(_e())
        results = pool.by_type_any(["handle", "email"])
        assert len(results) == 2

    def test_by_type_any_empty_types(self):
        pool = EntityPool()
        pool.add(_h())
        assert pool.by_type_any([]) == []

    def test_provenance_accumulates_all_sources(self):
        pool = EntityPool()
        pool.add(_h(source="seed"))
        pool.add(_h(confidence=0.3, source="maigret"))
        provs = pool.provenance("handle", "foo")
        assert "seed" in provs
        assert "maigret" in provs

    def test_snapshot_is_json_serializable(self):
        import json
        pool = EntityPool()
        pool.add(_h())
        json.dumps(pool.snapshot())

    def test_len(self):
        pool = EntityPool()
        pool.add(_h("foo"))
        pool.add(_h("bar"))
        assert len(pool) == 2

    def test_all_entities(self):
        pool = EntityPool()
        pool.add(_h("foo"))
        pool.add(_e())
        assert len(pool.all_entities()) == 2

    def test_thread_safe_concurrent_writes(self):
        pool = EntityPool()
        errors = []
        def worker(i):
            try:
                pool.add(make_entity("handle", f"user{i:03d}", source="t",
                                     confidence=0.5, depth=0, discovered_at=TS))
            except Exception as exc:
                errors.append(exc)
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
        for t in threads: t.start()
        for t in threads: t.join()
        assert not errors
        assert len(pool.by_type("handle")) == 50
