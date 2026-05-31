# Spec 0011 — Linkage Cross-Platform (Stage 4, v3a): Sumário Executivo

**Status:** accepted · **Data:** 2026-05-31 · **Método:** Spec-Driven Development

---

## Problema que resolve

O spec 0001 §6 *desenhou* o Stage 4 (UIL — Unified Identity Linkage) mas o deixou diferido: o
Stage 6 emite um placeholder `{"status": "deferred"}` no bloco `linkage` do dossier. Não existe
nenhum caminho que, dado um perfil de Instagram confirmado, descubra e pontue contas em outras
plataformas (Twitter/X, TikTok, YouTube) pertencentes à mesma pessoa real.

Linkage é o estágio de **maior risco jurídico** de todo o pipeline (afirmar que duas contas são a
mesma pessoa). Este spec implementa a fatia **v3a** desse estágio — 5 heurísticas de atributo de
perfil, classificador Fellegi-Sunter, gates de LIA/Art. 9, schema e surfacing no Stage 6 — a partir
de uma **fixture local, sem rede e sem egress para nuvem**. É a realização do 0001 §6, do mesmo modo
que o spec 0010 realizou o backend Ollama do 0003.

---

## O que o spec entrega

| Capacidade | Resumo |
|---|---|
| **Stage 4 opt-in** | `--stage 4` produz `04-linkage.json`; `--stage all` continua `1,2,3,6,7,8,9` e **nunca** dispara linkage |
| **Fonte local (SampleUILAdapter)** | Lê `00-input/cross_platform.json`; herda postura de governança; zero rede |
| **5 famílias de atributo (v3a)** | handle (exato + Jaro-Winkler), display_name (Jaro-Winkler), foto (pHash, atrás do extra `[uil]`), website (host exato), bio (Jaccard) |
| **Scoring Fellegi-Sunter** | log-LR por família → `confidence = logistic(LR)` + `likelihood_ratio` cru + `feature_evidence[]` (≥1) por candidato |
| **Gates de compliance** | `uil_lia_gate()` levanta na entrada se falta LIA; Art. 9-adjacente exige `consent_record_id`; `surfaceable` = confiança ≥ 0.7 **E** revisão humana aprovada |
| **Surfacing no Stage 6** | Substitui o placeholder diferido apenas por candidatos `surfaceable`, reaplicando o gate (defense-in-depth) |

---

## O que não entra (YAGNI)

| Fora de escopo | Motivo | Futuro |
|---|---|---|
| Adapters cross-platform ao vivo | v3a prova matching/scoring/compliance offline com fixture | Spec dedicado de adapters + revisão de ToS |
| Features v3b | Estilometria, estrutura de rede, temporal, embedding PALE | v3b |
| Blocking por LSH (`datasketch`) | Handle exato basta no corpus pequeno do v3a (~45% de reuso de handle) | v3b |
| Writeback no grafo (arestas `SAME_AS`) | 0011 para no artefato JSON + dossier (D9) | Spec follow-up sobre Stage 7 |
| Stage 4 no `--stage all` | Estágio de maior risco fica explicitamente opt-in | — |
| Calibração de priors `m`/`u` | v3a usa constantes da literatura | Anchor set rotulado (OQ1) |

---

## Arquitetura em resumo

```
02-normalized.json ─┐   uil_lia_gate() (levanta se falta LIA)
SampleUILAdapter  ──┤        │
                    ▼        ▼
              stage4_linkage.run
                    │
   blocking → features (5 famílias) → scoring (Fellegi-Sunter) → gate
                    │  valida contra 04-linkage.schema.json
                    ▼  escrita atômica
            projects/<handle>/04-linkage.json
                    │  (reaplica gate surfaceable)
                    ▼
            stage6_dossier → bloco linkage do dossier
```

`surfaceable` é aplicado **duas vezes** (emissão no Stage 4 + montagem no Stage 6); nenhum gate
sozinho é load-bearing. Stage 4 lê só `02-normalized.json` + fixture e escreve só `04-linkage.json`.

---

## Decisões Locked (D1–D9)

| # | Decisão | Fundamento |
|---|---|---|
| D1 | Stage 4 opt-in; `--stage all` inalterado (`1,2,3,6,7,8,9`); roda só via `--stage 4` | Estágio de maior risco jurídico + LIA-gated; não pode disparar num run de rotina |
| D2 | Fonte v3a = `SampleUILAdapter` (fixture local), sem rede | Espelha o `SampleAdapter` do Stage 1; adapters ao vivo são spec separado |
| D3 | 5 famílias v3a; pHash atrás do extra `[uil]` | 0001 §6 v3a; `rapidfuzz` já é dep core; pHash exige `imagehash`+`Pillow` opcionais |
| D4 | Scoring Fellegi-Sunter; `confidence=logistic(LR)`; `SURFACE_THRESHOLD=0.7` constante nomeada | Constantes num único lugar mantêm o classificador auditável |
| D5 | Blocking v3a = handle exato; LSH diferido para v3b | ~45% de reuso de handle dá bloqueio de alta precisão e baixo custo |
| D6 | `04-linkage.schema.json` (draft-7); `method_version` enum `v3a` | Schema é o contrato entre estágios; enum acompanha a progressão v3a→v3b |
| D7 | Gates: LIA na entrada, consentimento Art. 9, regra `surfaceable`, `multi_match_flag` soft | Invariantes 0001 §6; pHash é biométrico-adjacente e nunca sozinho leva a surfaceable |
| D8 | Stage 6 surfacia só candidatos `surfaceable`, reaplicando o gate | Regra aplicada nos dois pontos; bypass de um gate não vaza link não aprovado |
| D9 | Writeback de arestas `SAME_AS` no grafo fica fora de escopo | Mantém a primeira fatia do Stage 4 estreita |

(Espelha o bloco `decisions:` do `metadata.yml`.)

---

## Tracks de implementação (dependency-ordered)

```
A (contrato + models) ─┐
                       ├─→ C (engine + LIA gate) ─┐
B (fonte + extra [uil])┘                          ├─→ D (Stage 4 + CLI) ─→ E (Stage 6 surfacing) ─┐
                       (A e B paralelos)          ┘                                               ├─→ F (testes + validate)
                                                                                                  ┘
```

| Track | Entregável | Dependências |
|---|---|---|
| A | `04-linkage.schema.json` + `LinkageDocument`/`LinkageCandidate` | — |
| B | `CrossPlatformAdapter` + `SampleUILAdapter` + fixture + extra `[uil]` | — |
| C | `pipeline/linkage/{blocking,features,scoring,gate}.py` + `uil_lia_gate` | A |
| D | `stage4_linkage.run` + `STAGE_MAP[4]` (`all` inalterado) | A, B, C |
| E | Surfacing no `stage6_dossier.py` | A, D |
| F | `tests/linkage/` + end-to-end por fixture + `make validate` | A–E |

---

## Critérios de aceitação (sumário)

- **A1:** `_parse_stages("all")` exclui 4; `--stage 4` mapeia para o orquestrador
- **A2:** Sem LIA configurado, Stage 4 levanta `UilLiaError` na entrada, antes de pontuar
- **A3:** Stage 4 sobre a fixture emite `04-linkage.json` válido; todo candidato tem confidence,
  likelihood_ratio, ≥1 feature_evidence e classification
- **A4:** confiança ≥ 0.7 sem aprovação → `surfaceable=false`; confiança < 0.7 → `manual_review_required=true`
- **A5:** Candidato Art. 9-adjacente sem `consent_record_id` nunca é surfaceable
- **A6:** Stage 6 surfacia candidato aprovado+surfaceable; sem aprovados, mantém `{"status":"deferred"}`
- **A7:** Sem o extra `[uil]`, a família de foto pesa 0 e o Stage 4 ainda completa
- **A8:** `make validate` verde + suíte unitária offline verde; `SampleUILAdapter` não abre socket

---

## Riscos principais

| Risco | Mitigação |
|---|---|
| Priors `m`/`u` sem dados rotulados podem mal-rankear | Constantes num único lugar; surfaceable exige aprovação humana, então mal-rank não auto-surfacia |
| pHash é biométrico-adjacente (Art. 9) | Alimenta só confidence, nunca sozinho leva a surfaceable, atrás de `[uil]`, sob gate de consentimento |
| Surfacing de link de identidade errado | Gate duplo (Stage 4 + Stage 6), `manual_review_required`, LIA na entrada, v3a tunado para precisão |
| Ambiguidade `multi_match` | `multi_match_flag` soft em todos, nunca descarta silenciosamente; revisão por candidato |
