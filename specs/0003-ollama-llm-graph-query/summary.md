# Resumo 0003 — Consulta ao Grafo com LLM Local (Ollama)

> Resumo em português da especificação `spec.md`. A fonte de verdade é o `spec.md` (em inglês).

## O que é

A spec 0002 carrega o dossiê do criador no Neo4j, mas as consultas de auditoria são fixas (AQ1–AQ4,
exigem Cypher escrito à mão) e o Stage 3 só roda na API hospedada da Anthropic. Esta especificação
adiciona o **Ollama como provedor de LLM local** em dois pontos:

1. **Interface NL→Cypher** (`tools/ask.py`, flag `--ask`): o usuário pergunta em linguagem natural,
   um modelo local traduz para um Cypher **somente-leitura e validado**, executa contra o grafo da
   0002 e responde **apenas com base nas linhas retornadas** — nunca com o conhecimento do modelo.
2. **Backend de LLM plugável no Stage 3** (`anthropic | ollama`, via `LLM_BACKEND`): a extração de
   features pode rodar localmente, com a **mesma** validação contra `03-features.schema.json`.

Nenhum dado do criador sai do host quando o backend é `ollama`.

## Decisões principais

- **D1 — Ollama em dois pontos:** ferramenta NL→Cypher + backend plugável do Stage 3.
- **D2 — NL→Cypher é estritamente somente-leitura e aditivo;** as consultas AQ1–AQ4 da 0002
  continuam sendo o caminho exato e confiável.
- **D3 — Segurança = allowlist somente-leitura + validação** (denylist de escrita/admin, statement
  único, ancoragem no schema, limites de recursos, parametrização) + transação somente-leitura.
- **D4 — Protocolo `LLMBackend` plugável** (`anthropic | ollama`) por `LLM_BACKEND`; ambos emitem o
  `03-features.schema.json` inalterado.
- **D5 — Modelos por papel:** `OLLAMA_CYPHER_MODEL` padrão `qwen2.5-coder:32b` (código/estruturado),
  `OLLAMA_FEATURES_MODEL` padrão `qwen2.5:14b` (raciocínio/explicabilidade); ambos sobrescrevíveis.
- **D6 — Manifesto de consulta** por interação (pergunta, modelo, cypher, params, validação, linhas,
  resposta), validado contra `schemas/08-query.schema.json`; registra `data_egress=local-only`.
- **D7 — Algoritmos GDS renumerados da 0003 para a spec 0004;** esta spec assume o número 0003.

## Segurança da consulta (§6)

Todo Cypher gerado passa por **todos** os portões antes de executar, num único módulo
`tools/cypher_safety.py`: **S1** denylist de escrita/admin + allowlist positiva de `CALL`;
**S2** statement único; **S3** transação `execute_read` (+ papel somente-leitura no Neo4j);
**S4** ancoragem no schema (labels/relações/propriedades têm de existir); **S5** `LIMIT` automático
+ timeout; **S6** parametrização. A varredura de palavras-chave roda sobre o texto **sem strings
nem comentários**, evitando falso-positivo ("CREATE" numa legenda) e contrabando em comentário.
Rejeições levantam `QueryRejectedError` com `reason_code` legível por máquina.

## Conformidade (herdada da 0001 §9 / 0002 §7)

- **Art. 22 — modelo na explicação:** o manifesto registra qual modelo e versão produziram cada
  resposta (pergunta → modelo → Cypher → linhas → resposta).
- **Art. 9:** consultas que tocam sinais `art9_risk` exibem um aviso do Art. 9 na resposta.
- **Sem egresso externo:** com `LLM_BACKEND=ollama`, nenhum dado vai para API externa
  (`data_egress=local-only`).
- **Garantia de ancoragem:** a resposta usa só as linhas retornadas; zero linhas → diz que não há
  dados, sem inventar fatos.
- **Paridade do Stage 3:** a saída do `OllamaBackend` valida contra `03-features.schema.json` com
  `confidence`, `method` (`llm`), `art9_risk` e `ftc_disclosure_status`.

## Critérios de aceite (resumo)

A1 `--ask` gera Cypher somente-leitura, executa e grava manifesto válido · A2 pergunta de mutação é
rejeitada antes de executar · A3 transação somente-leitura barra escrita · A4 propriedade inexistente
rejeitada (ancoragem) · A5 zero linhas não inventa fatos · A6 Stage 3 com Ollama gera
`03-features.json` válido · A7 proveniência (modelo/papel/`data_egress`) · A8 erro claro com Ollama
fora do ar + fallback Anthropic · A9 aviso do Art. 9 · A10 `make validate` passa com o novo schema.

## Tracks de implementação (dependency-ordered)

```
A ──► B ──┐
     └──► (B,C) ──► D ──► E
A ──► C ──┘
```

| Track | Entregável | Dependências |
|---|---|---|
| A | Schema `08-query`, config/env, deps, `make ask` | — |
| B | `pipeline/llm/` (base, anthropic, ollama_client, ollama_backend) + swap do Stage 3 | A |
| C | `tools/cypher_safety.py` (S1–S6, reason codes) | A |
| D | `tools/ask.py` (NL→Cypher somente-leitura + manifesto) | B, C |
| E | Wiring de CLI `--ask` + testes (A1–A10) | B, C, D |

## Fora de escopo (YAGNI)

| Fora de escopo | Motivo |
|---|---|
| Algoritmos GDS (Louvain/centralidade/predição de links) | spec 0004 |
| Agente conversacional multi-turno / memória | até NL→Cypher single-shot ser confiável |
| Fine-tuning / treino de modelos | só modelos stock do Ollama |
| Caminho de escrita no grafo via LLM | NL→Cypher é somente-leitura por construção |
| Harness de benchmark entre modelos | trabalho futuro |

## Riscos principais

| Risco | Mitigação |
|---|---|
| Ollama/Neo4j indisponíveis no CI | `cypher_safety` e backends são puros/mockáveis; testes de DB usam `--integration`/testcontainers e pulam quando ausentes |
| Bypass da denylist | varre texto sem strings/comentários, match por token, allowlist positiva de `CALL`, ancoragem no schema, transação somente-leitura |
| Qualidade do modelo local (Cypher/JSON inválido) | saída estruturada + portão de validação; reparo único (OQ1); `qwen2.5-coder:32b` padrão |
| Determinismo do Stage 3 | `temperature=0` + seed fixo (OQ4); validação é a fonte de verdade |
