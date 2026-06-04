# Ingestion Pipeline — Specs 0018, 0019, 0020 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement three new modules — `pipeline/governance/` (spec-0020), `pipeline/account_discovery/` (spec-0018), and enrichment engine additions `pipeline/enrichment/seeder.py` + `pipeline/enrichment/enrichers/` (spec-0019) — as fully tested, independently runnable layers.

**Architecture:** Governance is a stdlib-only leaf implemented first; Discovery and Enrichment both depend on it. Discovery's `00-discovery.json` feeds the enrichment seeder. The adapter/enricher split in spec-0019 is introduced additively — existing `run()`-based adapters are not broken; the new `fetch()`+`enricher.extract()` pair is added alongside them.

**Tech Stack:** Python 3.11+ · `urllib.robotparser` (stdlib) · `threading.Lock` (stdlib) · `dataclasses` · `pytest` · existing `pipeline.enrichment.*` (spec-0014)

**Implementation order:** Task 1–9 = spec-0020 (governance); Task 10–18 = spec-0018 (discovery); Task 19–24 = spec-0019 additions.

---

## PHASE 1 — Spec 0020: Compliance & Governance

### Task 1: Bootstrap `pipeline/governance/` — models

**Why first:** Every other governance module imports from `models.py`.

**Files:**
- Create: `pipeline/governance/__init__.py`
- Create: `pipeline/governance/models.py`
- Create: `tests/governance/__init__.py`
- Create: `tests/governance/conftest.py`
- Create: `tests/governance/test_models.py`

**Step 1: Write the failing test**

`tests/governance/test_models.py`:
```python
import pytest
from datetime import datetime, timezone
from pipeline.governance.models import (
    PolicyDecision, ContractViolation, CoverageReport, GovernanceReport,
)

def test_policy_decision_allowed():
    pd = PolicyDecision(allowed=True, reason="N/A policy", checked_url="https://example.com", policy_type="robots")
    assert pd.allowed is True
    assert pd.reason == "N/A policy"

def test_policy_decision_denied():
    pd = PolicyDecision(allowed=False, reason="robots.txt disallows", checked_url="https://example.com/private", policy_type="robots")
    assert pd.allowed is False

def test_contract_violation_fields():
    v = ContractViolation(adapter_id="test", field="tos_compliant", expected="bool", got="None", message="missing field")
    assert v.field == "tos_compliant"

def test_coverage_report_ratio():
    r = CoverageReport(
        run_id="r1", module="discovery",
        adapters_registered=2, adapters_run=2, adapters_skipped=0, adapters_failed=0,
        entity_types_expected={"youtube_handle", "github_handle"},
        entity_types_discovered={"youtube_handle"},
        per_adapter_coverage={},
    )
    assert r.coverage_ratio == 0.5

def test_coverage_report_empty_run():
    r = CoverageReport(
        run_id="r1", module="discovery",
        adapters_registered=0, adapters_run=0, adapters_skipped=0, adapters_failed=0,
        entity_types_expected=set(), entity_types_discovered=set(),
        per_adapter_coverage={},
    )
    assert r.coverage_ratio == 1.0

def test_governance_report_serializable():
    import json, dataclasses
    r = GovernanceReport(run_id="r1", module="enrichment")
    as_dict = dataclasses.asdict(r)
    # Must not raise
    json.dumps(as_dict, default=str)
```

**Step 2: Run to confirm it fails**
```bash
cd /home/pedro/profile-analyst && python -m pytest tests/governance/test_models.py -v 2>&1 | head -20
```
Expected: `ModuleNotFoundError: pipeline.governance`

**Step 3: Implement `pipeline/governance/models.py`**

```python
"""Governance data models — shared across policies, compliance, and metrics."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class PolicyDecision:
    allowed: bool
    reason: str
    checked_url: str
    policy_type: str   # "robots" | "rate_limit"
    decided_at: str = field(default_factory=_now)


@dataclass
class ContractViolation:
    adapter_id: str
    field: str
    expected: str
    got: str
    message: str


@dataclass
class CoverageReport:
    run_id: str
    module: str
    adapters_registered: int
    adapters_run: int
    adapters_skipped: int
    adapters_failed: int
    entity_types_expected: set
    entity_types_discovered: set
    per_adapter_coverage: dict
    generated_at: str = field(default_factory=_now)

    @property
    def coverage_ratio(self) -> float:
        if not self.entity_types_expected:
            return 1.0
        found = self.entity_types_expected & self.entity_types_discovered
        return len(found) / len(self.entity_types_expected)


@dataclass
class GovernanceReport:
    run_id: str
    module: str
    started_at: str = field(default_factory=_now)
    completed_at: Optional[str] = None
    policy_decisions: list = field(default_factory=list)
    violations: list = field(default_factory=list)
    coverage: Optional[CoverageReport] = None
    total_rate_limit_waits: int = 0
    total_wait_s: float = 0.0
```

`pipeline/governance/__init__.py`:
```python
"""pipeline.governance — cross-cutting adapter runtime governance (spec-0020)."""
```

**Step 4: Run tests**
```bash
python -m pytest tests/governance/test_models.py -v
```
Expected: all green.

**Step 5: Commit**
```bash
git add pipeline/governance/ tests/governance/
git commit -m "feat(spec-0020): governance models — PolicyDecision, CoverageReport, GovernanceReport"
```

---

### Task 2: `compliance.py` — contract validation

**Files:**
- Create: `pipeline/governance/compliance.py`
- Create: `tests/governance/test_compliance.py`

**Step 1: Write the failing tests**

`tests/governance/test_compliance.py`:
```python
import ast, importlib, inspect
import pytest
from pipeline.governance.compliance import (
    validate_adapter_contract,
    validate_discovery_adapter_contract,
    validate_enricher_contract,
    assert_provenance_chain,
    AdapterContractError,
    ProvenanceError,
)

# ── Minimal valid enrichment adapter ─────────────────────────────────────────
class GoodEnrAdapter:
    adapter_id = "good"; display_name = "Good"; requires = []; produces = []
    tier = "fast"; priority = 1; cost_usd = 0.0; timeout_s = 5.0
    retry_max = 0; rate_limit_rpm = 0; ttl_hours = 0
    min_confidence = 0.5; max_instances = 1; osint_risk = False
    secrets_required = []; gdpr_basis = "NONE"
    data_category = "PUBLIC_API"; tos_compliant = True; robots_txt_policy = "N/A"

class GoodDiscoveryAdapter:
    adapter_id = "good_disc"; display_name = "Good Discovery"
    requires = []; produces = []
    data_category = "PUBLIC_API"; tos_compliant = True; robots_txt_policy = "N/A"

class GoodEnricher:
    enricher_id = "good_enr"; adapter_id = "good"; min_confidence = 0.5

def test_valid_enrichment_adapter_passes():
    validate_adapter_contract(GoodEnrAdapter)  # must not raise

def test_valid_discovery_adapter_passes():
    validate_discovery_adapter_contract(GoodDiscoveryAdapter)  # must not raise

def test_valid_enricher_passes():
    validate_enricher_contract(GoodEnricher)  # must not raise

def test_missing_field_raises():
    class Bad:
        adapter_id = "bad"  # missing everything else
    with pytest.raises(AdapterContractError, match="display_name"):
        validate_adapter_contract(Bad)

def test_invalid_robots_policy_raises():
    class Bad(GoodEnrAdapter):
        robots_txt_policy = "MAYBE"
    with pytest.raises(AdapterContractError, match="robots_txt_policy"):
        validate_adapter_contract(Bad)

def test_invalid_data_category_raises():
    class Bad(GoodEnrAdapter):
        data_category = "PRIVATE"
    with pytest.raises(AdapterContractError, match="data_category"):
        validate_adapter_contract(Bad)

def test_cross_module_validation():
    # Same function must accept both adapter types
    validate_adapter_contract(GoodEnrAdapter)
    validate_discovery_adapter_contract(GoodDiscoveryAdapter)

def test_assert_provenance_chain_passes():
    class FakeEntity:
        attribution_chain = [{"adapter_id": "bio_parser"}]
    assert_provenance_chain(FakeEntity())  # must not raise

def test_assert_provenance_chain_empty_raises():
    class FakeEntity:
        attribution_chain = []
    with pytest.raises(ProvenanceError):
        assert_provenance_chain(FakeEntity())

def test_no_cross_imports():
    """AST-check that pipeline/governance imports nothing from other pipeline subpackages."""
    import pathlib
    gov_dir = pathlib.Path("pipeline/governance")
    forbidden = {"pipeline.enrichment", "pipeline.account_discovery",
                 "pipeline.compliance", "pipeline.graph"}
    for pyfile in gov_dir.rglob("*.py"):
        tree = ast.parse(pyfile.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = getattr(node, "module", "") or ""
                for names in getattr(node, "names", []):
                    full = f"{module}.{names.name}" if module else names.name
                for pkg in forbidden:
                    assert not module.startswith(pkg), \
                        f"{pyfile} imports from {pkg} (forbidden)"
```

**Step 2: Run to confirm failure**
```bash
python -m pytest tests/governance/test_compliance.py -v 2>&1 | head -15
```

**Step 3: Implement `pipeline/governance/compliance.py`**

```python
"""Adapter/enricher contract validation and provenance assertions (spec-0020 §6)."""
from __future__ import annotations

_VALID_ROBOTS = frozenset({"RESPECT", "N/A"})
_VALID_CATS   = frozenset({"PUBLIC_API", "PUBLIC_SCRAPE", "OSINT", "OPEN_DATA"})
_VALID_GDPR   = frozenset({"LEGITIMATE_INTERESTS", "CONSENT", "NONE"})
_VALID_TIERS  = frozenset({"seed", "fast", "medium", "slow"})


class AdapterContractError(RuntimeError):
    pass


class ProvenanceError(RuntimeError):
    pass


_ENRICHMENT_REQUIRED = (
    "adapter_id", "display_name", "requires", "produces",
    "tier", "priority", "cost_usd", "timeout_s", "retry_max",
    "rate_limit_rpm", "ttl_hours", "min_confidence", "max_instances",
    "osint_risk", "secrets_required", "gdpr_basis",
    "data_category", "tos_compliant", "robots_txt_policy",
)

_DISCOVERY_REQUIRED = (
    "adapter_id", "display_name", "requires", "produces",
    "data_category", "tos_compliant", "robots_txt_policy",
)

_ENRICHER_REQUIRED = ("enricher_id", "adapter_id", "min_confidence")


def _validate_attrs(obj, required: tuple, label: str) -> None:
    for attr in required:
        if not hasattr(obj, attr):
            raise AdapterContractError(f"{label}: missing required attribute '{attr}'")
    # Vocabulary checks
    if hasattr(obj, "robots_txt_policy") and obj.robots_txt_policy not in _VALID_ROBOTS:
        raise AdapterContractError(
            f"{label}: robots_txt_policy={obj.robots_txt_policy!r} not in {_VALID_ROBOTS}"
        )
    if hasattr(obj, "data_category") and obj.data_category not in _VALID_CATS:
        raise AdapterContractError(
            f"{label}: data_category={obj.data_category!r} not in {_VALID_CATS}"
        )
    if hasattr(obj, "gdpr_basis") and obj.gdpr_basis not in _VALID_GDPR:
        raise AdapterContractError(
            f"{label}: gdpr_basis={obj.gdpr_basis!r} not in {_VALID_GDPR}"
        )
    if hasattr(obj, "tier") and obj.tier not in _VALID_TIERS:
        raise AdapterContractError(
            f"{label}: tier={obj.tier!r} not in {_VALID_TIERS}"
        )


def validate_adapter_contract(adapter_cls) -> None:
    _validate_attrs(adapter_cls, _ENRICHMENT_REQUIRED, getattr(adapter_cls, "adapter_id", repr(adapter_cls)))


def validate_discovery_adapter_contract(adapter_cls) -> None:
    _validate_attrs(adapter_cls, _DISCOVERY_REQUIRED, getattr(adapter_cls, "adapter_id", repr(adapter_cls)))


def validate_enricher_contract(enricher_cls) -> None:
    _validate_attrs(enricher_cls, _ENRICHER_REQUIRED, getattr(enricher_cls, "enricher_id", repr(enricher_cls)))


def assert_provenance_chain(entity) -> None:
    chain = getattr(entity, "attribution_chain", None)
    if not chain:
        raise ProvenanceError(
            f"Entity {getattr(entity, 'account_id', repr(entity))!r} has empty attribution_chain"
        )
```

**Step 4: Run tests**
```bash
python -m pytest tests/governance/test_compliance.py -v
```

**Step 5: Commit**
```bash
git add pipeline/governance/compliance.py tests/governance/test_compliance.py
git commit -m "feat(spec-0020): contract validation — validate_adapter_contract, assert_provenance_chain"
```

---

### Task 3: `policies.py` — RobotsPolicy

**Files:**
- Create: `pipeline/governance/policies.py` (partial — RobotsPolicy only)
- Create: `tests/governance/test_robots_policy.py`

**Step 1: Write the failing tests**

`tests/governance/test_robots_policy.py`:
```python
import pytest
from unittest.mock import patch, MagicMock
from pipeline.governance.policies import RobotsPolicy
from pipeline.governance.models import PolicyDecision


class _Adapter:
    robots_txt_policy = "RESPECT"
    adapter_id = "test_adapter"

class _NAAdapter:
    robots_txt_policy = "N/A"
    adapter_id = "api_adapter"

ROBOTS_ALLOW = "User-agent: *\nAllow: /"
ROBOTS_DENY  = "User-agent: *\nDisallow: /private"


def _make_policy(robots_txt_text: str) -> RobotsPolicy:
    policy = RobotsPolicy()
    with patch.object(policy, "_fetch_robots_txt", return_value=robots_txt_text):
        policy.check("https://example.com/page", _Adapter())
    return policy


def test_na_policy_skips_check():
    policy = RobotsPolicy()
    decision = policy.check("https://example.com", _NAAdapter())
    assert decision.allowed is True
    assert "N/A" in decision.reason


def test_allowed_path():
    policy = RobotsPolicy()
    with patch.object(policy, "_fetch_robots_txt", return_value=ROBOTS_ALLOW):
        decision = policy.check("https://example.com/page", _Adapter())
    assert decision.allowed is True


def test_disallowed_path():
    policy = RobotsPolicy()
    with patch.object(policy, "_fetch_robots_txt", return_value=ROBOTS_DENY):
        decision = policy.check("https://example.com/private/data", _Adapter())
    assert decision.allowed is False


def test_robots_fetch_failure_is_permissive():
    policy = RobotsPolicy()
    with patch.object(policy, "_fetch_robots_txt", side_effect=Exception("timeout")):
        decision = policy.check("https://example.com/page", _Adapter())
    assert decision.allowed is True
    assert "unreachable" in decision.reason.lower()


def test_robots_txt_cached_second_call():
    policy = RobotsPolicy()
    with patch.object(policy, "_fetch_robots_txt", return_value=ROBOTS_ALLOW) as mock_fetch:
        policy.check("https://example.com/a", _Adapter())
        policy.check("https://example.com/b", _Adapter())
    assert mock_fetch.call_count == 1  # cached after first call
```

**Step 2: Run to confirm failure**
```bash
python -m pytest tests/governance/test_robots_policy.py -v 2>&1 | head -15
```

**Step 3: Implement RobotsPolicy in `pipeline/governance/policies.py`**

```python
"""Runtime policies: RobotsPolicy and RateLimiter (spec-0020 §5)."""
from __future__ import annotations

import logging
import threading
import time
import urllib.parse
import urllib.robotparser
import urllib.request
from typing import Optional

from pipeline.governance.models import PolicyDecision

logger = logging.getLogger(__name__)

_USER_AGENT = "profile-analyst/1.0"
_ROBOTS_TTL_S = 3600


class RobotsPolicy:
    """Checks robots.txt before fetching. Thread-safe. In-process cache, TTL=1h."""

    def __init__(self) -> None:
        self._cache: dict[str, tuple[urllib.robotparser.RobotFileParser, float]] = {}
        self._lock = threading.Lock()

    def check(self, url: str, adapter) -> PolicyDecision:
        if adapter.robots_txt_policy == "N/A":
            return PolicyDecision(
                allowed=True, reason="robots_txt_policy=N/A",
                checked_url=url, policy_type="robots",
            )
        try:
            rp = self._get_parser(url)
            allowed = rp.can_fetch(_USER_AGENT, url)
            return PolicyDecision(
                allowed=allowed,
                reason="robots.txt permits" if allowed else "robots.txt disallows path",
                checked_url=url, policy_type="robots",
            )
        except Exception as exc:
            logger.warning("robots.txt unreachable for %s: %s", url, exc)
            return PolicyDecision(
                allowed=True, reason=f"robots.txt unreachable — permissive fallback ({exc})",
                checked_url=url, policy_type="robots",
            )

    def _get_parser(self, url: str) -> urllib.robotparser.RobotFileParser:
        parsed = urllib.parse.urlparse(url)
        domain = f"{parsed.scheme}://{parsed.netloc}"
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(domain)
            if cached and (now - cached[1]) < _ROBOTS_TTL_S:
                return cached[0]
        robots_url = f"{domain}/robots.txt"
        raw = self._fetch_robots_txt(robots_url)
        rp = urllib.robotparser.RobotFileParser()
        rp.parse(raw.splitlines())
        with self._lock:
            self._cache[domain] = (rp, time.monotonic())
        return rp

    def _fetch_robots_txt(self, robots_url: str) -> str:
        with urllib.request.urlopen(robots_url, timeout=5) as resp:
            return resp.read().decode("utf-8", errors="replace")
```

**Step 4: Run tests**
```bash
python -m pytest tests/governance/test_robots_policy.py -v
```

**Step 5: Commit**
```bash
git add pipeline/governance/policies.py tests/governance/test_robots_policy.py
git commit -m "feat(spec-0020): RobotsPolicy — robots.txt checker with TTL cache"
```

---

### Task 4: `policies.py` — RateLimiter

**Files:**
- Modify: `pipeline/governance/policies.py` (append RateLimiter class)
- Create: `tests/governance/test_rate_limiter.py`

**Step 1: Write the failing tests**

`tests/governance/test_rate_limiter.py`:
```python
import time
import pytest
from unittest.mock import patch
from pipeline.governance.policies import RateLimiter


class _Adapter:
    adapter_id = "test"
    rate_limit_rpm = 60   # 1 req/s
    timeout_s = 5.0


class _FreeAdapter:
    adapter_id = "free"
    rate_limit_rpm = 0
    timeout_s = 5.0


def test_no_rate_limit_returns_immediately():
    rl = RateLimiter()
    t0 = time.monotonic()
    token = rl.acquire(_FreeAdapter())
    elapsed = time.monotonic() - t0
    assert elapsed < 0.05
    assert token.wait_s == 0.0


def test_token_bucket_blocks_on_second_call():
    rl = RateLimiter()
    fake_time = [0.0]

    def _mono():
        return fake_time[0]

    with patch("pipeline.governance.policies.time.monotonic", side_effect=_mono):
        rl.acquire(_Adapter())          # first call — no wait
        fake_time[0] = 0.3              # 300 ms later — token not ready (need 1000ms)
        token = rl.acquire(_Adapter())
    assert token.wait_s > 0


def test_rate_limit_exceeded_raises():
    class SlowAdapter:
        adapter_id = "slow"; rate_limit_rpm = 60; timeout_s = 0.001
    rl = RateLimiter()
    rl.acquire(SlowAdapter())  # consume token
    with pytest.raises(Exception, match="RateLimitExceeded"):
        rl.acquire(SlowAdapter())  # next token in 1s; timeout is 1ms
```

**Step 2: Run to confirm failure**
```bash
python -m pytest tests/governance/test_rate_limiter.py -v 2>&1 | head -15
```

**Step 3: Append RateLimiter to `pipeline/governance/policies.py`**

```python
class RateLimitExceeded(RuntimeError):
    pass


from pipeline.governance.models import PolicyDecision  # already imported above


class RateLimiter:
    """Token-bucket rate limiter. Thread-safe. One bucket per adapter_id."""

    def __init__(self) -> None:
        self._buckets: dict[str, float] = {}   # adapter_id → timestamp of last token refill
        self._lock = threading.Lock()

    def acquire(self, adapter) -> "RateLimitToken":
        rpm = adapter.rate_limit_rpm
        if rpm == 0:
            return RateLimitToken(adapter_id=adapter.adapter_id, wait_s=0.0)

        interval_s = 60.0 / rpm
        now = time.monotonic()

        with self._lock:
            last = self._buckets.get(adapter.adapter_id, 0.0)
            next_token_at = last + interval_s
            wait_s = max(0.0, next_token_at - now)

            if wait_s > adapter.timeout_s:
                raise RateLimitExceeded(
                    f"RateLimitExceeded: {adapter.adapter_id} next token in {wait_s:.2f}s "
                    f"but timeout_s={adapter.timeout_s}"
                )
            self._buckets[adapter.adapter_id] = now + wait_s

        if wait_s > 0:
            time.sleep(wait_s)

        return RateLimitToken(adapter_id=adapter.adapter_id, wait_s=wait_s)


from dataclasses import dataclass as _dc


@_dc
class RateLimitToken:
    adapter_id: str
    wait_s: float
```

**Step 4: Run tests**
```bash
python -m pytest tests/governance/test_rate_limiter.py -v
```

**Step 5: Commit**
```bash
git add pipeline/governance/policies.py tests/governance/test_rate_limiter.py
git commit -m "feat(spec-0020): RateLimiter — token-bucket per adapter, thread-safe"
```

---

### Task 5: `metrics.py` — coverage and confidence

**Files:**
- Create: `pipeline/governance/metrics.py`
- Create: `tests/governance/test_metrics.py`

**Step 1: Write the failing tests**

`tests/governance/test_metrics.py`:
```python
import logging
import pytest
from pipeline.governance.metrics import normalize_confidence, compute_coverage
from pipeline.governance.models import CoverageReport


class FakeEntity:
    def __init__(self, typ):
        self.type = typ


class FakePool:
    def __init__(self, types):
        self._entities = [FakeEntity(t) for t in types]
    def all(self):
        return self._entities


class FakeAdapter:
    def __init__(self, aid, produces):
        self.adapter_id = aid
        self.produces = produces


def test_confidence_within_range():
    assert normalize_confidence(0.8) == 0.8

def test_confidence_clamped_high(caplog):
    with caplog.at_level(logging.WARNING):
        v = normalize_confidence(1.5)
    assert v == 1.0
    assert "clamp" in caplog.text.lower()

def test_confidence_clamped_low(caplog):
    with caplog.at_level(logging.WARNING):
        v = normalize_confidence(-0.1)
    assert v == 0.0
    assert "clamp" in caplog.text.lower()

def test_compute_coverage_empty_run():
    pool = FakePool([])
    r = compute_coverage("r1", "test", pool, adapters=[], ran_set={})
    assert isinstance(r, CoverageReport)
    assert r.coverage_ratio == 1.0
    assert r.adapters_registered == 0

def test_compute_coverage_partial():
    pool = FakePool(["youtube_handle"])
    adapters = [
        FakeAdapter("a", ["youtube_handle"]),
        FakeAdapter("b", ["github_handle"]),
    ]
    ran_set = {"a": "ran", "b": "skipped"}
    r = compute_coverage("r1", "test", pool, adapters, ran_set)
    assert r.coverage_ratio == 0.5
    assert r.adapters_run == 1
    assert r.adapters_skipped == 1
    assert r.per_adapter_coverage["a"] == 1.0
    assert r.per_adapter_coverage["b"] == 0.0
```

**Step 2: Run to confirm failure**
```bash
python -m pytest tests/governance/test_metrics.py -v 2>&1 | head -15
```

**Step 3: Implement `pipeline/governance/metrics.py`**

```python
"""Coverage metrics and confidence normalization (spec-0020 §7)."""
from __future__ import annotations

import logging
from pipeline.governance.models import CoverageReport

logger = logging.getLogger(__name__)


def normalize_confidence(value: float, *, warn_if_clamped: bool = True) -> float:
    if 0.0 <= value <= 1.0:
        return value
    clamped = max(0.0, min(1.0, value))
    if warn_if_clamped:
        logger.warning("confidence clamped: %.4f → %.4f", value, clamped)
    return clamped


def compute_coverage(
    run_id: str,
    module: str,
    pool,
    adapters: list,
    ran_set: dict,   # adapter_id → "ran" | "skipped" | "failed"
) -> CoverageReport:
    discovered = {e.type for e in pool.all()}
    expected: set[str] = set()
    per_adapter: dict[str, float] = {}

    adapters_run = adapters_skipped = adapters_failed = 0

    for adapter in adapters:
        produces = set(adapter.produces)
        expected |= produces
        status = ran_set.get(adapter.adapter_id, "skipped")
        if status == "ran":
            adapters_run += 1
            if produces:
                per_adapter[adapter.adapter_id] = len(produces & discovered) / len(produces)
            else:
                per_adapter[adapter.adapter_id] = 1.0
        elif status == "failed":
            adapters_failed += 1
            per_adapter[adapter.adapter_id] = 0.0
        else:
            adapters_skipped += 1
            per_adapter[adapter.adapter_id] = 0.0

    return CoverageReport(
        run_id=run_id,
        module=module,
        adapters_registered=len(adapters),
        adapters_run=adapters_run,
        adapters_skipped=adapters_skipped,
        adapters_failed=adapters_failed,
        entity_types_expected=expected,
        entity_types_discovered=discovered,
        per_adapter_coverage=per_adapter,
    )
```

**Step 4: Run tests**
```bash
python -m pytest tests/governance/test_metrics.py -v
```

**Step 5: Commit**
```bash
git add pipeline/governance/metrics.py tests/governance/test_metrics.py
git commit -m "feat(spec-0020): metrics — normalize_confidence, compute_coverage"
```

---

### Task 6: Wire `pipeline/governance/__init__.py` and run full governance suite

**Files:**
- Modify: `pipeline/governance/__init__.py`

**Step 1: Write the public surface**

```python
"""pipeline.governance — cross-cutting adapter runtime governance (spec-0020)."""
from pipeline.governance.models import (
    PolicyDecision, ContractViolation, CoverageReport, GovernanceReport,
)
from pipeline.governance.compliance import (
    validate_adapter_contract,
    validate_discovery_adapter_contract,
    validate_enricher_contract,
    assert_provenance_chain,
    AdapterContractError,
    ProvenanceError,
)
from pipeline.governance.policies import RobotsPolicy, RateLimiter, RateLimitExceeded
from pipeline.governance.metrics import normalize_confidence, compute_coverage

__all__ = [
    "PolicyDecision", "ContractViolation", "CoverageReport", "GovernanceReport",
    "validate_adapter_contract", "validate_discovery_adapter_contract",
    "validate_enricher_contract", "assert_provenance_chain",
    "AdapterContractError", "ProvenanceError",
    "RobotsPolicy", "RateLimiter", "RateLimitExceeded",
    "normalize_confidence", "compute_coverage",
]
```

**Step 2: Run full governance suite**
```bash
python -m pytest tests/governance/ -v
```
Expected: all green.

**Step 3: Commit**
```bash
git add pipeline/governance/__init__.py
git commit -m "feat(spec-0020): wire governance public API — spec-0020 complete"
```

---

## PHASE 2 — Spec 0018: Account Discovery

### Task 7: `models.py` + `contracts.py` — discovery data types and adapter ABC

**Files:**
- Create: `pipeline/account_discovery/__init__.py`
- Create: `pipeline/account_discovery/models.py`
- Create: `pipeline/account_discovery/contracts.py`
- Create: `tests/account_discovery/__init__.py`
- Create: `tests/account_discovery/conftest.py`
- Create: `tests/account_discovery/test_contracts.py`

**Step 1: Write the failing tests**

`tests/account_discovery/test_contracts.py`:
```python
import pytest
from pipeline.account_discovery.contracts import (
    DiscoveryAdapter, DiscoveryContractError, ENTITY_TYPES,
)
from pipeline.account_discovery.models import DiscoveredAccount, AttributionStep


def test_discovered_account_requires_attribution():
    acc = DiscoveredAccount(
        account_id="a1", platform="youtube", handle="creator",
        profile_url="https://youtube.com/@creator",
        confidence=0.9, method="bio_link", source_adapter_id="bio_parser",
        attribution_chain=[
            AttributionStep(adapter_id="bio_parser", from_entity_type="instagram_handle",
                            from_entity_value="creator", relationship="bio_url")
        ],
    )
    assert acc.platform == "youtube"
    assert len(acc.attribution_chain) == 1


def test_adapter_missing_field_raises():
    with pytest.raises(Exception):
        class BadAdapter(DiscoveryAdapter):
            # missing requires, produces, etc.
            adapter_id = "bad"
            def run(self, seed_entities, config): return []
        BadAdapter()   # contract check on instantiation or registration


def test_entity_types_non_empty():
    assert "instagram_handle" in ENTITY_TYPES
    assert "url" in ENTITY_TYPES
    assert "youtube_handle" in ENTITY_TYPES


def test_no_enrichment_import():
    import ast, pathlib
    disc_dir = pathlib.Path("pipeline/account_discovery")
    forbidden = {"pipeline.enrichment", "pipeline.graph"}
    for pyfile in disc_dir.rglob("*.py"):
        tree = ast.parse(pyfile.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = getattr(node, "module", "") or ""
                for pkg in forbidden:
                    assert not module.startswith(pkg), f"{pyfile} imports {pkg}"
```

**Step 2: Run to confirm failure**
```bash
python -m pytest tests/account_discovery/test_contracts.py -v 2>&1 | head -15
```

**Step 3: Implement models and contracts**

`pipeline/account_discovery/models.py`:
```python
"""Discovery data model (spec-0018 §4)."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class AttributionStep:
    adapter_id: str
    from_entity_type: str
    from_entity_value: str
    relationship: str


@dataclass
class DiscoveredAccount:
    account_id: str
    platform: str
    handle: str
    profile_url: str
    confidence: float
    method: str
    source_adapter_id: str
    attribution_chain: list[AttributionStep]
    discovered_at: str = field(default_factory=_now)
    verified: bool = False


@dataclass
class AccountRelationship:
    from_account_id: str
    to_account_id: str
    relationship_type: str
    confidence: float
    source_adapter_id: str


@dataclass
class DiscoveryStats:
    adapters_run: int = 0
    accounts_found: int = 0
    relationships_found: int = 0
    depth_reached: int = 0
    elapsed_s: float = 0.0


@dataclass
class DiscoveryManifest:
    seed_handle: str
    seed_platform: str
    run_id: str
    started_at: str
    completed_at: Optional[str] = None
    discovered_accounts: list[DiscoveredAccount] = field(default_factory=list)
    relationships: list[AccountRelationship] = field(default_factory=list)
    stats: DiscoveryStats = field(default_factory=DiscoveryStats)
    limit_reached: bool = False
    governance: Optional[dict] = None


@dataclass
class SeedAccount:
    handle: str
    platform: str
    bio_text: str = ""
    bio_urls: list[str] = field(default_factory=list)
    discovery_run_id: str = ""
```

`pipeline/account_discovery/contracts.py`:
```python
"""DiscoveryAdapter ABC and entity type registry (spec-0018 §5)."""
from __future__ import annotations
from abc import ABC, abstractmethod

ENTITY_TYPES = frozenset({
    "instagram_handle", "url", "youtube_handle", "github_handle",
    "spotify_handle", "itunes_artist_id", "twitch_handle",
    "reddit_handle", "substack_url", "linkedin_url", "tiktok_handle",
    "platform_handle", "email",
})

_VALID_ROBOTS = frozenset({"RESPECT", "N/A"})
_VALID_CATS   = frozenset({"PUBLIC_API", "PUBLIC_SCRAPE", "OSINT", "OPEN_DATA"})
_REQUIRED = ("adapter_id", "display_name", "requires", "produces",
             "data_category", "tos_compliant", "robots_txt_policy")


class DiscoveryContractError(RuntimeError):
    pass


class DiscoveryAdapter(ABC):
    adapter_id: str
    display_name: str
    requires: list[str]
    produces: list[str]
    data_category: str
    tos_compliant: bool
    robots_txt_policy: str

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if ABC in cls.__mro__[1:]:
            return  # skip the ABC itself
        for attr in _REQUIRED:
            if not hasattr(cls, attr):
                raise DiscoveryContractError(f"{cls.__name__}: missing '{attr}'")
        if cls.robots_txt_policy not in _VALID_ROBOTS:
            raise DiscoveryContractError(
                f"{cls.__name__}: robots_txt_policy={cls.robots_txt_policy!r} not in {_VALID_ROBOTS}"
            )
        if cls.data_category not in _VALID_CATS:
            raise DiscoveryContractError(
                f"{cls.__name__}: data_category={cls.data_category!r} not in {_VALID_CATS}"
            )

    @abstractmethod
    def run(self, seed_entities: dict[str, list[str]], config: dict) -> list:
        ...
```

**Step 4: Run tests**
```bash
python -m pytest tests/account_discovery/test_contracts.py -v
```

**Step 5: Commit**
```bash
git add pipeline/account_discovery/ tests/account_discovery/
git commit -m "feat(spec-0018): discovery models and adapter contract"
```

---

### Task 8: `pool.py` — AccountPool with dedup and attribution merge

**Files:**
- Create: `pipeline/account_discovery/pool.py`
- Create: `tests/account_discovery/test_pool.py`

**Step 1: Write failing tests**

`tests/account_discovery/test_pool.py`:
```python
import pytest
from pipeline.account_discovery.pool import AccountPool
from pipeline.account_discovery.models import DiscoveredAccount, AttributionStep


def _acc(platform, handle, confidence, adapter_id="a"):
    return DiscoveredAccount(
        account_id=f"{platform}:{handle}",
        platform=platform, handle=handle,
        profile_url=f"https://{platform}.com/@{handle}",
        confidence=confidence, method="test", source_adapter_id=adapter_id,
        attribution_chain=[AttributionStep(adapter_id, "url", "http://x.com", "link")],
    )


def test_add_new_account():
    pool = AccountPool()
    added = pool.add(_acc("youtube", "creator", 0.9))
    assert added is True
    assert len(pool.accounts()) == 1


def test_dedup_lower_confidence_ignored():
    pool = AccountPool()
    pool.add(_acc("youtube", "creator", 0.9, "a"))
    added = pool.add(_acc("youtube", "creator", 0.7, "b"))
    assert added is False
    assert pool.accounts()[0].confidence == 0.9


def test_dedup_higher_confidence_wins():
    pool = AccountPool()
    pool.add(_acc("youtube", "creator", 0.7, "a"))
    pool.add(_acc("youtube", "creator", 0.9, "b"))
    assert pool.accounts()[0].confidence == 0.9


def test_dedup_merge_attribution_chain():
    pool = AccountPool()
    acc_a = _acc("youtube", "creator", 0.7, "bio_parser")
    acc_b = _acc("youtube", "creator", 0.9, "link_expander")
    pool.add(acc_a)
    pool.add(acc_b)
    merged = pool.accounts()[0]
    adapter_ids = {s.adapter_id for s in merged.attribution_chain}
    assert "bio_parser" in adapter_ids
    assert "link_expander" in adapter_ids


def test_delta_tracking():
    pool = AccountPool()
    pool.add(_acc("youtube", "creator", 0.9))
    delta = pool.flush_delta()
    assert len(delta) == 1
    assert pool.flush_delta() == []  # delta is consumed
```

**Step 2: Run to confirm failure**
```bash
python -m pytest tests/account_discovery/test_pool.py -v 2>&1 | head -15
```

**Step 3: Implement `pipeline/account_discovery/pool.py`**

```python
"""AccountPool — dedup keyed on (platform, handle) with attribution merge (spec-0018 §6)."""
from __future__ import annotations
import threading
from pipeline.account_discovery.models import DiscoveredAccount


class AccountPool:
    def __init__(self):
        self._store: dict[tuple[str, str], DiscoveredAccount] = {}
        self._delta: list[DiscoveredAccount] = []
        self._lock = threading.Lock()

    def add(self, account: DiscoveredAccount) -> bool:
        key = (account.platform, account.handle)
        with self._lock:
            existing = self._store.get(key)
            if existing is None:
                self._store[key] = account
                self._delta.append(account)
                return True
            if account.confidence > existing.confidence:
                # Merge attribution chains
                merged_chain = list({
                    (s.adapter_id, s.from_entity_value): s
                    for s in (existing.attribution_chain + account.attribution_chain)
                }.values())
                import dataclasses
                merged = dataclasses.replace(
                    account, attribution_chain=merged_chain
                )
                self._store[key] = merged
                self._delta.append(merged)
                return True
            else:
                # Lower confidence: just append attribution steps
                existing.attribution_chain.extend(account.attribution_chain)
            return False

    def accounts(self) -> list[DiscoveredAccount]:
        with self._lock:
            return list(self._store.values())

    def flush_delta(self) -> list[DiscoveredAccount]:
        with self._lock:
            delta, self._delta = self._delta, []
            return delta

    def __len__(self) -> int:
        return len(self._store)
```

**Step 4: Run tests**
```bash
python -m pytest tests/account_discovery/test_pool.py -v
```

**Step 5: Commit**
```bash
git add pipeline/account_discovery/pool.py tests/account_discovery/test_pool.py
git commit -m "feat(spec-0018): AccountPool — dedup on (platform,handle), attribution merge"
```

---

### Task 9: `bio_parser.py` adapter — Instagram bio → URLs + handles

**Files:**
- Create: `pipeline/account_discovery/adapters/__init__.py`
- Create: `pipeline/account_discovery/adapters/bio_parser.py`
- Create: `tests/account_discovery/test_adapters/__init__.py`
- Create: `tests/account_discovery/test_adapters/test_bio_parser.py`

**Step 1: Write failing tests**

`tests/account_discovery/test_adapters/test_bio_parser.py`:
```python
import pytest
from pipeline.account_discovery.adapters.bio_parser import BioParsing


def _seed(bio_text="", bio_urls=None):
    return {
        "instagram_handle": ["creator123"],
        "bio_text": [bio_text],
        "url": bio_urls or [],
    }


def test_extracts_url_from_bio():
    adapter = BioParsing()
    results = adapter.run(_seed(bio_text="Check my work at https://linktr.ee/creator123"), {})
    urls = [r.profile_url for r in results]
    assert any("linktr.ee" in u for u in urls)


def test_extracts_youtube_handle():
    adapter = BioParsing()
    results = adapter.run(_seed(bio_text="YouTube: @Creator123Official"), {})
    platforms = [r.platform for r in results]
    assert "youtube" in platforms


def test_empty_bio_returns_empty():
    adapter = BioParsing()
    results = adapter.run(_seed(bio_text=""), {})
    assert results == []


def test_attribution_chain_non_empty():
    adapter = BioParsing()
    results = adapter.run(_seed(bio_text="https://youtube.com/@Creator"), {})
    for r in results:
        assert len(r.attribution_chain) > 0


def test_adapter_contract_valid():
    from pipeline.governance import validate_discovery_adapter_contract
    validate_discovery_adapter_contract(BioParsing)  # must not raise
```

**Step 2: Run to confirm failure**
```bash
python -m pytest tests/account_discovery/test_adapters/test_bio_parser.py -v 2>&1 | head -15
```

**Step 3: Implement `pipeline/account_discovery/adapters/bio_parser.py`**

```python
"""BioParsing adapter — extracts URLs and platform handles from Instagram bio (spec-0018)."""
from __future__ import annotations
import re, uuid
from pipeline.account_discovery.contracts import DiscoveryAdapter
from pipeline.account_discovery.models import DiscoveredAccount, AttributionStep

_URL_RE = re.compile(r"https?://[^\s\"'>]+", re.I)
_PLATFORM_PATTERNS = [
    ("youtube",   re.compile(r"(?:youtube\.com/@?|youtu\.be/)([A-Za-z0-9_\-]+)", re.I)),
    ("tiktok",    re.compile(r"tiktok\.com/@([A-Za-z0-9_.]+)", re.I)),
    ("twitter",   re.compile(r"twitter\.com/([A-Za-z0-9_]+)", re.I)),
    ("instagram", re.compile(r"instagram\.com/([A-Za-z0-9_.]+)", re.I)),
    ("github",    re.compile(r"github\.com/([A-Za-z0-9_\-]+)", re.I)),
    ("spotify",   re.compile(r"open\.spotify\.com/artist/([A-Za-z0-9]+)", re.I)),
    ("twitch",    re.compile(r"twitch\.tv/([A-Za-z0-9_]+)", re.I)),
    ("substack",  re.compile(r"([A-Za-z0-9_\-]+)\.substack\.com", re.I)),
    ("linkedin",  re.compile(r"linkedin\.com/in/([A-Za-z0-9_\-]+)", re.I)),
    ("youtube",   re.compile(r"@([A-Za-z0-9_]+)\s*(?:YouTube|YT)", re.I)),
]


class BioParsing(DiscoveryAdapter):
    adapter_id       = "bio_parser"
    display_name     = "Instagram Bio Parser"
    requires         = ["instagram_handle", "bio_text"]
    produces         = ["url", "platform_handle"]
    data_category    = "PUBLIC_API"
    tos_compliant    = True
    robots_txt_policy = "N/A"

    def run(self, seed_entities: dict, config: dict) -> list[DiscoveredAccount]:
        bio_texts = seed_entities.get("bio_text", [])
        handles   = seed_entities.get("instagram_handle", ["unknown"])
        seed_handle = handles[0] if handles else "unknown"

        results = []
        for bio_text in bio_texts:
            results.extend(self._parse(bio_text, seed_handle))
        return results

    def _parse(self, bio_text: str, seed_handle: str) -> list[DiscoveredAccount]:
        attribution = AttributionStep(
            adapter_id="bio_parser",
            from_entity_type="instagram_handle",
            from_entity_value=seed_handle,
            relationship="bio_text",
        )
        found = []
        # Extract via platform-specific URL patterns
        for platform, pattern in _PLATFORM_PATTERNS:
            for match in pattern.finditer(bio_text):
                handle = match.group(1)
                url = match.group(0)
                found.append(DiscoveredAccount(
                    account_id=str(uuid.uuid4()),
                    platform=platform, handle=handle,
                    profile_url=url, confidence=0.85,
                    method="bio_pattern_match", source_adapter_id="bio_parser",
                    attribution_chain=[attribution],
                ))
        # Bare URLs
        for url in _URL_RE.findall(bio_text):
            if not any(url in acc.profile_url for acc in found):
                found.append(DiscoveredAccount(
                    account_id=str(uuid.uuid4()),
                    platform="url", handle=url,
                    profile_url=url, confidence=0.6,
                    method="bio_url_extract", source_adapter_id="bio_parser",
                    attribution_chain=[attribution],
                ))
        return found
```

**Step 4: Run tests**
```bash
python -m pytest tests/account_discovery/test_adapters/test_bio_parser.py -v
```

**Step 5: Commit**
```bash
git add pipeline/account_discovery/adapters/ tests/account_discovery/test_adapters/
git commit -m "feat(spec-0018): BioParsing adapter — bio text → URLs and platform handles"
```

---

### Task 10: `engine.py` + `orchestrator.py` — fixed-point loop and manifest writer

**Files:**
- Create: `pipeline/account_discovery/scheduler.py`
- Create: `pipeline/account_discovery/engine.py`
- Create: `pipeline/account_discovery/orchestrator.py`
- Create: `tests/account_discovery/test_engine.py`

**Step 1: Write failing tests**

`tests/account_discovery/test_engine.py`:
```python
import pytest
from pipeline.account_discovery.engine import run_discovery
from pipeline.account_discovery.pool import AccountPool
from pipeline.account_discovery.models import SeedAccount, DiscoveredAccount, AttributionStep


def _acc(platform, handle, confidence=0.9):
    return DiscoveredAccount(
        account_id=f"{platform}:{handle}", platform=platform, handle=handle,
        profile_url=f"https://{platform}.com/@{handle}", confidence=confidence,
        method="test", source_adapter_id="fake",
        attribution_chain=[AttributionStep("fake","instagram_handle","seed","bio_url")],
    )


class FakeBioAdapter:
    adapter_id = "bio_parser"; display_name = "Fake Bio"
    requires = ["instagram_handle", "bio_text"]; produces = ["platform_handle"]
    data_category = "PUBLIC_API"; tos_compliant = True; robots_txt_policy = "N/A"

    def run(self, seed_entities, config):
        return [_acc("youtube", "creator_yt")]


class FakeExpanderAdapter:
    adapter_id = "link_expander"; display_name = "Fake Expander"
    requires = ["url"]; produces = ["platform_handle"]
    data_category = "PUBLIC_SCRAPE"; tos_compliant = True; robots_txt_policy = "RESPECT"

    def run(self, seed_entities, config):
        return [_acc("spotify", "creator_spotify")]


def test_engine_runs_bio_adapter():
    seed = SeedAccount(handle="creator", platform="instagram",
                       bio_text="check https://linktr.ee/creator", bio_urls=["https://linktr.ee/creator"])
    pool = AccountPool()
    ran = run_discovery(seed, [FakeBioAdapter()], pool, config={"max_depth": 2, "max_adapters": 10})
    assert any(a.platform == "youtube" for a in pool.accounts())


def test_depth_limit_sets_flag():
    seed = SeedAccount(handle="creator", platform="instagram", bio_text="")
    pool = AccountPool()
    result = run_discovery(seed, [FakeBioAdapter()], pool,
                           config={"max_depth": 0, "max_adapters": 1})
    assert result["limit_reached"] is True


def test_standalone_execution(tmp_path):
    """Discovery runs without any pipeline stage artifacts."""
    from pipeline.account_discovery.orchestrator import discover
    manifest = discover(
        handle="testcreator",
        project_dir=tmp_path,
        adapters=[FakeBioAdapter()],
        config={"max_depth": 2, "max_adapters": 5, "max_accounts": 50},
    )
    assert manifest.seed_handle == "testcreator"
    assert (tmp_path / "00-discovery.json").exists()
```

**Step 2: Run to confirm failure**
```bash
python -m pytest tests/account_discovery/test_engine.py -v 2>&1 | head -15
```

**Step 3: Implement scheduler, engine, orchestrator**

`pipeline/account_discovery/scheduler.py`:
```python
"""next_runnable — dependency resolution for discovery adapters (spec-0018 §6)."""
from __future__ import annotations

def next_runnable(pool, adapters, ran_set):
    """Return adapters that have all requires[] satisfied and haven't run yet."""
    pool_types = {a.platform for a in pool.accounts()} | {"instagram_handle", "bio_text", "url"}
    result = []
    for adapter in adapters:
        if adapter.adapter_id in ran_set:
            continue
        if all(req in pool_types for req in adapter.requires):
            result.append(adapter)
    return result
```

`pipeline/account_discovery/engine.py`:
```python
"""Fixed-point discovery loop (spec-0018 §6)."""
from __future__ import annotations
import logging
from pipeline.account_discovery.pool import AccountPool
from pipeline.account_discovery.scheduler import next_runnable
from pipeline.account_discovery.models import SeedAccount

logger = logging.getLogger(__name__)


def run_discovery(seed: SeedAccount, adapters, pool: AccountPool, config: dict) -> dict:
    max_depth   = config.get("max_depth", 2)
    max_adapters = config.get("max_adapters", 10)
    max_accounts = config.get("max_accounts", 50)

    seed_entities = {
        "instagram_handle": [seed.handle],
        "bio_text": [seed.bio_text],
        "url": seed.bio_urls,
    }

    ran_set = {}
    limit_reached = False
    depth = 0

    if depth >= max_depth or len(ran_set) >= max_adapters:
        return {"limit_reached": True, "ran_set": ran_set}

    while True:
        runnable = next_runnable(pool, adapters, ran_set)
        if not runnable:
            break
        for adapter in runnable:
            if len(ran_set) >= max_adapters or len(pool) >= max_accounts:
                limit_reached = True
                break
            try:
                accounts = adapter.run(seed_entities, config)
                for acc in accounts:
                    pool.add(acc)
                ran_set[adapter.adapter_id] = "ran"
            except Exception as exc:
                logger.warning("adapter %s failed: %s", adapter.adapter_id, exc)
                ran_set[adapter.adapter_id] = "failed"
        else:
            depth += 1
            continue
        limit_reached = True
        break

    return {"limit_reached": limit_reached, "ran_set": ran_set, "depth": depth}
```

`pipeline/account_discovery/orchestrator.py`:
```python
"""Entry point — seeds pool, runs engine, writes 00-discovery.json (spec-0018)."""
from __future__ import annotations
import dataclasses, json, os, time, uuid
from datetime import datetime, timezone
from pathlib import Path

from pipeline.account_discovery.engine import run_discovery
from pipeline.account_discovery.pool import AccountPool
from pipeline.account_discovery.models import (
    SeedAccount, DiscoveryManifest, DiscoveryStats,
)


def discover(
    handle: str,
    project_dir: Path,
    adapters: list,
    config: dict,
    bio_text: str = "",
    bio_urls: list[str] | None = None,
) -> DiscoveryManifest:
    run_id = f"disc-{uuid.uuid4().hex[:8]}"
    started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    t0 = time.monotonic()

    seed = SeedAccount(
        handle=handle, platform="instagram",
        bio_text=bio_text, bio_urls=bio_urls or [],
        discovery_run_id=run_id,
    )
    pool = AccountPool()
    engine_result = run_discovery(seed, adapters, pool, config)

    accounts = pool.accounts()
    elapsed = time.monotonic() - t0

    manifest = DiscoveryManifest(
        seed_handle=handle, seed_platform="instagram",
        run_id=run_id, started_at=started_at,
        completed_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        discovered_accounts=accounts, relationships=[],
        stats=DiscoveryStats(
            adapters_run=sum(1 for v in engine_result["ran_set"].values() if v == "ran"),
            accounts_found=len(accounts),
            depth_reached=engine_result.get("depth", 0),
            elapsed_s=round(elapsed, 2),
        ),
        limit_reached=engine_result["limit_reached"],
    )

    out_path = Path(project_dir) / "00-discovery.json"
    tmp_path = out_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(dataclasses.asdict(manifest), default=str, indent=2))
    os.replace(tmp_path, out_path)

    return manifest
```

**Step 4: Run tests**
```bash
python -m pytest tests/account_discovery/ -v
```

**Step 5: Commit**
```bash
git add pipeline/account_discovery/ tests/account_discovery/
git commit -m "feat(spec-0018): discovery engine, scheduler, orchestrator — writes 00-discovery.json"
```

---

### Task 11: `tools/discover.py` CLI

**Files:**
- Create: `tools/discover.py`

**Step 1: Implement**

```python
#!/usr/bin/env python3
"""Account Discovery CLI (spec-0018).

Usage:
    python tools/discover.py --handle <handle> [--project-dir <dir>]
                             [--depth N] [--timeout S]
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path

from pipeline.account_discovery.adapters.bio_parser import BioParsing
from pipeline.account_discovery.orchestrator import discover


def main(argv=None):
    p = argparse.ArgumentParser(description="Discover cross-platform accounts from an Instagram handle")
    p.add_argument("--handle", required=True)
    p.add_argument("--project-dir", default=None)
    p.add_argument("--depth", type=int, default=2)
    p.add_argument("--timeout", type=float, default=30.0)
    p.add_argument("--bio-text", default="")
    args = p.parse_args(argv)

    project_dir = Path(args.project_dir or f"projects/{args.handle}")
    project_dir.mkdir(parents=True, exist_ok=True)

    adapters = [BioParsing()]
    config = {"max_depth": args.depth, "max_adapters": 10, "max_accounts": 50}

    manifest = discover(
        handle=args.handle,
        project_dir=project_dir,
        adapters=adapters,
        config=config,
        bio_text=args.bio_text,
    )
    print(f"Discovery complete: {len(manifest.discovered_accounts)} accounts found")
    print(f"Written to: {project_dir}/00-discovery.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

**Step 2: Smoke test**
```bash
python tools/discover.py --handle testcreator --bio-text "YouTube: @TestCreator" --project-dir /tmp/test_disc
cat /tmp/test_disc/00-discovery.json | python -m json.tool | head -30
```

**Step 3: Commit**
```bash
git add tools/discover.py
git commit -m "feat(spec-0018): tools/discover.py CLI — standalone account discovery"
```

---

## PHASE 3 — Spec 0019: Enrichment Engine Additions

### Task 12: `seeder.py` — seed EntityPool from `00-discovery.json`

**Files:**
- Create: `pipeline/enrichment/seeder.py`
- Modify: `tests/enrichment/` — add `test_seeder.py`

**Step 1: Write failing tests**

`tests/enrichment/test_seeder.py`:
```python
import json, pytest
from pathlib import Path
from pipeline.enrichment.seeder import seed_from_raw, seed_from_discovery
from pipeline.enrichment.entity_pool import EntityPool


RAW = {
    "raw_profile": {"username": "creator123", "bio_url": "https://linktr.ee/creator123"},
    "_governance": {"gdpr_basis": "LEGITIMATE_INTERESTS"},
}

DISCOVERY = {
    "seed_handle": "creator123",
    "discovered_accounts": [
        {"platform": "youtube", "handle": "Creator123", "confidence": 0.9,
         "profile_url": "https://youtube.com/@Creator123"},
        {"platform": "github",  "handle": "creator-123", "confidence": 0.8,
         "profile_url": "https://github.com/creator-123"},
    ],
}


def test_seed_from_raw_adds_instagram_handle():
    pool = EntityPool()
    seed_from_raw(RAW, pool)
    types = {e.type for e in pool.all()}
    assert "instagram_handle" in types


def test_seed_from_raw_adds_url_from_bio_url():
    pool = EntityPool()
    seed_from_raw(RAW, pool)
    types = {e.type for e in pool.all()}
    assert "url" in types


def test_seed_from_discovery_adds_youtube_handle():
    pool = EntityPool()
    seed_from_discovery(DISCOVERY, pool)
    types = {e.type for e in pool.all()}
    assert "youtube_handle" in types


def test_seed_from_discovery_sets_depth_1():
    pool = EntityPool()
    seed_from_discovery(DISCOVERY, pool)
    for entity in pool.all():
        assert entity.depth == 1


def test_no_discovery_graceful():
    pool = EntityPool()
    seed_from_raw(RAW, pool)
    seed_from_discovery(None, pool)  # None = no discovery file
    assert len(list(pool.all())) >= 1
```

**Step 2: Run to confirm failure**
```bash
python -m pytest tests/enrichment/test_seeder.py -v 2>&1 | head -15
```

**Step 3: Implement `pipeline/enrichment/seeder.py`**

```python
"""Seeds EntityPool from 01-raw.json and 00-discovery.json (spec-0019 §4)."""
from __future__ import annotations
import logging
from datetime import datetime, timezone

from pipeline.enrichment.entity import make_entity
from pipeline.enrichment.entity_pool import EntityPool

logger = logging.getLogger(__name__)

_PLATFORM_TO_ENTITY = {
    "youtube":   "youtube_handle",
    "github":    "github_handle",
    "spotify":   "spotify_handle",
    "itunes":    "itunes_artist_id",
    "twitch":    "twitch_handle",
    "reddit":    "reddit_handle",
    "substack":  "substack_url",
    "linkedin":  "linkedin_url",
    "tiktok":    "tiktok_handle",
}

_NOW = lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def seed_from_raw(raw: dict, pool: EntityPool) -> None:
    profile = raw.get("raw_profile", {})
    handle = profile.get("username") or profile.get("handle")
    if handle:
        pool.add(make_entity("instagram_handle", handle, "seeder", 1.0, 0, _NOW()))
    bio_url = profile.get("bio_url")
    if bio_url:
        pool.add(make_entity("url", bio_url, "seeder", 0.9, 0, _NOW()))
    email = profile.get("email")
    if email:
        pool.add(make_entity("email", email, "seeder", 0.9, 0, _NOW()))


def seed_from_discovery(discovery: dict | None, pool: EntityPool) -> None:
    if not discovery:
        return
    for acc in discovery.get("discovered_accounts", []):
        platform = acc.get("platform", "url")
        entity_type = _PLATFORM_TO_ENTITY.get(platform, "url")
        value = acc.get("handle") or acc.get("profile_url", "")
        if not value:
            continue
        confidence = float(acc.get("confidence", 0.7))
        try:
            pool.add(make_entity(entity_type, value, "discovery", confidence, 1, _NOW()))
        except Exception as exc:
            logger.warning("Could not seed entity type=%s value=%s: %s", entity_type, value, exc)
```

**Step 4: Add `pool.all()` to EntityPool if missing**

Check if `EntityPool.all()` exists:
```bash
grep -n "def all" /home/pedro/profile-analyst/pipeline/enrichment/entity_pool.py
```

If missing, add it:
```python
def all(self):
    with self._lock:
        return list(self._store.values())
```

**Step 5: Run tests**
```bash
python -m pytest tests/enrichment/test_seeder.py -v
```

**Step 6: Commit**
```bash
git add pipeline/enrichment/seeder.py tests/enrichment/test_seeder.py
git commit -m "feat(spec-0019): seeder — seed EntityPool from 01-raw.json + 00-discovery.json"
```

---

### Task 13: `enrichers/base.py` — EnrichmentEnricher ABC

**Files:**
- Create: `pipeline/enrichment/enrichers/__init__.py`
- Create: `pipeline/enrichment/enrichers/base.py`
- Create: `tests/enrichment/test_enrichers/__init__.py`
- Create: `tests/enrichment/test_enrichers/test_base.py`

**Step 1: Write failing tests**

`tests/enrichment/test_enrichers/test_base.py`:
```python
import pytest
from pipeline.enrichment.enrichers.base import EnrichmentEnricher


class GoodEnricher(EnrichmentEnricher):
    enricher_id = "good"; adapter_id = "youtube"; min_confidence = 0.5

    def extract(self, raw_data):
        return []


class BadExtractEnricher(EnrichmentEnricher):
    enricher_id = "bad"; adapter_id = "bad_src"; min_confidence = 0.0

    def extract(self, raw_data):
        raise ValueError("boom")


def test_valid_enricher_instantiates():
    e = GoodEnricher()
    assert e.enricher_id == "good"


def test_extract_returns_empty_on_empty_data():
    e = GoodEnricher()
    assert e.extract({}) == []


def test_extract_failure_returns_empty_not_raises():
    e = BadExtractEnricher()
    result = e.safe_extract({})
    assert result == []


def test_enricher_is_pure_no_io(monkeypatch):
    """safe_extract must never make network calls."""
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network forbidden")))
    e = GoodEnricher()
    e.safe_extract({"data": "fixture"})  # must not raise
```

**Step 2: Run to confirm failure**
```bash
python -m pytest tests/enrichment/test_enrichers/test_base.py -v 2>&1 | head -15
```

**Step 3: Implement `pipeline/enrichment/enrichers/base.py`**

```python
"""EnrichmentEnricher ABC — pure data transformer, no I/O (spec-0019 §5.3)."""
from __future__ import annotations
import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class EnrichmentEnricher(ABC):
    enricher_id: str
    adapter_id: str     # None for CrossPlatformEnricher
    min_confidence: float

    @abstractmethod
    def extract(self, raw_data: dict) -> list:
        """Pure function: raw adapter JSON → list[Entity]. No I/O allowed."""

    def safe_extract(self, raw_data: dict) -> list:
        try:
            return self.extract(raw_data)
        except Exception as exc:
            logger.warning("enricher %s failed: %s", self.enricher_id, exc)
            return []
```

**Step 4: Run tests**
```bash
python -m pytest tests/enrichment/test_enrichers/test_base.py -v
```

**Step 5: Commit**
```bash
git add pipeline/enrichment/enrichers/ tests/enrichment/test_enrichers/
git commit -m "feat(spec-0019): EnrichmentEnricher ABC — pure extract() with safe_extract fallback"
```

---

### Task 14: Wire governance into enrichment Stage 1B orchestrator

**Files:**
- Modify: `pipeline/enrichment/engine.py` — call `RobotsPolicy.check()` before adapter run
- Modify: `pipeline/stage1b_enrichment.py` — call `seed_from_discovery()` before engine

**Step 1: Add `seed_from_discovery` call in Stage 1B**

Open `pipeline/stage1b_enrichment.py` and locate where `run_engine` is called. Add the discovery seeding before it:

```python
# After reading 01-raw.json but before run_engine call:
from pipeline.enrichment.seeder import seed_from_raw, seed_from_discovery
import json
from pathlib import Path

discovery_path = project_dir / "00-discovery.json"
discovery_data = None
if discovery_path.exists():
    discovery_data = json.loads(discovery_path.read_text())

# Seed pool from discovery
initial_pool = EntityPool()
seed_from_raw(raw_data, initial_pool)
seed_from_discovery(discovery_data, initial_pool)
```

**Step 2: Add governance check in engine**

In `pipeline/enrichment/engine.py`, before the adapter `run()` call in the BFS loop, add:

```python
from pipeline.governance import RobotsPolicy
_robots = RobotsPolicy()

# In is_runnable or before calling adapter.run():
if hasattr(adapter, "robots_txt_policy") and adapter.robots_txt_policy == "RESPECT":
    decision = _robots.check(f"https://placeholder/{adapter.adapter_id}", adapter)
    if not decision.allowed:
        logger.warning("robots.txt denied adapter %s: %s", adapter.adapter_id, decision.reason)
        state.adapter_errors.append({"adapter_id": adapter.adapter_id, "error": decision.reason})
        continue
```

**Step 3: Run full enrichment test suite to verify nothing broke**
```bash
python -m pytest tests/enrichment/ -v --tb=short 2>&1 | tail -20
```

**Step 4: Commit**
```bash
git add pipeline/enrichment/engine.py pipeline/stage1b_enrichment.py
git commit -m "feat(spec-0019): wire discovery seeder + robots governance into enrichment pipeline"
```

---

### Task 15: Run full test suite and validate all acceptance criteria

**Step 1: Run all new tests**
```bash
python -m pytest tests/governance/ tests/account_discovery/ tests/enrichment/test_seeder.py tests/enrichment/test_enrichers/ -v
```

**Step 2: Run acceptance criterion AC10 (no cross-imports)**
```bash
python -m pytest tests/governance/test_compliance.py::test_no_cross_imports tests/account_discovery/test_contracts.py::test_no_enrichment_import -v
```

**Step 3: Run full suite to check for regressions**
```bash
python -m pytest tests/ -v --tb=short -q 2>&1 | tail -30
```

**Step 4: Final commit**
```bash
git add .
git commit -m "test: validate all spec-0018/0019/0020 acceptance criteria"
```

---

## Acceptance Criteria Checklist

| Spec | AC | Test |
|------|----|------|
| 0020 | AC1 missing field → AdapterContractError | `tests/governance/test_compliance.py::test_missing_field_raises` |
| 0020 | AC2 empty provenance → ProvenanceError | `tests/governance/test_compliance.py::test_assert_provenance_chain_empty_raises` |
| 0020 | AC3 RateLimiter blocks | `tests/governance/test_rate_limiter.py::test_token_bucket_blocks_on_second_call` |
| 0020 | AC4 robots.txt disallows | `tests/governance/test_robots_policy.py::test_disallowed_path` |
| 0020 | AC5 N/A policy skips check | `tests/governance/test_robots_policy.py::test_na_policy_skips_check` |
| 0020 | AC6 confidence clamped + WARNING | `tests/governance/test_metrics.py::test_confidence_clamped_high` |
| 0020 | AC7 empty-run coverage | `tests/governance/test_metrics.py::test_compute_coverage_empty_run` |
| 0020 | AC9 cross-module validation | `tests/governance/test_compliance.py::test_cross_module_validation` |
| 0020 | AC10 no cross-imports | `tests/governance/test_compliance.py::test_no_cross_imports` |
| 0018 | AC1 bio → discovered account | `tests/account_discovery/test_engine.py::test_engine_runs_bio_adapter` |
| 0018 | AC2 attribution chain non-empty | `tests/account_discovery/test_adapters/test_bio_parser.py::test_attribution_chain_non_empty` |
| 0018 | AC4 standalone (no stages) | `tests/account_discovery/test_engine.py::test_standalone_execution` |
| 0018 | AC5 no enrichment import | `tests/account_discovery/test_contracts.py::test_no_enrichment_import` |
| 0018 | AC6 depth limit | `tests/account_discovery/test_engine.py::test_depth_limit_sets_flag` |
| 0018 | AC7 dedup merges attribution | `tests/account_discovery/test_pool.py::test_dedup_merge_attribution_chain` |
| 0019 | AC1 discovery accounts seeded | `tests/enrichment/test_seeder.py::test_seed_from_discovery_adds_youtube_handle` |
| 0019 | AC6 enricher tests no HTTP mock | `tests/enrichment/test_enrichers/test_base.py::test_enricher_is_pure_no_io` |
| 0019 | AC8 no discovery → valid output | `tests/enrichment/test_seeder.py::test_no_discovery_graceful` |
