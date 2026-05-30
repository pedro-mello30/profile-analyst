.PHONY: validate test run install lint

# ── Validation ──────────────────────────────────────────────────────────────
validate:
	@echo "==> Validating schemas and metadata..."
	python3 tools/validate.py
	@echo "==> OK"

# ── Tests ────────────────────────────────────────────────────────────────────
test:
	pytest tests/ -v

test-cov:
	pytest tests/ -v --cov=pipeline --cov=adapters --cov-report=term-missing

# ── Run ──────────────────────────────────────────────────────────────────────
# Usage: make run HANDLE=<instagram_handle> [STAGE=all]
run:
	python3 profile_analyst.py --handle $(HANDLE) --stage $(or $(STAGE),all)

# ── Load (Stage 7: Neo4j graph persistence) ───────────────────────────────────
# Usage: make load HANDLE=<instagram_handle>
load:
	python3 profile_analyst.py --handle $(HANDLE) --stage 7

# ── Install ──────────────────────────────────────────────────────────────────
install:
	pip install -e ".[dev]"

# ── Lint ─────────────────────────────────────────────────────────────────────
lint:
	ruff check . --fix
