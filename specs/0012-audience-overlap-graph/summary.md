# Spec 0012 — Grafo de Sobreposição de Audiência (Stage 5, v2a): Sumário Executivo

**Status:** draft · **Data:** 2026-05-31 · **Método:** Spec-Driven Development

---

## Problema que resolve

O spec 0001 §7 *desenhou* o Stage 5 (grafo de associações) mas o deixou diferido: o Stage 6 emite um
placeholder `{"associations": {"status": "deferred", "graph_summary": null}}` no dossier. Não existe
nenhum caminho que, dado um conjunto de criadores, construa um grafo criador–criador e descubra
comunidades, centralidade e vizinhos próximos do perfil-semente.

O desenho original do §7 assumia **infraestrutura de banco de grafos** (Neo4j GDS + Leiden). Este
spec implementa a fatia **v2a** desse estágio **sem Neo4j e sem GDS** — o grafo é construído
**em memória com `networkx`** (já uma dependência central) e o único artefato é um JSON
ego-cêntrico. Assim o Stage 5 entra no subconjunto "sem serviços, só filesystem" do pipeline
(`--stage 1,2,3,6`), do mesmo modo que o spec 0011 realizou o Stage 4 v3a a partir de uma fixture
local.

---

## O que o spec entrega

| Capacidade | Resumo |
|---|---|
| **Stage 5 opt-in** | `--stage 5` produz `projects/<handle>/05-graph.json`; `--stage all` continua `1,2,3,6,7,8,9` e **nunca** dispara associações |
| **Coorte on-disk** | `glob projects/*/02-normalized.json`, ordenada por handle; guarda `≥2` membros (levanta abaixo disso); zero rede, zero banco |
| **Motor `networkx` em memória** | **Sem Neo4j, sem GDS**; grafo construído e analisado no processo |
| **2 famílias de aresta (v2a)** | content_similar (Jaccard de tokens niche+hashtag; TF-IDF cosseno opcional) e collaborated (@mentions/co-tags/marcas co-patrocinadas mútuas) — ambas `method="computed"` |
| **Comunidades + centralidade** | Leiden (`leidenalg`+`igraph`, atrás do extra `[associations]`) com fallback Louvain (`networkx`); centralidade degree + PageRank + betweenness (`networkx` nativo) |
| **Artefato ego-cêntrico** | `05-graph.json`: comunidade e centralidade do semente, `neighbors[]` top-N com `signals[]` (≥1), e `communities_summary[]` |
| **Gates de compliance** | `Art9Scanner` marca `art9_risk` por comunidade; Stage 6 redige listas de membros de comunidades Art.9 sem consentimento; cada aresta carrega `signals[]` (Art.22) |

---

## Decisões-chave (D1–D9)

- **D1** Stage 5 é opt-in; `--stage all` permanece `1,2,3,6,7,8,9`.
- **D2** Coorte por `glob` de `02-normalized.json`, ordenada; guarda `≥2` (0001 §7).
- **D3** Motor `networkx` em processo; **Neo4j/GDS não são tocados** — sai do caminho crítico do GDS
  Enterprise e preserva a suíte de testes offline.
- **D4** Duas famílias de aresta: Jaccard de conteúdo (`CONTENT_SIM_THRESHOLD=0.60`; TF-IDF opcional)
  + colaboração. Sobreposição real de audiência (Jaccard de seguidores) **fica para v2b** — não
  existem listas de seguidores (CLAUDE.md).
- **D5** Leiden atrás do extra `[associations]` com fallback Louvain; `community_method` registra qual
  rodou. Centralidade combinada (degree+PageRank+betweenness).
- **D6** `05-graph.schema.json` (draft-7), ego-cêntrico, `additionalProperties:false`.
- **D7** Gates Art.9 (risco de comunidade) + Art.22 (`signals[]`), reaplicados no Stage 5 e no
  Stage 6 (defesa em profundidade).
- **D8** Determinismo: coorte ordenada, algoritmos com seed → `05-graph.json` byte-idêntico em
  re-execuções.
- **D9** Diferido para v2b: sobreposição real de audiência, similaridade por embeddings (Stage 8),
  alcance de-duplicado com IC, e writeback de arestas para Neo4j.

---

## Aceitação (A1–A8, todas `planned`)

Wiring opt-in com `--stage all` inalterado (A1); guarda `≥2` levanta (A2); emissão offline válida no
schema com `signals[]` por aresta (A3); comunidade Leiden + 3 centralidades presentes (A4); fallback
Louvain quando o extra está ausente, registrado em `community_method` (A5); flag Art.9 + redação no
Stage 6 (A6); surfacing no Stage 6 substitui/preserva o placeholder (A7); `make validate` + suíte
offline verdes, sem rede e sem banco, com `05-graph.json` byte-idêntico em duas execuções (A8).

---

## Posição no roadmap

Stage 5 era o **último estágio diferido** do pipeline (Stage 4 foi realizado pelo spec 0011 v3a).
Com o 0012 v2a, o dossier deixa de emitir o placeholder de associações para um perfil cuja coorte
está no disco — fechando o desenho do 0001 §7 em sua fatia honesta e offline, e deixando
explicitamente para v2b a sobreposição de audiência baseada em seguidores e o reuso opcional de um
banco de grafos.
