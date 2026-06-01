# Spec 0013 — Self-Healing Harness: Sumário Executivo

**Status:** accepted · **Data:** 2026-05-31 · **Método:** Spec-Driven Development

---

## Problema que resolve

O pipeline possui verificadores fortes em cada fronteira de estágio (`jsonschema.validate`,
`Art9Scanner`, `strip_forbidden_features`, status FTC), mas nenhum laço de feedback: uma única
falha de verificação encerra o run e exige reinício manual. O Stage 3, em particular, depende de
saída estocástica de LLM — o modelo às vezes produz JSON sutilmente malformado, um tipo de valor
errado ou um campo obrigatório ausente. Esses são erros de formatação, não falhas semânticas, e
são exatamente o tipo de problema recuperável que feedback estruturado pode corrigir em-loop.

Ao mesmo tempo, padrões sistêmicos (um `feature_id` que falha no schema 12× em 30 runs, uma
métrica de eval que regrediu 8%) ficam invisíveis sem agregação. O laço externo os expõe como um
relatório de diagnóstico que um humano pode agir.

---

## O que o spec entrega

| Capacidade | Resumo |
|---|---|
| **Laço interno (Track A)** | `extract_with_retry()` em `pipeline/llm/retry.py`: injeta o erro estruturado de volta como novo turno do usuário e re-tenta (máx. 2×) antes de falhar para humano |
| **Proveniência auditável** | Cada tentativa registrada em `RetryAttempt`; `notes` do feature recebe `healed:attempt_N/<error_type>`; `confidence` **nunca alterada** |
| **HealExhausted** | Exceção tipada com histórico completo de tentativas — MLflow e o operador veem tudo |
| **Rastreamento MLflow** | `log_retry_attempts()` grava `heal_retry_count` e `retry_attempts.json` no run ativo (no-op se desabilitado) |
| **Laço externo (Track B)** | `tools/heal_sweep.py` agrega padrões de falha de traces MLflow, difere scores de eval contra baseline fixado, emite relatório markdown em `docs/heal-reports/` |
| **make sweep** | Target no Makefile para rodar o sweep periodicamente, sem modificar nenhum arquivo-fonte |

---

## O que não entra (YAGNI)

| Fora de escopo | Motivo | Futuro |
|---|---|---|
| Retentativa em estágios determinísticos (1, 2, 6–9) | Falhas nesses estágios são bugs de dados ou configuração, não saída estocástica | — |
| Auto-aplicação de correções de prompt/schema | O laço fecha através do humano; modificação automática contornaria o processo de revisão spec-driven | OQ4 |
| `HEAL_MAX_RETRIES` configurável por env | Pode ser adicionado sem quebrar o contrato; 2 retentativas é suficiente para v1 | OQ2 |
| Integração com GitHub Issues / Linear | O relatório markdown é suficiente como artefato de handoff | OQ4 |
| Extensão do laço interno para Stage 4 / Stage 5 | Esses estágios não têm saída LLM ainda | spec futura |
| Re-tentativa de falhas de Art.9 | Um flag Art.9 é um sinal real de risco de compliance, não erro de formatação | invariante |

---

## Arquitetura em resumo

```
Stage 3 run()
    │
    ├── extract_with_retry(backend, req, max_retries=2)
    │       │  FAIL (schema / json_decode)
    │       │  → _build_retry_context(error_type, exc)
    │       │  → FeatureRequest(retry_context=...)
    │       │  → backend.extract_features(req_with_context)
    │       │  PASS → _stamp_provenance(response, attempts)
    │       ↓
    │   (FeatureResponse, list[RetryAttempt])
    │
    └── log_retry_attempts(...)  →  MLflow artifacts
                                        │
                                   (periodicamente)
                                        ▼
                                 make sweep
                                 heal_sweep.py
                                 group_failures() → diff_baseline() → render_report()
                                        ↓
                            docs/heal-reports/YYYY-MM-DD.md
                                        ↓
                                    humano → PR
```

`confidence` é aplicado exatamente **uma vez** — pelo modelo. Nenhum código neste spec o altera.
O laço externo nunca escreve em nenhum arquivo de código-fonte, prompt ou schema.

---

## Decisões Locked (D1–D6)

| # | Decisão | Fundamento |
|---|---|---|
| D1 | Laço interno scoped exclusivamente ao Stage 3 (fronteira LLM) | Estágios determinísticos falham por bugs de dados/config, não saída estocástica |
| D2 | Erro estruturado injetado como novo turno `user`; máx. 2 retentativas | Feedback exato (não genérico) dá ao modelo contexto acionável; 2 limita custo de tokens |
| D3 | `confidence` não modificada na retentativa; proveniência exclusivamente em `notes` + `extra.retry_attempts` | Confidence é afirmação epistêmica do modelo sobre o valor, não sinal de confiabilidade estrutural |
| D4 | Falhas Art.9 propagam imediatamente sem entrar no laço de retry | Flag Art.9 é sinal real de risco — o modelo não pode "negociar" um achado de compliance |
| D5 | HealSweep lê traces MLflow, agrupa falhas, emite relatório markdown; nunca toca prompts/schemas/código | O laço fecha pelo humano; modificação automática contorna revisão spec-driven |
| D6 | HealSweep compara scores de eval contra `baseline.json` fixado manualmente; flag regressões > 5% | Regressão de eval é sinal precoce de que mudança de prompt/schema ou drift de modelo prejudicou qualidade |

(Espelha o bloco `decisions:` do `metadata.yml`.)

---

## Tracks de implementação (dependency-ordered)

```
A (laço interno + tracing) ──→ B (sweep externo + make sweep)
```

| Track | Entregável | Dependências | Exit |
|---|---|---|---|
| A | `retry.py` + wiring Stage 3 + `log_retry_attempts` | — | A1–A5 met; `make test` green |
| B | `baseline.json` + `heal_sweep.py` + `make sweep` | A (precisa de traces MLflow) | A6–A7 met; `make sweep` escreve relatório |

---

## Critérios de aceitação (sumário)

- **A1:** `extract_with_retry()` retenta até `max_retries` em erros de schema/decode; `HealExhausted` carrega histórico completo (unit-testado sem modelo ao vivo)
- **A2:** Feature retentada tem `healed:attempt_N/<error_type>` em `notes`; `confidence` idêntica ao que o modelo retornou
- **A3:** Falhas Art.9 propagam imediatamente sem entrar no wrapper de retry
- **A4:** Contexto de retry contém path de schema específico + mensagem, não prompt genérico
- **A5:** Run MLflow inclui artefato `retry_attempts.json` quando retry ocorreu
- **A6:** `make sweep` escreve relatório de diagnóstico; não modifica nenhum arquivo-fonte
- **A7:** `make validate` + `make test` verdes após ambas as tracks

---

## Riscos principais

| Risco | Mitigação |
|---|---|
| Custo de tokens na retentativa (até 3× Stage 3 no caso de falha) | Bound explícito de max 2 retentativas; `HealExhausted` encerra — nunca ciclo infinito |
| `log_retry_attempts` bloqueando o Stage 3 se MLflow estiver fora | Best-effort: erros MLflow capturados com `logger.warning`, nunca propagados (mesmo padrão de `tracing.py` e `spans.py`) |
| HealSweep com histórico MLflow vazio | Renderiza relatório "sem falhas" em vez de levantar exceção |
| Backend Anthropic/Ollama rejeitando `retry_context` como turno extra | Verificado nos testes de backend existentes e nos novos testes de `test_retry.py` |
