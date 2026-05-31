# Spec 0010 — Local-LLM Runtime Reliability

> Status: **draft** · Owner: pedro · Depends on: 0003 (Ollama backend), 0001 (Stage 3 contract)
>
> Spec 0003 made the Ollama Stage 3 backend *exist*. This spec makes it **reliably run
> end-to-end on a constrained, CPU-only host** and documents the defects found and fixed while
> bringing the full pipeline up for Instagram handle **`rolandgarros`** with **no cloud egress**.

## 1. Context & motivation

The pipeline advertises a local-first path (`LLM_BACKEND=ollama`) so that no creator data leaves the
host. In practice, running the dossier path (`--stage 1,2,3,6`) on a modest box never completed:
Stage 3 failed before producing `03-features.json`. The target/reference host is deliberately small:

| Resource | Value |
|---|---|
| RAM | 7.7 GB total (~2.3 GB free at test time) |
| GPU | NVIDIA GeForce MX150, 4 GB — **Ollama runs CPU-only** here |
| CPUs | 8 |
| Ollama | 0.24.0 |
| Models pulled | `qwen2.5-coder:3b`, `nomic-embed-text` (the documented `qwen2.5:14b` / `qwen2.5-coder:32b` are **not** pulled and do not fit) |

This spec records the four root causes (§3), the decisions taken (§4 / `metadata.yml` D1–D8), the
acceptance criteria and their status (§5), and an operational runbook (§7).

## 2. Goals / Non-goals

**Goals**
- Stage 3 LLM feature extraction completes on `qwen2.5-coder:3b` and emits schema-valid features.
- The full dossier path runs end-to-end and produces `06-dossier.json` + `report.md` locally.
- No silent cloud fallback when the operator asked for local-only.
- Preserve every 0001/0003 invariant: `confidence`, `method`, `art9_risk`, FTC status, and the
  **"never repair feature content"** rule (0003 C6).

**Non-goals**
- Improving the *intelligence* of the small model (niche accuracy, Art. 9 precision). A 3B model is
  a quality floor, not a target; see §8 / Future Work.
- Stages 7–9 (Neo4j load / GDS) — they need a live, authenticated Neo4j and are out of scope.

## 3. Root-cause findings (evidence-first)

**RC1 — Unconfigurable HTTP timeout vs. cold model load.** A minimal warm call is ~3 s, but a
*cold* call reported `load_duration ≈ 113 s` (model paged into near-full RAM). `OllamaClient` hard-coded
a 120 s timeout with **no env override**, so Stage 3's larger prompt tipped past 120 s and raised
`httpx.ReadTimeout`, surfaced misleadingly as *"is the daemon running (`ollama serve`)?"* even though
the daemon was up. → **D1**.

**RC2 — `format:"json"` does not force an array.** The backend required a top-level JSON array, but
under `format:"json"` the 3B model returned a **single feature object** (`primary_niche` only), so
the backend raised *"returned dict, expected a JSON array"*. Ollama 0.24 **does** enforce JSON-Schema
`required` in its grammar (verified: instructing the model to omit `confidence` still produced it), so
a schema `format` is the right lever. → **D2**.

**RC3 — Permissive `value:{}` admits semantically-wrong values.** Once an array was enforced via the
full item schema, every feature object carried the required fields — but because the item schema types
`value` as `{}` (any), the grammar let the model emit **dict-shaped values** like
`primary_niche = {"Lifestyle": 0.85}` and `sponsored_posts = {"rg003": true}`. These *pass* validation
yet are wrong for Stage 6 (which expects a string niche and a list of media). Fix: tighten `value` to
`string|array|number|boolean|null` **in the grammar only** (validation schema untouched), plus a
container-coercion helper for `{"features":[…]}`/single-object shapes — container normalization only,
never content repair (C6 preserved). → **D3**.

**RC4 — Example-anchoring.** The 3B model copied the prompt's example niche `"Lifestyle"` for a tennis
account. The prompt now states the example values are placeholders and each value must be derived from
the actual profile, and must be a string or list (never an object). → **D4**.

## 4. Design / decisions

See `metadata.yml` `decisions:` for the authoritative list. Summary of the **implemented** set:

- **D1** `OLLAMA_TIMEOUT_S` (default 120) read in `OllamaClient.__init__`, mirroring `OLLAMA_HOST` /
  `OLLAMA_KEEP_ALIVE`; an explicit `timeout_s=` constructor arg still wins.
- **D2** `_array_format(item_schema)` builds `{"type":"array","items":<feature item schema>}` and is
  passed as Ollama `format`; this forces an array and grammar-enforces the required fields.
- **D3** `_array_format` deep-copies the item schema and replaces `value` with a non-object type union;
  `_coerce_to_feature_list` normalizes the top-level container shape. Per-item `jsonschema.validate`
  and `method="llm"` forcing are unchanged.
- **D4** `prompts/stage3-features.md` shows an **array** example and an explicit anti-anchoring +
  value-shape instruction.
- **D5** `qwen2.5-coder:3b` is the supported small-host features model.

**Proposed** (not yet implemented): **D6** flip `ASK_FALLBACK` default to `false` + loud egress log on
fallback; **D7** auto-load `.env` in the CLI (python-dotenv); **D8** pre-warm the features model once.

## 5. Acceptance

Authoritative list in `metadata.yml` `acceptance:`. **Met:** A1 (timeout env, unit-tested), A2
(container coercion, unit-tested), A3 (Stage 3 emits schema-valid, correctly-typed features on
`qwen2.5-coder:3b`), A4 (full dossier path local-only — `rolandgarros`, `ASK_FALLBACK=false`, empty
`ANTHROPIC_API_KEY`, 7 `method=llm` features), A5 (`make validate` + full non-graph suite green:
**283 passed**; the 10 errors are `graph/` Neo4j-auth integration tests, out of scope). **Proposed:**
A6–A8 track D6–D8.

## 6. Implementation status (this branch)

Changed: `pipeline/llm/ollama_client.py`, `pipeline/llm/ollama_backend.py`, `prompts/stage3-features.md`,
`tests/llm/test_backends.py` (+2 tests, 12 passing), and `projects/rolandgarros/00-input/sample.json`
(end-to-end fixture). Verified artifacts: `projects/rolandgarros/{01-raw,02-normalized,03-features,06-dossier}.json`
+ `report.md` — niche **Sports**, EQS **76/100**, Sponsorship Transparency **100/100** (3/3 disclosed),
Brand Safety **90/100**, FTC **compliant**, GDPR Art. 22 flagged, Art. 9 redacted.

## 7. Operational runbook (bare-metal, until D7 lands)

```bash
# 1. Ensure the daemon is up and the small model is pulled
ollama serve &                       # if not already running
ollama pull qwen2.5-coder:3b

# 2. (Recommended) pre-warm so the ~113s cold load is paid once
curl -s http://localhost:11434/api/chat -d '{"model":"qwen2.5-coder:3b",
  "messages":[{"role":"user","content":"[1]"}],"stream":false,"keep_alive":"30m"}' >/dev/null

# 3. Run the dossier path locally — no cloud egress
env LLM_BACKEND=ollama \
    OLLAMA_HOST=http://localhost:11434 \
    OLLAMA_FEATURES_MODEL=qwen2.5-coder:3b \
    OLLAMA_KEEP_ALIVE=30m \
    OLLAMA_TIMEOUT_S=600 \
    ASK_FALLBACK=false \
    OBSERVABILITY_ENABLED=false \
    ANTHROPIC_API_KEY= \
    python3 profile_analyst.py --handle rolandgarros --stage 1,2,3,6
```

Note: the committed `.env` targets docker-compose service names (`ollama:11434`, `neo4j:7687`,
`mlflow:5000`) and is **not** auto-loaded by the CLI; bare-metal runs must pass the overrides above
until D7 lands.

## 8. Known small-model limitations (not bugs)

- **Art. 9 over-flagging:** the 3B model set `art9_risk=true` on `caption_sentiment` for a Sports
  account (the prompt intends that only for Fitness/Health/Religion/Politics). It is conservative and
  correctly redacted, but it is a precision miss.
- **Latency:** ~5–8 min per Stage 3 run warm on CPU. A larger model and/or GPU offload would cut this.
- **`sponsored_posts` element shape** from the LLM may be objects rather than bare media-id strings;
  the deterministic pass remains authoritative for FTC scoring. See Future Work (de-dupe).
