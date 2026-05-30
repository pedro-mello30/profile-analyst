# Resumo 0004 — Neo4j GDS (Graph Data Science)

**Spec:** `specs/0004-neo4j-gds/spec.md`
**Status:** aceito

---

## Problema

A spec 0002 carrega o dossiê no Neo4j mas adia explicitamente todos os algoritmos de **ciência de
dados em grafo** (seu N1, item de trabalho futuro "Spec 0004"). As análises centrais de marketing de
influência são algorítmicas: detecção de pods de engajamento / anéis de fraude (comunidades),
detecção de bots (centralidade), sobreposição de audiência (similaridade de nós) e colaborações
prováveis (predição de links). Travessia pura não as resolve.

## O que entrega

- **Stage 9 GDS** (`pipeline/stage9_gds.py`): projeta o grafo 0002 em memória e roda o conjunto
  completo de algoritmos sobre o **grafo inteiro (cross-handle)**.
- **Algoritmos AL1–AL5:** Louvain (pods), centralidade de grau + intermediação (bots), Node
  Similarity (sobreposição de audiência), predição de links Adamic-Adar (colaborações prováveis).
- **Escrita de volta no grafo:** Signals `community_id` / `degree_centrality` /
  `betweenness_centrality`; arestas `SHARES_AUDIENCE {overlap_pct}` e `COLLABORATED_WITH
  {predicted,probability}` — preenchendo as arestas que a 0002 deixou adiadas `[v2]`.
- **Score `fraud_risk`** como combinação linear de pesos nomeados, com cadeia `CONTRIBUTED_TO
  {weight}` para o GDPR Art. 22.
- **Manifesto** `09-gds-manifest.json` validado por `schemas/11-gds.schema.json`.
- **Idempotência** via `run_id` + supersessão da execução anterior; projeção descartada em `finally`.

## O que NÃO entra (YAGNI)

- Pipeline de ML treinado para predição de links (AL5 usa heurística topológica) → trabalho futuro.
- Mudanças no Stage 7 LOAD ou nos artefatos JSON.
- Banco relacional/documento adicional.
- Fonte de dados Instagram ao vivo; escrita de volta para o JSON.
- Automação de apagamento (GDPR erasure) — segue como follow-up transversal.

## Alinhamento Constitucional

(constituição não encontrada — alinhamento padrão com invariantes 0001/0002: `confidence`/`method`,
`art9_risk`, cadeia de explicabilidade `signals[]`, gate de governança.)

## Decisões (locked)

- **D1–D7:** ver `metadata.yml`. Destaques: plugin GDS exigido (falha rápida se ausente); conjunto
  completo de algoritmos; execução cross-handle; arestas adiadas da 0002 materializadas; `fraud_risk`
  com pesos nomeados e explicabilidade Art. 22; todos os signals `method=computed`, `source=gds`.

## Riscos

- Neo4j + plugin GDS para testes (container com GDS ou skip).
- Normalização de `fraud_risk` instável em grafos pequenos → min-max dentro da execução (OQ3).
- Projeção cross-handle acopla à 0002 OQ3 (merge de `User` compartilhado); fixture precisa de
  múltiplos creators com comentaristas em comum.
- Nomes de procedimentos GDS variam entre versões → fixar versão e validar no gate.

## Próximos passos

- Implementar Track A–E (ver `tasks.md`).
- Spec 0005 (RAG) consome os signals de GDS (centralidade/comunidade) quando presentes.
