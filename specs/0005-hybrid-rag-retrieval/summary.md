# Spec 0005 — Hybrid RAG Retrieval: Sumário Executivo

**Status:** accepted · **Data:** 2026-05-30 · **Método:** Spec-Driven Development

> Resumo em português da especificação `spec.md`. A fonte de verdade é o `spec.md` (em inglês).

---

## Problema que resolve

A spec 0003 dá às equipes de marca/analytics um caminho **NL→Cypher**: a pergunta vira um Cypher
somente-leitura, executado, respondido a partir das linhas retornadas. Exato e auditável, mas com
dois pontos cegos estruturais:

- **Só encontra o que um padrão de grafo exato casa.** "Quais criadores combinam com uma marca de
  *activewear sustentável*?" não tem predicado Cypher único — a intenção é *semântica*, exige casar
  significado em bios/legendas/sinais de nicho, não um valor literal de propriedade.
- **Busca puramente vetorial perde termos exatos e relações.** Bios e legendas carregam tokens que
  precisam casar literalmente — `#ad`, `@nike`, um handle, um SKU, uma hashtag de campanha — e os
  embeddings densos borram isso. E as perguntas de maior valor são *relacionais multi-hop*
  ("criadores que colaboraram com X **e** compartilham audiência com Y **e** têm fraud_risk < 0.2"),
  terreno do grafo, não de um índice vetorial.

Nenhum modo único serve à intenção de influencer marketing.

---

## O que o spec entrega

Adiciona **Hybrid RAG**: busca **vetorial** densa + travessia de **grafo** multi-hop + **keyword
(full-text/BM25)** esparsa, fundidas com Reciprocal Rank Fusion (RRF), opcionalmente re-ranqueadas,
e então respondidas pelo backend Ollama da 0003 — tudo local, com citações e linhagem de sinais.

| Capacidade | Resumo |
|---|---|
| **Stage 8 EMBED** | Backfill idempotente de embeddings em nós `Creator`/`Media` existentes; re-embeda só quando `text_hash`/`embedding_model_version` muda. |
| **Três modos de retrieval** | Vetorial (`db.index.vector.queryNodes`), grafo (reusa NL→Cypher da 0003), keyword (`db.index.fulltext.queryNodes`). |
| **Fusão RRF** | RRF (k=60) com pesos por modo nomeados; sem normalização de score entre modos. |
| **Reranker opcional** | Cross-encoder local, **desligado por padrão** (`RAG_RERANK=false`). |
| **Geração ancorada** | Resposta só a partir dos registros recuperados, com citações e linhagem Art. 22; egress local-only. |

---

## O que não entra (YAGNI)

| Fora de escopo | Motivo |
|---|---|
| Algoritmos GDS (Louvain/centralidade/predição de links) | Spec 0004; a 0005 só *lê* esses sinais quando presentes. |
| Segundo banco vetorial (Qdrant/pgvector) | Índices nativos do Neo4j bastam (N1). |
| Embeddings/rerank hospedados (cloud) | Local-only (N4); só atrás de opt-in explícito. |
| RAG conversacional multi-turno / memória | Pergunta única e stateless (N5). |
| Caminho de escrita do retrieval para o grafo/JSON | Retrieval é somente-leitura (N3); só o Stage 8 escreve (upsert de embeddings). |

---

## Alinhamento constitucional

| Princípio | Como este spec se alinha |
|---|---|
| **Explicabilidade (Art. 22)** | Toda resposta de ranqueamento inclui a cadeia de sinais (`CONTRIBUTED_TO`/`HAS_SIGNAL`); ranking é só consultivo, humano confirma. |
| **Dados especiais (Art. 9)** | Candidato com `art9_risk:true` dispara aviso Art. 9 na resposta; nunca silenciosamente resumido. |
| **Minimização / egress** | Embedding, retrieval, rerank e geração rodam no host; manifesto registra `data_egress: local-only`. |
| **Governança** | Retrieval nunca retorna `Creator` que falhou o gate de governança da 0002; embeddings só para nós aprovados. |
| **Idempotência** | Stage 8 espelha o contrato do Stage 7 (0002): reexecução sem mudança é no-op. |

---

## Decisões Locked (D1–D9)

| # | Decisão | Fundamento |
|---|---|---|
| D1 | Hybrid RAG = três modos (vetor + grafo + keyword/BM25) fundidos, rerank opcional, resposta pelo Ollama da 0003 | Nenhum modo único serve à intenção (semântico/multi-hop/termo exato). |
| D2 | Um só store: índice vetorial + full-text nativos do Neo4j junto ao grafo 0002; sem segundo banco | Neo4j 5.13+ traz ambos; fusão compartilha identidade (`user_id`/`media_id`). |
| D3 | Embeddings local-only via Ollama (`nomic-embed-text`, 768-dim) | Mantém a garantia `data_egress=local-only` da 0003. |
| D4 | Stage 8 EMBED idempotente; re-embeda só com `text_hash`/versão alterada | Espelha a idempotência do Stage 7 (0002). |
| D5 | RRF (k=60) com pesos nomeados; sem normalização entre modos | RRF opera sobre ranks, robusto a escalas incomparáveis. |
| D6 | Reranker cross-encoder opcional e **off por padrão**, local quando ligado | Precisão a custo de latência/dependência; v1 enxuta. |
| D7 | Leg de grafo reusa o NL→Cypher da 0003 (gates S1–S6 + txn read-only) | Dono único dos gates de segurança; retrieval read-only. |
| D8 | Numeração: 0004 fica para GDS; Hybrid RAG é 0005 | Respeita referências cruzadas existentes. |
| D9 | Geração só a partir dos registros, com citações e linhagem Art. 22 | Garantia de ancoragem (0003 C5) + explicabilidade (0001). |

(Espelha o bloco `decisions:` do metadata.yml.)

---

## Arquitetura em resumo

```
--rag "pergunta" → tools/rag.py
  1. embeda pergunta (Ollama /api/embeddings)
  2. VECTOR | GRAPH (NL→Cypher 0003) | KEYWORD (BM25)   → Neo4j (read txn)
  3. FUSE (RRF) → 4. RERANK (opcional, off) → 5. GERA (OllamaBackend 0003)
  6. manifesto projects/<h>/queries/<ts>-rag.json

--stage 8 (EMBED) → pipeline/stage8_embed.py
  text_hash gate → embeda → upsert c.embedding / m.embedding (idempotente)
  + índices vector/fulltext → 08-embed-manifest.json
```

| Modo | Procedimento | Serve a |
|---|---|---|
| Vetor | `db.index.vector.queryNodes` | semântico / paráfrase |
| Grafo | NL→Cypher 0003 (read-only) | multi-hop / relacional / fraud-ring |
| Keyword | `db.index.fulltext.queryNodes` | termos exatos (`#ad`/`@handle`/SKU) |

---

## Tracks de implementação (dependency-ordered)

```
A → B, C → D → G
B, C → E → G
A → F → G
D, G → H
```

| Track | Entregável | Dependências |
|---|---|---|
| A | Schemas (`09-embed`, `10-rag`), env config, deps, Makefile | — |
| B | `ensure_rag_indexes` — índices vector + full-text (Neo4j 5.13+) | A |
| C | `OllamaEmbedder` — cliente `/api/embeddings` local | A |
| D | Stage 8 EMBED (gate `text_hash`, upsert) | B, C |
| E | Retrievers vetor / keyword / grafo (via 0003) | B, C |
| F | Fusão RRF + reranker opcional (off) | A |
| G | `HybridRAGOrchestrator` + geração ancorada (0003) | D, E, F |
| H | Wiring de CLI + `tests/rag/` (A1–A12) | D, G |

---

## Critérios de aceitação (sumário)

- **A1–A2:** Stage 8 cria embeddings + índices e manifesto válido; reexecução = zero re-embeds.
- **A3–A5:** vetor recupera paráfrase; keyword recupera termo exato; grafo passa pelos gates da 0003.
- **A6–A7:** RRF determinística com pesos sobreescrevíveis; reranker liga/desliga e registra modelo.
- **A8–A9:** resposta ancorada e citada (zero-result sem invenção); egress `local-only` (teste sem rede).
- **A10:** aviso Art. 9 e linhagem Art. 22 nas respostas de ranking.
- **A11–A12:** erros claros (Ollama down / índice ausente); `make validate` passa com os dois schemas.

---

## Riscos principais

| Risco | Mitigação |
|---|---|
| Neo4j 5.13+ e Ollama indisponíveis no CI | Fusão é pura e testada sem serviços; testes de embed/retriever via testcontainers/marker, pulam sem instância. |
| Lock-in de dimensão de embedding (OQ1) | Fixar `nomic-embed-text` (768) na v1; `ensure_rag_indexes` recusa em mismatch ("rebuild required"). |
| Regressão de egress hospedado | Embedder/reranker local por construção; teste sem-rede afirma `local-only`; Stage 8 recusa endpoint não-local sem opt-in. |
| Granularidade media↔creator (OQ4) | Roll-up por max por padrão; estratégia registrada no manifesto. |
| Escopo grafo-inteiro vs handle (OQ5) | `--rag` sobre o grafo inteiro por padrão; `--handle` é filtro opcional. |
