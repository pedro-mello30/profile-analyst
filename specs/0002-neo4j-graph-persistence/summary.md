# Resumo 0002 — Persistência em Grafo com Neo4j

> Resumo em português da especificação `spec.md`. A fonte de verdade é o `spec.md` (em inglês).

## O que é

A pipeline 0001 produz um dossiê de criador em JSON, mas não tem banco de grafos. Os casos de
uso centrais de marketing de influência (detecção de fraude, pods de engajamento, sobreposição
de audiência, explicação de scores para o Art. 22 do GDPR) são problemas de **grafo** que o JSON
plano não resolve bem. Esta especificação adiciona o **Neo4j como banco de grafos primário** e um
novo **Stage 7 LOAD** que carrega (upsert) o dossiê no grafo.

## Decisões principais

- **D1 — Spec nova (0002).** A 0001 permanece intacta; a 0002 consome os artefatos das etapas dela.
- **D2 — Neo4j + JSON.** O Neo4j é o banco de grafos; os arquivos `projects/<handle>/*.json`
  continuam sendo o armazenamento de documentos/auditoria. **Nenhum banco relacional novo.**
- **D3 — Stage 7 LOAD dedicado** (`pipeline/stage7_load.py`) lê os JSON e carrega o grafo.
- **D4 — MERGE por chave natural + sinais versionados.** Entidades têm identidade estável entre
  execuções; nós `Signal`/`Score` carregam `run_id` e são substituídos a cada execução
  (idempotência real + trilha de auditoria para o Art. 22).
- **D5 — Escopo = persistência + consultas de auditoria.** Algoritmos de grafo (Louvain,
  centralidade, predição de links) ficam **adiados para a spec 0004** (exigem o plugin GDS).
- **D6 — Driver oficial `neo4j`** com Cypher parametrizado e transações de escrita explícitas.

## Modelo de grafo (resumo)

- **Nós:** `Creator` (chave `user_id`), `Media` (`media_id`), `Comment` (`comment_id`),
  `User` (`username`), `Demographic`, `Signal` e `Score` (versionados por `run_id`).
- **Relações:** `HAS_MEDIA`, `HAS_COMMENT`, `FROM_USER`, `HAS_SIGNAL {weight}`,
  `CONTRIBUTED_TO {weight}`, e (adiadas para v2) `SHARES_AUDIENCE {overlap_pct}`,
  `COLLABORATED_WITH`, `HAS_AUDIENCE_SEGMENT`.

## Conformidade (herdada da 0001 §9)

- Metadados de governança (`gdpr_basis`, `subject_jurisdiction`, etc.) vão para o nó `Creator`;
  a carga falha sem eles, a menos que `--allow-noncompliant` seja passado.
- `art9_risk` é preservado nos nós `Signal`; a consulta AQ3 lista esses sinais.
- **Art. 22:** todo `Score` mantém a cadeia de sinais via arestas `CONTRIBUTED_TO {weight}`;
  a consulta AQ1 reconstrói a explicação completa do score.
- `ftc_disclosure_status` vai para `Media`; a AQ4 lista posts patrocinados não declarados.

## Critérios de aceite (resumo)

A1 carga cria nós/arestas e manifesto válido · A2 reexecução idempotente (sem duplicatas) ·
A3 explicação de score (Art. 22) · A4 flags do Art. 9 preservadas · A5 portão de conformidade ·
A6 associações adiadas quando não há `05-graph.json` · A7 versionamento de sinais/scores ·
A8 `make validate` passa com o novo schema.

## Fora de escopo

Algoritmos GDS (pods/bots/predição de links → spec 0004), banco relacional/documental adicional,
fonte de dados ao vivo do Instagram, e escrita de volta do grafo para o JSON.
