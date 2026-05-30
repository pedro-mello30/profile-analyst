# Observability — MLflow tracing for the profile-analyst pipeline

Self-hosted MLflow observability (spec 0006). Additive and best-effort: the
pipeline runs identically when observability is disabled or the server is down.

## Quick start

```bash
# Install the observability extra
pip install -e ".[observability]"

# Start the local MLflow server
mlflow server --host 127.0.0.1 --port 5000

# Enable and run a RAG query
OBSERVABILITY_ENABLED=true \
python3 profile_analyst.py --handle sample_creator --rag "Find fitness creators"

# Open the UI
open http://127.0.0.1:5000
```

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `OBSERVABILITY_ENABLED` | `false` | Master switch. Set `true` to enable. |
| `MLFLOW_TRACKING_URI` | `http://127.0.0.1:5000` | MLflow server URI. |
| `MLFLOW_EXPERIMENT` | `influencer-rag-observability` | Experiment for pipeline runs. |
| `MLFLOW_EXPERIMENT_EVAL` | `influencer-rag-eval` | Experiment for RAG eval runs. |

## Run the evaluation harness

```bash
OBSERVABILITY_ENABLED=true make eval
```

Prints aggregate `relevance_to_query/mean`, `retrieval_groundedness/mean`,
`retrieval_sufficiency/mean` to stdout and logs to the `influencer-rag-eval`
experiment.

## Production (Docker Compose + PostgreSQL + MinIO)

```bash
git clone --depth 1 --filter=blob:none --sparse https://github.com/mlflow/mlflow.git
cd mlflow && git sparse-checkout set docker-compose
cd docker-compose && cp .env.dev.example .env && docker compose up -d
```

## Trace tree

```
influencer_rag (CHAIN)
├── hybrid_retrieve (RETRIEVER)
│   ├── vector_retrieve (TOOL)
│   └── graph_retrieve  (TOOL)
├── calculate_fraud_risk (TOOL)   ← logs signal.* params + fraud_risk_score metric
└── chat.completions.create (LLM) ← auto-traced via mlflow.openai.autolog()
```

## Compliance notes

- No raw Art. 9 content is written into trace payloads (spec D9).
- The MLflow store is treated as personal-data-bearing; subject to the same
  erasure path as pipeline artifacts (manual for now — see spec OQ2).
- OpenTelemetry export to Grafana/Prometheus/Datadog is deferred (spec N1).
