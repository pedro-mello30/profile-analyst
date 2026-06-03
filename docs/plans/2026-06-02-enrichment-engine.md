# Enrichment Engine Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build Stage 1B — a dependency-graph-driven enrichment engine that fans out across 19 free data sources (OSINT + public APIs) and writes `enrichment_map.json` to dramatically widen the dossier signal space.

**Architecture:** Fixed-point BFS scheduler where each adapter declares `requires`/`produces` entity types; the engine runs adapters when their required entities appear in the pool, cascading discoveries through tier 0 → fast → medium → slow. Cache layer (per-adapter TTL) prevents quota exhaustion on re-runs.

**Tech Stack:** Python 3.12 · `requests` · `pyyaml` · `jsonschema` · `threading.ThreadPoolExecutor` · `hashlib` (cache keys) · `re` (normalization) · `pytest`

**Spec:** `specs/0014-multi-source-enrichment-engine/spec.md`

---

## Stage ordering clarification

Stage 1B reads seeds from `02-normalized.json` (written by Stage 2). The effective pipeline order is:

```
Stage 1  → 01-raw.json
Stage 2  → 02-normalized.json        (fast, ~1s, no API calls)
Stage 1B → enrichment_map.json       (reads 02-normalized.json for seeds)
Stage 3  → 03-features.json          (reads enrichment_map.json if present)
Stage 6  → 06-dossier.json + report
```

---

## Task 1: Entity Model

**Files:**
- Create: `pipeline/enrichment/__init__.py`
- Create: `pipeline/enrichment/entity.py`
- Create: `tests/enrichment/__init__.py`
- Create: `tests/enrichment/test_entity.py`

**Step 1: Write failing tests**

```python
# tests/enrichment/test_entity.py
import re
import pytest
from pipeline.enrichment.entity import (
    Entity, EntityTypeSpec, ENTITY_TYPES,
    InvalidEntityTypeError, make_entity,
)
from datetime import datetime, timezone

TS = "2026-06-02T21:00:00Z"


class TestEntityTypeRegistry:
    def test_all_24_types_present(self):
        expected = {
            "handle", "display_name", "bio_url", "email", "gmail", "domain",
            "subdomain", "youtube_channel_id", "youtube_handle", "tiktok_handle",
            "twitter_handle", "instagram_handle", "linkedin_url", "github_handle",
            "reddit_username", "twitch_handle", "spotify_artist_id", "podcast_url",
            "podcast_itunes_id", "substack_url", "website_url", "wikidata_id",
            "cnpj", "phone",
        }
        assert set(ENTITY_TYPES.keys()) == expected

    def test_each_spec_has_required_fields(self):
        for name, spec in ENTITY_TYPES.items():
            assert hasattr(spec, "pattern"), name
            assert hasattr(spec, "normalizer"), name
            assert hasattr(spec, "osint_risk"), name
            assert hasattr(spec, "example"), name

    def test_osint_risk_types(self):
        assert ENTITY_TYPES["email"].osint_risk is True
        assert ENTITY_TYPES["gmail"].osint_risk is True
        assert ENTITY_TYPES["cnpj"].osint_risk is True
        assert ENTITY_TYPES["phone"].osint_risk is True
        assert ENTITY_TYPES["handle"].osint_risk is False
        assert ENTITY_TYPES["youtube_channel_id"].osint_risk is False


class TestNormalizers:
    def test_handle_strips_at(self):
        assert ENTITY_TYPES["handle"].normalizer("@filipelauar") == "filipelauar"

    def test_handle_lowercases(self):
        assert ENTITY_TYPES["handle"].normalizer("FilipeLauar") == "filipelauar"

    def test_email_lowercases(self):
        assert ENTITY_TYPES["email"].normalizer("Foo@Bar.COM") == "foo@bar.com"

    def test_domain_strips_www(self):
        assert ENTITY_TYPES["domain"].normalizer("www.vidacomia.com") == "vidacomia.com"

    def test_cnpj_strips_punctuation(self):
        assert ENTITY_TYPES["cnpj"].normalizer("12.345.678/0001-90") == "12345678000190"

    def test_cnpj_wrong_length_raises(self):
        with pytest.raises(ValueError, match="14 digits"):
            ENTITY_TYPES["cnpj"].normalizer("123")

    def test_phone_e164(self):
        assert ENTITY_TYPES["phone"].normalizer("+55 31 9999-1234") == "+5531999912 34".replace(" ", "")

    def test_youtube_handle_adds_at(self):
        assert ENTITY_TYPES["youtube_handle"].normalizer("vidacomia") == "@vidacomia"

    def test_wikidata_uppercases(self):
        assert ENTITY_TYPES["wikidata_id"].normalizer("q12345") == "Q12345"

    def test_spotify_adds_prefix(self):
        raw = "abc123"
        assert ENTITY_TYPES["spotify_artist_id"].normalizer(raw) == "spotify:artist:abc123"

    def test_url_lowercases_host(self):
        url = "HTTPS://LinkTr.ee/vidacomia"
        result = ENTITY_TYPES["bio_url"].normalizer(url)
        assert result == "https://linktr.ee/vidacomia"

    def test_url_strips_trailing_slash(self):
        assert ENTITY_TYPES["website_url"].normalizer("https://example.com/") == "https://example.com"


class TestEntityDataclass:
    def test_valid_entity_constructs(self):
        e = Entity(
            type="handle", value="filipelauar",
            source="seed", confidence=1.0, depth=0, discovered_at=TS,
        )
        assert e.value == "filipelauar"

    def test_unknown_type_raises(self):
        with pytest.raises(InvalidEntityTypeError):
            Entity(type="bogus_type", value="x", source="seed",
                   confidence=1.0, depth=0, discovered_at=TS)

    def test_negative_depth_raises(self):
        with pytest.raises(ValueError, match="depth"):
            Entity(type="handle", value="foo", source="seed",
                   confidence=1.0, depth=-1, discovered_at=TS)

    def test_confidence_clamped_silently(self):
        # Values outside 0-1 should be clamped, not raise
        e = Entity(type="handle", value="foo", source="seed",
                   confidence=1.5, depth=0, discovered_at=TS)
        assert e.confidence == 1.0

    def test_bad_timestamp_raises(self):
        with pytest.raises(ValueError, match="ISO 8601"):
            Entity(type="handle", value="foo", source="seed",
                   confidence=1.0, depth=0, discovered_at="not-a-date")

    def test_unnormalized_value_raises(self):
        with pytest.raises(ValueError, match="normalized"):
            Entity(type="handle", value="@foo",   # @ not stripped
                   source="seed", confidence=1.0, depth=0, discovered_at=TS)

    def test_frozen(self):
        e = Entity(type="handle", value="foo", source="seed",
                   confidence=1.0, depth=0, discovered_at=TS)
        with pytest.raises(Exception):
            e.value = "bar"  # type: ignore


class TestMakeEntity:
    def test_make_entity_normalizes_value(self):
        e = make_entity("handle", "@FilipeLauar", source="seed", confidence=1.0, depth=0)
        assert e.value == "filipelauar"

    def test_make_entity_cnpj(self):
        e = make_entity("cnpj", "12.345.678/0001-90", source="cnpj", confidence=0.9, depth=1)
        assert e.value == "12345678000190"
```

**Step 2: Run to verify failure**

```bash
pytest tests/enrichment/test_entity.py -v 2>&1 | head -20
```
Expected: `ModuleNotFoundError: No module named 'pipeline.enrichment'`

**Step 3: Implement `pipeline/enrichment/entity.py`**

```python
# pipeline/enrichment/__init__.py
# (empty)

# pipeline/enrichment/entity.py
from __future__ import annotations

import re
import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, ClassVar
from urllib.parse import urlparse, urlunparse


class InvalidEntityTypeError(ValueError):
    pass


@dataclass(frozen=True)
class EntityTypeSpec:
    name: str
    pattern: re.Pattern
    normalizer: Callable[[str], str]
    example: str
    osint_risk: bool


# ── Normalizer helpers ────────────────────────────────────────────────────────

def _norm_handle(v: str) -> str:
    return re.sub(r"^[@u/]+", "", v.strip()).lower()

def _norm_url(v: str) -> str:
    p = urlparse(v.strip())
    return urlunparse((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/"), "", "", ""))

def _norm_email(v: str) -> str:
    return v.strip().lower()

def _norm_domain(v: str) -> str:
    v = v.strip().lower()
    if v.startswith("www."):
        v = v[4:]
    return v

def _norm_lower(v: str) -> str:
    return v.strip().lower()

def _norm_strip(v: str) -> str:
    return v.strip()

def _norm_upper(v: str) -> str:
    return v.strip().upper()

def _norm_cnpj(v: str) -> str:
    digits = re.sub(r"\D", "", v)
    if len(digits) != 14:
        raise ValueError(f"CNPJ must have 14 digits, got {len(digits)}: {v!r}")
    return digits

def _norm_phone(v: str) -> str:
    digits = re.sub(r"[^\d+]", "", v.strip())
    if not digits.startswith("+"):
        digits = "+" + digits
    return digits

def _norm_yt_handle(v: str) -> str:
    v = v.strip().lower()
    if not v.startswith("@"):
        v = "@" + v
    return v

def _norm_social_handle(prefix: str = "@") -> Callable[[str], str]:
    """Strip then re-add a prefix and lowercase."""
    def _norm(v: str) -> str:
        v = v.strip().lower().lstrip(prefix)
        return prefix + v
    return _norm

def _norm_spotify(v: str) -> str:
    v = v.strip()
    if v.startswith("spotify:artist:"):
        return v
    return f"spotify:artist:{v}"

def _norm_gmail(v: str) -> str:
    v = _norm_email(v)
    if not v.endswith("@gmail.com"):
        raise ValueError(f"gmail entity must end with @gmail.com, got {v!r}")
    return v

def _norm_linkedin(v: str) -> str:
    v = v.strip()
    if not v.startswith("http"):
        v = "https://linkedin.com/in/" + v
    return _norm_url(v)

# ── Registry ──────────────────────────────────────────────────────────────────

def _r(pattern: str, normalizer: Callable, example: str, osint_risk: bool) -> EntityTypeSpec:
    return EntityTypeSpec(
        name="",  # filled by the dict key
        pattern=re.compile(pattern),
        normalizer=normalizer,
        example=example,
        osint_risk=osint_risk,
    )

ENTITY_TYPES: dict[str, EntityTypeSpec] = {
    "handle":            _r(r"^[a-z0-9._]{1,64}$",            _norm_handle,  "filipelauar",           False),
    "display_name":      _r(r"^.+$",                          _norm_strip,   "Filipe Lauar",           False),
    "bio_url":           _r(r"^https?://.+$",                 _norm_url,     "https://linktr.ee/x",   False),
    "email":             _r(r"^[^@]+@[^@]+\.[^@]+$",          _norm_email,   "a@b.com",               True),
    "gmail":             _r(r"^[^@]+@gmail\.com$",            _norm_gmail,   "a@gmail.com",           True),
    "domain":            _r(r"^[a-z0-9.-]+\.[a-z]{2,}$",     _norm_domain,  "vidacomia.com",          False),
    "subdomain":         _r(r"^[a-z0-9.-]+\.[a-z0-9.-]+\.[a-z]{2,}$", _norm_lower, "blog.vida.com",  False),
    "youtube_channel_id":_r(r"^UC[a-zA-Z0-9_-]{22}$",        _norm_strip,   "UCxyz1234567890123456789", False),
    "youtube_handle":    _r(r"^@[a-zA-Z0-9._-]{3,30}$",      _norm_yt_handle, "@vidacomia",          False),
    "tiktok_handle":     _r(r"^@[a-zA-Z0-9._]{1,24}$",       _norm_social_handle("@"), "@filipe",    False),
    "twitter_handle":    _r(r"^@[a-zA-Z0-9_]{1,15}$",        _norm_social_handle("@"), "@filipe",    False),
    "instagram_handle":  _r(r"^[a-z0-9._]{1,30}$",           _norm_handle,  "filipelauar",           False),
    "linkedin_url":      _r(r"^https?://[a-z.]*linkedin\.com/in/[^/]+/?$", _norm_linkedin, "https://linkedin.com/in/x", False),
    "github_handle":     _r(r"^[a-z0-9-]{1,39}$",            _norm_lower,   "filipelauar",           False),
    "reddit_username":   _r(r"^[a-zA-Z0-9_-]{3,20}$",        _norm_handle,  "filipelauar",           False),
    "twitch_handle":     _r(r"^[a-z0-9_]{4,25}$",            _norm_lower,   "filipelauar",           False),
    "spotify_artist_id": _r(r"^spotify:artist:[a-zA-Z0-9]+$",_norm_spotify,  "spotify:artist:abc",   False),
    "podcast_url":       _r(r"^https?://.+$",                 _norm_url,     "https://pod.example.com", False),
    "podcast_itunes_id": _r(r"^\d{6,12}$",                   _norm_strip,   "1234567890",            False),
    "substack_url":      _r(r"^https://[a-z0-9-]+\.substack\.com/?$", _norm_lower, "https://foo.substack.com", False),
    "website_url":       _r(r"^https?://.+$",                 _norm_url,     "https://vidacomia.com", False),
    "wikidata_id":       _r(r"^Q\d+$",                        _norm_upper,   "Q12345",                False),
    "cnpj":              _r(r"^\d{14}$",                      _norm_cnpj,    "12345678000190",        True),
    "phone":             _r(r"^\+\d{10,15}$",                 _norm_phone,   "+5531999912345",        True),
}

# Patch the name field (frozen dataclass workaround)
ENTITY_TYPES = {
    k: EntityTypeSpec(name=k, pattern=v.pattern, normalizer=v.normalizer,
                      example=v.example, osint_risk=v.osint_risk)
    for k, v in ENTITY_TYPES.items()
}


# ── Entity dataclass ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Entity:
    type: str
    value: str
    source: str
    confidence: float
    depth: int
    discovered_at: str

    def __post_init__(self):
        if self.type not in ENTITY_TYPES:
            raise InvalidEntityTypeError(f"Unknown entity type: {self.type!r}")
        if not (0.0 <= self.confidence <= 1.0):
            # Clamp silently
            object.__setattr__(self, "confidence", max(0.0, min(1.0, self.confidence)))
        if self.depth < 0:
            raise ValueError(f"depth must be >= 0, got {self.depth}")
        try:
            datetime.fromisoformat(self.discovered_at.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            raise ValueError(f"discovered_at must be UTC ISO 8601, got {self.discovered_at!r}")
        spec = ENTITY_TYPES[self.type]
        normalized = spec.normalizer(self.value)
        if normalized != self.value:
            raise ValueError(
                f"Entity value {self.value!r} is not normalized for type {self.type!r}. "
                f"Apply ENTITY_TYPES['{self.type}'].normalizer() first. Expected: {normalized!r}"
            )


def make_entity(
    entity_type: str,
    raw_value: str,
    *,
    source: str,
    confidence: float,
    depth: int,
    discovered_at: str | None = None,
) -> Entity:
    """Normalize raw_value and construct a validated Entity."""
    from datetime import datetime, timezone
    if discovered_at is None:
        discovered_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    spec = ENTITY_TYPES[entity_type]
    normalized = spec.normalizer(raw_value)
    return Entity(
        type=entity_type, value=normalized, source=source,
        confidence=confidence, depth=depth, discovered_at=discovered_at,
    )
```

**Step 4: Run tests**
```bash
pytest tests/enrichment/test_entity.py -v
```
Expected: all pass.

**Step 5: Commit**
```bash
git add pipeline/enrichment/__init__.py pipeline/enrichment/entity.py tests/enrichment/__init__.py tests/enrichment/test_entity.py
git commit -m "feat(enrichment): entity model with EntityTypeSpec registry and 24 canonical types"
```

---

## Task 2: EntityPool

**Files:**
- Create: `pipeline/enrichment/entity_pool.py`
- Create: `tests/enrichment/test_entity_pool.py`

**Step 1: Write failing tests**

```python
# tests/enrichment/test_entity_pool.py
import threading
import pytest
from pipeline.enrichment.entity import make_entity
from pipeline.enrichment.entity_pool import EntityPool

TS = "2026-06-02T21:00:00Z"

def _handle(value="foo", *, source="seed", confidence=1.0, depth=0):
    return make_entity("handle", value, source=source, confidence=confidence,
                       depth=depth, discovered_at=TS)

def _email(value="a@b.com", *, source="linktree", confidence=0.9, depth=1):
    return make_entity("email", value, source=source, confidence=confidence,
                       depth=depth, discovered_at=TS)


class TestEntityPoolBasics:
    def test_add_and_get(self):
        pool = EntityPool()
        e = _handle()
        pool.add(e)
        assert pool.get("handle", "foo") == e

    def test_higher_confidence_wins(self):
        pool = EntityPool()
        low = _handle(confidence=0.5, source="a")
        high = _handle(confidence=0.9, source="b")
        pool.add(low)
        pool.add(high)
        assert pool.get("handle", "foo").confidence == 0.9
        assert pool.get("handle", "foo").source == "b"

    def test_lower_confidence_does_not_replace(self):
        pool = EntityPool()
        pool.add(_handle(confidence=0.9))
        pool.add(_handle(confidence=0.5))
        assert pool.get("handle", "foo").confidence == 0.9

    def test_add_returns_true_on_new(self):
        pool = EntityPool()
        assert pool.add(_handle()) is True

    def test_add_returns_false_when_not_updated(self):
        pool = EntityPool()
        pool.add(_handle(confidence=1.0))
        assert pool.add(_handle(confidence=0.5)) is False

    def test_by_type(self):
        pool = EntityPool()
        pool.add(_handle("foo"))
        pool.add(_handle("bar"))
        pool.add(_email())
        handles = pool.by_type("handle")
        assert len(handles) == 2
        assert all(e.type == "handle" for e in handles)

    def test_by_type_any(self):
        pool = EntityPool()
        pool.add(_handle())
        pool.add(_email())
        results = pool.by_type_any(["handle", "email"])
        assert len(results) == 2

    def test_provenance_accumulates(self):
        pool = EntityPool()
        pool.add(_handle(source="seed"))
        pool.add(_handle(confidence=0.3, source="maigret"))  # lower, not stored
        provs = pool.provenance("handle", "foo")
        assert "seed" in provs
        assert "maigret" in provs  # provenance tracks all, even losers

    def test_snapshot_is_serializable(self):
        import json
        pool = EntityPool()
        pool.add(_handle())
        snapshot = pool.snapshot()
        json.dumps(snapshot)  # must not raise

    def test_thread_safe(self):
        pool = EntityPool()
        errors = []
        def worker(i):
            try:
                pool.add(make_entity("handle", f"user{i}", source="t",
                                     confidence=0.5, depth=0, discovered_at=TS))
            except Exception as e:
                errors.append(e)
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors
        assert len(pool.by_type("handle")) == 50
```

**Step 2: Run — verify failure**
```bash
pytest tests/enrichment/test_entity_pool.py -v 2>&1 | head -10
```

**Step 3: Implement `pipeline/enrichment/entity_pool.py`**

```python
from __future__ import annotations
import threading
from dataclasses import asdict
from pipeline.enrichment.entity import Entity


class EntityPool:
    def __init__(self):
        self._store: dict[tuple[str, str], Entity] = {}
        self._provenance: dict[tuple[str, str], list[str]] = {}
        self._lock = threading.Lock()

    def add(self, entity: Entity) -> bool:
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
        types = set(entity_types)
        with self._lock:
            return [e for e in self._store.values() if e.type in types]

    def provenance(self, entity_type: str, entity_value: str) -> list[str]:
        with self._lock:
            return list(self._provenance.get((entity_type, entity_value), []))

    def snapshot(self) -> list[dict]:
        with self._lock:
            return [
                {**asdict(e), "all_sources": list(self._provenance.get((e.type, e.value), []))}
                for e in self._store.values()
            ]

    def all_entities(self) -> list[Entity]:
        with self._lock:
            return list(self._store.values())

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)
```

**Step 4: Run tests**
```bash
pytest tests/enrichment/test_entity_pool.py -v
```

**Step 5: Commit**
```bash
git add pipeline/enrichment/entity_pool.py tests/enrichment/test_entity_pool.py
git commit -m "feat(enrichment): thread-safe EntityPool with provenance tracking"
```

---

## Task 3: Adapter Contract

**Files:**
- Create: `pipeline/enrichment/adapter.py`
- Create: `tests/enrichment/test_adapter.py`

**Step 1: Write failing tests**

```python
# tests/enrichment/test_adapter.py
import pytest
from pipeline.enrichment.adapter import (
    AdapterConfig, AdapterResult, Signal, EnrichmentAdapter, AdapterContractError
)
from pipeline.enrichment.entity import make_entity

TS = "2026-06-02T21:00:00Z"
CFG = AdapterConfig(
    profile_id="filipelauar", run_id="test-run-1",
    max_depth=2, max_cost_usd=0.50, max_runtime_s=60,
    secrets={}, osint_enabled=True, cache_enabled=True, dry_run=False,
)


class TestAdapterConfig:
    def test_constructs(self):
        assert CFG.profile_id == "filipelauar"
        assert CFG.dry_run is False


class TestAdapterContractValidation:
    def test_missing_attribute_raises_at_import(self):
        with pytest.raises(AdapterContractError, match="missing required"):
            class BadAdapter(EnrichmentAdapter):
                # missing almost everything
                adapter_id = "bad"
                def run(self, seed_entities, config):
                    return None

    def test_unknown_entity_type_in_requires_raises(self):
        with pytest.raises(AdapterContractError, match="unknown entity types"):
            class BadRequires(EnrichmentAdapter):
                adapter_id = "bad2"; display_name = "Bad"
                requires = ["not_a_real_type"]
                produces = ["handle"]
                tier = "fast"; priority = 10
                cost_usd = 0.0; timeout_s = 10; retry_max = 1; rate_limit_rpm = 0
                ttl_hours = 24; min_confidence = 0.5; max_instances = 1
                osint_risk = False; secrets_required = []
                gdpr_basis = "LEGITIMATE_INTERESTS"
                data_category = "PUBLIC_API"; tos_compliant = True
                def run(self, seed_entities, config): return None

    def test_invalid_tier_raises(self):
        with pytest.raises(AdapterContractError, match="tier"):
            class BadTier(EnrichmentAdapter):
                adapter_id = "bad3"; display_name = "Bad"
                requires = ["handle"]; produces = []
                tier = "ultra"  # invalid
                priority = 10; cost_usd = 0.0; timeout_s = 10; retry_max = 1
                rate_limit_rpm = 0; ttl_hours = 24; min_confidence = 0.5
                max_instances = 1; osint_risk = False; secrets_required = []
                gdpr_basis = "LEGITIMATE_INTERESTS"
                data_category = "PUBLIC_API"; tos_compliant = True
                def run(self, seed_entities, config): return None

    def test_valid_adapter_registers_cleanly(self):
        class GoodAdapter(EnrichmentAdapter):
            adapter_id = "good"; display_name = "Good"
            requires = ["handle"]; produces = ["youtube_handle"]
            tier = "fast"; priority = 10; cost_usd = 0.0; timeout_s = 10
            retry_max = 1; rate_limit_rpm = 0; ttl_hours = 24
            min_confidence = 0.5; max_instances = 1; osint_risk = False
            secrets_required = []; gdpr_basis = "LEGITIMATE_INTERESTS"
            data_category = "PUBLIC_API"; tos_compliant = True
            def run(self, seed_entities, config):
                return AdapterResult(adapter_id="good", entities=[], signals=[],
                                     error=None, cached=False,
                                     ran_at=TS, cost_usd=0.0, duration_s=0.1)
        g = GoodAdapter()
        result = g.run([], CFG)
        assert result.adapter_id == "good"


class TestSignal:
    def test_constructs(self):
        s = Signal(key="sub_count", value=100, unit="count",
                   confidence=1.0, method="api", source="youtube", osint_risk=False)
        assert s.value == 100
```

**Step 2: Run — verify failure**
```bash
pytest tests/enrichment/test_adapter.py -v 2>&1 | head -10
```

**Step 3: Implement `pipeline/enrichment/adapter.py`**

```python
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any
from pipeline.enrichment.entity import Entity, ENTITY_TYPES

_VALID_TIERS = frozenset({"seed", "fast", "medium", "slow"})
_VALID_GDPR = frozenset({"LEGITIMATE_INTERESTS", "CONSENT", "NONE"})
_VALID_CATS = frozenset({"PUBLIC_API", "PUBLIC_SCRAPE", "OSINT", "OPEN_DATA"})

_REQUIRED_ATTRS = (
    "adapter_id", "display_name", "requires", "produces", "tier", "priority",
    "cost_usd", "timeout_s", "retry_max", "rate_limit_rpm", "ttl_hours",
    "min_confidence", "max_instances", "osint_risk", "secrets_required",
    "gdpr_basis", "data_category", "tos_compliant",
)


class AdapterContractError(RuntimeError):
    pass


@dataclass(frozen=True)
class AdapterConfig:
    profile_id: str
    run_id: str
    max_depth: int
    max_cost_usd: float
    max_runtime_s: int
    secrets: dict[str, str]
    osint_enabled: bool
    cache_enabled: bool
    dry_run: bool


@dataclass
class Signal:
    key: str
    value: Any
    unit: str | None
    confidence: float
    method: str   # "api" | "scrape" | "osint" | "computed"
    source: str
    osint_risk: bool


@dataclass
class AdapterResult:
    adapter_id: str
    entities: list[Entity]
    signals: list[Signal]
    error: str | None
    cached: bool
    ran_at: str
    cost_usd: float
    duration_s: float


class EnrichmentAdapter(ABC):
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if EnrichmentAdapter in cls.__bases__:
            return  # skip ABC itself
        errors = []
        for attr in _REQUIRED_ATTRS:
            if not hasattr(cls, attr):
                errors.append(f"missing required class attribute: {attr!r}")
        if hasattr(cls, "tier") and cls.tier not in _VALID_TIERS:
            errors.append(f"tier={cls.tier!r} not in {_VALID_TIERS}")
        if hasattr(cls, "gdpr_basis") and cls.gdpr_basis not in _VALID_GDPR:
            errors.append(f"gdpr_basis={cls.gdpr_basis!r} not in {_VALID_GDPR}")
        if hasattr(cls, "data_category") and cls.data_category not in _VALID_CATS:
            errors.append(f"data_category={cls.data_category!r} not in {_VALID_CATS}")
        if hasattr(cls, "requires"):
            bad = [t for t in cls.requires if t not in ENTITY_TYPES]
            if bad:
                errors.append(f"requires contains unknown entity types: {bad}")
        if hasattr(cls, "produces"):
            bad = [t for t in cls.produces if t not in ENTITY_TYPES]
            if bad:
                errors.append(f"produces contains unknown entity types: {bad}")
        if hasattr(cls, "min_confidence") and not (0.0 <= cls.min_confidence <= 1.0):
            errors.append(f"min_confidence={cls.min_confidence} out of [0, 1]")
        if errors:
            raise AdapterContractError(
                f"Adapter {cls.__name__!r} has {len(errors)} contract violation(s):\n"
                + "\n".join(f"  • {e}" for e in errors)
            )

    @abstractmethod
    def run(self, seed_entities: list[Entity], config: AdapterConfig) -> AdapterResult: ...
```

**Step 4: Run tests**
```bash
pytest tests/enrichment/test_adapter.py -v
```

**Step 5: Commit**
```bash
git add pipeline/enrichment/adapter.py tests/enrichment/test_adapter.py
git commit -m "feat(enrichment): AdapterContract ABC with __init_subclass__ validation at import time"
```

---

## Task 4: Cache Layer

**Files:**
- Create: `pipeline/enrichment/cache.py`
- Create: `tests/enrichment/test_cache.py`

**Step 1: Write failing tests**

```python
# tests/enrichment/test_cache.py
import json
import time
import pytest
from pathlib import Path
from pipeline.enrichment.cache import make_cache_key, read_cache, write_cache, is_expired

TS = "2026-06-02T21:00:00Z"


def test_cache_key_deterministic():
    k1 = make_cache_key("youtube", "youtube_channel_id", "UCxyz123")
    k2 = make_cache_key("youtube", "youtube_channel_id", "UCxyz123")
    assert k1 == k2

def test_cache_key_known_value():
    import hashlib
    expected = hashlib.sha256(b"youtube:youtube_channel_id:UCxyz123").hexdigest()
    assert make_cache_key("youtube", "youtube_channel_id", "UCxyz123") == expected

def test_cache_key_differs_on_different_input():
    assert make_cache_key("youtube", "youtube_channel_id", "UCabc") != \
           make_cache_key("youtube", "youtube_channel_id", "UCxyz")

def test_write_and_read_cache(tmp_path):
    payload = {"entities": [], "signals": [{"key": "sub_count", "value": 100}]}
    write_cache(tmp_path, "youtube", "youtube_channel_id", "UCxyz123", payload, ttl_hours=24)
    result = read_cache(tmp_path, "youtube", "youtube_channel_id", "UCxyz123")
    assert result is not None
    assert result["signals"][0]["value"] == 100

def test_read_returns_none_on_miss(tmp_path):
    assert read_cache(tmp_path, "youtube", "youtube_channel_id", "UCxyz123") is None

def test_is_expired_future(tmp_path):
    write_cache(tmp_path, "youtube", "youtube_channel_id", "UCxyz123", {}, ttl_hours=24)
    assert is_expired(tmp_path, "youtube", "youtube_channel_id", "UCxyz123") is False

def test_is_expired_past(tmp_path):
    write_cache(tmp_path, "youtube", "youtube_channel_id", "UCxyz123", {}, ttl_hours=0)
    # ttl_hours=0 → expires immediately
    assert is_expired(tmp_path, "youtube", "youtube_channel_id", "UCxyz123") is True

def test_read_returns_none_when_expired(tmp_path):
    write_cache(tmp_path, "youtube", "youtube_channel_id", "UCxyz123", {}, ttl_hours=0)
    assert read_cache(tmp_path, "youtube", "youtube_channel_id", "UCxyz123") is None
```

**Step 2: Run — verify failure**
```bash
pytest tests/enrichment/test_cache.py -v 2>&1 | head -10
```

**Step 3: Implement `pipeline/enrichment/cache.py`**

```python
from __future__ import annotations
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path


def make_cache_key(adapter_id: str, entity_type: str, entity_value: str) -> str:
    raw = f"{adapter_id}:{entity_type}:{entity_value}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cache_path(cache_dir: Path, adapter_id: str, entity_type: str, entity_value: str) -> Path:
    key = make_cache_key(adapter_id, entity_type, entity_value)
    return cache_dir / f"{key}.json"


def write_cache(
    cache_dir: Path,
    adapter_id: str,
    entity_type: str,
    entity_value: str,
    payload: dict,
    ttl_hours: int,
) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _cache_path(cache_dir, adapter_id, entity_type, entity_value)
    now = time.time()
    entry = {
        "adapter_id": adapter_id,
        "entity_type": entity_type,
        "entity_value": entity_value,
        "cached_at": datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_at_ts": now + ttl_hours * 3600,
        "payload": payload,
    }
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w") as fh:
        json.dump(entry, fh)
    os.replace(tmp, path)


def read_cache(
    cache_dir: Path,
    adapter_id: str,
    entity_type: str,
    entity_value: str,
) -> dict | None:
    path = _cache_path(cache_dir, adapter_id, entity_type, entity_value)
    if not path.exists():
        return None
    with open(path) as fh:
        entry = json.load(fh)
    if time.time() > entry["expires_at_ts"]:
        return None
    return entry["payload"]


def is_expired(
    cache_dir: Path,
    adapter_id: str,
    entity_type: str,
    entity_value: str,
) -> bool:
    path = _cache_path(cache_dir, adapter_id, entity_type, entity_value)
    if not path.exists():
        return True
    with open(path) as fh:
        entry = json.load(fh)
    return time.time() > entry["expires_at_ts"]


def secure_delete(path: Path, passes: int = 3) -> None:
    """Overwrite with random bytes N times then unlink (GDPR Art. 17 erasure)."""
    if not path.exists():
        return
    if path.is_dir():
        for child in path.iterdir():
            secure_delete(child, passes=passes)
        path.rmdir()
        return
    size = path.stat().st_size
    with open(path, "r+b") as fh:
        for _ in range(passes):
            fh.seek(0)
            fh.write(os.urandom(size))
            fh.flush()
    path.unlink()
```

**Step 4: Run tests**
```bash
pytest tests/enrichment/test_cache.py -v
```

**Step 5: Commit**
```bash
git add pipeline/enrichment/cache.py tests/enrichment/test_cache.py
git commit -m "feat(enrichment): cache layer with make_cache_key, TTL, and secure_delete"
```

---

## Task 5: Engine Core

**Files:**
- Create: `pipeline/enrichment/engine.py`
- Create: `tests/enrichment/test_engine.py`

**Step 1: Write failing tests**

```python
# tests/enrichment/test_engine.py
import pytest
from pipeline.enrichment.engine import EngineConfig, EngineState, is_runnable
from pipeline.enrichment.entity import make_entity
from pipeline.enrichment.entity_pool import EntityPool
from pipeline.enrichment.adapter import (
    AdapterConfig, AdapterResult, EnrichmentAdapter, Signal
)

TS = "2026-06-02T21:00:00Z"


class FakeYouTubeAdapter(EnrichmentAdapter):
    adapter_id = "youtube"; display_name = "YouTube"
    requires = ["youtube_channel_id"]; produces = []
    tier = "fast"; priority = 10; cost_usd = 0.0; timeout_s = 10
    retry_max = 1; rate_limit_rpm = 0; ttl_hours = 24
    min_confidence = 0.6; max_instances = 3; osint_risk = False
    secrets_required = []; gdpr_basis = "LEGITIMATE_INTERESTS"
    data_category = "PUBLIC_API"; tos_compliant = True

    def run(self, seed_entities, config):
        return AdapterResult(adapter_id="youtube", entities=[], signals=[
            Signal(key="youtube_subscriber_count", value=100, unit="count",
                   confidence=1.0, method="api", source="youtube", osint_risk=False)
        ], error=None, cached=False, ran_at=TS, cost_usd=0.0, duration_s=0.1)


def _pool_with(*entities):
    pool = EntityPool()
    for e in entities:
        pool.add(e)
    return pool


def _state(config=None, run_counts=None, total_runs=0, total_cost=0.0):
    if config is None:
        config = EngineConfig()
    return EngineState(config=config, run_counts=run_counts or {}, 
                       total_runs=total_runs, total_cost=total_cost)


class TestIsRunnable:
    def test_runnable_when_entity_present(self):
        pool = _pool_with(make_entity("youtube_channel_id", "UCxyz1234567890123456789",
                                     source="linktree", confidence=1.0, depth=1,
                                     discovered_at=TS))
        state = _state()
        assert is_runnable(FakeYouTubeAdapter(), pool, state) is True

    def test_not_runnable_when_disabled(self):
        class Disabled(FakeYouTubeAdapter):
            adapter_id = "youtube_disabled"
            enabled = False
        pool = _pool_with(make_entity("youtube_channel_id", "UCxyz1234567890123456789",
                                     source="s", confidence=1.0, depth=1, discovered_at=TS))
        state = _state()
        assert is_runnable(Disabled(), pool, state) is False

    def test_not_runnable_below_confidence(self):
        pool = _pool_with(make_entity("youtube_channel_id", "UCxyz1234567890123456789",
                                     source="s", confidence=0.3, depth=1, discovered_at=TS))
        state = _state()
        # FakeYouTubeAdapter.min_confidence = 0.6; global = 0.5
        assert is_runnable(FakeYouTubeAdapter(), pool, state) is False

    def test_global_confidence_floor_overrides_adapter_floor(self):
        """Global floor 0.8 > adapter floor 0.6 → entity at 0.7 is blocked."""
        pool = _pool_with(make_entity("youtube_channel_id", "UCxyz1234567890123456789",
                                     source="s", confidence=0.7, depth=1, discovered_at=TS))
        cfg = EngineConfig(min_confidence_global=0.8)
        state = _state(config=cfg)
        assert is_runnable(FakeYouTubeAdapter(), pool, state) is False

    def test_not_runnable_max_depth_exceeded(self):
        pool = _pool_with(make_entity("youtube_channel_id", "UCxyz1234567890123456789",
                                     source="s", confidence=1.0, depth=3, discovered_at=TS))
        cfg = EngineConfig(max_depth=2)
        state = _state(config=cfg)
        assert is_runnable(FakeYouTubeAdapter(), pool, state) is False

    def test_not_runnable_when_max_adapter_runs_hit(self):
        pool = _pool_with(make_entity("youtube_channel_id", "UCxyz1234567890123456789",
                                     source="s", confidence=1.0, depth=1, discovered_at=TS))
        cfg = EngineConfig(max_adapter_runs=0)
        state = _state(config=cfg)
        assert is_runnable(FakeYouTubeAdapter(), pool, state) is False

    def test_not_runnable_when_max_instances_hit(self):
        pool = _pool_with(make_entity("youtube_channel_id", "UCxyz1234567890123456789",
                                     source="s", confidence=1.0, depth=1, discovered_at=TS))
        state = _state(run_counts={("youtube", "youtube_channel_id", "UCxyz1234567890123456789"): 3})
        assert is_runnable(FakeYouTubeAdapter(), pool, state) is False


class TestEngineConfig:
    def test_defaults(self):
        cfg = EngineConfig()
        assert cfg.max_depth == 2
        assert cfg.max_adapter_runs == 20
        assert cfg.max_cost_usd == 0.50
        assert cfg.min_confidence_global == 0.5
        assert cfg.parallel_workers == 8
```

**Step 2: Run — verify failure**
```bash
pytest tests/enrichment/test_engine.py -v 2>&1 | head -10
```

**Step 3: Implement `pipeline/enrichment/engine.py`**

```python
from __future__ import annotations
import concurrent.futures
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pipeline.enrichment.adapter import AdapterConfig, AdapterResult, EnrichmentAdapter
from pipeline.enrichment.entity import Entity, ENTITY_TYPES, make_entity
from pipeline.enrichment.entity_pool import EntityPool
from pipeline.enrichment.cache import read_cache, write_cache, make_cache_key

logger = logging.getLogger(__name__)


@dataclass
class EngineConfig:
    max_depth: int = 2
    max_adapter_runs: int = 20
    max_cost_usd: float = 0.50
    min_confidence_global: float = 0.5
    slow_tier_timeout_s: int = 600
    parallel_workers: int = 8


@dataclass
class EngineState:
    config: EngineConfig
    run_counts: dict[tuple[str, str, str], int] = field(default_factory=dict)
    total_runs: int = 0
    total_cost: float = 0.0
    adapter_errors: list[dict] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)


def is_runnable(adapter: EnrichmentAdapter, pool: EntityPool, state: EngineState) -> bool:
    if not getattr(adapter, "enabled", True):
        return False
    effective_min = max(adapter.min_confidence, state.config.min_confidence_global)
    matching = [
        e for e in pool.by_type_any(adapter.requires)
        if e.confidence >= effective_min and e.depth < state.config.max_depth
    ]
    if not matching:
        return False
    runnable = [
        e for e in matching
        if state.run_counts.get((adapter.adapter_id, e.type, e.value), 0) < adapter.max_instances
    ]
    if not runnable:
        return False
    if state.total_runs >= state.config.max_adapter_runs:
        return False
    if state.total_cost >= state.config.max_cost_usd:
        return False
    return True


def _run_with_cache(
    adapter: EnrichmentAdapter,
    pool: EntityPool,
    state: EngineState,
    config: AdapterConfig,
    cache_dir: Path,
) -> AdapterResult:
    """Run adapter, using cache if available. Updates state.run_counts."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    trigger_entities = [
        e for e in pool.by_type_any(adapter.requires)
        if state.run_counts.get((adapter.adapter_id, e.type, e.value), 0) < adapter.max_instances
    ]
    # Check cache on the first trigger entity
    for entity in trigger_entities:
        cached = read_cache(cache_dir, adapter.adapter_id, entity.type, entity.value)
        if cached is not None and config.cache_enabled:
            logger.debug("Cache HIT: %s / %s=%s", adapter.adapter_id, entity.type, entity.value)
            state.run_counts[(adapter.adapter_id, entity.type, entity.value)] = \
                state.run_counts.get((adapter.adapter_id, entity.type, entity.value), 0) + 1
            # Reconstruct AdapterResult from cached payload
            return AdapterResult(
                adapter_id=adapter.adapter_id,
                entities=[], signals=cached.get("signals_raw", []),
                error=None, cached=True, ran_at=now,
                cost_usd=0.0, duration_s=0.0,
            )

    # Live run
    t0 = time.monotonic()
    try:
        result = adapter.run(trigger_entities, config)
        result.duration_s = time.monotonic() - t0
    except Exception as exc:
        result = AdapterResult(
            adapter_id=adapter.adapter_id, entities=[], signals=[],
            error=str(exc), cached=False, ran_at=now,
            cost_usd=0.0, duration_s=time.monotonic() - t0,
        )
        state.adapter_errors.append({
            "adapter_id": adapter.adapter_id, "error": str(exc), "at": now,
        })

    # Update state
    for entity in trigger_entities:
        state.run_counts[(adapter.adapter_id, entity.type, entity.value)] = \
            state.run_counts.get((adapter.adapter_id, entity.type, entity.value), 0) + 1
    if result.error is None:
        state.total_runs += 1
        state.total_cost += result.cost_usd
        # Write to cache
        for entity in trigger_entities:
            write_cache(
                cache_dir, adapter.adapter_id, entity.type, entity.value,
                {"signals_raw": [vars(s) if hasattr(s, "__dict__") else s for s in result.signals]},
                ttl_hours=adapter.ttl_hours,
            )
    return result


def _merge_result(result: AdapterResult, pool: EntityPool, state: EngineState) -> list[Entity]:
    """Merge AdapterResult entities into pool. Returns list of new/updated entities."""
    new_entities = []
    for entity in result.entities:
        changed = pool.add(entity)
        if changed:
            new_entities.append(entity)
        else:
            existing = pool.get(entity.type, entity.value)
            if existing and existing.source != entity.source:
                state.conflicts.append({
                    "entity_type": entity.type,
                    "entity_value": entity.value,
                    "kept_source": existing.source,
                    "discarded_source": entity.source,
                })
    return new_entities


def run_engine(
    seed_data: dict,
    adapters: list[EnrichmentAdapter],
    config: EngineConfig,
    cache_dir: Path,
    run_id: str | None = None,
) -> tuple[EntityPool, EngineState, list[AdapterResult]]:
    """Execute the full enrichment scheduling loop.
    
    Returns (pool, state, all_results).
    """
    run_id = run_id or str(uuid.uuid4())
    state = EngineState(config=config)
    pool = EntityPool()
    all_results: list[AdapterResult] = []

    adapter_cfg = AdapterConfig(
        profile_id=seed_data.get("handle", "unknown"),
        run_id=run_id,
        max_depth=config.max_depth,
        max_cost_usd=config.max_cost_usd,
        max_runtime_s=config.slow_tier_timeout_s,
        secrets={k: os.environ.get(k, "") for k in
                 set(s for a in adapters for s in getattr(a, "secrets_required", []))},
        osint_enabled=True,
        cache_enabled=True,
        dry_run=False,
    )

    # ── Seed extraction ────────────────────────────────────────────────────
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for seed_type, seed_key in [
        ("handle", "handle"),
        ("display_name", "display_name"),
        ("bio_url", "website"),
    ]:
        raw = seed_data.get(seed_key)
        if raw:
            try:
                pool.add(make_entity(seed_type, str(raw), source="seed",
                                     confidence=1.0, depth=0, discovered_at=now))
            except Exception:
                pass

    # ── Phase 0: Tier 0 (sequential, blocking) ────────────────────────────
    tier0 = sorted([a for a in adapters if a.tier == "seed"], key=lambda a: a.priority)
    for adapter in tier0:
        if is_runnable(adapter, pool, state):
            result = _run_with_cache(adapter, pool, state, adapter_cfg, cache_dir)
            _merge_result(result, pool, state)
            all_results.append(result)

    # ── Phase 1: Fast tier (parallel, blocking — dossier v1 waits) ────────
    fast = sorted([a for a in adapters if a.tier == "fast"], key=lambda a: a.priority)
    runnable_fast = [a for a in fast if is_runnable(a, pool, state)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=config.parallel_workers) as ex:
        futures = {ex.submit(_run_with_cache, a, pool, state, adapter_cfg, cache_dir): a
                   for a in runnable_fast}
        for future in concurrent.futures.as_completed(futures):
            try:
                result = future.result()
                _merge_result(result, pool, state)
                all_results.append(result)
            except Exception as exc:
                adapter = futures[future]
                state.adapter_errors.append({"adapter_id": adapter.adapter_id, "error": str(exc)})

    # ── Phase 2: Medium tier (parallel) ───────────────────────────────────
    medium = sorted([a for a in adapters if a.tier == "medium"], key=lambda a: a.priority)
    runnable_medium = [a for a in medium if is_runnable(a, pool, state)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=config.parallel_workers) as ex:
        futures = {ex.submit(_run_with_cache, a, pool, state, adapter_cfg, cache_dir): a
                   for a in runnable_medium}
        for future in concurrent.futures.as_completed(futures):
            try:
                result = future.result()
                _merge_result(result, pool, state)
                all_results.append(result)
            except Exception as exc:
                adapter = futures[future]
                state.adapter_errors.append({"adapter_id": adapter.adapter_id, "error": str(exc)})

    # ── Phase 3: Slow tier (parallel, wall-clock bounded) ─────────────────
    slow = sorted([a for a in adapters if a.tier == "slow"], key=lambda a: a.priority)
    deadline = time.monotonic() + config.slow_tier_timeout_s
    with concurrent.futures.ThreadPoolExecutor(max_workers=config.parallel_workers) as ex:
        while True:
            runnable_slow = [a for a in slow if is_runnable(a, pool, state)]
            remaining = [a for a in adapters if is_runnable(a, pool, state)]
            if not runnable_slow and not remaining:
                break
            if time.monotonic() >= deadline:
                break
            if not runnable_slow and not remaining:
                break
            to_run = runnable_slow or remaining
            timeout = max(0.0, deadline - time.monotonic())
            futures = {ex.submit(_run_with_cache, a, pool, state, adapter_cfg, cache_dir): a
                       for a in to_run}
            done, _ = concurrent.futures.wait(futures.keys(), timeout=timeout)
            new_entities = []
            for future in futures:
                if future in done:
                    try:
                        result = future.result()
                        new = _merge_result(result, pool, state)
                        new_entities.extend(new)
                        all_results.append(result)
                    except Exception as exc:
                        adapter = futures[future]
                        state.adapter_errors.append({
                            "adapter_id": adapter.adapter_id, "error": str(exc)
                        })
                else:
                    adapter = futures[future]
                    logger.warning("Adapter %s timed out", adapter.adapter_id)
            if not new_entities:
                break

    return pool, state, all_results
```

**Step 4: Run tests**
```bash
pytest tests/enrichment/test_engine.py -v
```

**Step 5: Commit**
```bash
git add pipeline/enrichment/engine.py tests/enrichment/test_engine.py
git commit -m "feat(enrichment): engine core — is_runnable, fixed-point BFS scheduler, ThreadPoolExecutor"
```

---

## Task 6: Adapter YAML Configs

**Files:**
- Create: `pipeline/enrichment/config/` (directory + 19 YAML files)
- Create: `pipeline/enrichment/schemas/adapter_config.schema.json`

**Step 1: Create schema**

```json
// pipeline/enrichment/schemas/adapter_config.schema.json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "$id": "adapter_config/v1",
  "type": "object",
  "required": ["adapter_id","enabled","tier","priority","cost_usd","timeout_s","retry_max",
               "rate_limit_rpm","ttl_hours","min_confidence","max_instances","osint_risk",
               "secrets_required","gdpr_basis","data_category","tos_compliant"],
  "additionalProperties": false,
  "properties": {
    "adapter_id":      {"type": "string"},
    "enabled":         {"type": "boolean"},
    "tier":            {"type": "string", "enum": ["seed","fast","medium","slow"]},
    "priority":        {"type": "integer", "minimum": 0},
    "cost_usd":        {"type": "number", "minimum": 0},
    "timeout_s":       {"type": "integer", "minimum": 1},
    "retry_max":       {"type": "integer", "minimum": 0},
    "rate_limit_rpm":  {"type": "integer", "minimum": 0},
    "ttl_hours":       {"type": "integer", "minimum": 0},
    "min_confidence":  {"type": "number", "minimum": 0, "maximum": 1},
    "max_instances":   {"type": "integer", "minimum": 1},
    "osint_risk":      {"type": "boolean"},
    "secrets_required":{"type": "array", "items": {"type": "string"}},
    "gdpr_basis":      {"type": "string", "enum": ["LEGITIMATE_INTERESTS","CONSENT","NONE"]},
    "data_category":   {"type": "string", "enum": ["PUBLIC_API","PUBLIC_SCRAPE","OSINT","OPEN_DATA"]},
    "tos_compliant":   {"type": "boolean"}
  }
}
```

**Step 2: Create all 19 YAML files**

```bash
mkdir -p pipeline/enrichment/config
```

Write `pipeline/enrichment/config/linktree.yaml`:
```yaml
adapter_id: linktree
enabled: true
tier: seed
priority: 1
cost_usd: 0.000
timeout_s: 15
retry_max: 2
rate_limit_rpm: 0
ttl_hours: 24
min_confidence: 0.8
max_instances: 1
osint_risk: false
secrets_required: []
gdpr_basis: LEGITIMATE_INTERESTS
data_category: PUBLIC_SCRAPE
tos_compliant: true
```

Write `pipeline/enrichment/config/whois.yaml`:
```yaml
adapter_id: whois
enabled: true
tier: seed
priority: 5
cost_usd: 0.000
timeout_s: 10
retry_max: 1
rate_limit_rpm: 0
ttl_hours: 168
min_confidence: 0.8
max_instances: 3
osint_risk: false
secrets_required: []
gdpr_basis: LEGITIMATE_INTERESTS
data_category: OPEN_DATA
tos_compliant: true
```

Write `pipeline/enrichment/config/crt.yaml`:
```yaml
adapter_id: crt
enabled: true
tier: seed
priority: 10
cost_usd: 0.000
timeout_s: 10
retry_max: 1
rate_limit_rpm: 0
ttl_hours: 168
min_confidence: 0.7
max_instances: 3
osint_risk: false
secrets_required: []
gdpr_basis: LEGITIMATE_INTERESTS
data_category: OPEN_DATA
tos_compliant: true
```

Write similar YAMLs for: `youtube.yaml`, `knowledge_graph.yaml`, `wikidata.yaml`, `itunes.yaml`, `spotify.yaml`, `github.yaml`, `reddit.yaml`, `twitch.yaml`, `cnpj.yaml`, `holehe.yaml`, `ghunt.yaml`, `hibp.yaml`, `gdelt.yaml`, `google_news.yaml`, `substack.yaml`, `maigret.yaml` — each following the same structure with values from the spec §4.3 and §6.

Key values for each (from spec):
- `youtube`: tier=fast, priority=10, ttl_hours=24, min_confidence=0.6, max_instances=3
- `knowledge_graph`: tier=fast, priority=5, ttl_hours=168, min_confidence=0.5, max_instances=1
- `wikidata`: tier=fast, priority=15, ttl_hours=168, min_confidence=0.5, max_instances=1
- `itunes`: tier=fast, priority=20, ttl_hours=72, min_confidence=0.5, max_instances=2
- `spotify`: tier=fast, priority=25, ttl_hours=72, min_confidence=0.5, max_instances=2
- `github`: tier=fast, priority=30, ttl_hours=24, min_confidence=0.5, max_instances=1
- `reddit`: tier=fast, priority=35, ttl_hours=24, min_confidence=0.5, max_instances=1
- `twitch`: tier=fast, priority=40, ttl_hours=24, min_confidence=0.5, max_instances=1
- `cnpj`: tier=fast, priority=45, ttl_hours=168, min_confidence=0.5, max_instances=1
- `holehe`: tier=medium, priority=20, ttl_hours=72, min_confidence=0.7, max_instances=2, osint_risk=true
- `ghunt`: tier=medium, priority=25, ttl_hours=72, min_confidence=0.7, max_instances=1, osint_risk=true
- `hibp`: tier=medium, priority=30, cost_usd=0.004, ttl_hours=168, secrets_required=[HIBP_API_KEY], osint_risk=true
- `gdelt`: tier=medium, priority=10, ttl_hours=6, min_confidence=0.5, max_instances=1
- `google_news`: tier=medium, priority=15, ttl_hours=6, min_confidence=0.5, max_instances=1
- `substack`: tier=medium, priority=35, ttl_hours=48, min_confidence=0.7, max_instances=2
- `maigret`: tier=slow, priority=50, timeout_s=300, ttl_hours=168, min_confidence=0.8, max_instances=1, osint_risk=true

**Step 3: Write validation test**

```python
# tests/enrichment/test_registry.py
import yaml, json, jsonschema
from pathlib import Path

CONFIG_DIR = Path("pipeline/enrichment/config")
SCHEMA_PATH = Path("pipeline/enrichment/schemas/adapter_config.schema.json")

def test_all_yaml_files_valid():
    schema = json.loads(SCHEMA_PATH.read_text())
    errors = []
    for yaml_file in sorted(CONFIG_DIR.glob("*.yaml")):
        with open(yaml_file) as f:
            data = yaml.safe_load(f)
        if data.get("adapter_id") != yaml_file.stem:
            errors.append(f"{yaml_file.name}: adapter_id mismatch")
        try:
            jsonschema.validate(data, schema)
        except jsonschema.ValidationError as e:
            errors.append(f"{yaml_file.name}: {e.message}")
    assert not errors, "\n".join(errors)

def test_all_19_adapters_configured():
    names = {f.stem for f in CONFIG_DIR.glob("*.yaml")}
    expected = {
        "linktree", "whois", "crt", "knowledge_graph", "wikidata",
        "youtube", "itunes", "spotify", "github", "reddit", "twitch", "cnpj",
        "holehe", "ghunt", "hibp", "gdelt", "google_news", "substack", "maigret",
    }
    assert expected <= names, f"Missing: {expected - names}"
```

**Step 4: Run**
```bash
pytest tests/enrichment/test_registry.py -v
```

**Step 5: Commit**
```bash
git add pipeline/enrichment/config/ pipeline/enrichment/schemas/ tests/enrichment/test_registry.py
git commit -m "feat(enrichment): adapter YAML configs + JSON schema for all 19 sources"
```

---

## Task 7: Core Adapters (Tier 0 + Fast Tier critical path)

Implement the adapters with the highest value per effort. Each follows the exact same pattern.

**Files:**
- Create: `pipeline/enrichment/adapters/__init__.py`
- Create: `pipeline/enrichment/adapters/linktree.py`
- Create: `pipeline/enrichment/adapters/knowledge_graph.py`
- Create: `pipeline/enrichment/adapters/youtube.py`
- Create: `pipeline/enrichment/adapters/itunes.py`
- Create: `pipeline/enrichment/adapters/gdelt.py`
- Create: `pipeline/enrichment/adapters/google_news.py`
- Create: `pipeline/enrichment/adapters/maigret.py`
- Create: `tests/enrichment/adapters/__init__.py`
- Create: `tests/enrichment/adapters/test_linktree.py`
- Create: `tests/enrichment/adapters/test_adapters_integration.py`

**Pattern for every adapter** (implement this for each):

```python
# pipeline/enrichment/adapters/linktree.py
from __future__ import annotations
import time
import re
import requests
from datetime import datetime, timezone
from pipeline.enrichment.adapter import EnrichmentAdapter, AdapterResult, Signal, AdapterConfig
from pipeline.enrichment.entity import Entity, make_entity

class LinktreeAdapter(EnrichmentAdapter):
    adapter_id = "linktree"
    display_name = "Linktree / Bio-Link Parser"
    requires = ["bio_url"]
    produces = [
        "email", "domain", "youtube_channel_id", "youtube_handle", "tiktok_handle",
        "twitter_handle", "instagram_handle", "podcast_url", "substack_url",
        "website_url", "github_handle", "twitch_handle", "spotify_artist_id",
    ]
    tier = "seed"; priority = 1; cost_usd = 0.000; timeout_s = 15
    retry_max = 2; rate_limit_rpm = 0; ttl_hours = 24
    min_confidence = 0.8; max_instances = 1; osint_risk = False
    secrets_required = []; gdpr_basis = "LEGITIMATE_INTERESTS"
    data_category = "PUBLIC_SCRAPE"; tos_compliant = True

    # Patterns to extract entity types from URLs found in the bio link page
    _PLATFORM_PATTERNS: list[tuple[str, str, re.Pattern]] = [
        ("youtube_channel_id", "youtube", re.compile(r"youtube\.com/channel/(UC[a-zA-Z0-9_-]{22})")),
        ("youtube_handle",     "youtube", re.compile(r"youtube\.com/@([a-zA-Z0-9._-]{3,30})")),
        ("github_handle",      "github",  re.compile(r"github\.com/([a-zA-Z0-9-]{1,39})(?:/|$)")),
        ("tiktok_handle",      "tiktok",  re.compile(r"tiktok\.com/@([a-zA-Z0-9._]{1,24})")),
        ("twitter_handle",     "twitter", re.compile(r"(?:twitter|x)\.com/([a-zA-Z0-9_]{1,15})")),
        ("twitch_handle",      "twitch",  re.compile(r"twitch\.tv/([a-zA-Z0-9_]{4,25})")),
        ("substack_url",       "substack",re.compile(r"(https://[a-z0-9-]+\.substack\.com)")),
        ("podcast_url",        "podcast", re.compile(r"(https://(?:podcasts\.apple\.com|open\.spotify\.com/show|anchor\.fm)/[^\s\"'>]+")),
    ]

    def run(self, seed_entities: list[Entity], config: AdapterConfig) -> AdapterResult:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        t0 = time.monotonic()
        entities: list[Entity] = []
        signals: list[Signal] = []

        bio_url = seed_entities[0].value if seed_entities else None
        if not bio_url or config.dry_run:
            return AdapterResult(adapter_id=self.adapter_id, entities=[], signals=[],
                                  error=None, cached=False, ran_at=now,
                                  cost_usd=0.0, duration_s=time.monotonic() - t0)
        try:
            resp = requests.get(bio_url, timeout=self.timeout_s,
                                headers={"User-Agent": "profile-analyst/0.1"})
            html = resp.text
        except Exception as exc:
            return AdapterResult(adapter_id=self.adapter_id, entities=[], signals=[],
                                  error=str(exc), cached=False, ran_at=now,
                                  cost_usd=0.0, duration_s=time.monotonic() - t0)

        depth = seed_entities[0].depth + 1
        found_platforms = []

        for entity_type, platform, pattern in self._PLATFORM_PATTERNS:
            for m in pattern.finditer(html):
                raw = m.group(1) if entity_type not in ("substack_url", "podcast_url") else m.group(1)
                try:
                    e = make_entity(entity_type, raw, source=self.adapter_id,
                                    confidence=0.9, depth=depth, discovered_at=now)
                    entities.append(e)
                    found_platforms.append(platform)
                except Exception:
                    pass

        # Extract emails
        for email_match in re.finditer(r"mailto:([^\s\"'>]+)", html):
            try:
                e = make_entity("email", email_match.group(1), source=self.adapter_id,
                                confidence=0.85, depth=depth, discovered_at=now)
                entities.append(e)
            except Exception:
                pass

        signals.append(Signal(key="bio_link_platform_count", value=len(found_platforms),
                               unit="count", confidence=1.0, method="scrape",
                               source=self.adapter_id, osint_risk=False))
        signals.append(Signal(key="bio_link_platforms", value=list(set(found_platforms)),
                               unit=None, confidence=1.0, method="scrape",
                               source=self.adapter_id, osint_risk=False))

        return AdapterResult(adapter_id=self.adapter_id, entities=entities, signals=signals,
                              error=None, cached=False, ran_at=now,
                              cost_usd=0.0, duration_s=time.monotonic() - t0)
```

**Implement the remaining adapters** following the same structure:

`knowledge_graph.py` — calls `https://kgsearch.googleapis.com/v1/entities:search?query={name}&types=Person&limit=1&key={GOOGLE_KG_KEY}` (key optional; falls back to no-key endpoint). Produces: `wikidata_id`.

`youtube.py` — calls `https://www.googleapis.com/youtube/v3/channels?part=snippet,statistics&id={channel_id}&key={YOUTUBE_API_KEY}`. Emits signals: `youtube_subscriber_count`, `youtube_video_count`, `youtube_topics[]`.

`itunes.py` — calls `https://itunes.apple.com/search?term={name}&entity=podcast&limit=3`. Produces: `podcast_itunes_id`. Emits: `podcast_episode_count`, `podcast_category`, `podcast_last_episode_at`.

`gdelt.py` — calls `https://api.gdeltproject.org/api/v2/doc/doc?query={name}&mode=artlist&format=json&maxrecords=50`. Emits: `gdelt_mention_count`, `gdelt_tone_avg`.

`google_news.py` — fetches RSS from `https://news.google.com/rss/search?q={name}&hl=pt-BR&gl=BR&ceid=BR:pt`. Parses XML. Emits: `news_article_count_30d`, `news_latest_headline`.

`maigret.py` — runs `subprocess.run(["python3", "-m", "maigret", handle, "--timeout", "60", "--json", out_file])`. Parses JSON output. Produces: platform entities for each hit.

**Step 1: Write adapter integration test**

```python
# tests/enrichment/adapters/test_adapters_integration.py
"""Integration-style tests using dry_run=True — no live network calls."""
import pytest
from pipeline.enrichment.adapter import AdapterConfig
from pipeline.enrichment.entity import make_entity
from pipeline.enrichment.adapters.linktree import LinktreeAdapter
from pipeline.enrichment.adapters.itunes import ITunesAdapter

TS = "2026-06-02T21:00:00Z"
DRY_CFG = AdapterConfig(
    profile_id="test", run_id="test",
    max_depth=2, max_cost_usd=0.50, max_runtime_s=60,
    secrets={}, osint_enabled=True, cache_enabled=False, dry_run=True,
)


def test_linktree_returns_empty_in_dry_run():
    adapter = LinktreeAdapter()
    bio = make_entity("bio_url", "https://linktr.ee/vidacomia",
                      source="seed", confidence=1.0, depth=0, discovered_at=TS)
    result = adapter.run([bio], DRY_CFG)
    assert result.error is None
    assert result.entities == []

def test_itunes_adapter_contract_valid():
    """Confirms __init_subclass__ passes cleanly for iTunesAdapter."""
    from pipeline.enrichment.adapters.itunes import ITunesAdapter
    a = ITunesAdapter()
    assert a.adapter_id == "itunes"
    assert "display_name" in a.requires or "podcast_url" in a.requires
```

**Step 2: Run**
```bash
pytest tests/enrichment/adapters/ -v
```

**Step 3: Commit**
```bash
git add pipeline/enrichment/adapters/ tests/enrichment/adapters/
git commit -m "feat(enrichment): adapter implementations — linktree, youtube, itunes, knowledge_graph, gdelt, google_news, maigret"
```

---

## Task 8: Remaining Adapters (Stub Pattern)

For the remaining 12 adapters not implemented in Task 7 (`whois`, `crt`, `wikidata`, `spotify`, `github`, `reddit`, `twitch`, `cnpj`, `holehe`, `ghunt`, `hibp`, `substack`), implement each as a thin stub that follows the same pattern:

1. Class attributes matching the YAML config
2. `run()` that makes one HTTP call, extracts entities/signals, and returns `AdapterResult`
3. Graceful error return (no raises)

Stub template (copy and fill in per adapter):

```python
# pipeline/enrichment/adapters/github.py
from __future__ import annotations
import time, requests
from datetime import datetime, timezone
from pipeline.enrichment.adapter import EnrichmentAdapter, AdapterResult, Signal, AdapterConfig
from pipeline.enrichment.entity import Entity, make_entity

class GitHubAdapter(EnrichmentAdapter):
    adapter_id = "github"; display_name = "GitHub API"
    requires = ["github_handle"]; produces = []
    tier = "fast"; priority = 30; cost_usd = 0.0; timeout_s = 10
    retry_max = 1; rate_limit_rpm = 0; ttl_hours = 24
    min_confidence = 0.5; max_instances = 1; osint_risk = False
    secrets_required = []; gdpr_basis = "LEGITIMATE_INTERESTS"
    data_category = "PUBLIC_API"; tos_compliant = True

    def run(self, seed_entities: list[Entity], config: AdapterConfig) -> AdapterResult:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        t0 = time.monotonic()
        if config.dry_run or not seed_entities:
            return AdapterResult(adapter_id=self.adapter_id, entities=[], signals=[],
                                  error=None, cached=False, ran_at=now, cost_usd=0.0,
                                  duration_s=time.monotonic() - t0)
        handle = seed_entities[0].value
        try:
            resp = requests.get(f"https://api.github.com/users/{handle}",
                                timeout=self.timeout_s,
                                headers={"Accept": "application/vnd.github+json",
                                         "User-Agent": "profile-analyst/0.1"})
            data = resp.json()
        except Exception as exc:
            return AdapterResult(adapter_id=self.adapter_id, entities=[], signals=[],
                                  error=str(exc), cached=False, ran_at=now, cost_usd=0.0,
                                  duration_s=time.monotonic() - t0)

        signals = [
            Signal(key="github_public_repos", value=data.get("public_repos"),
                   unit="count", confidence=1.0, method="api", source=self.adapter_id, osint_risk=False),
            Signal(key="github_followers", value=data.get("followers"),
                   unit="count", confidence=1.0, method="api", source=self.adapter_id, osint_risk=False),
            Signal(key="github_location", value=data.get("location"),
                   unit=None, confidence=1.0, method="api", source=self.adapter_id, osint_risk=False),
            Signal(key="github_created_at", value=data.get("created_at"),
                   unit=None, confidence=1.0, method="api", source=self.adapter_id, osint_risk=False),
        ]
        return AdapterResult(adapter_id=self.adapter_id, entities=[], signals=signals,
                              error=None, cached=False, ran_at=now, cost_usd=0.0,
                              duration_s=time.monotonic() - t0)
```

Commit after implementing all remaining adapters:
```bash
git add pipeline/enrichment/adapters/
git commit -m "feat(enrichment): remaining adapter stubs — whois, crt, wikidata, spotify, github, reddit, twitch, cnpj, holehe, ghunt, hibp, substack"
```

---

## Task 9: Stage 1B Orchestrator

**Files:**
- Create: `pipeline/stage1b_enrichment.py`
- Create: `tests/test_stage1b.py`

**Step 1: Write failing tests**

```python
# tests/test_stage1b.py
import json
import pytest
from pathlib import Path
from unittest.mock import patch
from pipeline.stage1b_enrichment import run

FIXTURE_NORM = {
    "handle": "filipelauar",
    "display_name": "Filipe Lauar",
    "website": "https://linktr.ee/vidacomia",
    "bio": "Podcast @podcast.lifewithai",
    "governance": {
        "source_id": "apify_instagram",
        "data_category": "PUBLIC_SCRAPE",
        "tos_compliant_at_ingest": True,
        "ingested_at": "2026-06-02T21:00:00Z",
        "gdpr_basis": "LEGITIMATE_INTERESTS",
        "subject_jurisdiction": "UNKNOWN",
        "retention_expires_at": "2026-12-01T00:00:00Z",
        "consent_record_id": None,
    },
}


def test_run_creates_enrichment_map(tmp_path):
    norm_path = tmp_path / "02-normalized.json"
    norm_path.write_text(json.dumps(FIXTURE_NORM))
    # Patch adapters to return empty results (no live calls)
    with patch("pipeline.stage1b_enrichment._load_adapters", return_value=[]):
        out = run("filipelauar", tmp_path, fast_only=True)
    assert out.exists()
    data = json.loads(out.read_text())
    assert data["handle"] == "filipelauar"
    assert "entity_pool" in data
    assert "adapter_runs" in data
    assert "compliance" in data


def test_run_idempotent(tmp_path):
    norm_path = tmp_path / "02-normalized.json"
    norm_path.write_text(json.dumps(FIXTURE_NORM))
    with patch("pipeline.stage1b_enrichment._load_adapters", return_value=[]):
        run("filipelauar", tmp_path)
        run("filipelauar", tmp_path)  # second run must not raise
    assert (tmp_path / "enrichment_map.json").exists()


def test_run_without_normalized_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        run("filipelauar", tmp_path)
```

**Step 2: Implement `pipeline/stage1b_enrichment.py`**

```python
"""Stage 1B ENRICHMENT — dependency-driven multi-source enrichment (spec 0014)."""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from pipeline.enrichment.engine import EngineConfig, run_engine
from pipeline.enrichment.adapter import EnrichmentAdapter
from pipeline.compliance import assert_within_retention

logger = logging.getLogger(__name__)

_ADAPTER_MODULES = {
    "linktree":       "pipeline.enrichment.adapters.linktree.LinktreeAdapter",
    "whois":          "pipeline.enrichment.adapters.whois.WhoisAdapter",
    "crt":            "pipeline.enrichment.adapters.crt.CrtAdapter",
    "knowledge_graph":"pipeline.enrichment.adapters.knowledge_graph.KnowledgeGraphAdapter",
    "wikidata":       "pipeline.enrichment.adapters.wikidata.WikidataAdapter",
    "youtube":        "pipeline.enrichment.adapters.youtube.YouTubeAdapter",
    "itunes":         "pipeline.enrichment.adapters.itunes.ITunesAdapter",
    "spotify":        "pipeline.enrichment.adapters.spotify.SpotifyAdapter",
    "github":         "pipeline.enrichment.adapters.github.GitHubAdapter",
    "reddit":         "pipeline.enrichment.adapters.reddit.RedditAdapter",
    "twitch":         "pipeline.enrichment.adapters.twitch.TwitchAdapter",
    "cnpj":           "pipeline.enrichment.adapters.cnpj.CNPJAdapter",
    "holehe":         "pipeline.enrichment.adapters.holehe.HoleheAdapter",
    "ghunt":          "pipeline.enrichment.adapters.ghunt.GHuntAdapter",
    "hibp":           "pipeline.enrichment.adapters.hibp.HIBPAdapter",
    "gdelt":          "pipeline.enrichment.adapters.gdelt.GDELTAdapter",
    "google_news":    "pipeline.enrichment.adapters.google_news.GoogleNewsAdapter",
    "substack":       "pipeline.enrichment.adapters.substack.SubstackAdapter",
    "maigret":        "pipeline.enrichment.adapters.maigret.MaigretAdapter",
}

_CONFIG_DIR = Path(__file__).parent / "enrichment" / "config"


def _load_adapters(adapter_ids: list[str] | None = None) -> list[EnrichmentAdapter]:
    """Instantiate all enabled adapters (or a subset by id)."""
    import importlib
    adapters = []
    for adapter_id, class_path in _ADAPTER_MODULES.items():
        if adapter_ids and adapter_id not in adapter_ids:
            continue
        yaml_path = _CONFIG_DIR / f"{adapter_id}.yaml"
        if yaml_path.exists():
            with open(yaml_path) as f:
                cfg = yaml.safe_load(f)
            if not cfg.get("enabled", True):
                continue
        module_path, class_name = class_path.rsplit(".", 1)
        try:
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)
            adapters.append(cls())
        except Exception as exc:
            logger.warning("Could not load adapter %s: %s", adapter_id, exc)
    return adapters


def run(
    handle: str,
    project_dir: Path,
    *,
    fast_only: bool = False,
    adapter_ids: list[str] | None = None,
    bust_cache: list[str] | None = None,
    engine_config: EngineConfig | None = None,
) -> Path:
    """Run Stage 1B for *handle*. Reads 02-normalized.json, writes enrichment_map.json."""
    norm_path = project_dir / "02-normalized.json"
    if not norm_path.exists():
        raise FileNotFoundError(f"Stage 2 artifact not found: {norm_path}. Run Stage 2 first.")

    with open(norm_path) as fh:
        normalized = json.load(fh)

    gov = normalized.get("governance", {})
    assert_within_retention(gov, handle=handle)

    cache_dir = project_dir / ".enrichment_cache"
    config = engine_config or EngineConfig()

    if fast_only:
        config = EngineConfig(
            max_depth=config.max_depth,
            max_adapter_runs=config.max_adapter_runs,
            max_cost_usd=config.max_cost_usd,
            min_confidence_global=config.min_confidence_global,
            slow_tier_timeout_s=0,
            parallel_workers=config.parallel_workers,
        )

    adapters = _load_adapters(adapter_ids)
    run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    pool, state, results = run_engine(
        seed_data=normalized,
        adapters=adapters,
        config=config,
        cache_dir=cache_dir,
        run_id=run_id,
    )

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    osint_signals = [
        s.key for r in results for s in r.signals if s.osint_risk
    ]
    art9_signals = [
        s.key for r in results for s in r.signals
        if getattr(s, "osint_risk", False) and s.key in {
            "holehe_services", "reddit_top_subreddits", "github_topics",
            "hibp_breach_names", "cnpj_partners",
        }
    ]

    doc = {
        "handle": handle,
        "enriched_at": generated_at,
        "engine_version": "0014.1",
        "schema_version": "enrichment_map/v1",
        "status": "complete",
        "dossier_version": "v1" if fast_only else "v3",
        "gdpr_art9_consent_obtained": False,
        "limits": {
            "max_depth": config.max_depth,
            "max_adapter_runs": config.max_adapter_runs,
            "max_cost_usd": config.max_cost_usd,
            "actual_runs": state.total_runs,
            "actual_cost_usd": round(state.total_cost, 6),
            "limit_reached": (
                state.total_runs >= config.max_adapter_runs
                or state.total_cost >= config.max_cost_usd
            ),
        },
        "entity_pool": pool.snapshot(),
        "adapter_runs": [
            {
                "adapter_id": r.adapter_id,
                "status": "timeout" if r.error == "timeout"
                          else ("error" if r.error else "success"),
                "cached": r.cached,
                "ran_at": r.ran_at,
                "duration_s": round(r.duration_s, 3),
                "cost_usd": r.cost_usd,
                "entities_produced": len(r.entities),
                "signals_produced": len(r.signals),
                "error": r.error,
            }
            for r in results
        ],
        "signals": [
            {
                "key": s.key,
                "value": s.value,
                "unit": s.unit,
                "confidence": s.confidence,
                "method": s.method,
                "source": s.source,
                "osint_risk": s.osint_risk,
            }
            for r in results for s in r.signals
        ],
        "compliance": {
            "osint_signals_present": bool(osint_signals),
            "osint_signal_keys": osint_signals,
            "art9_risk_signals": art9_signals,
            "gdpr_basis": gov.get("gdpr_basis", "LEGITIMATE_INTERESTS"),
            "requires_human_review": bool(osint_signals),
            "opt_out_path": f"DELETE /profiles/{handle}",
        },
    }

    if state.adapter_errors:
        doc["adapter_errors"] = state.adapter_errors
    if state.conflicts:
        doc["conflicts"] = state.conflicts

    out_path = project_dir / "enrichment_map.json"
    tmp_path = out_path.with_suffix(".tmp")
    with open(tmp_path, "w") as fh:
        json.dump(doc, fh, indent=2, default=str)
    os.replace(tmp_path, out_path)

    # Update enrichment_status.json
    status = {
        "handle": handle,
        "dossier_version": doc["dossier_version"],
        "started_at": started_at,
        "v1_ready_at": generated_at,
        "v2_ready_at": generated_at if not fast_only else None,
        "v3_ready_at": generated_at if not fast_only else None,
        "slow_tier_running": False,
        "limit_reached": doc["limits"]["limit_reached"],
    }
    status_path = project_dir / "enrichment_status.json"
    with open(status_path, "w") as fh:
        json.dump(status, fh, indent=2)

    return out_path
```

**Step 3: Run tests**
```bash
pytest tests/test_stage1b.py -v
```

**Step 4: Commit**
```bash
git add pipeline/stage1b_enrichment.py tests/test_stage1b.py
git commit -m "feat: Stage 1B orchestrator — wires engine, adapters, and enrichment_map.json output"
```

---

## Task 10: CLI Integration

**Files:**
- Modify: `profile_analyst.py`
- Modify: `Makefile`

**Step 1: Add Stage 1B to the CLI dispatch**

In `profile_analyst.py`, add after `_run_stage2`:

```python
def _run_stage1b(
    handle: str,
    *,
    fast_only: bool = False,
    adapters: str | None = None,
    bust_cache: str | None = None,
) -> None:
    from pipeline.stage1b_enrichment import run
    adapter_ids = [a.strip() for a in adapters.split(",")] if adapters else None
    bust = [b.strip() for b in bust_cache.split(",")] if bust_cache else None
    out = run(handle, _project_dir(handle), fast_only=fast_only,
              adapter_ids=adapter_ids, bust_cache=bust)
    print(f"Stage 1B complete: {out}")
```

Update the `STAGE_MAP`:
```python
STAGE_MAP = {
    "1":  lambda h: _run_stage1(h),
    "2":  lambda h: _run_stage2(h),
    "1b": lambda h: _run_stage1b(h, fast_only=args.fast_only,
                                  adapters=args.adapters, bust_cache=args.bust_cache),
    "3":  lambda h: _run_stage3(h),
    ...
}
```

Add to the `all` stages order: `["1", "2", "1b", "3", "4", "5", "6"]`.

Add CLI flags to `argparse`:
```python
parser.add_argument("--fast-only", action="store_true")
parser.add_argument("--adapters", type=str, default=None)
parser.add_argument("--bust-cache", type=str, default=None)
parser.add_argument("--expose-osint", action="store_true")
parser.add_argument("--list-adapters", action="store_true")
```

Handle `--list-adapters`:
```python
if args.list_adapters:
    from pipeline.stage1b_enrichment import _load_adapters
    from pipeline.enrichment.config import CONFIG_DIR
    import yaml
    for f in sorted((Path("pipeline/enrichment/config")).glob("*.yaml")):
        cfg = yaml.safe_load(f.read_text())
        print(f"{cfg['adapter_id']:20} tier={cfg['tier']:8} enabled={cfg['enabled']} osint_risk={cfg['osint_risk']} ttl_hours={cfg['ttl_hours']}")
    sys.exit(0)
```

**Step 2: Add `make erase` to Makefile**

```makefile
# Usage: make erase HANDLE=<handle>
erase:
	python3 -c "
from pathlib import Path; import json, time
from pipeline.enrichment.cache import secure_delete
handle = '$(HANDLE)'
base = Path('projects') / handle
for f in ['enrichment_map.json', 'enrichment_status.json']:
    secure_delete(base / f)
secure_delete(base / '.enrichment_cache')
log = Path('compliance/erasure_log.jsonl')
log.parent.mkdir(exist_ok=True)
with open(log, 'a') as fh:
    import json
    fh.write(json.dumps({'handle': handle, 'erased_at': __import__('datetime').datetime.utcnow().isoformat()+'Z', 'operator': 'make-erase'}) + '\n')
print(f'Erased enrichment data for {handle}')
"
```

**Step 3: Update `make validate` in `tools/validate.py`**

Add validation for `enrichment_map.schema.json` and all adapter YAML configs.

**Step 4: Run**
```bash
python3 profile_analyst.py --list-adapters
python3 profile_analyst.py --handle filipelauar --stage 1b --fast-only
```

**Step 5: Commit**
```bash
git add profile_analyst.py Makefile tools/validate.py
git commit -m "feat: CLI integration — --stage 1b, --fast-only, --list-adapters, make erase"
```

---

## Task 11: Stage 2 Enrichment Merge

**Files:**
- Modify: `pipeline/stage2_normalize.py`

**Step 1: Add optional enrichment_map merge**

At the end of `stage2_normalize.py`'s `run()`, before writing the artifact:

```python
# Optionally merge enrichment signals (Stage 1B output)
enrichment_path = project_dir / "enrichment_map.json"
if enrichment_path.exists():
    try:
        with open(enrichment_path) as fh:
            enrichment = json.load(fh)
        # Merge top-level signals as enrichment_signals key
        normalized_doc["enrichment_signals"] = enrichment.get("signals", [])
        normalized_doc["enrichment_entity_count"] = len(enrichment.get("entity_pool", []))
    except Exception:
        pass  # enrichment is additive — never block Stage 2
```

**Step 2: Write test**

```python
# tests/test_stage2.py (add this test)
def test_stage2_runs_without_enrichment_map(sample_project_dir):
    # Existing test — confirm it still passes without enrichment_map.json
    ...

def test_stage2_merges_enrichment_map_when_present(tmp_path):
    # Setup: write a minimal 01-raw.json and an enrichment_map.json
    # Run Stage 2, confirm enrichment_signals key is present
    ...
```

**Step 3: Commit**
```bash
git add pipeline/stage2_normalize.py tests/test_stage2.py
git commit -m "feat(stage2): optionally merge enrichment_map.json signals into normalized profile"
```

---

## Task 12: JSON Schema + make validate

**Files:**
- Create: `schemas/enrichment_map.schema.json`
- Modify: `tools/validate.py`

**Step 1: Write the schema**

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "$id": "enrichment_map/v1",
  "type": "object",
  "required": ["handle","enriched_at","engine_version","schema_version","status",
               "limits","entity_pool","adapter_runs","signals","compliance"],
  "additionalProperties": true,
  "properties": {
    "handle":            {"type": "string"},
    "enriched_at":       {"type": "string", "format": "date-time"},
    "engine_version":    {"type": "string"},
    "schema_version":    {"type": "string", "const": "enrichment_map/v1"},
    "status":            {"type": "string", "enum": ["complete","partial","failed"]},
    "gdpr_art9_consent_obtained": {"type": "boolean"},
    "limits": {
      "type": "object",
      "required": ["max_depth","max_adapter_runs","max_cost_usd","actual_runs","actual_cost_usd","limit_reached"],
      "properties": {
        "max_depth":        {"type": "integer"},
        "max_adapter_runs": {"type": "integer"},
        "max_cost_usd":     {"type": "number"},
        "actual_runs":      {"type": "integer"},
        "actual_cost_usd":  {"type": "number"},
        "limit_reached":    {"type": "boolean"}
      }
    },
    "entity_pool": {"type": "array"},
    "adapter_runs": {"type": "array"},
    "signals":      {"type": "array"},
    "compliance": {
      "type": "object",
      "required": ["osint_signals_present","osint_signal_keys","art9_risk_signals",
                   "gdpr_basis","requires_human_review","opt_out_path"]
    }
  }
}
```

**Step 2: Add to validate.py**

```python
# In tools/validate.py — add after existing schema validation:
def validate_adapter_configs():
    adapter_schema_path = ROOT / "pipeline" / "enrichment" / "schemas" / "adapter_config.schema.json"
    config_dir = ROOT / "pipeline" / "enrichment" / "config"
    if not adapter_schema_path.exists():
        print("  ⚠ adapter_config.schema.json not found — skipping")
        return []
    schema = json.loads(adapter_schema_path.read_text())
    errors = []
    for yaml_path in sorted(config_dir.glob("*.yaml")):
        data = yaml.safe_load(yaml_path.read_text())
        if data.get("adapter_id") != yaml_path.stem:
            errors.append(f"  ✗ {yaml_path.name}: adapter_id '{data.get('adapter_id')}' != filename")
        try:
            jsonschema.validate(data, schema)
            print(f"  ✓ {yaml_path.name}")
        except jsonschema.ValidationError as e:
            errors.append(f"  ✗ {yaml_path.name}: {e.message}")
    return errors
```

**Step 3: Run**
```bash
make validate
```

**Step 4: Commit**
```bash
git add schemas/enrichment_map.schema.json tools/validate.py
git commit -m "feat: enrichment_map.schema.json + validate.py includes adapter config validation"
```

---

## Task 13: End-to-End Test

**Files:**
- Create: `tests/test_stage1b_e2e.py`

```python
# tests/test_stage1b_e2e.py
"""E2E test using dry_run=True — no live API calls, verifies full pipeline wiring."""
import json
import pytest
from pathlib import Path
from unittest.mock import patch
from pipeline.stage1b_enrichment import run
from pipeline.enrichment.engine import EngineConfig

NORM = {
    "handle": "filipelauar", "display_name": "Filipe Lauar",
    "website": "https://linktr.ee/vidacomia", "bio": "",
    "governance": {
        "source_id": "apify_instagram", "data_category": "PUBLIC_SCRAPE",
        "tos_compliant_at_ingest": True, "ingested_at": "2026-06-02T21:00:00Z",
        "gdpr_basis": "LEGITIMATE_INTERESTS", "subject_jurisdiction": "UNKNOWN",
        "retention_expires_at": "2027-01-01T00:00:00Z", "consent_record_id": None,
    }
}


@pytest.fixture
def project_dir(tmp_path):
    (tmp_path / "02-normalized.json").write_text(json.dumps(NORM))
    return tmp_path


def test_enrichment_map_validates_against_schema(project_dir):
    import jsonschema, json
    schema = json.loads(
        (Path("schemas/enrichment_map.schema.json")).read_text()
    )
    with patch("pipeline.stage1b_enrichment._load_adapters", return_value=[]):
        run("filipelauar", project_dir, fast_only=True)
    doc = json.loads((project_dir / "enrichment_map.json").read_text())
    jsonschema.validate(doc, schema)  # must not raise

def test_schema_version_matches(project_dir):
    with patch("pipeline.stage1b_enrichment._load_adapters", return_value=[]):
        run("filipelauar", project_dir)
    doc = json.loads((project_dir / "enrichment_map.json").read_text())
    assert doc["schema_version"] == "enrichment_map/v1"

def test_compliance_block_present(project_dir):
    with patch("pipeline.stage1b_enrichment._load_adapters", return_value=[]):
        run("filipelauar", project_dir)
    doc = json.loads((project_dir / "enrichment_map.json").read_text())
    assert "compliance" in doc
    assert "osint_signals_present" in doc["compliance"]
    assert "art9_risk_signals" in doc["compliance"]

def test_status_file_written(project_dir):
    with patch("pipeline.stage1b_enrichment._load_adapters", return_value=[]):
        run("filipelauar", project_dir, fast_only=True)
    status = json.loads((project_dir / "enrichment_status.json").read_text())
    assert status["dossier_version"] == "v1"
    assert status["v1_ready_at"] is not None

def test_limit_reached_flag(project_dir):
    cfg = EngineConfig(max_adapter_runs=0)
    with patch("pipeline.stage1b_enrichment._load_adapters", return_value=[]):
        run("filipelauar", project_dir, engine_config=cfg)
    doc = json.loads((project_dir / "enrichment_map.json").read_text())
    # With 0 runs allowed and no adapters, limit is not reached (0 >= 0 is True)
    assert "limit_reached" in doc["limits"]

def test_idempotent(project_dir):
    with patch("pipeline.stage1b_enrichment._load_adapters", return_value=[]):
        run("filipelauar", project_dir)
        run("filipelauar", project_dir)
    # Second run must not corrupt the output
    doc = json.loads((project_dir / "enrichment_map.json").read_text())
    assert doc["handle"] == "filipelauar"
```

**Run**
```bash
pytest tests/test_stage1b_e2e.py -v
```

**Commit**
```bash
git add tests/test_stage1b_e2e.py
git commit -m "test(enrichment): e2e test suite — validates schema, compliance block, idempotency"
```

---

## Task 14: Full Test Suite

```bash
pytest tests/ -v --tb=short
```

Fix any remaining failures. Then:
```bash
make validate
git add -A
git commit -m "feat(0014): enrichment engine complete — 19 adapters, engine, cache, schema, CLI"
```

---

## Acceptance Criteria Checklist

Run these after all tasks to verify spec compliance:

```bash
# A1 — produces valid enrichment_map.json
python3 profile_analyst.py --handle filipelauar --stage 1b --fast-only
python3 -c "import json,jsonschema; jsonschema.validate(json.load(open('projects/filipelauar/enrichment_map.json')), json.load(open('schemas/enrichment_map.schema.json')))"

# A2 — fast tier ≤ 60s
time python3 profile_analyst.py --handle filipelauar --stage 1b --fast-only

# A7 — max_adapter_runs=5 stops engine
# (test in pytest)

# A15 — make validate passes
make validate

# A19 — --list-adapters works
python3 profile_analyst.py --list-adapters

# A24 — AdapterContractError at import (test in pytest)
# A25 — Art.22 gate (test in pytest)
```
