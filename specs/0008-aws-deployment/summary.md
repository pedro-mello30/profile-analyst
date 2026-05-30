# Spec 0008 — AWS Deployment (ECS Fargate): Sumário Executivo

**Status:** draft → accepted · **Data:** 2026-05-30 · **Método:** Spec-Driven Development

---

## Problema que resolve

Spec 0007 empacota o pipeline em Docker Compose, mas sua postura é explicitamente **single-host**
com datastores locais, `.env` injeção de secrets, e GPU obrigatória no Ollama. Isso é correto para
um box de desenvolvimento, mas não oferece uma **implantação durável na nuvem**: nem durabilidade
multi-AZ, nem escalabilidade, nem gerenciamento de secrets em nível de produção.

Três lacunas concretas bloqueiam rodar isso em AWS:

1. **Sem runtime gerenciado.** Uma única caixa EC2 rodando docker-compose é um "pet", não "cattle":
   sem substituição baseada em saúde, sem deploys sem-tempo-de-inatividade, sem durabilidade multi-AZ.
   O pipeline de lote (handle → dossier) e a API read-only têm ciclos de vida diferentes.

2. **GPU + Fargate são incompatíveis.** Fargate não tem suporte a GPU. Uma implantação na nuvem deve
   defaultar o Stage 3 / `/ask` para a **API Anthropic** (sem GPU), ou rodar Ollama em capacidade
   EC2 separada com GPU — não em Fargate.

3. **Estado local não sobrevive a "cattle".** A árvore `projects/`, neo4j_data, Postgres do MLflow, e
   bucket MinIO desaparecem quando uma task é substituída. Precisam mover para armazenamento
   **compartilhado, multi-AZ, durável**: **EFS** para a árvore `projects/` e dados do Neo4j,
   **RDS** para o backend do MLflow, **S3** para o artifact store (substituindo MinIO).

---

## O que o spec entrega

Uma **implantação ECS Fargate na AWS** que carrega o 0007 sem mudanças no pipeline. Principais entregáveis:

| Capacidade | Resumo |
|---|---|
| **ECS Fargate services** | api + neo4j + mlflow rodando em ≥2 AZs, atrás de ALB com HTTPS (ACM), saúde por /healthz |
| **Async batch runs** | POST /runs enfileira um handle → SQS → ECS RunTask worker executa pipeline → GET /runs/{id} status |
| **Durable shared state** | EFS: projects/ + neo4j_data; RDS: MLflow metadata; S3: MLflow artifacts (MinIO →  S3) |
| **Managed secrets** | AWS Secrets Manager para ANTHROPIC_API_KEY, NEO4J_PASSWORD, RDS URI; injetado no task-definition, nunca baked (0007 C1/A7) |
| **Anthropic-default** | LLM_BACKEND=anthropic é o padrão na nuvem (sem GPU). Ollama é opt-in via EC2 GPU capacity provider |
| **Compliance fim-a-fim** | Art.17 erasure em EFS+Neo4j+S3; gate ToS; lineage Art.9/Art.22; metadados de governança carregados; local-only-egress preservado |
| **IaC (Terraform)** | VPC, ALB, ECS cluster, storage, secrets, IAM, Cloud Map DNS — tudo idempotente; output para copy-paste em `.env` |

---

## O que não entra (YAGNI)

| Fora de escopo | Motivo | Futura |
|---|---|---|
| Kubernetes / EKS | Fora (N2): ECS Fargate only; EKS é Future Work | — |
| GPU on Fargate | Impossible (N4); GPU é opt-in EC2 profile | — |
| CI/CD pipeline | Fora (N5): build + push manual v1; GitHub Actions / CodePipeline é Future Work | — |
| Multi-region DR | Fora (N7): single region, multi-AZ; cross-region replication é Future Work | — |
| Autoscaling tuning | Documentado mas não gatekeyed (N8); target-tracking é Future Work | — |
| Managed Neo4j AuraDB | Neo4j self-managed em Fargate+EFS (default); Aura é alternativa (OQ6) | — |
| Authenticated MLflow UI | Privado por padrão (N6); caminho ALB autenticado é Future Work (OQ4) | — |

---

## Alinhamento com princípios de design

| Princípio | Como este spec se alinha |
|---|---|
| **Spec como fonte de verdade** | spec.md §1–9 definem topologia AWS, sem mudança no pipeline (0001–0007 intocados) |
| **Sem mudanças no pipeline logic** | Mesmo 0007 image, mesmos entrypoints; net-new code é apenas enqueue/worker orchestration |
| **Idempotência** | Terraform é idempotente; `terraform plan` limpo em re-run; ECS services são cattle (replaceable) |
| **Conformidade fim-a-fim** | Art.17 erasure em estado durável (EFS); Art.9/Art.22 lineage preservado; governança carregada; ToS gate honrado |
| **Local-egress option preservada** | LLM_BACKEND=anthropic é default (via NAT); LLM_BACKEND=ollama + EC2 GPU profile = VPC-only (opt-in D6) |
| **YAGNI** | Sem K8s, sem multi-region, sem features de produção não-essenciais (OQ documentadas); v1 = core stack só Fargate |

---

## Decisões Locked (D1–D7)

| # | Decisão | Fundamento |
|---|---|---|
| D1 | ECS Fargate lift do 0007 sem mudanças no pipeline | Managed runtime, multi-AZ, health replacement; imagem 0007 reutilizada |
| D2 | api (sempre-on service) + worker (RunTask on-demand) | Ciclos de vida diferentes (query vs batch); escalabilidade independente |
| D3 | Durable state: EFS (projects+neo4j), RDS (MLflow meta), S3 (artifacts) | Container-local morre em replacement; AWS-native equivalents (EFS=shared, RDS=managed, S3=native) |
| D4 | Anthropic API = default; Ollama = opt-in EC2 profile | Fargate sem GPU; LLM_BACKEND selector permite choice |
| D5 | Secrets Manager + task-definition secrets block | No .env in prod; runtime injection; 0007 C1/A7 carregado |
| D6 | Cloud Map private DNS (neo4j.analyst.local) | Resolve compose service names dentro do VPC; private-by-default |
| D7 | Terraform IaC, S3+DynamoDB state | Cloud-agnostic-ish; idempotent; CI-ready |

---

## Arquitetura em resumo

```
Internet ─ HTTPS (ACM) ─ ALB ─┐
                               ├─ api (Fargate, /ask /rag /runs /healthz)
                               ├─ neo4j (Fargate, EFS data)
                               ├─ mlflow (Fargate, RDS meta, S3 artifacts)
                               ├─ SQS (runs queue + DLQ)
                               └─ worker (Fargate, RunTask on-demand, CLI mode)

EFS (projects/ + neo4j_data, multi-AZ, shared)
RDS PostgreSQL (MLflow backend, multi-AZ)
S3 (MLflow artifacts, MinIO dropped)
Secrets Manager (ANTHROPIC_API_KEY, NEO4J_PASSWORD, RDS URI)
Cloud Map (DNS privado: neo4j.analyst.local, ollama.analyst.local, mlflow.analyst.local)

opt-in: EC2 GPU capacity provider → ollama service (when LLM_BACKEND=ollama)
```

Sem mudanças no pipeline. Compliance (Art.17, Art.9, Art.22, ToS, governança) carregado.

---

## Tracks de implementação (dependency-ordered)

```
A (Infrastructure)  ─┐
B (API + ECR)      ─┼─→ D (Smoke tests)
C (Worker)         ─┘
```

| Track | Entregável | Dependências | Exit |
|---|---|---|---|
| A | Terraform IaC (VPC, ALB, ECS, EFS, RDS, S3, SQS, secrets, IAM) | — | `terraform plan` limpo; recursos provisioned |
| B | ECR image push; POST/GET /runs endpoints (runs.py) | A (SQS URL, secrets ARNs) | /runs endpoints callable; image no ECR |
| C | Worker loop (worker.py); ECS RunTask orchestration | A, B (SQS, task role, task def) | Batch run → EFS artifacts; status marker |
| D | Smoke tests (11 assertions); documentação; validação | A, B, C (stack deve estar healthy) | All tests pass; `make validate` green |

---

## Critérios de aceitação (sumário)

- **A1:** terraform apply provisiona VPC, ALB, ECS, EFS, RDS, S3, SQS, secrets, IAM; plan idempotente
- **A2:** GET /healthz retorna 200; target group ALB ≥1 task saudável
- **A3:** POST /runs retorna {run_id, status:queued}; worker task executa; artifacts no EFS; GET /runs/{id} → succeeded
- **A4:** Stage 7 popula Neo4j cloud (Creator/Media/Signal/Score nodes)
- **A5:** /ask retorna resposta fundamentada; mutação rejeitada; /rag funciona com Stage 8
- **A6:** Sem secrets em docker history; task-definition secrets valueFrom funciona; remover secret → task falha iniciar
- **A7:** Killing/restart api task → projects/ e Neo4j graph persistem (EFS + RDS)
- **A8:** MLflow com OBSERVABILITY_ENABLED=true → trace metadata em RDS + artifacts em S3
- **A9:** Core stack roda em Fargate com LLM_BACKEND=anthropic, sem GPU
- **A10:** Ollama profile opt-in provisiona EC2 GPU; /ask funciona LLM_BACKEND=ollama, zero NAT egress
- **A11:** erase --handle → projects/{handle}/ deletado no EFS (Art.17 em AWS)
- **A12:** Apenas ALB internet-facing; neo4j/ollama/mlflow/RDS privados (security group audit)
- **A13:** Invalid handle → status:failed, message → DLQ, sem crash loop

---

## Riscos principais

| Risco | Mitigação |
|---|---|
| Secrets Manager injection falha na inicialização de task | Task execution role com GetSecretValue; IAM policy permite; testar com secret dummy antes de full deploy |
| EFS performance sob carga | v1 single EFS; documentar workloads read-heavy; DynamoDB (OQ3) se metadados escalarem |
| RDS replica lag | MLflow metadata não-crítico; RPO/RTO aceitável; runbook failover documentado |
| Ollama GPU profile untested em CI | Documented opt-in; smoke test skips default; GPU prerequisites documentados em README |
| SQS poison messages | Monitor DLQ depth; drain manual documentado; default 3 retries antes de DLQ |

---

## Tracks e dependencies

A, B rodáveis em paralelo (nenhuma dependency). C depende de A, B. D depende de A–C.

A→ B, C→ D → done.

Estimated ~2–3 semanas bare-bones (Terraform + runs.py + worker.py); +1 semana smoke tests + docs.

---

## Alinhamento constitucional

- **Spec-driven:** toda mudança tem seção correspondente em spec.md
- **Sem pipeline-logic changes:** 0007 image intocada; apenas orchestração AWS + enqueue
- **Conformidade:** Art.17/Art.9/Art.22/ToS/governança carregado; erasure em estado durável
- **YAGNI:** sem K8s, sem multi-region, sem autoscaling tuning (documentado, não gatekeyed)
