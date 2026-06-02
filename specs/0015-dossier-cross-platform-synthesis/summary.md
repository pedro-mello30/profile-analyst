# Spec 0015 — Síntese Cross-Platform no Dossier: Sumário Executivo

**Status:** accepted · **Data:** 2026-06-02 · **Método:** Spec-Driven Development

---

## Problema que resolve

O Stage 6 (Dossier) ignora completamente o `enrichment_map.json` produzido pelo Stage 1B
(spec 0014). Um criador como `@filipelauar` aparece no relatório como *"Travel, Micro, 1.703
seguidores"* quando a imagem completa é: podcaster de IA/tech com 38 episódios publicados no
iTunes, 4.200 seguidores no YouTube e presença confirmada no GitHub. Os scores de Brand Safety
e Sponsorship Transparency são calculados exclusivamente a partir de dados do Instagram — mas
nada no relatório informa isso ao leitor.

---

## O que o spec entrega

| Capacidade | Resumo |
|---|---|
| **Seção 8 — Platform Presence** | Nova seção em `report.md` com tabela estruturada (plataforma → handle/ID → métrica-chave) e parágrafo narrativo factual gerado por template |
| **Enrichment Uplift advisory** | Bloco factual que lista as plataformas encontradas e declara que os scores existentes são baseados apenas em Instagram |
| **Deduplicação por plataforma** | Uma linha por plataforma, independente de quantos adaptadores contribuíram; `confidence` = máximo entre os sinais; `sources[]` acumula todos os adaptadores |
| **`platform_presence` no JSON** | Bloco opcional em `06-dossier.json` com `platforms_found[]`, `uplift_advisory`, e `rows[]` (cada um com `confidence` e `sources[]`) |
| **Gate OSINT** | Sinais com `osint_risk: true` excluídos por padrão; expostos apenas via `--expose-osint` |
| **Degradação graciosa** | Se `enrichment_map.json` estiver ausente ou corrompido, Stage 6 se comporta de forma byte-a-byte idêntica ao comportamento atual |

---

## O que não entra (YAGNI)

- **Recálculo de scores** — EQS, Brand Safety, Sponsorship Transparency não são alterados; deferred para spec seguinte
- **Chamada LLM** — narrativa gerada por templates estáticos; zero custo adicional
- **Alterações ao Stage 1B / spec 0014** — este spec é read-only sobre o enrichment_map
- **OSINT por padrão** — consistente com spec 0014 §9; exige `--expose-osint` explícito

---

## Decisões locked (D1–D6)

- **D1** Puramente aditivo: scores e tier não são recalculados — fecha a lacuna de visibilidade sem introduzir risco de scoring.
- **D2** Sem LLM — templates factual-only; inferência pertence ao Stage 3, não ao Stage 6.
- **D3** Uma linha por plataforma com deduplicação: evita linhas duplicadas quando Linktree e Maigret descobrem o mesmo handle.
- **D4** `confidence` por linha = máximo entre sinais contribuintes; `sources[]` explícito para rastreabilidade de compliance.
- **D5** Sinais OSINT excluídos por padrão, consistente com spec 0014 §9 / Art.22.
- **D6** Templates sem linguagem interpretativa ("signals", "confirms") — cada frase reporta um valor de sinal diretamente.

---

## Tracks (4 tracks, 18 tarefas)

| Track | Escopo | Depende de |
|---|---|---|
| A — Schema contract | Atualiza `06-dossier.schema.json`; `make validate` verde | — |
| B — PlatformPresenceExtractor | `platform_presence.py` (função pura) + testes unitários | — |
| C — Stage 6 integration | Wiring em `stage6_dossier.py`; renderer em `report.md` | A + B |
| D — Tests | Testes de integração (4 cenários); `make test` verde | B + C |

A e B podem ser desenvolvidos em paralelo.

---

## Riscos

- **Churn de chaves de sinais entre 0014 e 0015** — chaves desconhecidas são silenciosamente ignoradas; o acoplamento está documentado com referência a spec 0014 §4.
- **enrichment_map.json ausente em projetos existentes** — extrator retorna bloco vazio; Stage 6 usa comportamento atual sem alteração.
- **Creep para recálculo de scores** — explicitamente diferido em D1; `platform_presence` é somente-leitura no pipeline de scoring.
