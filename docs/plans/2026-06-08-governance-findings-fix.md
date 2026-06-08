# Governance Findings Fix Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix all 7 findings from the spec-0018/0019/0020 flowchart verification: missing coverage wiring, empty violations list, thread-unsafe cache, lazy imports, missing type annotation, undocumented sleep behavior, and broad except clauses.

**Architecture:** All changes are local to `pipeline/governance/` and `pipeline/account_discovery/`. No pipeline stage outputs change shape (except `00-discovery.json` gains a non-null `governance.coverage` block). Changes are ordered lowest-risk-first so early commits don't block later ones.

**Tech Stack:** Python 3.11 · pytest · threading · dataclasses

---

## Finding Summary

| ID | File | Impact | Risk |
|----|------|--------|------|
| C4 | `governance/compliance.py` | Code quality | Zero |
| C5 | `governance/metrics.py` | Type clarity | Zero |
| C3 | `governance/policies.py` | Documentation | Zero |
| C6 | `account_discovery/engine.py` | Missing coverage data in artifact | Low |
| C1 | `governance/compliance.py` + callers | Empty audit trail | Medium |
| C2 | `governance/policies.py` | Race condition under parallel enrichment | Medium |
| KG | 4 discovery adapter files | Swallowed errors in adapters | Low |

---

## Task 1: C4 — Elevate lazy imports in compliance.py

**Why it's first:** Pure refactor, zero behavior change, makes C1 code cleaner.

**Files:**
- Modify: `pipeline/governance/compliance.py`

**Step 1: Read the file to confirm lazy import locations**

```bash
grep -n "from pipeline.governance.models import" pipeline/governance/compliance.py
```

Expected output:
```
43:    from pipeline.governance.models import ContractViolation
64:    from pipeline.governance.models import ContractViolation
117:    from pipeline.governance.models import ContractViolation
```

**Step 2: Move the import to module level**

In `compliance.py`, after the existing module-level imports (after `from __future__ import annotations`), add:

```python
from pipeline.governance.models import ContractViolation
```

Remove all three occurrences inside function bodies (`_validate_attrs`, `_validate_vocab`, `validate_enricher_contract`).

**Step 3: Verify tests still pass**

```bash
python3 -m pytest pipeline/governance/tests/test_compliance.py -q
```

Expected: all pass, same count as before.

**Step 4: Commit**

```bash
git add pipeline/governance/compliance.py
git commit -m "refactor(governance): elevate ContractViolation import to module level (C4)"
```

---

## Task 2: C5 — Type annotation for compute_coverage pool parameter

**Files:**
- Modify: `pipeline/governance/metrics.py`

**Step 1: Add `Iterable` to the signature**

Change the function signature from:

```python
def compute_coverage(
    pool,
    adapters: list,
    ran_set: dict,
```

to:

```python
from typing import Iterable

def compute_coverage(
    pool: Iterable,
    adapters: list,
    ran_set: dict,
```

Add `from typing import Iterable` at the top of `metrics.py` (after `from __future__ import annotations`).

**Step 2: Verify tests still pass**

```bash
python3 -m pytest pipeline/governance/tests/test_metrics.py -q
```

Expected: all pass.

**Step 3: Commit**

```bash
git add pipeline/governance/metrics.py
git commit -m "refactor(governance): annotate compute_coverage pool as Iterable (C5)"
```

---

## Task 3: C3 — Document intentional sleep-outside-lock in RateLimiter

**Files:**
- Modify: `pipeline/governance/policies.py`

**Step 1: Add explanatory comment**

In `RateLimiter.acquire()`, the block after `with self._lock:` exits and before `time.sleep(wait_s)` (currently line 148), add a comment:

```python
        # Sleep OUTSIDE the lock: holding the lock while sleeping would block other
        # adapters from acquiring tokens. The token is already consumed atomically
        # inside the lock above — the sleep is only the inter-request pacing delay.
        # Future fix: replace with asyncio.sleep in an async upgrade (spec-0020 §5.2).
        if wait_s > 0:
            time.sleep(wait_s)
```

**Step 2: Verify tests still pass**

```bash
python3 -m pytest pipeline/governance/tests/test_rate_limiter.py -q
```

Expected: all pass.

**Step 3: Commit**

```bash
git add pipeline/governance/policies.py
git commit -m "docs(governance): document intentional sleep-outside-lock in RateLimiter (C3)"
```

---

## Task 4: C6 — Wire compute_coverage in discovery engine

**This is the highest-impact fix.** After this, `00-discovery.json` gains a non-null `governance.coverage` block.

**Files:**
- Modify: `pipeline/account_discovery/engine.py`
- Modify: `pipeline/account_discovery/tests/test_engine.py`

**Step 1: Write the failing test first**

Add to `pipeline/account_discovery/tests/test_engine.py`:

```python
def test_governance_report_has_coverage():
    """AC6-ext: coverage block is computed and non-None after the engine run."""
    pool = AccountPool()
    state = DiscoveryEngineState()
    engine = DiscoveryEngine(adapters=[FakeBioParser()], config=DiscoveryConfig())
    engine.run(pool, _seed(), state)
    report = state.governance_report
    assert report is not None
    assert report.coverage is not None
    assert report.coverage.adapters_registered >= 1
    assert report.coverage.module == "account_discovery"
```

**Step 2: Run to confirm it fails**

```bash
python3 -m pytest pipeline/account_discovery/tests/test_engine.py::test_governance_report_has_coverage -v
```

Expected: FAIL — `AssertionError: assert None is not None`

**Step 3: Add coverage wiring to the engine**

In `pipeline/account_discovery/engine.py`, at the very end of `DiscoveryEngine.run()` (currently line 196, right before `gov_report.completed_at = ...`), add:

```python
        # Compute coverage using pool_entity_types as discovered entity types.
        # DiscoveredAccount objects don't carry a .type attribute, so we pass
        # lightweight wrappers built from the already-maintained pool_entity_types set.
        class _PoolEntity:
            __slots__ = ("type",)
            def __init__(self, t: str) -> None:
                self.type = t

        gov_report.coverage = compute_coverage(
            [_PoolEntity(t) for t in pool_entity_types],
            valid_adapters,
            state.ran_set,
            run_id=effective_run_id,
            module="account_discovery",
        )
        gov_report.completed_at = datetime.now(timezone.utc)
```

Note: `_PoolEntity` is defined inline inside `run()` to keep it out of module scope — it is a one-use wrapper.

**Step 4: Run the new test**

```bash
python3 -m pytest pipeline/account_discovery/tests/test_engine.py::test_governance_report_has_coverage -v
```

Expected: PASS

**Step 5: Confirm live artifact**

```bash
python3 tools/discover.py --handle testuser \
  --bio-text "YouTube: youtube.com/@testchannel" \
  --bio-urls "https://youtube.com/@testchannel" \
  --output-dir /tmp/c6-verify
python3 -c "
import json
d = json.load(open('/tmp/c6-verify/00-discovery.json'))
cov = d['governance']['coverage']
print('coverage_ratio:', cov['coverage_ratio'])
print('adapters_registered:', cov['adapters_registered'])
print('entity_types_discovered:', cov['entity_types_discovered'])
"
```

Expected: coverage block is non-null with real values.

**Step 6: Run full discovery test suite**

```bash
python3 -m pytest pipeline/account_discovery/tests/ -q
```

Expected: all pass + 1 new test.

**Step 7: Commit**

```bash
git add pipeline/account_discovery/engine.py \
        pipeline/account_discovery/tests/test_engine.py
git commit -m "feat(spec-0018): wire compute_coverage in discovery engine (C6)"
```

---

## Task 5: C1 — Populate GovernanceReport.violations from contract errors

**Why:** The governance audit trail stays empty even when adapters fail validation. Callers (engine.py in both discovery and enrichment) already catch `AdapterContractError` — they just don't record it in the report.

**Files:**
- Modify: `pipeline/governance/compliance.py` (add optional `report` param)
- Modify: `pipeline/account_discovery/engine.py` (pass `gov_report` to validate call)
- Modify: `pipeline/enrichment/engine.py` (pass `gov_report` to validate call)
- Modify: `pipeline/governance/tests/test_compliance.py` (new tests)

**Step 1: Write failing tests**

Add to `pipeline/governance/tests/test_compliance.py`:

```python
from pipeline.governance import build_report


class TestViolationsPopulatedOnError:
    def test_enrichment_adapter_violations_appended_to_report(self):
        """C1: validate_adapter_contract appends to report.violations before raising."""
        a = make_valid_enrichment_adapter(data_category="INVALID_CAT")
        report = build_report("run-c1", "test")
        with pytest.raises(AdapterContractError):
            validate_adapter_contract(a, report=report)
        assert len(report.violations) == 1
        assert report.violations[0].field == "data_category"

    def test_discovery_adapter_violations_appended_to_report(self):
        """C1: validate_discovery_adapter_contract appends to report.violations."""
        a = make_valid_discovery_adapter(robots_txt_policy="FOLLOW")
        report = build_report("run-c1b", "test")
        with pytest.raises(AdapterContractError):
            validate_discovery_adapter_contract(a, report=report)
        assert len(report.violations) == 1
        assert report.violations[0].field == "robots_txt_policy"

    def test_report_none_still_raises(self):
        """C1: passing report=None does not crash (backward compat)."""
        a = make_valid_enrichment_adapter(tier="TURBO")
        with pytest.raises(AdapterContractError):
            validate_adapter_contract(a, report=None)

    def test_no_violation_does_not_append(self):
        """C1: valid adapter leaves report.violations empty."""
        report = build_report("run-c1c", "test")
        validate_adapter_contract(make_valid_enrichment_adapter(), report=report)
        assert report.violations == []
```

**Step 2: Run to confirm failure**

```bash
python3 -m pytest pipeline/governance/tests/test_compliance.py::TestViolationsPopulatedOnError -v
```

Expected: all 4 FAIL — `TypeError: validate_adapter_contract() got unexpected keyword argument 'report'`

**Step 3: Add `report` param to all three validate functions**

In `pipeline/governance/compliance.py`, update each function signature and add the append-before-raise pattern:

```python
def validate_adapter_contract(adapter, report: "GovernanceReport | None" = None) -> None:
    """Validate an EnrichmentAdapter contract at registration time. Raises AdapterContractError."""
    adapter_id = str(getattr(adapter, "adapter_id", repr(adapter)))
    violations = []
    violations += _validate_attrs(adapter, _SHARED_REQUIRED)
    violations += _validate_attrs(adapter, _ENRICHMENT_EXTRA)
    violations += _validate_vocab(adapter, "data_category", _VALID_DATA_CATS, adapter_id)
    violations += _validate_vocab(adapter, "robots_txt_policy", _VALID_ROBOTS, adapter_id)
    violations += _validate_vocab(adapter, "gdpr_basis", _VALID_GDPR, adapter_id)
    violations += _validate_vocab(adapter, "tier", _VALID_TIERS, adapter_id)
    if violations:
        if report is not None:
            report.violations.extend(violations)
        raise AdapterContractError(
            f"Adapter {adapter_id!r} has {len(violations)} contract violation(s):\n"
            + "\n".join(f"  • {v.message}" for v in violations)
        )


def validate_discovery_adapter_contract(adapter, report: "GovernanceReport | None" = None) -> None:
    """Validate a DiscoveryAdapter contract at registration time. Raises AdapterContractError."""
    adapter_id = str(getattr(adapter, "adapter_id", repr(adapter)))
    violations = []
    violations += _validate_attrs(adapter, _SHARED_REQUIRED)
    violations += _validate_vocab(adapter, "data_category", _VALID_DATA_CATS, adapter_id)
    violations += _validate_vocab(adapter, "robots_txt_policy", _VALID_ROBOTS, adapter_id)
    if violations:
        if report is not None:
            report.violations.extend(violations)
        raise AdapterContractError(
            f"Discovery adapter {adapter_id!r} has {len(violations)} contract violation(s):\n"
            + "\n".join(f"  • {v.message}" for v in violations)
        )


def validate_enricher_contract(enricher, report: "GovernanceReport | None" = None) -> None:
    """Validate an Enricher contract at registration time. Raises AdapterContractError."""
    enricher_id = str(getattr(enricher, "enricher_id", repr(enricher)))
    violations = _validate_attrs(enricher, _ENRICHER_REQUIRED, id_attr="enricher_id")
    if hasattr(enricher, "min_confidence"):
        mc = enricher.min_confidence
        if isinstance(mc, (int, float)) and not (0.0 <= mc <= 1.0):
            violations.append(ContractViolation(
                adapter_id=enricher_id, field="min_confidence",
                expected="float in [0.0, 1.0]", got=repr(mc),
                message=f"min_confidence={mc!r} out of [0.0, 1.0]",
            ))
    if violations:
        if report is not None:
            report.violations.extend(violations)
        raise AdapterContractError(
            f"Enricher {enricher_id!r} has {len(violations)} contract violation(s):\n"
            + "\n".join(f"  • {v.message}" for v in violations)
        )
```

Note: `"GovernanceReport | None"` as a string avoids a circular import since `GovernanceReport` is in `models.py` which is already imported only at function level. After Task 1 moves `ContractViolation` to module-level, we can also add `from pipeline.governance.models import GovernanceReport` at the top — but to avoid circular imports, use `TYPE_CHECKING`:

```python
from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from pipeline.governance.models import GovernanceReport
```

**Step 4: Update callers to pass gov_report**

In `pipeline/account_discovery/engine.py`, in the adapter validation loop (around line 73):

Change:
```python
validate_discovery_adapter_contract(adapter)
```
To:
```python
validate_discovery_adapter_contract(adapter, report=gov_report)
```

In `pipeline/enrichment/engine.py`, in the adapter validation loop (around line 297):

Change:
```python
validate_adapter_contract(adapter)
```
To:
```python
validate_adapter_contract(adapter, report=gov_report)
```

**Step 5: Run the new tests**

```bash
python3 -m pytest pipeline/governance/tests/test_compliance.py::TestViolationsPopulatedOnError -v
```

Expected: all 4 PASS

**Step 6: Run full governance and discovery suites**

```bash
python3 -m pytest pipeline/governance/tests/ pipeline/account_discovery/tests/ -q
```

Expected: all pass.

**Step 7: Commit**

```bash
git add pipeline/governance/compliance.py \
        pipeline/account_discovery/engine.py \
        pipeline/enrichment/engine.py \
        pipeline/governance/tests/test_compliance.py
git commit -m "feat(governance): populate GovernanceReport.violations on contract error (C1)"
```

---

## Task 6: C2 — Thread-safe RobotsPolicy cache

**Why:** The enrichment engine runs adapters in a `ThreadPoolExecutor` (8 workers). All workers share a single `RobotsPolicy` instance. Concurrent `_get_parser` reads and writes to `self._cache` are a real data race.

**Files:**
- Modify: `pipeline/governance/policies.py`
- Modify: `pipeline/governance/tests/test_robots_policy.py`

**Step 1: Write the concurrent test**

Add to `pipeline/governance/tests/test_robots_policy.py`:

```python
import threading
from unittest.mock import patch, MagicMock


class TestRobotsPolicyConcurrency:
    def test_cache_is_thread_safe(self):
        """C2: concurrent check() calls on the same instance do not corrupt _cache."""
        policy = RobotsPolicy()
        adapter = SimpleNamespace(adapter_id="scraper", robots_txt_policy="RESPECT")

        mock_rp = MagicMock()
        mock_rp.can_fetch.return_value = True
        errors = []

        def worker():
            try:
                with patch("urllib.robotparser.RobotFileParser") as MockRFP:
                    MockRFP.return_value = mock_rp
                    mock_rp.read.return_value = None
                    for _ in range(20):
                        policy.check("https://example.com/path", adapter)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Thread errors: {errors}"
        assert len(policy._cache) == 1  # one domain, one cached parser
```

**Step 2: Run to confirm it passes (race may not be deterministic to catch)**

```bash
python3 -m pytest pipeline/governance/tests/test_robots_policy.py::TestRobotsPolicyConcurrency -v
```

Note: data races are non-deterministic. The test passing now doesn't mean the race is absent — it passes trivially without the fix too. The fix is still required for correctness.

**Step 3: Add the lock**

In `pipeline/governance/policies.py`, in `RobotsPolicy.__init__`:

```python
def __init__(self):
    self._cache: dict[str, tuple] = {}  # domain -> (RobotFileParser, expires_monotonic)
    self._cache_lock = threading.Lock()
```

In `_get_parser`, wrap the read and write of `self._cache` in the lock:

```python
def _get_parser(self, url: str, domain: str):
    now = time.monotonic()
    with self._cache_lock:
        cached = self._cache.get(domain)
        if cached is not None:
            rp, expires_at = cached
            if now < expires_at:
                return rp

    scheme = urlparse(url).scheme
    robots_url = f"{scheme}://{domain}/robots.txt"
    try:
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(robots_url)
        rp.read()
        with self._cache_lock:
            self._cache[domain] = (rp, now + self._TTL_S)
        return rp
    except Exception:
        return None
```

Note: The read and write are in separate lock acquisitions (double-checked locking pattern). This is intentional — `rp.read()` makes a network call and must not hold the lock. Two threads may both miss the cache and both fetch, but the second write is idempotent (same domain, same TTL window).

**Step 4: Run all robots policy tests**

```bash
python3 -m pytest pipeline/governance/tests/test_robots_policy.py -v
```

Expected: all pass including the new concurrency test.

**Step 5: Run full suite**

```bash
python3 -m pytest pipeline/governance/tests/ pipeline/account_discovery/tests/ -q
```

Expected: all pass.

**Step 6: Commit**

```bash
git add pipeline/governance/policies.py \
        pipeline/governance/tests/test_robots_policy.py
git commit -m "fix(governance): make RobotsPolicy._cache thread-safe with Lock (C2)"
```

---

## Task 7: KG-pattern — Narrow broad except in discovery adapters

**Context:** All four discovery adapters have `except Exception` in two levels of nesting inside `run()`. The outer catch is a last-resort guard; the inner catch wraps per-entity processing. Both are marked `# noqa: BLE001` (broad-exception lint suppression). The flowchart says "Fix: narrow to ValueError" but the actual risk is `AttributeError` / `TypeError` from duck-typed entities. We narrow the inner loop to those; the outer guard stays as a documented safety net.

**Files:**
- Modify: `pipeline/account_discovery/adapters/bio_parser.py`
- Modify: `pipeline/account_discovery/adapters/link_expander.py`
- Modify: `pipeline/account_discovery/adapters/url_resolver.py`
- Modify: `pipeline/account_discovery/adapters/pattern_matcher.py`

**Step 1: Check what can actually raise in bio_parser inner loop**

```bash
# The inner try block does:
# - getattr(entity, "type", None)     → never raises
# - entity.get("type")                → guarded by isinstance(entity, dict)
# - _extract_accounts(str(...))       → regex.finditer → never raises
# The only realistic exception is TypeError if str() fails on a weird object.
```

**Step 2: Update bio_parser inner except**

In `pipeline/account_discovery/adapters/bio_parser.py`, change:

```python
            except Exception:  # noqa: BLE001
                continue
```
To:
```python
            except (AttributeError, TypeError, ValueError):
                continue
```

Keep the outer `except Exception: return []` with a comment:

```python
        except Exception:  # noqa: BLE001 — last-resort guard; inner loop is narrowed above
            return []
```

**Step 3: Apply the same pattern to the other three adapters**

In each adapter's `run()` method:
- Inner `except Exception` (per-entity/per-URL) → `except (AttributeError, TypeError, ValueError, OSError)`
  - `OSError` is added for `link_expander` and `url_resolver` which do URL parsing that can raise on malformed input.
- Outer `except Exception` (whole-run guard) → stays broad with a comment.

For `link_expander.py`: check what the inner try wraps — URL expansion, `urllib.parse` calls. These raise `ValueError` (bad URL scheme) or `OSError` (from socket). Narrow to `(ValueError, OSError)`.

For `url_resolver.py`: wraps HTTP calls via `urllib.request`. These raise `urllib.error.URLError` (subclass of `OSError`). Narrow inner to `(ValueError, OSError)`.

For `pattern_matcher.py`: regex matching on string values. Raise `TypeError` if value is not a string. Narrow inner to `(TypeError, ValueError)`.

**Step 4: Run adapter-specific tests**

```bash
python3 -m pytest pipeline/account_discovery/tests/test_adapters/ -q
```

Expected: all pass (behavior is identical — the narrower catches still cover all realistic exceptions).

**Step 5: Run full discovery suite**

```bash
python3 -m pytest pipeline/account_discovery/tests/ -q
```

Expected: all pass.

**Step 6: Commit**

```bash
git add pipeline/account_discovery/adapters/bio_parser.py \
        pipeline/account_discovery/adapters/link_expander.py \
        pipeline/account_discovery/adapters/url_resolver.py \
        pipeline/account_discovery/adapters/pattern_matcher.py
git commit -m "fix(spec-0018): narrow broad except in discovery adapters (KG-pattern)"
```

---

## Final Verification

**Step 1: Run all three module test suites together**

```bash
python3 -m pytest pipeline/governance/tests/ \
                  pipeline/account_discovery/tests/ \
                  -q --tb=short
```

Expected: all pass (net gain: 5 new tests).

**Step 2: Live artifact check**

```bash
python3 tools/discover.py --handle verifyhandle \
  --bio-text "Dev | YouTube: youtube.com/@chan | GitHub: github.com/user" \
  --bio-urls "https://youtube.com/@chan" "https://github.com/user" \
  --output-dir /tmp/final-verify

python3 -c "
import json
d = json.load(open('/tmp/final-verify/00-discovery.json'))
gov = d['governance']
print('violations:', gov['violations'])
print('coverage_ratio:', gov['coverage']['coverage_ratio'])
print('entity_types_discovered:', gov['coverage']['entity_types_discovered'])
print('adapters_registered:', gov['coverage']['adapters_registered'])
"
```

Expected: `violations: []`, `coverage` is a full dict with `adapters_registered > 0`.
