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

# ── GDS (Stage 9: graph data-science algorithms, spec 0004) ──────────────────
# Usage: make gds HANDLE=<instagram_handle>
gds:
	python3 profile_analyst.py gds --handle $(HANDLE)

# ── Ask (NL→Cypher graph query, spec 0003) ────────────────────────────────────
# Usage: make ask HANDLE=<instagram_handle> Q="<natural-language question>"
ask:
ifeq ($(strip $(HANDLE))$(strip $(Q)),)
	@echo "Usage: make ask HANDLE=<handle> Q=\"<question>\""
else ifeq ($(strip $(HANDLE)),)
	@echo "Usage: make ask HANDLE=<handle> Q=\"<question>\"  (HANDLE missing)"
else ifeq ($(strip $(Q)),)
	@echo "Usage: make ask HANDLE=<handle> Q=\"<question>\"  (Q missing)"
else
	python3 profile_analyst.py --handle $(HANDLE) --ask "$(Q)"
endif

# ── Embed (Stage 8: embedding backfill, spec 0005) ───────────────────────────
# Usage: make embed HANDLE=<instagram_handle>
embed:
ifeq ($(strip $(HANDLE)),)
	@echo "Usage: make embed HANDLE=<handle>"
else
	python3 profile_analyst.py --handle $(HANDLE) --stage 8
endif

# ── RAG (Hybrid RAG query, spec 0005) ────────────────────────────────────────
# Usage: make rag HANDLE=<instagram_handle> Q="<natural-language question>"
rag:
ifeq ($(strip $(Q)),)
	@echo "Usage: make rag HANDLE=<handle> Q=\"<question>\""
else
	python3 profile_analyst.py $(if $(strip $(HANDLE)),--handle $(HANDLE),) --rag "$(Q)"
endif

# Usage: make rag-rerank HANDLE=<instagram_handle> Q="<natural-language question>"
rag-rerank:
ifeq ($(strip $(Q)),)
	@echo "Usage: make rag-rerank HANDLE=<handle> Q=\"<question>\""
else
	python3 profile_analyst.py $(if $(strip $(HANDLE)),--handle $(HANDLE),) --rag "$(Q)" --rerank
endif

# ── Eval (RAG quality evaluation harness, spec 0006) ─────────────────────────
eval:
	OBSERVABILITY_ENABLED=true python3 -m observability.evaluation

# ── Install ──────────────────────────────────────────────────────────────────
install:
	pip install -e ".[dev]"

# ── Lint ─────────────────────────────────────────────────────────────────────
lint:
	ruff check . --fix
