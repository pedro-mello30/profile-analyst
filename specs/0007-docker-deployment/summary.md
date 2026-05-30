# Resumo 0007 — Implantação em Docker e Orquestração de Serviços

> Resumo em português da especificação `spec.md`. A fonte de verdade é o `spec.md` (em inglês).

**Status:** accepted · **Data:** 2026-05-30 · **Método:** Spec-Driven Development

---

## O que é

O sistema cresceu de uma pipeline Python única (0001) para uma plataforma multi-serviço: agora
exige **Neo4j 5.13+** (grafo + índices vetorial/full-text, 0002/0005), o runtime local **Ollama**
(NL→Cypher e extração de features, 0003; embeddings, 0005), a **API da Anthropic** (backend padrão
do Stage 3, 0001) e um **MLflow** auto-hospedado com **PostgreSQL + MinIO** (observabilidade, 0006).
Cada spec documenta suas variáveis de ambiente e "assume um daemon X rodando" — mas nada amarra tudo.

Esta especificação adiciona **containerização em Docker e uma única topologia `docker compose`** que
constrói a imagem da pipeline, sobe todos os serviços de apoio nas versões corretas, conecta toda a
configuração das specs anteriores e expõe um serviço **FastAPI** somente-leitura para `/ask` e `/rag`.
Não muda nenhuma lógica de pipeline — apenas empacota e orquestra o que 0001–0006 já definem.

---

## O que o spec entrega

| Capacidade | Resumo |
|---|---|
| **Stack completa em um comando** | `docker compose up` sobe Neo4j, Ollama, MLflow (+ PostgreSQL + MinIO) e a API, com healthchecks e ordenação de inicialização. |
| **Imagem única multi-stage** | Um `Dockerfile` (builder → runtime, não-root) serve os dois modos: CLI one-shot e API long-running, sem bifurcar lógica. |
| **Paridade de CLI no container** | `docker compose run --rm app --handle X --stage all` roda a pipeline completa (Stages 1–8) e os subcomandos `erase`/`gc` do Art. 17. |
| **API de consulta somente-leitura** | FastAPI `POST /ask` (0003 NL→Cypher), `POST /rag` (0005 híbrido) e `GET /healthz`, delegando às funções existentes — herda as travas de segurança 0003/0005. |
| **Ollama com GPU** | Serviço `ollama` com passagem de GPU NVIDIA + serviço-init `ollama-pull` que baixa os modelos padrão em volume. |
| **Configuração num só ponto** | Um `.env` (+ `.env.example`) conecta toda variável de 0001–0006; segredos injetados em runtime, nunca embutidos na imagem. |
| **Persistência e conformidade** | Volumes nomeados para estado dos serviços; `projects/` em bind-mount no host para artefatos, retenção e apagamento GDPR. |

---

## O que não entra (YAGNI)

| Fora de escopo | Motivo |
|---|---|
| Mudanças na lógica de pipeline/schemas/analytics (N1/N2) | Spec puramente de empacotamento/orquestração. |
| Caminho de escrita / `POST /run` pela API (N6, OQ2) | API permanece somente-leitura; batch via `docker compose run`. |
| Orquestração multi-host, Kubernetes/Helm (N3) | Deploy single-host (espelha 0006 N2); k8s é Future Work. |
| Datastores gerenciados/cloud (N4) | Serviços rodam como containers locais (Neo4j Community, Postgres, MinIO). |
| CI/CD, publicação de imagens em registry, SBOM (N5, OQ4) | Future Work. |
| Plugin GDS no Neo4j (N7) | Spec 0004 ainda não escrita; adição de uma linha quando ela existir. |

---

## Decisões Locked (D1–D8)

| # | Decisão | Fundamento |
|---|---|---|
| D1 | Uma topologia `docker compose` orquestra toda a stack (imagem + Neo4j + Ollama + MLflow + Postgres + MinIO). | Cada spec assume um serviço rodando, mas nenhuma os amarra; um compose é a fonte única da topologia. |
| D2 | Um `Dockerfile` multi-stage (builder → runtime) produz uma imagem enxuta não-root servindo os dois modos via branch no entrypoint. | Sem bifurcação de lógica CLI/API; menor superfície de ataque. |
| D3 | FastAPI fino (`api/`) expõe `/ask`, `/rag`, `/healthz` delegando a `tools/ask.py` e `tools/rag.py`; único código novo. | 0003/0005 são só-CLI; um endpoint long-running é a superfície interativa, herdando S1–S6 + segurança. |
| D4 | Serviço Ollama exige GPU NVIDIA; serviço-init `ollama-pull` baixa modelos em volume em runtime. | Modelo Cypher padrão (qwen2.5-coder:32b ~20 GB) exige GPU; embutir 20 GB na imagem é inviável. |
| D5 | Ordem de inicialização via `depends_on` + healthchecks. | Stage 7 precisa de Neo4j; `--ask` de Neo4j+Ollama; Stage 8 do modelo de embedding; observabilidade do MLflow. |
| D6 | Um `.env` é o ponto único de configuração; segredos em runtime, nunca na imagem; URIs internas usam nomes de serviço. | Colapsa config de seis specs; "sem segredo na imagem" é requisito de conformidade (A7). |
| D7 | `projects/` em bind-mount no host; estado dos serviços em volumes nomeados. | Mantém artefatos + apagamento GDPR Art. 17 em arquivos duráveis e inspecionáveis no host (0001 §9). |
| D8 | Sem mudança de lógica/schema/analytics; sem GDS, CI/CD, registry ou multi-host. | Spec puro de empacotamento; YAGNI até a 0004; k8s/registry/CI adiados para Future Work. |

(Espelha o bloco `decisions:` do `metadata.yml`.)

---

## Topologia em resumo

```
app:api (FastAPI long-running)        app:cli (one-shot, run --rm)
 ├─ /ask → tools/ask.py                profile_analyst.py --stage 1..8 | erase | gc
 ├─ /rag → tools/rag.py        (MESMA imagem; ENTRYPOINT: api | <args do cli>)
 └─ /healthz
        └──► neo4j 5.13+ · ollama (GPU) · mlflow ──► postgres + minio
   bind-mount host:  ./projects ⇄ /app/projects   (artefatos, erase, gc)
```

---

## Tracks de implementação (dependency-ordered)

```
A → B ;  C ∥ (A,B) ;  {A, B, C} → D → E
```

| Track | Entregável | Dependências |
|---|---|---|
| A | Imagem da pipeline (`Dockerfile`, `entrypoint.sh`, `.dockerignore`, deps FastAPI) | — |
| B | API somente-leitura `api/` (`/ask`, `/rag`, `/healthz`) | A |
| C | Serviços de apoio + config (`mlflow.Dockerfile`, `.env.example`, definições de serviço) | — |
| D | Topologia compose + wiring (`compose.yaml`, `compose.gpu.yaml`, `depends_on`, Makefile) | A, B, C |
| E | Verificação de aceite (A1–A12) + doc de deploy | D |

---

## Critérios de aceite (resumo)

A1 stack sobe saudável (init `ollama-pull` sai 0) · A2 imagem não-root (UID 10001) ·
A3 paridade de CLI (artefatos `01..08` válidos no host) · A4 Stage 7 carrega no Neo4j composto ·
A5 `/ask` aterrado + mutação rejeitada · A6 `/rag` com citações + honestidade em zero resultados ·
A7 sem segredos embutidos na imagem · A8 reserva de GPU nvidia presente no `compose config` ·
A9 readiness se recupera ao reiniciar Neo4j (sem crash loop) · A10 trace MLflow on/off ·
A11 `erase` apaga `projects/<handle>/` no host · A12 `make validate` passa (sem novos schemas).

---

## Riscos principais

| Risco | Mitigação |
|---|---|
| GPU indisponível (esp. WSL2) | Pré-requisito de host documentado; `compose.gpu.yaml` + overrides de modelo leve dão caminho de dev; A8 checa `compose config`, não GPU ao vivo. |
| Cold-start de modelos (~20 GB) | `ollama-pull` baixa uma vez em volume nomeado; `OLLAMA_PULL_MODELS` configurável para conjunto leve. |
| Segredos na imagem | Só `.env` + injeção em runtime; `.dockerignore` exclui `.env`; A7 verifica `docker history`. |
| Instabilidade de readiness | `depends_on` com healthcheck; `/healthz` reflete dependências, mantendo a API unhealthy (não crashed) até recuperação. |
| Drift de config entre specs | `.env.example` é o ponto único; URIs por nome de serviço substituem os defaults `localhost` de bare-metal. |
