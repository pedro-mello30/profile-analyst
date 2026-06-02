# Spec 0014 — Multi-Source Enrichment Engine: Sumário Executivo

**Status:** accepted · **Data:** 2026-06-02 · **Método:** Spec-Driven Development + Spec Ensemble (WEQS §3, §4, §5, §9, §11)

---

## Problema que resolve

O pipeline atual (Stages 1–6) produz um dossiê alimentado exclusivamente por dados do Instagram via Apify. O resultado é um perfil raso: um tier, um nicho, uma taxa de engajamento e algumas pontuações calculadas. Um criador real deixa dezenas de sinais pela web aberta — feed de podcast, canal no YouTube, newsletter, menções na imprensa, registros empresariais públicos, contas cross-platform e entradas em grafos de conhecimento — que o pipeline atual ignora completamente.

Lacunas concretas:
- A bio link do criador (`linktr.ee/...`) expande em 6–12 plataformas adicionais que nunca são analisadas.
- Presença em podcasts (iTunes, Spotify) nunca é consultada, mesmo quando a bio menciona um.
- Google Knowledge Graph e Wikidata contêm fatos estruturados sobre criadores notórios que ficam completamente sem uso.
- Enumeração de username em 3.000+ sites (Maigret) pode descobrir automaticamente contas no TikTok, YouTube, LinkedIn e GitHub.
- Ferramentas OSINT de comunicação (Holehe, GHunt) mapeiam um e-mail descoberto para 120+ serviços registrados, revelando o rastro digital completo do criador.
- GDELT e Google News RSS fornecem sinais de cobertura de imprensa totalmente ausentes das métricas sociais.
- Registros empresariais brasileiros (CNPJ/ReceitaWS) revelam se um criador opera como pessoa jurídica — crítico para parcerias B2B de marca.

---

## O que o spec entrega

Um **Motor de Enriquecimento** (Stage 1B) que recebe um perfil semente (`02-normalized.json`) e irradia por 19 fontes de dados gratuitas em ordem de dependência, retornando um `enrichment_map.json` estruturado que amplia dramaticamente o espaço de sinais do dossiê.

| Capacidade | Resumo |
|---|---|
| **Engine de grafo de dependência** | Cada adapter declara `requires[]` e `produces[]`; o engine resolve a ordem de execução automaticamente via BFS de ponto fixo |
| **Execução em 3 tiers** | Tier 0 (~5s, sequencial), Fast (~30s, paralelo, bloqueia dossier v1), Medium+Slow (assíncrono, atualiza v2/v3) |
| **19 adapters** | Cobrindo: Linktree, WHOIS, crt.sh, Google KG, Wikidata, YouTube, iTunes, Spotify, GitHub, Reddit, Twitch, CNPJ, Holehe, GHunt, HIBP, GDELT, Google News, Substack, Maigret |
| **Cache por adapter** | Chave SHA-256 `(adapter_id, entity_type, entity_value)`, TTL configurável por YAML, sem infraestrutura adicional |
| **Modelo de entidade** | 24 tipos canônicos com normalizador e padrão de validação por tipo; EntityPool thread-safe com rastreamento de proveniência |
| **Contrato de adapter** | `EnrichmentAdapter` ABC valida todos os atributos de classe em tempo de importação via `__init_subclass__` |
| **Compliance OSINT** | Sinais OSINT (`osint_risk: true`) armazenados mas nunca expostos em `report.md` sem flag `--expose-osint`; campo `gdpr_art9_consent_obtained` gatea sinais Art.9 |
| **Erasure segura** | `secure_delete(passes=3)` sobrescreve com bytes aleatórios antes de desvincular (GDPR Art.17) |

---

## O que não entra (YAGNI)

| Fora de escopo | Motivo | Versão futura |
|---|---|---|
| Scrapers de plataformas pagas (Modash, Clearbit) | Fontes gratuitas cobrem o sinal necessário | — |
| Scraping autenticado de perfis privados | Risco legal; fora dos ToS das plataformas | nunca |
| Push webhook para disponibilidade de dossier v2/v3 | Fase 2 — v1 usa polling via `enrichment_status.json` | futuro |
| Streaming em tempo real | Batch por perfil é suficiente para v1 | futuro |
| Facebook, LinkedIn scrapers diretos | ToS complexo; cobertos por SociaVault se necessário | futuro |

---

## Alinhamento com princípios de design

| Princípio | Como este spec se alinha |
|---|---|
| **Spec como fonte de verdade** | `spec.md` define o contrato de adapter, o modelo de entidade e o algoritmo do scheduler; nenhuma mudança de código é válida sem seção correspondente |
| **Enriquecimento aditivo** | `enrichment_map.json` ausente não bloqueia Stages 2–6; Stage 2 faz merge silencioso de sinais quando o arquivo existe |
| **Conformidade desde o início** | Sinais OSINT gateados por padrão; `art22_applies: true` automático quando `osint_signals_present: true`; `review.log` como mecanismo de override de revisão humana |
| **Ponto fixo garantido** | Terminação garantida por `max_depth`, `max_adapter_runs`, `max_instances` e deduplicação de entidades |
| **Determinismo** | `EntityPool.snapshot()` ordena entidades por `(type, value)`; duas execuções com os mesmos inputs produzem o mesmo pool |
| **YAGNI** | Providers pagos, webhooks e streaming explicitamente diferidos; v1 = fontes gratuitas apenas |

---

## Decisões Locked (D1–D10)

| # | Decisão | Fundamento |
|---|---|---|
| D1 | Grafo de dependência explícito: `requires[]` e `produces[]` por adapter; engine resolve ordem via BFS de ponto fixo | Substitui a execução em tier estático; adapters descobertos pelo Maigret que encontram um canal do YouTube desbloqueiam automaticamente o YouTubeAdapter sem fiação manual |
| D2 | Execução em 3 tiers: Tier 0 (seed, sequencial), Fast (paralelo, bloqueia dossier v1), Medium+Slow (assíncrono) | O chamador recebe um dossier v1 utilizável em ≤60s; fontes lentas (Maigret, GDELT) completam em background |
| D3 | Modelo de entidade: `(type, value, source, confidence, depth)` frozen dataclass; EntityPool keyed por `(type, value)` | Deduplicação automática; a mesma entidade descoberta por dois adapters executa downstream apenas uma vez |
| D4 | Limites rígidos por perfil: `max_depth=2`, `max_adapter_runs=20`, `max_cost_usd=0.50` | Cotas de tier gratuito são finitas; depth=2 cobre seed→descoberta→enriquecimento sem cascatas fora de controle |
| D5 | Cache por adapter keyed por SHA-256 `(adapter_id:entity_type:entity_value)`, armazenado como JSON local em `.enrichment_cache/` | Sem infraestrutura adicional; re-executar o pipeline no mesmo perfil dentro do TTL é quase instantâneo e sem custo de cota |
| D6 | Adapters OSINT (Maigret, Holehe, GHunt, HIBP) de primeira classe mas gateados: sinais `osint_risk: true` nunca expostos em `report.md` sem flag explícita | Dados OSINT (registros de conta, presença em breaches) são legalmente obtíveis por interesse legítimo mas requerem revisão humana antes do uso em decisões de campanha (GDPR Art.22) |
| D7 | Enriquecimento é Stage 1B — aditivo, opcional; Stage 2 funciona identicamente com ou sem `enrichment_map.json` | Preserva retrocompatibilidade; falha de enriquecimento nunca bloqueia geração do dossiê |
| D8 | Registro de tipos de entidade canônica definido em spec (§3.1); adapters só podem produzir tipos desta lista; novos tipos requerem emenda ao spec | Previne deriva de schema; torna o grafo de dependências estaticamente analisável |
| D9 | Todos os 18 adapters (exceto HIBP) usam apenas tiers gratuitos ou freemium; HIBP é skip-gateado se `HIBP_API_KEY` ausente | Custo marginal zero por execução de perfil; tetos gratuitos cobrem o sinal necessário |
| D10 | LGPD (Brasil) e CCPA incluídos na tabela de postura legal (§9.2) além do GDPR | Perfis de criadores brasileiros (jurisdição `BR`) estão sujeitos à LGPD; adapter CNPJ retorna dados Receita Federal sujeitos a ambos |

---

## Arquitetura em resumo

```
02-normalized.json (Stage 2 output)
    ↓  assert_within_retention
Stage 1B ENRICHMENT   ← seed: handle, display_name, bio_url
    │
    ├─ Tier 0 (seed, sequencial ~5s)
    │   LinktreeAdapter → WhoisAdapter → CrtAdapter
    │
    ├─ Fast Tier (paralelo, bloqueia dossier v1, ~30s)
    │   KG · Wikidata · YouTube · iTunes · Spotify
    │   GitHub · Reddit · Twitch · CNPJ
    │
    ├─ Medium Tier (assíncrono, dossier v2)
    │   Holehe · GHunt · HIBP · GDELT · Google News · Substack
    │
    └─ Slow Tier (limitado por wall-clock, dossier v3)
        Maigret (3.000+ sites) → novas entidades → desbloqueiam fast adapters
    ↓
enrichment_map.json  (schema_version: "enrichment_map/v1")
enrichment_status.json
    ↓
Stage 2 NORMALIZE     ← merge aditivo de enrichment_signals
Stage 3 FEATURES      ← LLM vê perfil enriquecido (niche, persona, brand fit)
Stage 6 DOSSIER       ← art22_applies=True se osint_signals_present=True
```

---

## Critérios de aceitação (sumário)

- **A1:** `enrichment_map.json` valida contra `enrichment_map.schema.json`
- **A2:** Fast tier completa em ≤60s; `enrichment_status.json` mostra `dossier_version: v1`
- **A3:** Adapter Linktree parseia `linktr.ee/vidacomia` e produz ≥1 entidade de tipo `youtube_channel_id` ou `podcast_url`
- **A7:** Engine para quando `max_adapter_runs=5`; `limit_reached: true` no output
- **A8:** Cache hit: re-executar Stage 1B dentro do TTL não incrementa `actual_runs`
- **A15:** `make validate` passa: schema draft-7 válido; todos os YAMLs passam em YAMLLint strict
- **A19:** `--list-adapters` imprime tabela com todos os 19 adapters
- **A24:** `AdapterContractError` levantado em tempo de importação (não runtime) para adapter mal configurado
- **A25:** `osint_signals_present: true` causa `art22_applies: true` no Stage 6; sem `review.log`, Stage 6 emite `human_review_required: true`
- **A26:** Duas execuções com os mesmos inputs produzem `entity_pool[]` idêntico (determinismo por ordenação)
- **A30:** `schema_version` no output corresponde ao `$id` do schema

---

## Riscos principais

| Risco | Mitigação |
|---|---|
| Rate limits de API de terceiros em execução paralela | `rate_limit_rpm` por adapter; timeout por adapter; `fallback: skip` retorna AdapterResult vazio sem crash |
| Maigret timeout em máquinas lentas | `slow_tier_timeout_s=600` padrão configurável; `--fast-only` pula slow tier completamente |
| Sinal OSINT exposto sem consentimento | `gdpr_art9_consent_obtained=False` padrão; gateado em `report.md` a menos que `--expose-osint` seja passado |
| Stage 2 falha se engine de enriquecimento falhar | Enriquecimento é aditivo — Stage 2 captura todas as exceções do merge e prossegue |
| Excesso de créditos de ensemble em execução de specs | Build de implementação não depende do ensemble; ensemble documentado no histórico do spec |
