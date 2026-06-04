# Compliance & Quality Refactor Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Refactor `pipeline/enrichment/` to fully embody the "Compliance & Quality" role by adding robots.txt policy, rate-limit enforcement, adapter governance, provenance tracking, and coverage metrics — then rename the module to `pipeline/compliance_quality/`.

**Architecture:** The enrichment subsystem already has the contract skeleton (adapter governance via `_REQUIRED_ATTRS`, confidence floors in the engine, GDPR fields). We extend it with five new capabilities: a `robots_txt_policy` declaration on every adapter, a `RobotsPolicy` checker, a `RateLimiter`, a `Provenance`-aware `AdapterResult`, and a `CoverageReport` emitted by `run_engine`. The module is renamed last, after all tests pass, minimizing the blast radius of the large import update.

**Tech Stack:** Python 3.11+, `urllib.robotparser` (stdlib), `threading.Lock` (stdlib), `dataclasses`, `pytest`, existing `pipeline.enrichment.*`.

---

## Scope of files

```
MODIFIED
  pipeline/enrichment/adapter.py            ← add robots_txt_policy to contract + AdapterResult.triggered_by
  pipeline/enrichment/schemas/adapter_config.schema.json  ← add robots_txt_policy field
  pipeline/enrichment/config/*.yaml (×20)   ← add robots_txt_policy
  pipeline/enrichment/adapters/*.py  (×20)  ← add robots_txt_policy class attribute
  pipeline/enrichment/engine.py             ← wire RobotsPolicy, RateLimiter, emit CoverageReport

CREATED
  pipeline/enrichment/robots_policy.py      ← RobotsPolicy checker (urllib.robotparser)
  pipeline/enrichment/rate_limiter.py       ← per-adapter token-bucket RateLimiter
  pipeline/enrichment/coverage.py           ← CoverageReport dataclass + compute()
  tests/enrichment/test_robots_policy.py
  tests/enrichment/test_rate_limiter.py
  tests/enrichment/test_coverage.py

RENAMED (last step — Task 9)
  pipeline/enrichment/  →  pipeline/compliance_quality/
  (all callers updated: pipeline/stage1b_enrichment.py, profile_analyst.py, all test files)
```

---

## robots_txt_policy values

| `data_category`  | `robots_txt_policy` | Why |
|------------------|---------------------|-----|
| PUBLIC_SCRAPE    | `RESPECT`           | Fetches HTML from target sites |
| OSINT            | `RESPECT`           | May fetch login / account pages |
| PUBLIC_API       | `N/A`               | REST calls; robots.txt irrelevant |
| OPEN_DATA        | `N/A`               | Structured datasets; robots.txt irrelevant |

Adapters: linktree, instagram_bio, substack, google_news → `RESPECT`
Adapters: holehe, maigret, hibp, ghunt → `RESPECT`
Adapters: itunes, twitch, youtube, knowledge_graph, reddit, spotify, github → `N/A`
Adapters: gdelt, crt, cnpj, whois, wikidata → `N/A`

---

## Task 1: Extend adapter contract — `robots_txt_policy`

**Files:**
- Modify: `pipeline/enrichment/adapter.py`
- Modify: `pipeline/enrichment/schemas/adapter_config.schema.json`
- Test: `tests/enrichment/test_adapter.py` (add to existing file)

### Step 1: Write the failing test

Add to the bottom of `tests/enrichment/test_adapter.py`:

```python
def test_adapter_missing_robots_policy_raises():
    with pytest.raises(AdapterContractError, match="robots_txt_policy"):
        class BadAdapter(EnrichmentAdapter):
            adapter_id = "bad"; display_name = "Bad"
            requires = []; produces = []
            tier = "fast"; priority = 1; cost_usd = 0.0; timeout_s = 5
            retry_max = 0; rate_limit_rpm = 0; ttl_hours = 0
            min_confidence = 0.5; max_instances = 1; osint_risk = False
            secrets_required = []; gdpr_basis = "NONE"
            data_category = "PUBLIC_API"; tos_compliant = True
            # robots_txt_policy intentionally omitted

            def run(self, seed_entities, config): pass


def test_adapter_invalid_robots_policy_raises():
    with pytest.raises(AdapterContractError, match="robots_txt_policy"):
        class BadPolicyAdapter(EnrichmentAdapter):
            adapter_id = "bad2"; display_name = "Bad2"
            requires = []; produces = []
            tier = "fast"; priority = 1; cost_usd = 0.0; timeout_s = 5
            retry_max = 0; rate_limit_rpm = 0; ttl_hours = 0
            min_confidence = 0.5; max_instances = 1; osint_risk = False
            secrets_required = []; gdpr_basis = "NONE"
            data_category = "PUBLIC_API"; tos_compliant = True
            robots_txt_policy = "MAYBE"  # invalid

            def run(self, seed_entities, config): pass
```

### Step 2: Run to verify it fails

```bash
pytest tests/enrichment/test_adapter.py::test_adapter_missing_robots_policy_raises -v
```
Expected: `FAIL` — attribute not validated yet.

### Step 3: Implement

In `pipeline/enrichment/adapter.py`:

```python
_VALID_TIERS = frozenset({"seed", "fast", "medium", "slow"})
_VALID_GDPR  = frozenset({"LEGITIMATE_INTERESTS", "CONSENT", "NONE"})
_VALID_CATS  = frozenset({"PUBLIC_API", "PUBLIC_SCRAPE", "OSINT", "OPEN_DATA"})
_VALID_ROBOTS = frozenset({"RESPECT", "IGNORE", "N/A"})   # ← ADD

_REQUIRED_ATTRS = (
    "adapter_id", "display_name", "requires", "produces", "tier", "priority",
    "cost_usd", "timeout_s", "retry_max", "rate_limit_rpm", "ttl_hours",
    "min_confidence", "max_instances", "osint_risk", "secrets_required",
    "gdpr_basis", "data_category", "tos_compliant",
    "robots_txt_policy",   # ← ADD
)
```

And inside `__init_subclass__`, after the `data_category` check:

```python
if hasattr(cls, "robots_txt_policy") and cls.robots_txt_policy not in _VALID_ROBOTS:
    errors.append(f"robots_txt_policy={cls.robots_txt_policy!r} not in {_VALID_ROBOTS}")
```

Also add `triggered_by: list[str]` to `AdapterResult`:

```python
@dataclass
class AdapterResult:
    adapter_id: str
    entities: list[Entity]
    signals: list[Signal]
    error: str | None
    cached: bool
    ran_at: str
    cost_usd: float
    duration_s: float = 0.0
    triggered_by: list[str] = field(default_factory=list)   # ← ADD (provenance)
```

### Step 4: Update JSON schema

In `pipeline/enrichment/schemas/adapter_config.schema.json`:

Add `"robots_txt_policy"` to `"required"` array and add its property:

```json
"robots_txt_policy": {
  "type": "string",
  "enum": ["RESPECT", "IGNORE", "N/A"]
}
```

### Step 5: Run tests

```bash
pytest tests/enrichment/test_adapter.py -v
```
Expected: all PASS.

### Step 6: Commit

```bash
git add pipeline/enrichment/adapter.py pipeline/enrichment/schemas/adapter_config.schema.json tests/enrichment/test_adapter.py
git commit -m "feat(compliance-quality): add robots_txt_policy to adapter contract + provenance triggered_by"
```

---

## Task 2: Add `robots_txt_policy` to all 20 YAML configs

**Files:**
- Modify: `pipeline/enrichment/config/*.yaml` (all 20)

The attribute placement: add it directly after `tos_compliant:` in each YAML file (keep alphabetical order: **r** comes after **r**ate_limit_rpm and before **s**ecrets_required, so insert after `rate_limit_rpm:`).

Policy assignment (based on `data_category`):

```
RESPECT:  google_news, holehe, instagram_bio, linktree, maigret, substack, ghunt, hibp
N/A:      cnpj, crt, gdelt, github, itunes, knowledge_graph, reddit, spotify, twitch, whois, wikidata, youtube
```

### Step 1: Write a schema-validation test

Create / add to `tests/enrichment/test_adapter.py`:

```python
import json, yaml
from jsonschema import validate
from pathlib import Path

def test_all_yaml_configs_valid():
    schema_path = Path("pipeline/enrichment/schemas/adapter_config.schema.json")
    schema = json.loads(schema_path.read_text())
    config_dir = Path("pipeline/enrichment/config")
    for yaml_file in sorted(config_dir.glob("*.yaml")):
        config = yaml.safe_load(yaml_file.read_text())
        validate(instance=config, schema=schema)  # raises on invalid
```

### Step 2: Run to verify it fails

```bash
pytest tests/enrichment/test_adapter.py::test_all_yaml_configs_valid -v
```
Expected: FAIL — `robots_txt_policy` missing from all YAMLs.

### Step 3: Update each YAML

For PUBLIC_SCRAPE / OSINT adapters (google_news, holehe, instagram_bio, linktree, maigret, substack, ghunt, hibp):
```yaml
robots_txt_policy: RESPECT
```

For PUBLIC_API / OPEN_DATA adapters (all others):
```yaml
robots_txt_policy: "N/A"
```

Use `sed` for bulk update — do RESPECT group first, then N/A for remaining:

```bash
# RESPECT group
for f in google_news holehe instagram_bio linktree maigret substack ghunt hibp; do
  sed -i 's/^tos_compliant: .*/&\nrobots_txt_policy: RESPECT/' pipeline/enrichment/config/$f.yaml
done

# N/A group
for f in cnpj crt gdelt github itunes knowledge_graph reddit spotify twitch whois wikidata youtube; do
  sed -i "s/^tos_compliant: .*/\&\nrobots_txt_policy: \"N\/A\"/" pipeline/enrichment/config/$f.yaml
done
```

Note: verify with `grep -h robots_txt_policy pipeline/enrichment/config/*.yaml | sort` that all 20 are present.

### Step 4: Run test

```bash
pytest tests/enrichment/test_adapter.py::test_all_yaml_configs_valid -v
```
Expected: PASS.

### Step 5: Commit

```bash
git add pipeline/enrichment/config/ tests/enrichment/test_adapter.py
git commit -m "feat(compliance-quality): add robots_txt_policy to all 20 adapter YAML configs"
```

---

## Task 3: Add `robots_txt_policy` class attr to all 20 Python adapters

**Files:**
- Modify: `pipeline/enrichment/adapters/*.py` (20 files)

### Step 1: Write the failing test

Add to `tests/enrichment/test_adapter.py`:

```python
def test_all_adapter_classes_declare_robots_policy():
    """Import every concrete adapter and assert robots_txt_policy is set."""
    import importlib
    from pathlib import Path
    adapters_dir = Path("pipeline/enrichment/adapters")
    for py_file in sorted(adapters_dir.glob("*.py")):
        if py_file.name == "__init__.py":
            continue
        mod = importlib.import_module(f"pipeline.enrichment.adapters.{py_file.stem}")
        for name in dir(mod):
            obj = getattr(mod, name)
            if isinstance(obj, type) and issubclass(obj, EnrichmentAdapter) and obj is not EnrichmentAdapter:
                assert hasattr(obj, "robots_txt_policy"), (
                    f"{obj.__name__} missing robots_txt_policy"
                )
```

### Step 2: Run to verify it fails

```bash
pytest tests/enrichment/test_adapter.py::test_all_adapter_classes_declare_robots_policy -v
```
Expected: FAIL (first adapter class that lacks the attribute will trigger `AdapterContractError` on import, or assertion error).

### Step 3: Implement — add to each adapter class

For each of the 20 adapter files, add `robots_txt_policy` after `tos_compliant`:

**RESPECT adapters:** `linktree.py`, `instagram_bio.py`, `substack.py`, `google_news.py`, `holehe.py`, `maigret.py`, `hibp.py`, `ghunt.py`

```python
tos_compliant  = True
robots_txt_policy = "RESPECT"   # ← ADD
```

**N/A adapters:** `itunes.py`, `twitch.py`, `youtube.py`, `knowledge_graph.py`, `reddit.py`, `spotify.py`, `github.py`, `gdelt.py`, `crt.py`, `cnpj.py`, `whois.py`, `wikidata.py`

```python
tos_compliant  = True
robots_txt_policy = "N/A"       # ← ADD
```

### Step 4: Run tests

```bash
pytest tests/enrichment/test_adapter.py -v
```
Expected: all PASS.

### Step 5: Commit

```bash
git add pipeline/enrichment/adapters/
git commit -m "feat(compliance-quality): add robots_txt_policy to all 20 adapter classes"
```

---

## Task 4: Build `RobotsPolicy` checker

**Files:**
- Create: `pipeline/enrichment/robots_policy.py`
- Create: `tests/enrichment/test_robots_policy.py`

### Step 1: Write the failing tests

```python
# tests/enrichment/test_robots_policy.py
import pytest
from unittest.mock import patch, MagicMock
from pipeline.enrichment.robots_policy import RobotsPolicy, RobotsPolicyError


class TestRobotsPolicy:
    def test_na_policy_always_allowed(self):
        rp = RobotsPolicy()
        assert rp.is_allowed("N/A", "https://api.example.com/endpoint") is True

    def test_ignore_policy_always_allowed(self):
        rp = RobotsPolicy()
        assert rp.is_allowed("IGNORE", "https://example.com/private") is True

    def test_respect_allows_permitted_url(self):
        rp = RobotsPolicy()
        robots_txt = "User-agent: *\nAllow: /\n"
        with patch("urllib.robotparser.RobotFileParser.read") as mock_read:
            with patch("urllib.robotparser.RobotFileParser.can_fetch", return_value=True):
                assert rp.is_allowed("RESPECT", "https://linktr.ee/someuser") is True

    def test_respect_blocks_disallowed_url(self):
        rp = RobotsPolicy()
        with patch("urllib.robotparser.RobotFileParser.read"):
            with patch("urllib.robotparser.RobotFileParser.can_fetch", return_value=False):
                assert rp.is_allowed("RESPECT", "https://example.com/private") is False

    def test_respect_allows_on_fetch_error(self):
        """Network error fetching robots.txt → allow (fail open)."""
        rp = RobotsPolicy()
        with patch("urllib.robotparser.RobotFileParser.read", side_effect=Exception("timeout")):
            assert rp.is_allowed("RESPECT", "https://example.com/page") is True

    def test_invalid_policy_raises(self):
        rp = RobotsPolicy()
        with pytest.raises(RobotsPolicyError):
            rp.is_allowed("UNKNOWN", "https://example.com")

    def test_cache_avoids_duplicate_fetch(self):
        rp = RobotsPolicy()
        with patch("urllib.robotparser.RobotFileParser.read") as mock_read:
            with patch("urllib.robotparser.RobotFileParser.can_fetch", return_value=True):
                rp.is_allowed("RESPECT", "https://linktr.ee/a")
                rp.is_allowed("RESPECT", "https://linktr.ee/b")
                # Same host — robots.txt fetched once
                assert mock_read.call_count == 1
```

### Step 2: Run to verify it fails

```bash
pytest tests/enrichment/test_robots_policy.py -v
```
Expected: `ModuleNotFoundError`.

### Step 3: Implement

```python
# pipeline/enrichment/robots_policy.py
"""robots.txt policy checker for enrichment adapters (Compliance & Quality)."""
from __future__ import annotations

import logging
import urllib.robotparser
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

USER_AGENT = "profile-analyst/0.1"

_VALID_POLICIES = frozenset({"RESPECT", "IGNORE", "N/A"})


class RobotsPolicyError(ValueError):
    pass


class RobotsPolicy:
    """Thread-safe robots.txt checker with per-host in-memory cache."""

    def __init__(self):
        self._cache: dict[str, urllib.robotparser.RobotFileParser] = {}

    def is_allowed(self, policy: str, url: str) -> bool:
        """Return True if the adapter may fetch *url* under *policy*."""
        if policy not in _VALID_POLICIES:
            raise RobotsPolicyError(f"Unknown policy {policy!r}. Valid: {_VALID_POLICIES}")
        if policy in ("N/A", "IGNORE"):
            return True
        # RESPECT: parse robots.txt for this host
        parsed = urlparse(url)
        host_key = f"{parsed.scheme}://{parsed.netloc}"
        if host_key not in self._cache:
            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(f"{host_key}/robots.txt")
            try:
                rp.read()
            except Exception as exc:
                logger.debug("robots.txt fetch failed for %s: %s — allowing", host_key, exc)
                rp = None
            self._cache[host_key] = rp
        parser = self._cache[host_key]
        if parser is None:
            return True  # fail open
        return parser.can_fetch(USER_AGENT, url)
```

### Step 4: Run tests

```bash
pytest tests/enrichment/test_robots_policy.py -v
```
Expected: all PASS.

### Step 5: Commit

```bash
git add pipeline/enrichment/robots_policy.py tests/enrichment/test_robots_policy.py
git commit -m "feat(compliance-quality): add RobotsPolicy checker with per-host cache"
```

---

## Task 5: Build `RateLimiter`

**Files:**
- Create: `pipeline/enrichment/rate_limiter.py`
- Create: `tests/enrichment/test_rate_limiter.py`

### Step 1: Write the failing tests

```python
# tests/enrichment/test_rate_limiter.py
import time
import pytest
from pipeline.enrichment.rate_limiter import RateLimiter


class TestRateLimiter:
    def test_zero_rpm_never_blocks(self):
        rl = RateLimiter()
        t0 = time.monotonic()
        for _ in range(10):
            rl.acquire("adapter_a", rate_limit_rpm=0)
        assert time.monotonic() - t0 < 0.05  # no sleeping

    def test_high_rpm_does_not_block_within_limit(self):
        """600 RPM = 10 calls/sec — 3 calls should be near-instant."""
        rl = RateLimiter()
        t0 = time.monotonic()
        for _ in range(3):
            rl.acquire("adapter_b", rate_limit_rpm=600)
        assert time.monotonic() - t0 < 0.1

    def test_different_adapters_are_independent(self):
        rl = RateLimiter()
        rl.acquire("a1", rate_limit_rpm=60)
        rl.acquire("a2", rate_limit_rpm=60)  # different key — no block

    def test_state_is_per_adapter_id(self):
        rl = RateLimiter()
        rl.acquire("x", rate_limit_rpm=60)
        rl.acquire("y", rate_limit_rpm=60)
        assert "x" in rl._last_call
        assert "y" in rl._last_call
```

### Step 2: Run to verify it fails

```bash
pytest tests/enrichment/test_rate_limiter.py -v
```
Expected: `ModuleNotFoundError`.

### Step 3: Implement

```python
# pipeline/enrichment/rate_limiter.py
"""Per-adapter rate limiter (Compliance & Quality)."""
from __future__ import annotations

import threading
import time


class RateLimiter:
    """Enforces rate_limit_rpm per adapter_id using a simple minimum-interval strategy."""

    def __init__(self):
        self._last_call: dict[str, float] = {}
        self._lock = threading.Lock()

    def acquire(self, adapter_id: str, rate_limit_rpm: int) -> None:
        """Block until the adapter is allowed to run (no-op when rate_limit_rpm == 0)."""
        if rate_limit_rpm <= 0:
            return
        min_interval = 60.0 / rate_limit_rpm
        with self._lock:
            last = self._last_call.get(adapter_id, 0.0)
            elapsed = time.monotonic() - last
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)
            self._last_call[adapter_id] = time.monotonic()
```

### Step 4: Run tests

```bash
pytest tests/enrichment/test_rate_limiter.py -v
```
Expected: all PASS.

### Step 5: Commit

```bash
git add pipeline/enrichment/rate_limiter.py tests/enrichment/test_rate_limiter.py
git commit -m "feat(compliance-quality): add per-adapter RateLimiter"
```

---

## Task 6: Build `CoverageReport`

**Files:**
- Create: `pipeline/enrichment/coverage.py`
- Create: `tests/enrichment/test_coverage.py`

### Step 1: Write the failing tests

```python
# tests/enrichment/test_coverage.py
import pytest
from pipeline.enrichment.coverage import CoverageReport, compute_coverage
from pipeline.enrichment.adapter import AdapterResult, Signal
from pipeline.enrichment.entity import make_entity

TS = "2026-06-03T00:00:00Z"


def _result(adapter_id, signal_keys=(), entity_types=(), error=None):
    entities = [
        make_entity(t, _sample_value(t), source="test", confidence=1.0, depth=1, discovered_at=TS)
        for t in entity_types
    ]
    signals = [Signal(key=k, value=1, unit=None, confidence=1.0,
                      method="api", source=adapter_id, osint_risk=False)
               for k in signal_keys]
    return AdapterResult(
        adapter_id=adapter_id, entities=entities, signals=signals,
        error=error, cached=False, ran_at=TS, cost_usd=0.0,
    )


def _sample_value(entity_type):
    samples = {"handle": "testuser", "youtube_handle": "@testchan",
               "domain": "example.com"}
    return samples.get(entity_type, "testvalue")


class TestCoverageReport:
    def test_empty_results_zero_coverage(self):
        report = compute_coverage("run-1", [])
        assert report.adapters_run == 0
        assert report.total_signals == 0
        assert report.total_entities == 0

    def test_counts_adapters_run(self):
        results = [_result("yt"), _result("gh")]
        report = compute_coverage("run-1", results)
        assert report.adapters_run == 2

    def test_counts_errored_adapters(self):
        results = [_result("yt"), _result("gh", error="timeout")]
        report = compute_coverage("run-1", results)
        assert report.adapters_errored == 1

    def test_collects_signal_types(self):
        results = [_result("yt", signal_keys=["sub_count", "view_count"])]
        report = compute_coverage("run-1", results)
        assert "sub_count" in report.signal_types_covered
        assert "view_count" in report.signal_types_covered

    def test_collects_entity_types(self):
        results = [_result("lt", entity_types=["handle", "domain"])]
        report = compute_coverage("run-1", results)
        assert "handle" in report.entity_types_covered
        assert "domain" in report.entity_types_covered

    def test_total_counts(self):
        results = [
            _result("lt", signal_keys=["s1"], entity_types=["handle"]),
            _result("yt", signal_keys=["s2", "s3"]),
        ]
        report = compute_coverage("run-1", results)
        assert report.total_signals == 3
        assert report.total_entities == 1
```

### Step 2: Run to verify it fails

```bash
pytest tests/enrichment/test_coverage.py -v
```
Expected: `ModuleNotFoundError`.

### Step 3: Implement

```python
# pipeline/enrichment/coverage.py
"""Coverage metrics for Compliance & Quality reporting."""
from __future__ import annotations

from dataclasses import dataclass, field

from pipeline.enrichment.adapter import AdapterResult


@dataclass
class CoverageReport:
    run_id: str
    adapters_run: int
    adapters_errored: int
    total_signals: int
    total_entities: int
    signal_types_covered: set[str] = field(default_factory=set)
    entity_types_covered: set[str] = field(default_factory=set)


def compute_coverage(run_id: str, results: list[AdapterResult]) -> CoverageReport:
    """Derive a CoverageReport from the full list of AdapterResults."""
    signal_types: set[str] = set()
    entity_types: set[str] = set()
    errored = 0
    total_signals = 0
    total_entities = 0

    for r in results:
        if r.error is not None:
            errored += 1
        for s in r.signals:
            signal_types.add(s.key)
            total_signals += 1
        for e in r.entities:
            entity_types.add(e.type)
            total_entities += 1

    return CoverageReport(
        run_id=run_id,
        adapters_run=len(results),
        adapters_errored=errored,
        total_signals=total_signals,
        total_entities=total_entities,
        signal_types_covered=signal_types,
        entity_types_covered=entity_types,
    )
```

### Step 4: Run tests

```bash
pytest tests/enrichment/test_coverage.py -v
```
Expected: all PASS.

### Step 5: Commit

```bash
git add pipeline/enrichment/coverage.py tests/enrichment/test_coverage.py
git commit -m "feat(compliance-quality): add CoverageReport and compute_coverage()"
```

---

## Task 7: Wire everything into `engine.py`

**Files:**
- Modify: `pipeline/enrichment/engine.py`
- Modify: `tests/enrichment/test_engine.py`

The engine must:
1. Instantiate `RobotsPolicy` and `RateLimiter` once per `run_engine` call.
2. Before running any adapter: call `RateLimiter.acquire(adapter_id, rate_limit_rpm)`.
3. Before running any RESPECT-policy adapter: call `RobotsPolicy.is_allowed(policy, url)` using the first trigger entity's value as the URL; skip adapter (log warning) if blocked.
4. Populate `triggered_by` on each `AdapterResult` with the trigger entities' values.
5. Return `CoverageReport` as the 4th element of the tuple.

### Step 1: Write the failing tests

Add to `tests/enrichment/test_engine.py`:

```python
from pipeline.enrichment.coverage import CoverageReport

# Existing FakeYouTubeAdapter stays unchanged.

class TestEngineReturnsCoverage:
    def test_run_engine_returns_four_tuple(self, tmp_path):
        seed = {"handle": "testuser"}
        cfg = EngineConfig()
        result = run_engine(seed, [], cfg, tmp_path)
        assert len(result) == 4
        pool, state, all_results, coverage = result
        assert isinstance(coverage, CoverageReport)

    def test_coverage_counts_run_adapters(self, tmp_path):
        seed = {"handle": "testuser"}
        cfg = EngineConfig()
        _, _, _, coverage = run_engine(seed, [], cfg, tmp_path)
        assert coverage.adapters_run == 0  # no adapters registered

class TestEngineProvenanceTriggeredBy:
    def test_adapter_result_has_triggered_by(self, tmp_path):
        seed = {"handle": "testuser"}

        class SimpleHandleAdapter(EnrichmentAdapter):
            adapter_id = "simple"; display_name = "Simple"
            requires = ["handle"]; produces = []
            tier = "fast"; priority = 1; cost_usd = 0.0; timeout_s = 5
            retry_max = 0; rate_limit_rpm = 0; ttl_hours = 0
            min_confidence = 0.0; max_instances = 1; osint_risk = False
            secrets_required = []; gdpr_basis = "NONE"
            data_category = "PUBLIC_API"; tos_compliant = True
            robots_txt_policy = "N/A"

            def run(self, seed_entities, config):
                return AdapterResult(
                    adapter_id=self.adapter_id, entities=[], signals=[],
                    error=None, cached=False, ran_at=TS, cost_usd=0.0,
                )

        cfg = EngineConfig(min_confidence_global=0.0)
        _, _, results, _ = run_engine(seed, [SimpleHandleAdapter()], cfg, tmp_path)
        assert len(results) == 1
        assert "testuser" in results[0].triggered_by
```

### Step 2: Run to verify it fails

```bash
pytest tests/enrichment/test_engine.py::TestEngineReturnsCoverage -v
```
Expected: FAIL (run_engine returns 3-tuple currently).

### Step 3: Implement changes in `engine.py`

At the top of the file, add imports:
```python
from pipeline.enrichment.robots_policy import RobotsPolicy
from pipeline.enrichment.rate_limiter import RateLimiter
from pipeline.enrichment.coverage import CoverageReport, compute_coverage
```

Modify `_run_with_cache` signature to accept `robots_policy` and `rate_limiter`:

```python
def _run_with_cache(
    adapter: EnrichmentAdapter,
    pool: EntityPool,
    state: EngineState,
    config: AdapterConfig,
    cache_dir: Path,
    robots_policy: RobotsPolicy | None = None,
    rate_limiter: RateLimiter | None = None,
) -> AdapterResult:
    ...
    # Before live run, AFTER cache check:
    if rate_limiter is not None:
        rate_limiter.acquire(adapter.adapter_id, adapter.rate_limit_rpm)
    if robots_policy is not None and getattr(adapter, "robots_txt_policy", "N/A") == "RESPECT":
        for entity in trigger_entities:
            if not robots_policy.is_allowed("RESPECT", entity.value):
                logger.warning("robots.txt blocks %s for %s — skipping", adapter.adapter_id, entity.value)
                return AdapterResult(adapter_id=adapter.adapter_id, entities=[], signals=[],
                                     error="blocked by robots.txt", cached=False, ran_at=now,
                                     cost_usd=0.0, triggered_by=[e.value for e in trigger_entities])
    ...
    # After running adapter, set triggered_by:
    result.triggered_by = [e.value for e in trigger_entities]   # AdapterResult is a dataclass (mutable)
    return result
```

Modify `run_engine` to:
1. Instantiate `RobotsPolicy()` and `RateLimiter()`
2. Pass them through `_run_parallel` → `_run_with_cache`
3. Change return type to include `CoverageReport`:

```python
def run_engine(...) -> tuple[EntityPool, EngineState, list[AdapterResult], CoverageReport]:
    ...
    # At the very end, before return:
    coverage = compute_coverage(run_id, all_results)
    return pool, state, all_results, coverage
```

### Step 4: Fix all callers of `run_engine`

Search and update all callers that unpack the 3-tuple:

```bash
grep -rn "run_engine" pipeline/ tests/ profile_analyst.py --include="*.py"
```

Update each call site that does `pool, state, results = run_engine(...)` to:
```python
pool, state, results, coverage = run_engine(...)
```

Key file: `pipeline/stage1b_enrichment.py` — find the call and add `coverage` to the unpack.

### Step 5: Run full test suite

```bash
pytest tests/enrichment/ -v
```
Expected: all PASS.

### Step 6: Commit

```bash
git add pipeline/enrichment/engine.py pipeline/stage1b_enrichment.py tests/enrichment/test_engine.py
git commit -m "feat(compliance-quality): wire RobotsPolicy, RateLimiter, CoverageReport into engine; add provenance triggered_by"
```

---

## Task 8: Run full test suite and verify acceptance criteria

### Step 1: Run all enrichment tests

```bash
pytest tests/enrichment/ tests/test_stage1b.py -v --tb=short 2>&1 | tail -20
```
Expected: all PASS.

### Step 2: Verify acceptance criteria manually

```bash
# AC1: every adapter declares policy
python3 -c "
from pipeline.enrichment.adapters import *
import pipeline.enrichment.adapters as pkg
import importlib, pkgutil
from pipeline.enrichment.adapter import EnrichmentAdapter
for mod_info in pkgutil.iter_modules(pkg.__path__):
    m = importlib.import_module(f'pipeline.enrichment.adapters.{mod_info.name}')
    for name in dir(m):
        obj = getattr(m, name)
        if isinstance(obj, type) and issubclass(obj, EnrichmentAdapter) and not getattr(obj, '__abstractmethods__', None):
            policy = getattr(obj, 'robots_txt_policy', 'MISSING')
            print(f'{obj.adapter_id}: robots_txt_policy={policy}')
"
```

Expected: 20 lines, no `MISSING`.

```bash
# AC2: every enrichment record has provenance (triggered_by populated)
python3 -c "
from pipeline.enrichment.engine import run_engine, EngineConfig
from pipeline.enrichment.adapters.linktree import LinktreeAdapter
from pathlib import Path
seed = {'handle': 'filipelauar', 'website': 'https://linktr.ee/filipelauar'}
_, _, results, coverage = run_engine(seed, [LinktreeAdapter()], EngineConfig(), Path('/tmp/test-cache'), dry_run_override=True)
for r in results:
    print(f'{r.adapter_id}: triggered_by={r.triggered_by}')
print(f'Coverage: {coverage.adapters_run} run, {coverage.total_signals} signals')
"
```

Expected: each result shows a non-empty `triggered_by` list.

### Step 3: Commit

```bash
git add .
git commit -m "test(compliance-quality): verify all acceptance criteria pass"
```

---

## Task 9: Rename module to `pipeline/compliance_quality/`

**Files:**
- Create: `pipeline/compliance_quality/` (copy of `pipeline/enrichment/`)
- Modify: all callers (`pipeline/stage1b_enrichment.py`, `profile_analyst.py`, all test files)
- Keep: `pipeline/enrichment/` as a shim (re-exports from compliance_quality) for backward compat

### Step 1: Write the failing import test

```python
# tests/test_compliance_quality_imports.py
def test_compliance_quality_importable():
    from pipeline.compliance_quality.adapter import EnrichmentAdapter, AdapterResult
    from pipeline.compliance_quality.engine import run_engine, EngineConfig
    from pipeline.compliance_quality.coverage import CoverageReport
    from pipeline.compliance_quality.robots_policy import RobotsPolicy
    from pipeline.compliance_quality.rate_limiter import RateLimiter
    assert EnrichmentAdapter is not None
```

### Step 2: Run to verify it fails

```bash
pytest tests/test_compliance_quality_imports.py -v
```
Expected: `ModuleNotFoundError`.

### Step 3: Rename the directory

```bash
cp -r pipeline/enrichment pipeline/compliance_quality
```

Update `pipeline/compliance_quality/__init__.py` (or create one that does not re-import enrichment).

Keep `pipeline/enrichment/__init__.py` as a backward-compat shim:

```python
# pipeline/enrichment/__init__.py  — backward-compat shim
"""Backward-compat shim. Import from pipeline.compliance_quality instead."""
from pipeline.compliance_quality import *  # noqa: F401, F403
```

And update internal relative imports inside `pipeline/compliance_quality/*.py` from `pipeline.enrichment.*` to `pipeline.compliance_quality.*`:

```bash
find pipeline/compliance_quality -name "*.py" -exec \
  sed -i 's/from pipeline\.enrichment\./from pipeline.compliance_quality./g' {} \;
find pipeline/compliance_quality -name "*.py" -exec \
  sed -i 's/import pipeline\.enrichment\./import pipeline.compliance_quality./g' {} \;
```

### Step 4: Update all external callers

Files to update (replace `pipeline.enrichment` → `pipeline.compliance_quality`):
- `pipeline/stage1b_enrichment.py`
- `profile_analyst.py`
- All `tests/enrichment/*.py` (update import paths; keep directory name `tests/enrichment/` for now or rename to `tests/compliance_quality/`)

```bash
for f in pipeline/stage1b_enrichment.py profile_analyst.py; do
  sed -i 's/from pipeline\.enrichment\./from pipeline.compliance_quality./g' "$f"
  sed -i 's/import pipeline\.enrichment\./import pipeline.compliance_quality./g' "$f"
done
```

### Step 5: Run the full test suite

```bash
pytest tests/ -v --tb=short 2>&1 | tail -30
```
Expected: all PASS (enrichment shim keeps old tests working, new compliance_quality tests pass).

### Step 6: Commit

```bash
git add pipeline/compliance_quality/ pipeline/enrichment/__init__.py pipeline/stage1b_enrichment.py profile_analyst.py
git commit -m "refactor(compliance-quality): rename pipeline/enrichment → pipeline/compliance_quality; add backward-compat shim"
```

---

## Acceptance Criteria Checklist

- [ ] `robots_txt_policy` in `_REQUIRED_ATTRS` — `AdapterContractError` if missing
- [ ] All 20 YAML configs declare `robots_txt_policy` and pass JSON schema validation
- [ ] All 20 adapter classes declare `robots_txt_policy`
- [ ] `RobotsPolicy` checker respects robots.txt for `RESPECT` adapters; no-ops for `N/A`/`IGNORE`
- [ ] `RateLimiter` enforces `rate_limit_rpm` per adapter (no-op when `rate_limit_rpm == 0`)
- [ ] `AdapterResult.triggered_by` populated with triggering entity values (provenance)
- [ ] `run_engine` returns `CoverageReport` as 4th element
- [ ] `pipeline/compliance_quality/` importable; old `pipeline/enrichment/` still works via shim
- [ ] `pytest tests/` all green

---

## Quick Reference

```bash
# Run only enrichment/C&Q tests
pytest tests/enrichment/ tests/test_compliance_quality_imports.py -v

# Check all adapter policies
grep -h "robots_txt_policy" pipeline/enrichment/config/*.yaml | sort | uniq -c

# Validate all YAML configs
python3 -c "
import json, yaml
from jsonschema import validate
from pathlib import Path
schema = json.loads(Path('pipeline/enrichment/schemas/adapter_config.schema.json').read_text())
for f in sorted(Path('pipeline/enrichment/config').glob('*.yaml')):
    validate(yaml.safe_load(f.read_text()), schema)
    print(f'OK: {f.name}')
"
```
