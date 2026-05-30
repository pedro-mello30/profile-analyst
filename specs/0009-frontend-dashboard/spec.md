# Spec 0009 — Frontend Dashboard (React + Vite SPA)

**Status:** draft
**Depends on:** `0008-aws-deployment` (ALB, CloudFront integration, Secrets Manager) ·
`0003-ollama-llm-graph-query` (`/ask`) · `0005-hybrid-rag-retrieval` (`/rag`) ·
`0001-social-media-associations-profile` (dossier schema)
**Owner:** Pedro Mello
**Created:** 2026-05-30
**Source of truth:** this document. Read before implementing anything under `frontend/` or
adding CloudFront/S3 Terraform resources.

---

## 1. Problem Statement

All pipeline capabilities — batch runs, NL graph queries, hybrid RAG, and dossier artifacts — are
accessible only through `curl` or direct API calls. There is no human-facing surface for analysts
to trigger runs, monitor progress, ask questions about a creator, or read a completed dossier
without parsing raw JSON.

This spec defines a **React + Vite single-page application** that wraps the existing API surface
(spec 0008 ALB) in a three-view dashboard. It adds no new backend logic — it is a thin UI layer
over endpoints that already exist.

---

## 2. Goals

- **G1. Run Manager.** A landing-page view where an analyst enters an Instagram handle, selects
  pipeline stages, submits a batch run (`POST /api/runs`), and monitors status in a polling table
  (`GET /api/runs/{id}`).
- **G2. Query Interface.** A two-tab view: **Ask** (`POST /api/ask` — NL→Cypher) and **RAG**
  (`POST /api/rag` — hybrid retrieval), both rendering answers, source metadata, and rejection
  reasons on failure.
- **G3. Dossier Browser.** A table of completed handles; clicking a row renders the dossier as
  structured human-readable cards (niche, engagement, sponsored-post flags, compliance block) —
  not raw JSON.
- **G4. Health indicator.** A persistent nav-bar dot polling `GET /healthz` every 30 s; turns red
  within one polling interval of a 503, green on recovery.
- **G5. Shared-token auth.** A lock screen on first load; correct token stored in `sessionStorage`;
  every API call carries `Authorization: Bearer <token>`; the ALB enforces it server-side.
- **G6. S3 + CloudFront deployment.** Static assets served from a private S3 bucket via
  CloudFront OAC; ALB is a second CloudFront origin on path `/api/*` so the browser speaks to one
  domain; Terraform-managed.

---

## 3. Non-Goals

- **N1. No new backend code.** `/ask`, `/rag`, `/runs`, `/healthz` are consumed as-is. The only
  net-new infrastructure is S3 + CloudFront + one ALB listener rule.
- **N2. No user management.** A single shared secret; no Cognito, no roles, no per-user sessions.
  Auth is the ALB listener rule — the lock screen is UX only.
- **N3. No CI/CD pipeline.** Build and deploy are manual (`npm run build` → `aws s3 sync` →
  CloudFront invalidation) for v1. GitHub Actions is Future Work.
- **N4. No mobile-first design.** The dashboard is optimized for desktop analyst workstations;
  basic responsive layout is acceptable but not a goal.
- **N5. No dossier artifact write path.** The browser reads completed dossiers; it cannot trigger
  edits, corrections, or re-runs from the Dossier Browser (re-runs go through Run Manager).
- **N6. No direct Neo4j or MLflow UI embedding.** Those remain internal-only (spec 0008 N6);
  the frontend never proxies or iframes them.

---

## 4. Architecture

### 4.1 Topology

```
Browser
  ├── GET /          → CloudFront → S3 (static assets; OAC)
  └── POST /api/*    → CloudFront → ALB (spec 0008)
                              ↑
                    Authorization: Bearer <token>
                    enforced by ALB listener rule
                    (secret stored in Secrets Manager)
```

CloudFront has two origins:

| Origin | Path pattern | Cache policy |
|--------|-------------|--------------|
| S3 (private bucket, OAC) | `/*` (default) | `CachingOptimized` |
| ALB | `/api/*` | `CachingDisabled` |

The `/api/*` path prefix is stripped before forwarding to the ALB (CloudFront origin path
rewrite), so the ALB sees `/ask`, `/rag`, `/runs`, `/healthz` unchanged.

### 4.2 Auth Flow

1. App loads; checks `sessionStorage` for `pa_token`.
2. Token absent → `LockScreen` rendered; analyst enters shared secret → stored as `pa_token`.
3. `client.ts` axios instance reads `pa_token` on every request and sets
   `Authorization: Bearer <token>`.
4. ALB listener rule (Terraform): path `/api/*` + header value does **not** match the secret →
   fixed 401 response. Secret value sourced from `aws_secretsmanager_secret` → injected into the
   listener rule condition via Terraform data source.
5. `sessionStorage` is cleared when the tab is closed; the analyst must re-enter the token on
   next session.

### 4.3 Views

#### Run Manager (`/`) — landing page

Two panels:

**New Run (left panel)**

- Handle text input (alphanumeric + underscore, matches API validation)
- Stages selector: radio group — `all` / `1,2,3` / `1,2,3,6` / custom text field
- Submit → `POST /api/runs {handle, stages}` → displays `run_id` in a success banner

**Recent Runs (right panel)**

- Table: handle | stages | status | started_at | elapsed
- Status rendered as colour-coded badges: `queued` (grey) / `running` (blue, animated) /
  `done` (green) / `failed` (red)
- Polls every 5 s for any run with status `queued` or `running`; stops polling once all settle
- Rows are stored in component state (survives tab navigation via React Query cache)

#### Query Interface (`/query`)

Two tabs — **Ask** and **RAG** — sharing a common layout: handle input at top, question
textarea, Submit button, result panel below.

**Ask tab**

- Calls `POST /api/ask {handle, question}`
- On success: renders answer (prose), Cypher block (monospace), row count
- On 422: renders rejection reasons list

**RAG tab**

- Calls `POST /api/rag {handle, question}`
- On success: renders answer (prose), source chunks table (chunk text | score | mode)
- On error: renders error detail

#### Dossier Browser (`/dossiers`)

- Fetches the runs list (all `status=done` entries from React Query cache + fresh poll)
- Table: handle | completed_at | niche | engagement_rate (top-line numbers only)
- Click a row → **detail panel** slides in (or navigates to `/dossiers/:handle`):
  - **Profile card:** handle, platform, follower count, niche + confidence
  - **Engagement card:** ER by Followers, avg likes, avg comments
  - **Sponsored Posts card:** count, FTC disclosure status, flagged post list
  - **Compliance card:** `compliance_flags` block from dossier — Art.9 risks highlighted in amber,
    FTC violations in red
  - **Attributes card:** brand affinities, content attributes with confidence bars

Dossier JSON is fetched from `GET /api/runs/{id}` manifest path or a dedicated
`GET /api/dossiers/{handle}` endpoint (see §7 Open Questions).

### 4.4 Global State & Data Fetching

| State | Store | Notes |
|-------|-------|-------|
| Auth token | `sessionStorage` | Read by axios interceptor |
| Health status | React Query, 30 s poll | Nav dot |
| Runs list | React Query, 5 s poll (while any active) | Shared across views |
| Ask/RAG results | React Query, manual trigger | Keyed by (handle, question) |

No Redux. No context beyond the token.

---

## 5. File Layout

```
frontend/
├── package.json
├── tsconfig.json
├── vite.config.ts          # /api proxy in dev; VITE_API_BASE_URL
├── tailwind.config.ts
├── index.html
└── src/
    ├── main.tsx
    ├── App.tsx              # BrowserRouter + nav bar + health dot + lock screen gate
    ├── auth/
    │   └── LockScreen.tsx   # password field → sessionStorage
    ├── api/
    │   └── client.ts        # axios instance; Bearer token interceptor; base URL from env
    ├── views/
    │   ├── RunManager.tsx
    │   ├── QueryInterface.tsx
    │   └── DossierBrowser.tsx
    ├── components/
    │   ├── RunTable.tsx         # polling table + status badges
    │   ├── NewRunForm.tsx
    │   ├── AskPanel.tsx
    │   ├── RagPanel.tsx
    │   ├── DossierCard.tsx      # structured renderer for one dossier
    │   └── HealthDot.tsx        # green/red dot
    └── hooks/
        ├── useRuns.ts           # React Query: list runs, poll active
        ├── useAsk.ts            # React Query mutation
        ├── useRag.ts            # React Query mutation
        └── useHealth.ts         # 30 s poll → HealthResponse
```

---

## 6. Deployment

### 6.1 New Terraform Resources (`deploy/aws/terraform/frontend.tf`)

```hcl
# S3 bucket — private, versioning on
resource "aws_s3_bucket" "frontend" { ... }
resource "aws_s3_bucket_versioning" "frontend" { ... }

# OAC — CloudFront-only access to S3
resource "aws_cloudfront_origin_access_control" "frontend" { ... }

# CloudFront distribution — two origins
resource "aws_cloudfront_distribution" "frontend" {
  # Origin 1: S3 (default /*  )
  # Origin 2: ALB  (/api/*)
  # Viewer protocol: redirect-to-https
  # Default root object: index.html
  # Custom error response: 404 → /index.html 200 (SPA routing)
  ...
}

# Secrets Manager secret for the shared token
resource "aws_secretsmanager_secret" "frontend_api_token" { ... }

# ALB listener rule — enforce token on /api/*
resource "aws_alb_listener_rule" "frontend_auth" {
  # condition: path_pattern /api/* AND
  #            http_header Authorization != "Bearer <token>"
  # action: fixed-response 401
  ...
}
```

### 6.2 Build & Deploy (manual, v1)

```bash
# 1. Build
cd frontend
VITE_API_BASE_URL=https://<cloudfront-domain> npm run build

# 2. Upload
aws s3 sync dist/ s3://<frontend-bucket-name>/ --delete

# 3. Invalidate CloudFront cache
aws cloudfront create-invalidation \
  --distribution-id <dist-id> \
  --paths "/*"
```

### 6.3 Local Development

```bash
cd frontend
VITE_API_BASE_URL=http://localhost:8000 npm run dev
```

`vite.config.ts` proxy:
```ts
server: {
  proxy: {
    '/api': {
      target: process.env.VITE_API_BASE_URL,
      rewrite: (path) => path.replace(/^\/api/, ''),
    },
  },
},
```

The Bearer token flows through the proxy unchanged; local dev hits the local API service directly.

---

## 7. Open Questions

| # | Question | Decision |
|---|----------|----------|
| OQ1 | Does `GET /api/runs` (list all runs) exist, or does the Dossier Browser reconstruct the list from client-side state only? | **Resolved — client-side only.** The runs list is accumulated in React Query cache from `POST /api/runs` responses and individual `GET /api/runs/{id}` polls. No list endpoint is added to the API. The Dossier Browser reads `status=done` entries from that cache. Cache is session-scoped (lost on page reload). |
| OQ2 | How is the dossier JSON surfaced to the browser? | **Resolved — client-side only.** The run manifest returned by `GET /api/runs/{id}` includes the artifact paths. The frontend calls `GET /api/runs/{id}` and reads the dossier fields directly from the manifest JSON. No separate `/api/dossiers/{handle}` endpoint is added. |
| OQ3 | Should the CloudFront distribution use a custom domain + ACM cert, or the default `*.cloudfront.net` domain for v1? | Default `*.cloudfront.net` for v1. Custom domain is Future Work. |
| OQ4 | Should incorrect token attempts be rate-limited via ALB WAF? | Deferred. Low risk for an internal tool in v1. WAF rule is Future Work. |

---

## 8. Future Work

- **CI/CD:** GitHub Actions workflow — `npm run build` + `aws s3 sync` + CloudFront invalidation
  on push to `main`
- **Auth upgrade:** Replace shared token with Cognito user pool + CloudFront Lambda@Edge JWT
  validation when the analyst team grows beyond one or two people
- **Mobile layout:** Responsive breakpoints for tablet/phone access
- **Run log streaming:** WebSocket or SSE from the worker to stream pipeline stage progress
  in real time inside the Run Manager
- **Dossier diff view:** Compare two versions of the same handle's dossier side-by-side
