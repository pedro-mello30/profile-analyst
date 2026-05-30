# Spec 0001 — Social-Media Associations Profile: Sumário Executivo

**Status:** accepted · **Data:** 2026-05-29 · **Método:** Spec-Driven Development (híbrido: rascunho solo + ensemble nos §§ de maior risco)

---

## Problema que resolve

Decisões de marketing de influência — seleção de criadores, estimativa de alcance, detecção de fraude, pontuação de fit de marca — exigem hoje ferramentas SaaS caras (HypeAuditor, Modash, CreatorIQ) ou pesquisa manual que não escala. Essas ferramentas são caixas-pretas: emitem pontuações sem explicar os sinais que as compõem, o que é problemático legalmente sob GDPR Art. 22 (decisão automatizada) e opaco para equipes de marca.

Ao mesmo tempo, o acesso a dados do Instagram estreitou drasticamente:
- **Instagram Basic Display API** encerrada em 2024-12-04 — contas pessoais sem caminho oficial.
- **Instagram Graph API** só expõe contas Business/Creator próprias + `business_discovery` limitado (sem lista de seguidores, sem dados demográficos de terceiros).
- **Provedores de consentimento** (Phyllo, InsightIQ) são os mais limpos legalmente mas exigem enrolamento do criador.
- **Scrapers** operam em zona cinza — *Meta v. Bright Data* (2024) confirmou que scraping público deslogado não viola os ToS, mas scraping autenticado e perfilamento de pessoas reais carregam risco real sob GDPR e CCPA.

**Resultado:** não existe pipeline open-source, orientado à conformidade, agnóstico a fonte, que produza um dossiê estruturado e explicável a partir de dados de perfil do Instagram.

---

## O que o spec entrega

Um pipeline Python por estágios, idempotente, que ingere um perfil do Instagram e produz um **dossiê unificado de "perfil de associações"** — niche, qualidade de engajamento, afinidade de marca, detecção de posts patrocinados, sinais de autenticidade de audiência — e (em versões posteriores) linkagem de identidade cross-platform e grafo de sobreposição de audiência.

| Capacidade | Resumo |
|---|---|
| **Stage 1 INGEST** | Ingere via `SourceAdapter` agnóstico a fonte; estampa metadados de governança em cada registro |
| **Stage 2 NORMALIZE** | Modelo canônico `Profile` (Pydantic v2) validado por schema; preserva bloco de governança |
| **Stage 3 FEATURES** | 61 features: ER (4 variantes), cadência, niche (NLP Claude), detecção de patrocínio (regra + LLM F1≈0.93), sinais de autenticidade heurísticos |
| **Stage 6 DOSSIER** | 4 pontuações compostas explicáveis (EQS, Autenticidade, Transparência de Patrocínio, Segurança de Marca) + `compliance_flags` + `report.md` |
| **Compliance layer** | `pipeline/compliance/`: gate ToS, scanner Art.9 (defesa em profundidade), Art.22 (revisão humana obrigatória), guarda de equidade (sem gênero binário/etnia), erasure GDPR Art.17, GC de retenção |
| **SampleAdapter** | Adapter v1: lê fixture JSON local; nenhuma busca ao vivo |

---

## O que não entra (YAGNI)

| Fora de escopo | Motivo | Versão futura |
|---|---|---|
| Stage 4 LINKAGE | Linkagem cross-platform (UIL) requer dados multi-perfil; maior risco legal | v3 |
| Stage 5 ASSOCIATIONS | Grafo de sobreposição de audiência requer dados multi-perfil | v2 |
| Adapters ao vivo (Graph API, Apify, Phyllo) | Restrições da API; postura de conformidade ainda não estabelecida | v2 |
| Dados demográficos da audiência | Requer OAuth do criador | v2 |
| Análise profunda de seguidores falsos | Sem acesso à lista de seguidores via API oficial | v2 |
| API de serviço / UI de dashboard | Fora de escopo | — |

---

## Alinhamento com princípios de design

| Princípio | Como este spec se alinha |
|---|---|
| **Spec como fonte de verdade** | `spec.md` define comportamento; nenhuma mudança de código é válida sem seção correspondente |
| **Idempotência por estágio** | Cada estágio sobrescreve apenas seu artefato; re-execução não afeta artefatos anteriores |
| **Conformidade desde o início** | `pipeline/compliance/` é uma dependência de todos os estágios, não um afterthought |
| **Pontuações explicáveis** | `signals: list` não-vazio em toda pontuação; `Art9Scanner.enforce` garante A9 deterministicamente |
| **YAGNI** | Stages 4–5 explicitamente diferidos; v1 = perfil único apenas |

---

## Decisões Locked (D1–D12)

| # | Decisão | Fundamento |
|---|---|---|
| D1 | Dossiê unificado = linkagem + grafo + atributos, sequenciado estreito→amplo | Leitura mais rica de "perfil de associações"; entrega incremental |
| D2 | SourceAdapter ABC agnóstico a fonte; v1 = SampleAdapter | Instagram Basic Display morreu dez/2024; postura de conformidade deve ser por adapter |
| D3 | Pipeline idempotente por estágios | Padrão comprovado no carrosel-generation; iteração barata |
| D4 | Conformidade cross-cutting e de primeira classe | GDPR/FTC/ToS: exposição legal concreta ao perfilar pessoas reais |
| D5 | v1 = estreito: Stages 1–3+6; Stages 4–5 diferidos | Stages 4–5 carregam maior risco legal/técnico |
| D6 | NLP via Claude; grafo via networkx+Leiden; similaridade via rapidfuzz | Fundamentado na literatura acadêmica citada |
| D7 | Sem scraping ao vivo em v1; adapters de scraping diferidos e gate-ados por ToS | *Meta v. Bright Data* (2024) |
| D8 | Pontuações explicáveis: toda pontuação emite lista de sinais | GDPR Art.22; transparência tipo HypeAuditor |
| D9 | Formato SDD: specs/0001-*/ + metadata.yml + spec.md + schemas/ | Compatível com spec-ensemble-driver + spec-finalizer |
| D10 | Refinamento híbrido: ensemble só em §6 Linkagem, §8 Pontuação, §9 Conformidade | Equilíbrio custo/exposição de modelos externos |
| D11 | Inferências demográficas nunca como fato; confidence<1.0, method:inferred, art9_risk conforme aplicável | Buolamwini & Gebru 2018; GDPR Art.9 em dados inferidos |
| D12 | Stage 3 usa claude-sonnet-4-6 com prompt caching | InstaSynth F1≈0.93; eficiência de custo |

---

## Arquitetura em resumo

```
SampleAdapter (local JSON)
    ↓  enforce_tos_gate
Stage 1 INGEST → 01-raw.json
    ↓  assert_within_retention
Stage 2 NORMALIZE → 02-normalized.json (Profile Pydantic)
    ↓  claude-sonnet-4-6 + strip_forbidden + Art9Scanner
Stage 3 FEATURES → 03-features.json (61 features + art9_risk flags)
    ↓  build_scores + build_compliance_flags
Stage 6 DOSSIER → 06-dossier.json + report.md

pipeline/compliance/  (cross-cutting)
├── tos.py       — ToS gate + bloco de governança
├── art9.py      — Art9Scanner (defesa em profundidade sobre saída do LLM)
├── art22.py     — Art.22 acoplamento + assert_scores_explainable
├── fairness.py  — strip_forbidden (gênero/etnia) + humildade demográfica
└── erasure.py   — erase_profile + gc_sweep (Art.17)
```

---

## Tracks de implementação (dependency-ordered)

```
A (Schemas)   ─┐
B (Adapters)  ─┼─→ D (Stage 1) → E (Stage 2) → F (Stage 3) → G (Stage 6) → H (CLI + Testes)
C (Compliance)─┘
```

| Track | Entregável | Dependências |
|---|---|---|
| A | 4 schemas JSON + make validate | — |
| B | SourceAdapter ABC + SampleAdapter + fixture | — |
| C | pipeline/compliance/ (5 módulos) | — |
| D | Stage 1 INGEST (01-raw.json) | A, B, C |
| E | Stage 2 NORMALIZE + models.py (02-normalized.json) | D |
| F | Stage 3 FEATURES + prompts/stage3-features.md (03-features.json) | E |
| G | Stage 6 DOSSIER + scoring (06-dossier.json + report.md) | F |
| H | CLI profile_analyst.py + suite de testes completa | A–G |

---

## Critérios de aceitação (sumário)

- **A1:** `make validate` verde — schemas + metadata.yml válidos
- **A2:** pipeline completo (`--stage all`) produz artefatos schema-válidos para stages 1,2,3,6 + `report.md`
- **A3:** ER by Followers correto (correspondência numérica exata no fixture)
- **A4:** ≥1 post patrocinado detectado no fixture com #ad explícito
- **A5:** niche primário atribuído com confidence ≥ 0.5, method: llm
- **A6:** Idempotência — re-executar stage 2 não modifica `01-raw.json`
- **A7:** SampleAdapter emite todos os campos de governança; gate ToS rejeita adapter não-conforme sem `ALLOW_NONCOMPLIANT=true`
- **A8:** Toda pontuação em `06-dossier.json` tem lista de sinais não-vazia; bloco `compliance_flags` presente
- **A9:** Features com risco Art.9 (saúde, sexualidade, religião, política) carregam `art9_risk: true`
- **A10 (v3):** Candidato UIL abaixo de 0.7 ou sem revisão humana nunca aparece em `dossier.linkage.candidates`

---

## Riscos principais

| Risco | Mitigação |
|---|---|
| Disponibilidade da API Claude em CI | Testes com fixtures; flag `--integration` para testes ao vivo separados |
| Acesso a dados do Instagram | v1 usa apenas SampleAdapter + fixtures locais; adapters ao vivo diferidos para v2 |
| Instabilidade da fórmula de pontuação (benchmarks ClickAnalytic dez/2025) | Benchmarks em constantes nomeadas, atualizáveis por fonte de dados |
| Rate limits do ensemble (429s) | Build v1 não depende do ensemble; documentado no histórico do spec |
| Viés em inferência de atributos | Buolamwini & Gebru citado; inferências demográficas desabilitadas por padrão; `art9_risk` forçado pelo scanner |
