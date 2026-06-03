# Spec 0016 — Layer 3 Creator Diagnostics: Sumário Executivo

**Status:** accepted · **Data:** 2026-06-03 · **Método:** Spec-Driven Development

---

## Problema que resolve

O Stage 6 hoje converte features brutas e scores diretamente em narrativa.
O relatório descreve fatos ("ER: 6.3%, tier: Mid") mas não produz interpretação.

Um gestor de marca que lê o dossier ainda precisa responder manualmente:
- *Que tipo de criador é esse?*
- *Esse perfil está pronto para patrocínio?*
- *Que categorias de marcas fazem sentido?*
- *Quais são os riscos?*

Essas perguntas exigem uma camada de interpretação entre os sinais brutos e a narrativa final.
Hoje essa camada não existe — e os diagnósticos não são persistidos, não são versionados,
e não são consultáveis via Neo4j.

---

## O que o spec entrega

| Capacidade | Resumo |
|---|---|
| **`derived_insights`** | Observações de conteúdo: `theme_mix` (concentração temática com `unmapped_ratio`), `top_topics` (hashtags + captions), `editorial_consistency_score` (coerência temática, não frequência), `content_format_mix` |
| **`derived_diagnostics`** | Labels interpretativas: `creator_archetype`, `creator_size`, `lifecycle_stage`, `sponsorship_readiness`, `brand_fit[]`, `risk_flags[]` |
| **Proveniência completa** | Cada campo interpretativo carrega `method`, `version`, `confidence` (onde aplicável), `evidence[]`, `matched_rule` |
| **Queryabilidade Neo4j** | `c.creator_archetype = "specialist_educator"` · `"saas" IN c.brand_fit` |
| **Seção de Diagnósticos no relatório** | Creator Archetype, Lifecycle Stage, Sponsorship Readiness, Brand Fit, Risk Assessment — narrativa gerada de labels, sem prosa no JSON |
| **Degradação graciosa** | Features ausentes → defaults neutros; niche desconhecido → `brand_fit = []`; media vazia → `content_analysis` com campos nulos |

---

## O que não entra (YAGNI)

- **Classificação de archetype via LLM** — rule-based v1 é suficiente para MVP; deferred
- **Recálculo de scores a partir de diagnósticos** — diagnósticos leem scores, não os produzem
- **Diagnósticos demográficos de audiência** — exige consentimento Art. 9; deferred
- **Backfill de dossiers existentes** — recomputado em cada execução do Stage 6

---

## Decisões locked (D1–D12)

- **D1** Dois blocos separados: `derived_insights` (observações) vs `derived_diagnostics` (interpretações) — distinção necessária para auditabilidade e queries Neo4j.
- **D2** Labels persistidas, narrativas renderizadas — prosa envelhece; labels são estáveis, versionáveis e consultáveis.
- **D3** Todo campo interpretativo carrega `method`, `version`, `confidence`, `evidence`, `matched_rule` — sem isso, diagnósticos são caixas-pretas.
- **D4** `editorial_consistency_score` = concentração temática, não regularidade de postagem — misturar os dois produziria diagnósticos de archetype incorretos.
- **D5** `top_topics` usa captions + hashtags — muitos criadores spammam hashtags ou não as usam; o texto da legenda é um sinal mais forte.
- **D6** `unmapped_ratio` é um indicador operacional — quando > 40% das hashtags não são mapeadas, o dicionário precisa de atualização.
- **D7** `creator_size` e `lifecycle_stage` são campos independentes — tamanho ≠ saúde de crescimento.
- **D8** `sponsorship_readiness` usa fórmula ponderada (auth 40% + brand_safety 30% + consistency 20% + FTC 10%); `ftc=at_risk` sempre retorna `low`.
- **D9** Entradas de `brand_fit` têm nível de aderência (`high`/`medium`/`low`) + confidence — lista flat não informa qualidade.
- **D10** Entradas de `risk_flags` têm `severity` + `evidence` — nem todos os riscos têm o mesmo peso.
- **D11** Protocolo de confidence: `computed` → sem confidence; `heuristic`/`llm` → confidence obrigatório.
- **D12** Sem novas dependências externas — stdlib (re, collections.Counter) suficiente para v1.

---

## Tracks (6 tracks, 30 tarefas)

| Track | Escopo | Depende de |
|---|---|---|
| A — Modelos + schema | Pydantic models + `06-dossier.schema.json`; `make validate` verde | — |
| B — Content analysis | `compute_theme_mix`, `top_topics`, `format_mix`, `editorial_consistency` | — |
| C — Classifiers | `archetype`, `size`, `lifecycle`, `readiness`, `brand_fit`, `risk_flags` | A |
| D — Stage 6 wiring | Orchestrators + `stage6_dossier.run()` → JSON persiste os dois blocos | A+B+C |
| E — Report rendering | `_render_diagnostics_section()` + 5 sub-seções em `report.md` | D |
| F — Tests | Unit + integração; `make test` + `make validate` verdes | D+E |

A e B podem ser desenvolvidos em paralelo. C depende de A. D depende de A+B+C. E depende de D. F depende de D+E.

---

## Riscos

- **Niche não mapeado em `brand_fit`** — retorna lista vazia, não erro; adicionar niche ao dicionário na iteração seguinte.
- **`unmapped_ratio` alto** — `editorial_consistency_score` cai proporcionalmente; archetype pode cair para `content_creator` fallback. Comportamento correto — dados genuinamente esparsos.
- **Drift de features entre spec 0001 e 0016** — todas as funções aceitam `None` como input e degradam com defaults neutros; nenhuma função crasha por feature ausente.
- **Confusão entre `editorial_consistency` e `posting_consistency`** — campos com nomes e funções distintos; decisão D4 documentada; comentário no código aponta para spec §6.1.
