# Resumo 0006 — Observabilidade com MLflow

> Resumo em português da especificação `spec.md`. A fonte de verdade é o `spec.md` (em inglês).

**Status:** accepted · **Data:** 2026-05-30 · **Método:** Spec-Driven Development

---

## Problema que resolve

A pipeline já produz o dossiê (0001), persiste o grafo no Neo4j (0002), responde consultas em
linguagem natural via LLM local Ollama (0003) e serve respostas por um laço de RAG híbrido (0005).
Esses passos são **opacos**: quando um criador recebe um score alto/baixo de risco de fraude, ou
quando uma resposta de RAG parece errada, não há registro estruturado de *quais sinais*, *qual
contexto recuperado* e *quais parâmetros de modelo* produziram o resultado.

Isso trava duas frentes ao mesmo tempo:

- **Engenharia** — depurar latência, custo em tokens, qualidade de recuperação e regressões entre
  versões de modelo/prompt.
- **Conformidade** — o Art. 22 do GDPR exige que todo score que afeta criadores (seleção de
  campanha, sinalização de fraude) seja **explicável e auditável**. Falta o registro durável de
  *como os sinais foram combinados em tempo de execução* e *qual modelo mediou a resposta*.

Esta especificação adiciona o **MLflow** (auto-hospedado, open-source) como backend de
observabilidade: tracing de LLM, spans customizados para grafo/recuperação/fraude, registro de
linhagem de sinais, harness de avaliação e rastreamento de experimentos. É compatível com
OpenTelemetry — sem dependência de SaaS nem lock-in.

---

## O que o spec entrega

| Capacidade | Resumo |
|---|---|
| **Tracing automático de LLM** | `mlflow.openai.autolog()` captura prompt, resposta, latência, tokens, modelo e parâmetros das chamadas Ollama (0003) sem mudança no call site. |
| **Spans manuais** | Decorador `@trace(span_type=…)` instrumenta consultas Neo4j (0002), recuperação híbrida (0005) e algoritmos GDS de fraude (0004) aninhados sob a requisição. |
| **Linhagem de sinais (Art. 22)** | `log_signal_lineage(...)` grava cada sinal como `param` e o score como `metric`, completando a cadeia de explicabilidade do 0001/0002/0003. |
| **Harness de avaliação** | `mlflow.genai.evaluate` com juízes nativos (relevância, groundedness, suficiência) sobre dataset versionado; `make eval`. |
| **Rastreamento de experimentos** | Comparar modelos, prompts e estratégias de recuperação lado a lado. |
| **Best-effort + auto-hospedado** | Falha de servidor degrada para no-op (nunca quebra a pipeline); exportável via OpenTelemetry. |

Taxonomia fixa de spans: `CHAIN` / `RETRIEVER` / `LLM` / `TOOL`.

---

## O que não entra (YAGNI)

| Fora de escopo | Motivo |
|---|---|
| Alerta/paging em tempo real + export Grafana/Prometheus/Datadog | Limiares apenas documentados (§10); fiação fica para trabalho futuro (N1). |
| Tracing distribuído multi-host | v1 assume host único (N2). |
| Substituir os artefatos JSON por etapa | Tracing é **aditivo**; os artefatos canônicos seguem inalterados (N3). |
| Tracing obrigatório dos Stages 1–2 (ingest/normalize) | Pouco conteúdo LLM/grafo; opcional em v1 — começa no Stage 3 e no caminho de RAG (N4). |
| Apagamento GDPR automatizado dos runs/traces do MLflow | Sinalizado como follow-up (OQ2). |

---

## Decisões Locked (D1–D10)

| # | Decisão | Fundamento |
|---|---|---|
| D1 | MLflow auto-hospedado como backend de observabilidade | Open-source, gratuito, compatível com OTel; tracing + avaliação + experimentos nativos. |
| D2 | `mlflow.openai.autolog()` no caminho Ollama | Ollama é compatível com a API OpenAI; uma linha auto-rastreia todas as chamadas. |
| D3 | Spans manuais via `@mlflow.trace(span_type=…)` | Consultas Neo4j, recuperação híbrida e GDS precisam de spans aninhados. |
| D4 | URI, experimento e liga/desliga via env; helpers viram no-op | Precisa ser desligável em testes/CI e apontável para qualquer servidor. |
| D5 | Scores registram sinais via `log_params` + score via `log_metric` | Mapeamento direto à explicabilidade do Art. 22; linhagem durável e consultável. |
| D6 | Taxonomia fixa `CHAIN`/`RETRIEVER`/`LLM`/`TOOL` | Árvore de traces estável e inspecionável. |
| D7 | Avaliação com juízes nativos do MLflow | Métricas padrão e comparáveis, sem manutenção de juiz próprio. |
| D8 | Falhas de observabilidade NÃO podem quebrar a pipeline | Indisponibilidade do servidor degrada para no-op, nunca exceção ao usuário. |
| D9 | Nenhum conteúdo de categoria especial (Art. 9) cru nos payloads de trace | Traces são novo armazenamento de dados pessoais; herdam a minimização do Art. 9. |
| D10 | Esta é a spec 0006; 0004 segue reservada para o Neo4j GDS | Respeita as referências cruzadas das specs 0002/0003/0005; segue o RAG híbrido (0005). |

(Espelha o bloco `decisions:` do `metadata.yml`.)

---

## Arquitetura em resumo

```
profile_analyst.py (CLI) · tools/rag.py (0005)
   └─ init_tracing()  → set_uri + set_experiment + openai.autolog()  (no-op se desligado)

observability/  config.py · tracing.py · spans.py · lineage.py · evaluation.py · eval/rag-eval.jsonl

Árvore de trace alvo:
  influencer_rag (CHAIN)                    # 0005
  ├─ hybrid_retrieve (RETRIEVER)            # 0005
  │   ├─ neo4j_vector_search (TOOL)         # 0002
  │   └─ neo4j_graph_traversal (TOOL)       # 0002
  ├─ detect_engagement_pods (TOOL)          # 0004 GDS (quando presente)
  ├─ calculate_fraud_risk (TOOL)            # → log_signal_lineage(...)
  └─ chat.completions.create (LLM)          # 0003 Ollama (auto-traced)
        → MLflow self-hosted (exportável via OpenTelemetry)
```

---

## Tracks de implementação (dependency-ordered)

```
A → {B, C, D} → E → F → G
```

| Track | Entregável | Dependências |
|---|---|---|
| A | Pacote `observability/` + `config.py` + extra `[observability]` | — |
| B | `init_tracing()` + autolog Ollama (best-effort, no-op se desligado) | A |
| C | Decorador `trace()` + taxonomia + hook de redação Art. 9 | A |
| D | `log_signal_lineage()` (Art. 22) | A |
| E | Integração nos pontos do §4.3 (preserva comportamento) | B, C, D |
| F | Harness de avaliação + `rag-eval.jsonl` + `make eval` | E |
| G | Testes (`tests/observability/`) + docs | A–F |

---

## Critérios de aceitação (sumário)

- **A1–A2:** com observabilidade ligada, uma consulta de RAG gera **um** trace `CHAIN` contendo
  `RETRIEVER`, ≥1 `TOOL` e ≥1 `LLM`; cada span `LLM` registra prompt/resposta/latência/tokens/
  modelo/parâmetros.
- **A3:** `calculate_fraud_risk` registra cada sinal como `signal.*` e o score como métrica (Art. 22).
- **A4–A5:** com observabilidade **desligada**, a pipeline roda idêntica sem nenhuma emissão; um
  `MLFLOW_TRACKING_URI` inacessível **não** lança exceção (best-effort).
- **A6:** `make eval` imprime as médias agregadas de relevância/groundedness/suficiência.
- **A7:** nenhum conteúdo cru de Art. 9 aparece nos payloads de trace (teste de redação).
- **A8:** `make validate` e `make test` passam com os novos testes.

---

## Riscos principais

| Risco | Mitigação |
|---|---|
| Servidor MLflow indisponível no CI | Testes usam cliente em processo/mock ou validam o caminho no-op; servidor ausente é condição testada (A5). |
| Mudança na API `openai.autolog()` entre versões do MLflow | Fixar minor conhecida no extra `[observability]`; isolar a chamada em `tracing.py`. |
| Vazamento de Art. 9 nos payloads de trace | Hook de redação em todo span sensível; `test_redaction.py` (A7) é portão obrigatório. |
| Sobrecarga quando ligado | Decorador é passthrough quando desligado (padrão em testes/CI); spans só nos pontos nomeados (§4.3). |
| Acoplamento a módulos 0004/0005 ainda não mesclados | Track E decora o que existe; span de GDS é condicional; degrada graciosamente. |
| PII no armazenamento do MLflow (retenção) | Documentado em §9 C3; apagamento automatizado é follow-up (OQ2), fora do escopo de v1. |
