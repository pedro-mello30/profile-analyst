# Stage 1 Ingest — Refactoring Diagnosis

**Date:** 2026-06-03
**Scope:** `pipeline/stage1_ingest.py`, `adapters/base.py`, `pipeline/compliance/tos.py`

## Code Smells Identified

| Smell | Location | Pattern |
|---|---|---|
| Long Method | `run()` — 5 steps, all inline | Extract Method → Template Method |
| Feature Envy | `raw_profile.get("location") or "UNKNOWN"` inside `run()` | Move to adapter |
| Primitive Obsession | record assembled as plain `dict`, `"instagram"` hardcoded | Builder + adapter attribute |
| Data Clumps | `ingested_at` + `subject_jurisdiction` always travel together | Introduce Parameter Object |
| Magic Number | `fetch_media(handle, limit=20)` | Named constant |
| No Observability | zero logging in a 9-stage pipeline | Hooks in Template Method steps |

## Design Patterns to Apply

- **Template Method** — `Stage1Processor` class with fixed step sequence, override points per step
- **Strategy** — `resolve_jurisdiction()` per adapter (replaces hardcoded dict lookup)
- **Builder** — `RawRecordBuilder` assembles and validates before write

---

## Specs

---

### Spec A: Ingest Core

Responsável por:
- `SourceAdapter` interface
- Adapter registry / factory
- Execution orchestration (`Stage1Processor`)
- Idempotent artifact write

Output:
`01-raw.json`

Acceptance criteria:
- Can execute any registered adapter
- Handles adapter failures with typed exceptions
- Produces deterministic output on re-run
- Steps are independently testable

---

### Spec B: Platform Fetch

Responsável por:
- `fetch_profile()` contract
- `fetch_media()` contract
- `resolve_jurisdiction()` per adapter
- `platform` attribute per adapter
- Named fetch limit constant

Output:
raw profile + media payload (input to builder)

Acceptance criteria:
- Input: `handle` + adapter
- Output: typed profile + media collection
- Platform and jurisdiction sourced from adapter, not hardcoded
- Every adapter declares `platform`

---

### Spec C: Ingest Governance

Responsável por:
- ToS gate
- Governance block builder
- `IngestionContext` parameter object
- GDPR basis + retention policy
- Governance completeness assertion

Output:
`_governance` block embedded in `01-raw.json`

Acceptance criteria:
- Every adapter declares governance posture
- Non-compliant adapters blocked before any fetch
- Governance block always complete before write
- `IngestionContext` is the only entry point for timing + jurisdiction
