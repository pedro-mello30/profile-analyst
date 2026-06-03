# Spec 0017 — Instagram Bio Enrichment: Sumário Executivo

**Status:** accepted · **Data:** 2026-06-03 · **Depende de:** spec-0014

---

## Problema que resolve

O motor de enriquecimento (spec 0014) ignora completamente o campo `bio` do perfil do Instagram. Para criadores brasileiros, isso é uma lacuna significativa: bios frequentemente contêm emails de contato, CNPJs, telefones e URLs diretas que não aparecem no Linktree. Esses dados poderiam desbloquear adapters downstream (WHOIS via `domain`, HIBP/GHunt via `email`, lookup CNPJ via `cnpj`) com custo marginal zero.

Problema secundário: o contrato do adapter (`AdapterConfig`) não oferece mecanismo para que adapters acessem dados brutos do perfil. Isso cria uma barreira artificial para adapters de parsing local que poderiam extrair entidades de alto valor a partir de dados já ingeridos.

---

## O que o spec entrega

| Componente | O que faz |
|---|---|
| **`AdapterContext`** | Novo dataclass adicionado a `AdapterConfig` com `raw_profile`, `raw_media`, `source_platform`. Opt-in: adapters que não precisam ignoram `config.context` |
| **`BioEntityExtractor`** | Classe de parsing reutilizável em `extractors/bio.py`. Extrai email, CNPJ, phone, website_url, domain do texto da bio via regex compiladas. Independente de qualquer adapter |
| **`InstagramBioAdapter`** | Adapter `tier=seed, priority=0`. Roda antes do Linktree. Custo zero (sem chamada de rede). Lê `config.context.raw_profile["bio"]` e delega ao extractor |

---

## Por que isso importa para criadores brasileiros

```
Bio: "Podcast sobre IA 🎙️ Parcerias: filipe@vidacomia.com.br | CNPJ 12.345.678/0001-90"
                         ↓
              BioEntityExtractor
         /          |            \
   email          cnpj          domain
 filipe@...    12345678...   vidacomia.com.br
     ↓               ↓            ↓
   HIBP           CNPJ          WHOIS
   GHunt         Lookup        → crt.sh
   Holehe      (empresa,       → subdomínios
               sócios)         → vazamentos
```

Um campo de bio com 80 caracteres pode abrir uma cadeia de enriquecimento inteira.

---

## O que não entra (YAGNI)

| Fora de escopo | Versão futura |
|---|---|
| `CaptionMentionsAdapter` (lê `raw_media`) | `AdapterContext.raw_media` já está disponível; adapter é spec separado |
| Validação de dígito verificador de CNPJ | O adapter CNPJ lookup valida; aqui só extraímos |
| Bio parser para TikTok/YouTube | Mesmo `BioEntityExtractor`; trigger via adapter separado |
| Detecção automática de `source_platform` | Hardcoded `"instagram"` por ora |

---

## Impacto arquitetural

| Princípio | Como este spec se alinha |
|---|---|
| **Adapter = unidade de extração** | Lógica de parsing vive no adapter, não no orquestrador |
| **Extrator reutilizável** | `BioEntityExtractor` independente de plataforma; futuros adapters reusam |
| **Contrato explícito** | `AdapterContext` documenta o que pode ser acessado — não um `dict` arbitrário |
| **Enriquecimento aditivo** | Adapter ausente ou context=None → resultado vazio, nunca erro |
| **Custo zero** | Parsing local; zero chamadas de API, zero custo de quota |

---

## Decisões Locked (D1–D7)

| # | Decisão |
|---|---|
| D1 | Option A+: `AdapterContext` como campo explícito em `AdapterConfig`, não pre-processing no orquestrador |
| D2 | Três campos nomeados no context (`raw_profile`, `raw_media`, `source_platform`) — sem `dict` genérico |
| D3 | `BioEntityExtractor` como classe standalone em `extractors/` — não inline no adapter |
| D4 | `tier=seed, priority=0` — roda antes do Linktree para que `domain` chegue ao pool mais cedo |
| D5 | Prioridade de entidades: `website_url > domain > email > cnpj > phone` |
| D6 | Domínios de bio-link aggregators (linktr.ee etc.) excluídos da produção de `domain` |
| D7 | Contagem de adapters 19→20; test atualizado |
