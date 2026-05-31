# Plan 0009 — Frontend Dashboard (React + Vite SPA)

Derived from `spec.md`. Single-PR-per-track landing; tracks below are dependency-ordered.
Wraps the existing spec 0008 API surface in a React + Vite SPA deployed to S3 + CloudFront.
No pipeline logic is touched; net-new code is limited to `frontend/` and one new Terraform file.

## Architecture (reference)

```
Browser
  ├── GET /          → CloudFront (*.cloudfront.net)
  │                        └── Origin 1: S3 (private bucket, OAC)
  │                              └── static assets (HTML/JS/CSS)
  └── POST /api/*    → CloudFront
                           └── Origin 2: ALB (spec 0008)
                                    ↑
                          Authorization: Bearer <token>
                          enforced by ALB listener rule
                          (secret in Secrets Manager)

SessionStorage
  └── pa_token → axios interceptor → Authorization header on every /api/* request

React Query
  ├── useHealth()    → GET /api/healthz   (30 s poll → nav dot)
  ├── useRuns()      → GET /api/runs/{id} (5 s poll while any active; cache = session)
  ├── useAsk()       → POST /api/ask      (mutation, manual trigger)
  └── useRag()       → POST /api/rag      (mutation, manual trigger)

Views
  /             → Run Manager      (New Run form + Recent Runs polling table)
  /query        → Query Interface  (Ask tab + RAG tab)
  /dossiers     → Dossier Browser  (completed handles → DossierCard detail panel)
```

Dossier data is sourced entirely from the React Query runs cache (no new API endpoints).
`GET /api/runs/{id}` returns the manifest which contains all dossier fields. The Dossier Browser
reads `status=done` entries from the in-memory cache — cache is session-scoped.

## Implementation tracks (dependency-ordered)

### Track A — Terraform Infrastructure (S3, CloudFront, ALB auth rule)

Add `deploy/aws/terraform/frontend.tf` with all resources needed to serve the SPA and enforce
token auth at the ALB. No existing Terraform resources are modified; this file is purely additive.

**Resources:**

- `aws_s3_bucket.frontend` — private bucket, versioning enabled, all public access blocked.
- `aws_s3_bucket_policy.frontend` — allows only the CloudFront OAC principal to `s3:GetObject`.
- `aws_cloudfront_origin_access_control.frontend` — sigv4 signing, S3 origin type.
- `aws_cloudfront_distribution.frontend` — two origins:
  - Origin 1 (default `/*`): S3 + OAC, `CachingOptimized` policy.
  - Origin 2 (`/api/*`): ALB, `CachingDisabled` policy, origin path strips `/api` prefix.
  - Viewer protocol: redirect HTTP → HTTPS.
  - Default root object: `index.html`.
  - Custom error response: `404 → /index.html` with status 200 (SPA client-side routing).
- `aws_secretsmanager_secret.frontend_api_token` + `aws_secretsmanager_secret_version.frontend_api_token`
  — stores the shared Bearer token (value supplied out-of-band via AWS CLI after `terraform apply`).
- `aws_alb_listener_rule.frontend_auth` — attached to the existing ALB HTTPS listener:
  - Condition: path pattern `/api/*` AND `http-header` `Authorization` value does NOT match
    `Bearer <token>` (sourced from Secrets Manager via data source at plan time).
  - Action: fixed-response 401 with body `{"error":"unauthorized"}`.
- `aws_cloudfront_response_headers_policy.frontend` (optional) — `X-Frame-Options: DENY`,
  `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`.

**Outputs** (added to `outputs.tf`): `cloudfront_domain`, `frontend_bucket_name`,
`cloudfront_distribution_id`, `frontend_token_secret_arn`.

**Makefile targets** (added):
- `make frontend-deploy` — `npm run build` + `aws s3 sync dist/ s3://<bucket>/` + CloudFront
  invalidation. Reads bucket name and distribution ID from Terraform outputs.
- `make frontend-invalidate` — CloudFront invalidation only (for cache busts without a full redeploy).

**Exit (Track A):** `terraform plan` is clean (no changes to existing resources); `terraform apply`
creates the S3 bucket, CloudFront distribution, ALB listener rule, and Secrets Manager secret;
`curl https://<cloudfront_domain>/` returns the `index.html` placeholder (or 403 until first deploy);
`curl https://<cloudfront_domain>/api/healthz` without a Bearer token returns 401;
`curl https://<cloudfront_domain>/api/healthz -H "Authorization: Bearer <token>"` returns 200.

---

### Track B — React + Vite Application

Scaffold and implement the full SPA under `frontend/`. Track A and Track B can be developed
in parallel — locally, `VITE_API_BASE_URL=http://localhost:8000 npm run dev` hits the local
API directly via the Vite proxy.

**Scaffold:**

- `frontend/package.json` — dependencies: `react`, `react-dom`, `react-router-dom@6`,
  `@tanstack/react-query`, `axios`, `tailwindcss`, `vite`, `@vitejs/plugin-react`, TypeScript
  dev dependencies.
- `frontend/vite.config.ts` — `server.proxy` rewrites `/api/*` → `VITE_API_BASE_URL`, stripping
  the `/api` prefix so the local API sees clean paths (`/ask`, `/rag`, etc.).
- `frontend/tailwind.config.ts`, `frontend/tsconfig.json`.
- `frontend/index.html` — entry point; charset UTF-8, viewport, title "Profile Analyst".

**Auth layer (`src/auth/`):**

- `LockScreen.tsx` — centred card: "Profile Analyst" heading, password `<input>`, Submit button.
  On submit: stores value in `sessionStorage` under key `pa_token`; calls a provided `onUnlock()`
  callback. No network call — the ALB validates the real token on the first API request.
- `App.tsx` checks `sessionStorage.getItem('pa_token')` on mount; renders `<LockScreen>` if null,
  the full app otherwise.

**API client (`src/api/client.ts`):**

- `axios.create({ baseURL: '/api' })`.
- Request interceptor: reads `pa_token` from `sessionStorage`, sets `Authorization: Bearer <token>`.
- Response interceptor: on 401, clears `pa_token` and reloads the page (forces re-lock).

**Hooks (`src/hooks/`):**

- `useHealth.ts` — `useQuery({ queryKey: ['health'], queryFn: () => client.get('/healthz'), refetchInterval: 30_000 })`.
  Returns `{ isHealthy: boolean, isLoading }`.
- `useRuns.ts` — manages the runs cache: `addRun(run: RunResponse)` mutates the cache;
  `pollRun(run_id)` uses `useQuery` with `refetchInterval: 5_000` while status is `queued` or
  `running`, stopping when settled. Exposes `{ runs, addRun, pollRun }`.
- `useAsk.ts` — `useMutation({ mutationFn: (req) => client.post('/ask', req) })`.
- `useRag.ts` — `useMutation({ mutationFn: (req) => client.post('/rag', req) })`.

**Components (`src/components/`):**

- `HealthDot.tsx` — 10 px circle: green (`bg-green-500`) when healthy, red (`bg-red-500`) when
  not, grey (`bg-gray-400`) when loading. Used in the nav bar.
- `NewRunForm.tsx` — handle `<input>` (pattern validation: `[a-zA-Z0-9_]+`), stages radio group
  (`all` / `1,2,3` / `1,2,3,6` / custom text field), Submit button. On submit: calls
  `POST /api/runs`, receives `{run_id, status}`, passes to parent via `onRunCreated(run)`.
- `RunTable.tsx` — table of `RunResponse[]`; columns: handle, stages, status (badge), started_at,
  elapsed (computed from `created_at`). Status badges: queued=grey, running=blue+animate-pulse,
  done=green, failed=red.
- `AskPanel.tsx` — handle input + question `<textarea>` + Submit; renders answer (prose block),
  Cypher (`<pre>` monospace), row count badge; rejection reasons as a `<ul>` on 422.
- `RagPanel.tsx` — same form; renders answer (prose block) + source chunks table (text | score |
  mode columns).
- `DossierCard.tsx` — renders one dossier manifest as five cards:
  - **Profile:** handle, follower count, platform, niche + confidence bar.
  - **Engagement:** ER by Followers, avg likes, avg comments.
  - **Sponsored Posts:** count, FTC disclosure status, flagged post list (if any).
  - **Compliance:** `compliance_flags` block — Art.9 risks amber, FTC violations red.
  - **Attributes:** brand affinities list, content attributes with confidence bars.

**Views (`src/views/`):**

- `RunManager.tsx` — two-column layout: `<NewRunForm>` on left, `<RunTable>` on right.
  Wires `onRunCreated` to `useRuns().addRun` + immediately starts polling with `pollRun(run_id)`.
- `QueryInterface.tsx` — tab bar (Ask / RAG); renders `<AskPanel>` or `<RagPanel>` based on
  active tab.
- `DossierBrowser.tsx` — reads `useRuns().runs.filter(r => r.status === 'done')`; renders a
  summary table; click → fetches full manifest via `GET /api/runs/{id}` → opens `<DossierCard>`
  in a detail panel (right-side drawer or separate route `/dossiers/:run_id`).

**App shell (`src/App.tsx`):**

- `<BrowserRouter>` + `<QueryClientProvider>`.
- Persistent top nav bar: logo/title, three nav links (`/`, `/query`, `/dossiers`),
  `<HealthDot>` on the right.
- `<Routes>`: `/` → `<RunManager>`, `/query` → `<QueryInterface>`,
  `/dossiers` → `<DossierBrowser>`, `/dossiers/:run_id` → `<DossierBrowser>` with run pre-selected.
- Lock screen gate wraps the entire `<Routes>` tree.

**Exit (Track B):** `npm run build` produces `dist/` with no TypeScript errors; bundle < 500 kB
gzipped; `npm run dev` with local API serves all three views; LockScreen blocks without token;
correct token unlocks and all views are interactive; RunManager creates a run and polls status;
AskPanel and RagPanel surface results and rejection reasons; DossierBrowser renders structured
cards for completed runs.

---

### Track C — Deployment & Integration

Wire the built frontend into the AWS infrastructure (Track A) and verify end-to-end in the
cloud. Depends on both Track A (Terraform resources exist) and Track B (app is built).

**Makefile:**

- `make frontend-build` — `cd frontend && VITE_API_BASE_URL=https://$(CLOUDFRONT_DOMAIN) npm run build`.
- `make frontend-deploy` — `make frontend-build` + `aws s3 sync frontend/dist/ s3://$(FRONTEND_BUCKET)/ --delete`
  + `aws cloudfront create-invalidation --distribution-id $(CF_DIST_ID) --paths "/*"`.
- `make frontend-invalidate` — invalidation only.
- `CLOUDFRONT_DOMAIN`, `FRONTEND_BUCKET`, `CF_DIST_ID` read from `terraform output` or `.env`.

**Smoke checks (manual, v1 — no automated test file):**

1. `curl https://<cloudfront_domain>/api/healthz` without token → 401.
2. `curl https://<cloudfront_domain>/api/healthz -H "Authorization: Bearer <token>"` → 200.
3. Open `https://<cloudfront_domain>` in a browser → LockScreen appears.
4. Enter correct token → Run Manager loads; health dot is green.
5. Submit a run for `sample` handle → run_id appears; table updates to `running` then `done`.
6. Navigate to Query Interface → Ask tab query returns answer + Cypher.
7. RAG tab query returns answer + source chunks.
8. Navigate to Dossier Browser → completed `sample` handle appears; click → DossierCard renders
   all five sections with no raw JSON visible.
9. Enter wrong token on LockScreen → error message; no API calls made.
10. Close and reopen tab → LockScreen reappears (sessionStorage cleared).

**Exit (Track C):** All 10 smoke checks pass against the CloudFront domain; `make frontend-deploy`
completes in < 60 s; `make validate` is green; the SPA is reachable at the CloudFront domain and
all features work end-to-end.

---

## Risks

| Risk | Mitigation |
|---|---|
| ALB listener rule condition syntax for negative header match | Test with `curl` before deploying app; Terraform `aws_alb_listener_rule` uses `not` condition block — verify provider version supports it |
| CloudFront `/api/*` path rewrite strips prefix incorrectly | Test with `curl` against CloudFront before building the app; ALB access logs confirm paths received |
| Runs cache is session-scoped — page reload loses run history | Accepted as N5 (no persistent run history in v1); Future Work: persist to localStorage with expiry |
| Bearer token in sessionStorage is readable by JS (XSS risk) | Acceptable for an internal tool with IP restriction; upgrade path is HttpOnly cookie + Lambda@Edge (Future Work) |
| `npm run build` bundle size creep | Monitor with `vite build --report`; cap at 500 kB gzipped (A1); drop unused Tailwind via purge config |

---

## Open Questions (resolved)

- **OQ1** (runs list): client-side cache only — no `GET /api/runs` list endpoint added.
- **OQ2** (dossier data): sourced from `GET /api/runs/{id}` manifest — no `/api/dossiers/{handle}` endpoint.
- **OQ3** (custom domain): default `*.cloudfront.net` for v1 — custom domain + ACM cert is Future Work.
- **OQ4** (WAF rate limiting): deferred — low risk for internal tool in v1.
