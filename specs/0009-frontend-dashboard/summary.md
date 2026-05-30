# Spec 0009 — Frontend Dashboard: Sumário Executivo

**Status:** accepted · **Data:** 2026-05-30 · **Método:** Spec-Driven Development

---

## Problema que resolve

Todas as capacidades do pipeline — batch runs, queries NL→Cypher, RAG híbrido, e artefatos de
dossier — estão acessíveis apenas via `curl` ou chamadas diretas à API. Não existe uma superfície
humana para analistas dispararem runs, acompanharem progresso, fazerem perguntas sobre um criador
ou lerem um dossier completo sem parsear JSON bruto.

Este spec define uma **SPA React + Vite** que envolve a superfície de API existente (ALB do spec
0008) em um dashboard de três views. Nenhuma lógica de pipeline é tocada — é apenas uma camada
de UI sobre endpoints que já existem.

---

## O que o spec entrega

| Capacidade | Resumo |
|---|---|
| **Run Manager (landing page)** | Formulário para disparar batch runs (`POST /runs`); tabela com polling de status (`GET /runs/{id}`) em tempo real |
| **Query Interface** | Duas abas: Ask (`POST /ask` — NL→Cypher com resposta + Cypher + row count) e RAG (`POST /rag` — resposta + source chunks) |
| **Dossier Browser** | Tabela de handles concluídos; clique → DossierCard com 5 seções estruturadas (perfil, engajamento, posts patrocinados, compliance, atributos) |
| **Health dot no nav** | Polling de `GET /healthz` a cada 30 s; dot verde/vermelho no topo da tela |
| **Auth por token compartilhado** | Lock screen no primeiro acesso; token em `sessionStorage`; `Authorization: Bearer` em toda chamada; regra no ALB bloqueia sem token válido |
| **Deploy S3 + CloudFront** | Assets estáticos no S3 privado via OAC; ALB como segunda origem no `/api/*`; um único domínio elimina CORS |

---

## O que não entra (YAGNI)

| Fora de escopo | Motivo | Futuro |
|---|---|---|
| Nenhuma lógica de backend nova | Consome `/ask`, `/rag`, `/runs`, `/healthz` como existem | — |
| Sem gerenciamento de usuários | Token compartilhado; sem Cognito, roles, ou sessões por usuário | Auth com Cognito + Lambda@Edge |
| Sem CI/CD | Build + deploy manual (`npm run build` → `aws s3 sync`) para v1 | GitHub Actions |
| Sem design mobile-first | Dashboard para workstations de analistas; layout responsivo básico ok | — |
| Sem write path no dossier | Browser apenas lê; re-runs vão pelo Run Manager | — |
| Sem lista de runs persistente | Cache em sessão apenas (page reload perde histórico) | localStorage com TTL |
| Sem endpoint novo na API | `GET /api/runs` list e `GET /api/dossiers/{handle}` não são adicionados; dados vêm do cache client-side | — |
| Sem domínio customizado | `*.cloudfront.net` para v1; certificado ACM + Route 53 é futuro | Custom domain + HTTPS cert |

---

## Arquitetura em resumo

```
Browser
  ├── GET /          → CloudFront → S3 (assets estáticos, OAC)
  └── POST /api/*    → CloudFront → ALB (spec 0008)
                              ↑
                    Authorization: Bearer <token>
                    ALB listener rule bloqueia sem token
                    (secret no Secrets Manager)

sessionStorage["pa_token"] → interceptor axios → header em toda chamada /api/*

React Query:
  useHealth()  → GET /healthz    (poll 30 s → dot)
  useRuns()    → GET /runs/{id}  (poll 5 s enquanto ativo; cache = sessão)
  useAsk()     → POST /ask       (mutation)
  useRag()     → POST /rag       (mutation)
```

---

## Decisões Locked (D1–D10)

| # | Decisão | Fundamento |
|---|---|---|
| D1 | React + Vite SPA; sem SSR, sem BFF | Site estático é o deploy mais simples; API já expõe toda a superfície; zero código backend novo |
| D2 | S3 + CloudFront; dois origins (S3 assets + ALB `/api/*`) | Encaixa no Terraform do 0008; único domínio elimina CORS; ~$1–2/mês |
| D3 | Auth = Bearer token compartilhado; regra no ALB aplica server-side; lock screen em sessionStorage | Sem overhead de user management; secret fica no Secrets Manager + config do ALB, nunca no bundle JS |
| D4 | Três views: Run Manager (landing), Query Interface, Dossier Browser | Mapeia diretamente às três superfícies de API: /runs, /ask+/rag, artefatos de dossier |
| D5 | React Query para todo server state; sem Redux | Server state domina (runs, health, resultados); React Query cuida de cache, polling e retries sem boilerplate |
| D6 | Tailwind CSS; sem component library | Utility-first mantém bundle pequeno; sem lock-in de design system para ferramenta interna |
| D7 | Health dot no nav bar, poll 30 s | Visibilidade imediata de saúde do Neo4j/API sem sair da UI |
| D8 | Dossier Browser renderiza cards estruturados, não JSON bruto | Usuários são analistas, não desenvolvedores; compliance flags destacados com cores |
| D9 | `VITE_API_BASE_URL` controla base em dev e prod; proxy Vite em dev | Ponto único de config; nenhuma mudança de código entre ambientes |
| D10 | Sem CI/CD em v1; build + deploy manual | Espelha spec 0008 N5; GitHub Actions é futuro |

---

## Tracks de implementação (dependency-ordered)

```
A (Terraform: S3 + CloudFront + ALB rule)
B (React app: scaffold + auth + views)    ─┬─→ C (Deploy + smoke checks)
  (A e B paralelos; C depende de ambos)   ─┘
```

| Track | Entregável | Dependências | Exit |
|---|---|---|---|
| A | `frontend.tf` — S3, CloudFront (2 origins), ALB listener rule, Secrets Manager token | Terraform 0008 aplicado | `terraform plan` limpo; curl sem token → 401; com token → 200 |
| B | App React completa — auth, hooks, components, 3 views | — (dev usa proxy local) | `npm run build` sem erros; bundle ≤ 500 kB; todas as views funcionam localmente |
| C | `make frontend-deploy`; 9 smoke checks contra CloudFront | A + B | Todos os checks passam; `make validate` verde |

---

## Critérios de aceitação (sumário)

- **A1:** `npm run build` sem erros TypeScript; bundle < 500 kB gzipped
- **A2:** Lock screen aparece sem token; token correto libera acesso; token errado mostra erro
- **A3:** ALB retorna 401 para `/api/*` sem ou com token incorreto (verificado via `curl`)
- **A4:** Run Manager cria run e tabela reflete transições de status em tempo real
- **A5:** Ask tab renderiza resposta + Cypher + row count; 422 mostra razões de rejeição
- **A6:** RAG tab renderiza resposta + source chunks com scores
- **A7:** Dossier Browser lista runs concluídos; clique renderiza DossierCard com 5 seções
- **A8:** Health dot fica vermelho em ≤ 35 s de 503; verde em ≤ 35 s de recuperação
- **A9:** `make frontend-deploy` sobe o app no CloudFront em < 60 s
- **A10:** Proxy Vite em dev funciona com `VITE_API_BASE_URL=http://localhost:8000`

---

## Riscos principais

| Risco | Mitigação |
|---|---|
| Sintaxe de condição negativa no ALB listener rule | Testar com `curl` antes de subir o app; verificar suporte no provider Terraform |
| Rewrite do path `/api/*` no CloudFront errado | Testar curl contra CloudFront antes de buildar o app; verificar logs de acesso do ALB |
| Cache de runs é sessão-scoped — reload perde histórico | Aceito como N5 v1; futuro: localStorage com TTL |
| Bearer token em sessionStorage acessível por JS (XSS) | Aceitável para ferramenta interna com restrição de IP; upgrade: HttpOnly cookie + Lambda@Edge |
| Bundle size creep | Monitorar com `vite build --report`; cap 500 kB; Tailwind purge configurado |
