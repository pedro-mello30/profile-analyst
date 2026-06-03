# Instagram Bio Enrichment (Option A+) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `AdapterContext` to the enrichment contract, then implement `BioEntityExtractor` + `InstagramBioAdapter` so bio-embedded entities (email, phone, CNPJ, domain, website_url) are discovered at tier 0 and seed downstream adapters.

**Architecture:** Add an explicit `AdapterContext` dataclass to `AdapterConfig` (Option A+). A reusable `BioEntityExtractor` parses plain text for PII/identity entities using compiled regexes. `InstagramBioAdapter` is a zero-cost tier-0 adapter that reads `config.context.raw_profile["bio"]` and delegates entirely to the extractor — keeping the orchestrator clean and making the extractor reusable across any future text-bearing adapter.

**Tech Stack:** Python 3.11+ · dataclasses · re · `pipeline.enrichment.adapter` · `pipeline.enrichment.entity.make_entity`

---

### Task 1: Add `AdapterContext` dataclass and wire it into `AdapterConfig`

**Files:**
- Modify: `pipeline/enrichment/adapter.py` (lines 26–37)

**Step 1: Write the failing test**

File: `tests/enrichment/test_adapter_context.py`

```python
"""AdapterContext contract tests."""
import pytest
from pipeline.enrichment.adapter import AdapterConfig, AdapterContext


def test_adapter_config_accepts_context():
    ctx = AdapterContext(
        raw_profile={"handle": "filipelauar", "bio": "contato@x.com"},
        raw_media=[],
        source_platform="instagram",
    )
    cfg = AdapterConfig(
        profile_id="filipelauar", run_id="r1", max_depth=2,
        max_cost_usd=0.5, max_runtime_s=600, secrets={},
        osint_enabled=True, cache_enabled=True, dry_run=False,
        context=ctx,
    )
    assert cfg.context.raw_profile["bio"] == "contato@x.com"
    assert cfg.context.source_platform == "instagram"


def test_adapter_config_context_is_optional():
    cfg = AdapterConfig(
        profile_id="x", run_id="r1", max_depth=2,
        max_cost_usd=0.5, max_runtime_s=600, secrets={},
        osint_enabled=True, cache_enabled=True, dry_run=False,
    )
    assert cfg.context is None


def test_adapter_context_raw_media_defaults_to_none():
    ctx = AdapterContext(raw_profile={"handle": "x"})
    assert ctx.raw_media is None
    assert ctx.source_platform is None
```

**Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/enrichment/test_adapter_context.py -v
```
Expected: `FAILED` — `AdapterContext` not defined, `AdapterConfig` has no `context` param.

**Step 3: Write minimal implementation**

In `pipeline/enrichment/adapter.py`, add after the imports block (before `AdapterContractError`):

```python
@dataclass
class AdapterContext:
    """Raw source data made available to adapters that need access beyond entity seeds."""
    raw_profile: dict | None = None
    raw_media: list[dict] | None = None
    source_platform: str | None = None
```

Then update `AdapterConfig` — append `context` as the last field (with default so existing callers don't break):

```python
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
    context: AdapterContext | None = None    # ← new
```

**Step 4: Run test to verify it passes**

```bash
python3 -m pytest tests/enrichment/test_adapter_context.py -v
```
Expected: `3 passed`

**Step 5: Run full suite for regressions**

```bash
python3 -m pytest --timeout=30 -q
```
Expected: all previously-passing tests still pass.

**Step 6: Commit**

```bash
git add pipeline/enrichment/adapter.py tests/enrichment/test_adapter_context.py
git commit -m "feat(0014/ctx): add AdapterContext to AdapterConfig contract"
```

---

### Task 2: Wire `AdapterContext` through the engine

**Files:**
- Modify: `pipeline/enrichment/engine.py` (around line 205 — `run_engine` signature and `AdapterConfig` construction at line 219)
- Modify: `pipeline/stage1b_enrichment.py` (around line 130 — `run_engine` call)

**Step 1: Write the failing test**

Add to `tests/enrichment/test_engine.py` (append, don't replace existing tests):

```python
def test_engine_passes_context_to_adapters():
    """Adapters receive AdapterContext with raw_profile when run_engine is called with raw_media."""
    from pipeline.enrichment.adapter import AdapterConfig, AdapterContext, AdapterResult, EnrichmentAdapter
    from pipeline.enrichment.entity import Entity, make_entity
    from pipeline.enrichment.engine import EngineConfig, run_engine
    import tempfile, pathlib

    received_context = {}

    class ContextCapture(EnrichmentAdapter):
        adapter_id = "ctx_capture"; display_name = "ContextCapture"
        requires = ["handle"]; produces = ["display_name"]
        tier = "seed"; priority = 99; cost_usd = 0.0; timeout_s = 5
        retry_max = 0; rate_limit_rpm = 0; ttl_hours = 0
        min_confidence = 0.0; max_instances = 1; osint_risk = False
        secrets_required = []; gdpr_basis = "LEGITIMATE_INTERESTS"
        data_category = "PUBLIC_API"; tos_compliant = True

        def run(self, seeds, config):
            now = "2026-06-03T00:00:00Z"
            received_context["context"] = config.context
            return AdapterResult(adapter_id=self.adapter_id, entities=[],
                                 signals=[], error=None, cached=False,
                                 ran_at=now, cost_usd=0.0)

    seed_data = {"handle": "test", "display_name": "Test", "website": None}
    raw_media = [{"media_id": "m1"}]
    with tempfile.TemporaryDirectory() as td:
        run_engine(
            seed_data=seed_data,
            adapters=[ContextCapture()],
            config=EngineConfig(),
            cache_dir=pathlib.Path(td),
            raw_media=raw_media,
        )
    ctx = received_context.get("context")
    assert ctx is not None
    assert ctx.raw_profile == seed_data
    assert ctx.raw_media == raw_media
    assert ctx.source_platform == "instagram"
```

**Step 2: Run to verify it fails**

```bash
python3 -m pytest tests/enrichment/test_engine.py::test_engine_passes_context_to_adapters -v
```
Expected: `FAILED` — `run_engine` doesn't accept `raw_media` yet.

**Step 3: Implement**

In `pipeline/enrichment/engine.py`, update `run_engine` signature and `AdapterConfig` construction:

```python
def run_engine(
    seed_data: dict,
    adapters: list[EnrichmentAdapter],
    config: EngineConfig,
    cache_dir: Path,
    run_id: str | None = None,
    raw_media: list[dict] | None = None,           # ← new
) -> tuple[EntityPool, EngineState, list[AdapterResult]]:
```

Then update the `AdapterConfig` block (around line 219):

```python
    from pipeline.enrichment.adapter import AdapterContext   # add to top-of-file imports instead

    adapter_cfg = AdapterConfig(
        profile_id=seed_data.get("handle", "unknown"),
        run_id=run_id,
        max_depth=config.max_depth,
        max_cost_usd=config.max_cost_usd,
        max_runtime_s=config.slow_tier_timeout_s,
        secrets={k: os.environ.get(k, "")
                 for a in adapters
                 for k in getattr(a, "secrets_required", [])},
        osint_enabled=True,
        cache_enabled=True,
        dry_run=False,
        context=AdapterContext(                              # ← new
            raw_profile=seed_data,
            raw_media=raw_media,
            source_platform="instagram",                    # hardcoded for now; extend later
        ),
    )
```

Move the `AdapterContext` import to the top of `engine.py` alongside other adapter imports.

Then in `pipeline/stage1b_enrichment.py`, pass `raw_media` to `run_engine` (around line 130):

```python
    pool, state, results = run_engine(
        seed_data=raw.get("raw_profile", {}),
        adapters=adapters,
        config=config,
        cache_dir=cache_dir,
        run_id=run_id,
        raw_media=raw.get("raw_media", []),               # ← new
    )
```

**Step 4: Run test**

```bash
python3 -m pytest tests/enrichment/test_engine.py -v
```
Expected: all engine tests pass.

**Step 5: Full suite**

```bash
python3 -m pytest --timeout=30 -q
```
Expected: all previously-passing tests still pass.

**Step 6: Commit**

```bash
git add pipeline/enrichment/engine.py pipeline/stage1b_enrichment.py tests/enrichment/test_engine.py
git commit -m "feat(0014/ctx): wire AdapterContext + raw_media through run_engine"
```

---

### Task 3: Create `BioEntityExtractor`

**Files:**
- Create: `pipeline/enrichment/extractors/__init__.py` (empty)
- Create: `pipeline/enrichment/extractors/bio.py`
- Test: `tests/enrichment/test_bio_extractor.py`

**Step 1: Write the failing tests**

```python
"""BioEntityExtractor unit tests."""
import pytest
from pipeline.enrichment.extractors.bio import BioEntityExtractor


def test_extracts_email():
    hits = BioEntityExtractor().extract("Contato: pedro@vidacomia.com.br para parcerias")
    types = {h[0] for h in hits}
    assert "email" in types
    emails = [h[1] for h in hits if h[0] == "email"]
    assert "pedro@vidacomia.com.br" in emails


def test_extracts_cnpj_formatted():
    hits = BioEntityExtractor().extract("Empresa: 12.345.678/0001-90 | NF disponível")
    types = {h[0] for h in hits}
    assert "cnpj" in types
    cnpjs = [h[1] for h in hits if h[0] == "cnpj"]
    assert "12345678000190" in cnpjs


def test_extracts_cnpj_raw_digits():
    hits = BioEntityExtractor().extract("CNPJ 12345678000190")
    cnpjs = [h[1] for h in hits if h[0] == "cnpj"]
    assert "12345678000190" in cnpjs


def test_extracts_br_phone():
    hits = BioEntityExtractor().extract("WhatsApp: +55 31 99999-1234")
    types = {h[0] for h in hits}
    assert "phone" in types


def test_extracts_url_as_website_url():
    hits = BioEntityExtractor().extract("Acesse: https://vidacomia.com.br/cursos")
    types = {h[0] for h in hits}
    assert "website_url" in types


def test_extracts_domain_from_url():
    hits = BioEntityExtractor().extract("Acesse: https://vidacomia.com.br/cursos")
    domains = [h[1] for h in hits if h[0] == "domain"]
    assert "vidacomia.com.br" in domains


def test_skips_linktr_ee_domain():
    """linktr.ee is already seeded as bio_url — don't produce it as a domain entity."""
    hits = BioEntityExtractor().extract("", website="https://linktr.ee/vidacomia")
    domains = [h[1] for h in hits if h[0] == "domain"]
    assert "linktr.ee" not in domains


def test_website_from_website_field():
    hits = BioEntityExtractor().extract("", website="https://vidacomia.com.br")
    urls = [h[1] for h in hits if h[0] == "website_url"]
    assert any("vidacomia.com.br" in u for u in urls)


def test_empty_bio_returns_empty():
    assert BioEntityExtractor().extract("") == []


def test_none_bio_returns_empty():
    assert BioEntityExtractor().extract(None) == []


def test_returns_list_of_tuples():
    hits = BioEntityExtractor().extract("hello@world.com")
    assert isinstance(hits, list)
    assert all(len(h) == 3 for h in hits)  # (entity_type, value, confidence)
```

**Step 2: Run to verify failures**

```bash
python3 -m pytest tests/enrichment/test_bio_extractor.py -v
```
Expected: all `FAILED` — module doesn't exist yet.

**Step 3: Create `pipeline/enrichment/extractors/__init__.py`** (empty file).

**Step 4: Implement `pipeline/enrichment/extractors/bio.py`**

```python
"""BioEntityExtractor — parse plain text for identity entities (spec 0014+)."""
from __future__ import annotations

import re
from urllib.parse import urlparse

# ── Compiled patterns ─────────────────────────────────────────────────────────

_EMAIL_RE = re.compile(
    r"\b([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})\b"
)
_PHONE_RE = re.compile(
    r"(\+?55[\s\-]?)?(\(?\d{2}\)?[\s\-]?)(9\d{4}[\s\-]?\d{4}|\d{4}[\s\-]?\d{4})"
)
_CNPJ_FORMATTED_RE = re.compile(
    r"\b(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})\b"
)
_CNPJ_RAW_RE = re.compile(
    r"(?<!\d)(\d{14})(?!\d)"
)
_URL_RE = re.compile(
    r"https?://[^\s\"'<>]+"
)

# Bio-link aggregators that are not useful as standalone domain entities
_SKIP_DOMAINS = frozenset({
    "linktr.ee", "linktree.com", "bio.link", "beacons.ai",
    "msha.ke", "campsite.bio", "carrd.co",
})


class BioEntityExtractor:
    """Extract identity entities from free-form bio text and website fields.

    Returns list of (entity_type, normalized_value, confidence) tuples.
    Delegates normalization to caller (InstagramBioAdapter uses make_entity).
    """

    def extract(
        self,
        bio: str | None,
        *,
        website: str | None = None,
    ) -> list[tuple[str, str, float]]:
        hits: list[tuple[str, str, float]] = []
        text = (bio or "") + (" " + website if website else "")

        # ── Emails ────────────────────────────────────────────────────────────
        for m in _EMAIL_RE.finditer(text):
            hits.append(("email", m.group(1).lower(), 0.7))

        # ── CNPJs (formatted first, then raw digits) ──────────────────────────
        seen_cnpj: set[str] = set()
        for m in _CNPJ_FORMATTED_RE.finditer(text):
            digits = re.sub(r"\D", "", m.group(1))
            if digits not in seen_cnpj:
                seen_cnpj.add(digits)
                hits.append(("cnpj", digits, 0.85))
        for m in _CNPJ_RAW_RE.finditer(text):
            d = m.group(1)
            if d not in seen_cnpj:
                seen_cnpj.add(d)
                hits.append(("cnpj", d, 0.6))

        # ── Phones ────────────────────────────────────────────────────────────
        for m in _PHONE_RE.finditer(text):
            raw = re.sub(r"[^\d+]", "", m.group(0))
            if not raw.startswith("+"):
                raw = "+" + raw
            if 10 <= len(raw.lstrip("+")) <= 15:
                hits.append(("phone", raw, 0.6))

        # ── URLs → website_url + domain ───────────────────────────────────────
        sources = list(_URL_RE.finditer(text))
        if website and not any(website in m.group(0) for m in sources):
            # Ensure the explicit website field is always processed
            sources_extra = [website]
        else:
            sources_extra = []

        seen_domain: set[str] = set()
        for raw_url in [m.group(0) for m in sources] + sources_extra:
            try:
                parsed = urlparse(raw_url)
                host = parsed.netloc.lower().lstrip("www.")
                if not host:
                    continue
                hits.append(("website_url", raw_url.rstrip(".,)"), 0.9))
                if host not in _SKIP_DOMAINS and host not in seen_domain:
                    seen_domain.add(host)
                    hits.append(("domain", host, 0.9))
            except Exception:
                pass

        return hits
```

**Step 5: Run tests**

```bash
python3 -m pytest tests/enrichment/test_bio_extractor.py -v
```
Expected: all `PASSED`.

**Step 6: Full suite**

```bash
python3 -m pytest --timeout=30 -q
```
Expected: no regressions.

**Step 7: Commit**

```bash
git add pipeline/enrichment/extractors/ tests/enrichment/test_bio_extractor.py
git commit -m "feat(0014/bio): add BioEntityExtractor for email/phone/cnpj/domain/website"
```

---

### Task 4: Create `InstagramBioAdapter`

**Files:**
- Create: `pipeline/enrichment/adapters/instagram_bio.py`
- Test: `tests/enrichment/adapters/test_instagram_bio.py`

**Step 1: Write the failing tests**

```python
"""InstagramBioAdapter unit tests."""
import pytest
from unittest.mock import patch
from datetime import datetime, timezone

from pipeline.enrichment.adapter import AdapterConfig, AdapterContext, AdapterResult
from pipeline.enrichment.adapters.instagram_bio import InstagramBioAdapter


def _make_config(bio: str | None, website: str | None = None) -> AdapterConfig:
    return AdapterConfig(
        profile_id="filipelauar", run_id="test", max_depth=2,
        max_cost_usd=0.5, max_runtime_s=600, secrets={},
        osint_enabled=True, cache_enabled=False, dry_run=False,
        context=AdapterContext(
            raw_profile={"handle": "filipelauar", "bio": bio, "website": website},
            raw_media=[],
            source_platform="instagram",
        ),
    )


def _make_seeds():
    from pipeline.enrichment.entity import make_entity
    now = "2026-06-03T00:00:00Z"
    return [make_entity("handle", "filipelauar", source="seed",
                        confidence=1.0, depth=0, discovered_at=now)]


def test_extracts_email_from_bio():
    cfg = _make_config("Contato: pedro@vidacomia.com.br")
    result = InstagramBioAdapter().run(_make_seeds(), cfg)
    assert result.error is None
    types = {e.type for e in result.entities}
    assert "email" in types


def test_extracts_domain_from_bio():
    cfg = _make_config("", website="https://vidacomia.com.br")
    result = InstagramBioAdapter().run(_make_seeds(), cfg)
    domains = [e.value for e in result.entities if e.type == "domain"]
    assert "vidacomia.com.br" in domains


def test_extracts_cnpj():
    cfg = _make_config("CNPJ: 12.345.678/0001-90")
    result = InstagramBioAdapter().run(_make_seeds(), cfg)
    cnpjs = [e.value for e in result.entities if e.type == "cnpj"]
    assert "12345678000190" in cnpjs


def test_no_context_returns_empty():
    cfg = AdapterConfig(
        profile_id="x", run_id="r1", max_depth=2, max_cost_usd=0.5,
        max_runtime_s=600, secrets={}, osint_enabled=True,
        cache_enabled=False, dry_run=False,
    )
    result = InstagramBioAdapter().run(_make_seeds(), cfg)
    assert result.entities == []
    assert result.error is None


def test_dry_run_returns_empty():
    cfg = _make_config("pedro@example.com")
    cfg = AdapterConfig(**{**cfg.__dict__, "dry_run": True})
    result = InstagramBioAdapter().run(_make_seeds(), cfg)
    assert result.entities == []


def test_empty_bio_returns_empty():
    cfg = _make_config(None)
    result = InstagramBioAdapter().run(_make_seeds(), cfg)
    assert result.entities == []
    assert result.error is None


def test_emits_bio_signal():
    cfg = _make_config("pedro@example.com e CNPJ 12345678000190")
    result = InstagramBioAdapter().run(_make_seeds(), cfg)
    signal_keys = {s.key for s in result.signals}
    assert "bio_entity_count" in signal_keys


def test_cost_is_zero():
    cfg = _make_config("pedro@example.com")
    result = InstagramBioAdapter().run(_make_seeds(), cfg)
    assert result.cost_usd == 0.0


def test_source_on_entities_is_adapter_id():
    cfg = _make_config("pedro@example.com")
    result = InstagramBioAdapter().run(_make_seeds(), cfg)
    for e in result.entities:
        assert e.source == InstagramBioAdapter.adapter_id
```

**Step 2: Run to verify failures**

```bash
python3 -m pytest tests/enrichment/adapters/test_instagram_bio.py -v
```
Expected: all `FAILED` — adapter doesn't exist.

**Step 3: Implement `pipeline/enrichment/adapters/instagram_bio.py`**

```python
"""InstagramBioAdapter — parse Instagram bio text for identity entities (spec 0014+)."""
from __future__ import annotations

import time
from datetime import datetime, timezone

from pipeline.enrichment.adapter import AdapterConfig, AdapterResult, EnrichmentAdapter, Signal
from pipeline.enrichment.entity import Entity, make_entity
from pipeline.enrichment.extractors.bio import BioEntityExtractor

_EXTRACTOR = BioEntityExtractor()


class InstagramBioAdapter(EnrichmentAdapter):
    adapter_id       = "instagram_bio"
    display_name     = "Instagram Bio Entity Extractor"
    requires         = ["handle"]
    produces         = ["email", "phone", "cnpj", "website_url", "domain"]
    tier             = "seed"
    priority         = 0          # before Linktree (priority=1) so domain seeds WHOIS early
    cost_usd         = 0.0
    timeout_s        = 5
    retry_max        = 0
    rate_limit_rpm   = 0
    ttl_hours        = 168
    min_confidence   = 0.5
    max_instances    = 1
    osint_risk       = True       # email/phone/cnpj are PII
    secrets_required = []
    gdpr_basis       = "LEGITIMATE_INTERESTS"
    data_category    = "PUBLIC_SCRAPE"
    tos_compliant    = True

    def run(self, seed_entities: list[Entity], config: AdapterConfig) -> AdapterResult:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        t0 = time.monotonic()

        if config.dry_run or config.context is None or config.context.raw_profile is None:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error=None, cached=False, ran_at=now, cost_usd=0.0,
                duration_s=time.monotonic() - t0,
            )

        raw_profile = config.context.raw_profile
        bio = raw_profile.get("bio") or ""
        website = raw_profile.get("website")

        depth = (seed_entities[0].depth + 1) if seed_entities else 1

        hits = _EXTRACTOR.extract(bio, website=website)

        entities: list[Entity] = []
        for entity_type, raw_value, confidence in hits:
            try:
                ent = make_entity(
                    entity_type, raw_value,
                    source=self.adapter_id,
                    confidence=confidence,
                    depth=depth,
                    discovered_at=now,
                )
                entities.append(ent)
            except Exception:
                pass

        # De-duplicate by (type, value)
        seen: set[tuple[str, str]] = set()
        deduped: list[Entity] = []
        for e in entities:
            key = (e.type, e.value)
            if key not in seen:
                seen.add(key)
                deduped.append(e)

        signals = [
            Signal(
                key="bio_entity_count",
                value=len(deduped),
                unit="count",
                confidence=1.0,
                method="computed",
                source=self.adapter_id,
                osint_risk=False,
            ),
        ]

        return AdapterResult(
            adapter_id=self.adapter_id,
            entities=deduped,
            signals=signals,
            error=None,
            cached=False,
            ran_at=now,
            cost_usd=0.0,
            duration_s=time.monotonic() - t0,
        )
```

**Step 4: Run tests**

```bash
python3 -m pytest tests/enrichment/adapters/test_instagram_bio.py -v
```
Expected: all `PASSED`.

**Step 5: Full suite**

```bash
python3 -m pytest --timeout=30 -q
```

**Step 6: Commit**

```bash
git add pipeline/enrichment/adapters/instagram_bio.py tests/enrichment/adapters/test_instagram_bio.py
git commit -m "feat(0014/bio): add InstagramBioAdapter (tier=seed, priority=0)"
```

---

### Task 5: Register adapter + create YAML config

**Files:**
- Create: `pipeline/enrichment/config/instagram_bio.yaml`
- Modify: `pipeline/stage1b_enrichment.py` (add to `_ADAPTER_MODULES`, update `list_adapters` count)
- Test: update `tests/test_stage1b.py::test_list_adapters_returns_19` → 20

**Step 1: Write the failing test**

In `tests/test_stage1b.py`, update the count test:

```python
def test_list_adapters_returns_20(project_dir):   # was 19
    rows = list_adapters()
    assert len(rows) == 20
    ids = {r["adapter_id"] for r in rows}
    assert "instagram_bio" in ids
    assert "linktree" in ids
    assert "maigret" in ids
```

Also rename the old `test_list_adapters_returns_19` function to `test_list_adapters_returns_20`.

**Step 2: Run to verify failure**

```bash
python3 -m pytest tests/test_stage1b.py::test_list_adapters_returns_20 -v
```
Expected: `FAILED` — count is 19, `instagram_bio` not in ids.

**Step 3: Create `pipeline/enrichment/config/instagram_bio.yaml`**

```yaml
adapter_id: instagram_bio
display_name: Instagram Bio Entity Extractor
tier: seed
priority: 0
cost_usd: 0.0
timeout_s: 5
retry_max: 0
rate_limit_rpm: 0
ttl_hours: 168
min_confidence: 0.5
max_instances: 1
osint_risk: true
secrets_required: []
gdpr_basis: LEGITIMATE_INTERESTS
data_category: PUBLIC_SCRAPE
tos_compliant: true
enabled: true
```

**Step 4: Register in `pipeline/stage1b_enrichment.py`**

Add to `_ADAPTER_MODULES` (insert as first entry, priority 0):

```python
_ADAPTER_MODULES = {
    "instagram_bio":   "pipeline.enrichment.adapters.instagram_bio.InstagramBioAdapter",
    "linktree":        "pipeline.enrichment.adapters.linktree.LinktreeAdapter",
    # ... rest unchanged
}
```

**Step 5: Run test**

```bash
python3 -m pytest tests/test_stage1b.py -v
```
Expected: all `PASSED`.

**Step 6: Full suite**

```bash
python3 -m pytest --timeout=30 -q
```
Expected: all pass.

**Step 7: Commit**

```bash
git add pipeline/enrichment/config/instagram_bio.yaml pipeline/stage1b_enrichment.py tests/test_stage1b.py
git commit -m "feat(0014/bio): register InstagramBioAdapter, update adapter count to 20"
```

---

### Task 6: Final integration smoke test

**Step 1: Run stage 1B against the existing `sample_creator` fixture to verify the new adapter fires**

```bash
python3 profile_analyst.py --handle sample_creator --stage 1b 2>&1
```

Expected: stage completes, `projects/sample_creator/enrichment_map.json` contains adapter run for `instagram_bio`.

**Step 2: Inspect enrichment map for bio entities**

```bash
python3 -c "
import json
doc = json.load(open('projects/sample_creator/enrichment_map.json'))
bio_run = next((r for r in doc['adapter_runs'] if r['adapter_id'] == 'instagram_bio'), None)
print('instagram_bio run:', bio_run)
bio_entities = [e for e in doc['entity_pool'] if e.get('source') == 'instagram_bio']
print('entities from bio:', bio_entities)
"
```

Expected: `instagram_bio` run present; bio entities (email/domain) from `sample_creator`'s bio text.

**Step 3: Commit smoke evidence if output looks correct**

```bash
git add -p   # stage only if desired
git commit -m "test(0014/bio): verify InstagramBioAdapter fires on sample_creator"
```
