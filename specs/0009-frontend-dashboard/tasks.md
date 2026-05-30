# Tasks 0009 — Frontend Dashboard (React + Vite SPA)

From `plan.md`. Track-by-track landing; each task independently verifiable.
Tracks A and B can be done in parallel. C depends on A + B.

---

## Track A — Terraform Infrastructure

### S3 & CloudFront

- [ ] T1 Create `deploy/aws/terraform/frontend.tf` — skeleton with provider data sources and
      local variables (`frontend_bucket_name`, `cloudfront_comment`).
- [ ] T2 Add `aws_s3_bucket.frontend` — private, versioning enabled, all public access blocked;
      tag `Name = "analyst-frontend"`.
- [ ] T3 Add `aws_s3_bucket_policy.frontend` — allows only the CloudFront OAC principal
      `s3:GetObject` on `arn:aws:s3:::<bucket>/*`; denies all other principals.
- [ ] T4 Add `aws_cloudfront_origin_access_control.frontend` — `signing_behavior = "always"`,
      `signing_protocol = "sigv4"`, `origin_access_control_origin_type = "s3"`.
- [ ] T5 Add `aws_cloudfront_distribution.frontend`:
      - Origin 1 (S3, default `/*`): bucket regional domain + OAC, `CachingOptimized` managed policy.
      - Origin 2 (ALB, `/api/*`): ALB DNS name, `CachingDisabled` managed policy, origin path = `""` (no
        prefix; CloudFront behaviour strips `/api` via path pattern match).
      - Viewer protocol: `redirect-to-https`.
      - Default root object: `index.html`.
      - Custom error response: HTTP 404 → `/index.html`, response code 200 (SPA routing).
      - Price class: `PriceClass_100` (North America + Europe).
- [ ] T6 Add `aws_cloudfront_response_headers_policy.frontend` — `X-Frame-Options: DENY`,
      `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`; attach to both
      CloudFront behaviours.

### Auth rule

- [ ] T7 Add `aws_secretsmanager_secret.frontend_api_token` — name `analyst/frontend_api_token`,
      description "Shared Bearer token for the frontend dashboard".
- [ ] T8 Add `data.aws_secretsmanager_secret_version.frontend_api_token` — reads the token value
      at plan time so it can be injected into the ALB rule condition.
- [ ] T9 Add `aws_alb_listener_rule.frontend_auth` — condition: path pattern `/api/*` AND
      `http-header` `Authorization` does NOT match `Bearer <token_value>`; action: fixed-response
      401 `{"error":"unauthorized"}` with `Content-Type: application/json`. Priority lower than any
      existing rules (check existing rule priorities in `alb.tf`).

### Outputs & Makefile

- [ ] T10 Append to `deploy/aws/terraform/outputs.tf`:
      `cloudfront_domain`, `frontend_bucket_name`, `cloudfront_distribution_id`,
      `frontend_token_secret_arn`.
- [ ] T11 Add `make frontend-deploy` and `make frontend-invalidate` targets to `Makefile` —
      reads `CLOUDFRONT_DOMAIN`, `FRONTEND_BUCKET`, `CF_DIST_ID` from env or `terraform output`.
- [ ] T12 Run `terraform validate` and `terraform plan` — confirm no errors, no changes to
      existing resources, only net-new resources in the plan.

**Exit (Track A):** `terraform apply` creates S3, CloudFront, ALB rule, and Secrets Manager secret;
`terraform output` returns all four new outputs; `curl <cf_domain>/api/healthz` without token → 401;
with correct `Authorization: Bearer <token>` → 200.

---

## Track B — React + Vite Application

### Scaffold

- [ ] T13 Create `frontend/package.json` — dependencies: `react@18`, `react-dom@18`,
      `react-router-dom@6`, `@tanstack/react-query@5`, `axios`; devDependencies: `vite`,
      `@vitejs/plugin-react`, `typescript`, `tailwindcss`, `postcss`, `autoprefixer`,
      `@types/react`, `@types/react-dom`; scripts: `dev`, `build`, `preview`.
- [ ] T14 Create `frontend/vite.config.ts` — `@vitejs/plugin-react`, server proxy
      `/api → process.env.VITE_API_BASE_URL` (strip `/api` prefix in rewrite), define
      `VITE_API_BASE_URL` env var.
- [ ] T15 Create `frontend/tsconfig.json` — strict mode, `jsx: react-jsx`, path aliases
      (`@/` → `src/`), `moduleResolution: bundler`.
- [ ] T16 Create `frontend/tailwind.config.ts` — content glob `./src/**/*.{ts,tsx}`;
      theme extend for brand colours if needed.
- [ ] T17 Create `frontend/index.html` — UTF-8, viewport, title "Profile Analyst", mount `<div id="root">`.
- [ ] T18 Create `frontend/src/main.tsx` — `ReactDOM.createRoot`, mount `<App />` inside
      `<QueryClientProvider client={new QueryClient()}>`.

### Auth layer

- [ ] T19 Create `frontend/src/auth/LockScreen.tsx` — centred card: "Profile Analyst" h1, password
      `<input type="password">`, "Unlock" button. On submit: `sessionStorage.setItem('pa_token', value)`,
      call `onUnlock()`. Show "Invalid token" message only after a failed API call (401 from interceptor).
- [ ] T20 Create `frontend/src/api/client.ts` — `axios.create({ baseURL: '/api' })`;
      request interceptor adds `Authorization: Bearer <sessionStorage.getItem('pa_token')>`;
      response interceptor on 401 clears `pa_token` and calls `window.location.reload()`.
- [ ] T21 Create `frontend/src/App.tsx` — reads `sessionStorage.getItem('pa_token')` on mount;
      renders `<LockScreen onUnlock={() => setUnlocked(true)}>` when null, full app shell when set.
      App shell: top nav bar with logo, nav links (`/`, `/query`, `/dossiers`), `<HealthDot>` right-aligned;
      `<Routes>` for the three views.

### Hooks

- [ ] T22 Create `frontend/src/hooks/useHealth.ts` — `useQuery` hitting `GET /healthz`,
      `refetchInterval: 30_000`, returns `{ isHealthy: boolean, isLoading: boolean }`.
- [ ] T23 Create `frontend/src/hooks/useRuns.ts` — in-memory cache of `RunResponse[]` in component state
      or React Query cache; `addRun(run)` appends; `useRunPoller(run_id)` calls `useQuery` on
      `GET /runs/{id}` with `refetchInterval: 5_000`, stops when `status` is `done` or `failed`.
      Returns `{ runs, addRun, useRunPoller }`.
- [ ] T24 Create `frontend/src/hooks/useAsk.ts` — `useMutation` calling `POST /ask`; exposes
      `{ mutate, data, error, isPending }`.
- [ ] T25 Create `frontend/src/hooks/useRag.ts` — same shape as `useAsk`, calling `POST /rag`.

### Components

- [ ] T26 Create `frontend/src/components/HealthDot.tsx` — `useHealth()` → 10 px circle:
      `bg-green-500` healthy, `bg-red-500` unhealthy, `bg-gray-400` loading.
- [ ] T27 Create `frontend/src/components/NewRunForm.tsx` — controlled form: handle `<input>`
      (pattern `[a-zA-Z0-9_]+`, required), stages radio group (`all` | `1,2,3` | `1,2,3,6` | custom),
      custom text `<input>` shown when "custom" selected, Submit button (disabled while pending).
      `onRunCreated(run: RunResponse)` callback prop.
- [ ] T28 Create `frontend/src/components/RunTable.tsx` — `runs: RunResponse[]` prop; table
      columns: handle, stages, status (badge), started_at (local datetime format), elapsed.
      Status badges: queued=`bg-gray-200`, running=`bg-blue-500 animate-pulse`, done=`bg-green-500`,
      failed=`bg-red-500`. Empty state: "No runs yet — submit one on the left."
- [ ] T29 Create `frontend/src/components/AskPanel.tsx` — handle + question form; on submit calls
      `useAsk().mutate`; success state: answer prose block, Cypher `<pre>` (monospace, `whitespace-pre-wrap`),
      row count badge; error/422 state: rejection reasons `<ul>`.
- [ ] T30 Create `frontend/src/components/RagPanel.tsx` — same form shape as AskPanel; success:
      answer prose, source chunks table (text | score | mode); error state with message.
- [ ] T31 Create `frontend/src/components/DossierCard.tsx` — receives a manifest object;
      renders five sections:
      - **Profile card:** handle, platform, follower count, niche + confidence progress bar.
      - **Engagement card:** ER by Followers, avg likes, avg comments.
      - **Sponsored Posts card:** count, FTC disclosure status badge, flagged post slugs list.
      - **Compliance card:** `compliance_flags` array — each flag has label + severity;
        Art.9 = amber background, FTC = red background.
      - **Attributes card:** brand affinities list, content attributes with confidence bars.
      "No dossier data" empty state when manifest is null.

### Views

- [ ] T32 Create `frontend/src/views/RunManager.tsx` — two-column grid: `<NewRunForm>` left,
      `<RunTable runs={runs}>` right. `onRunCreated`: calls `addRun(run)` + `useRunPoller(run_id)`
      immediately. Show success banner with `run_id` for 5 s after form submit.
- [ ] T33 Create `frontend/src/views/QueryInterface.tsx` — tab bar with "Ask" and "RAG" tabs
      (Tailwind pill style); renders `<AskPanel>` or `<RagPanel>` based on active tab.
- [ ] T34 Create `frontend/src/views/DossierBrowser.tsx` — reads completed runs from `useRuns()`;
      summary table: handle, completed_at, niche (top-line). Click row → fetches full manifest
      via `GET /runs/{id}`, stores in local state, renders `<DossierCard>` in a right-side drawer
      (fixed panel, closes with ✕). Empty state: "No completed runs yet."

### Final wiring & build check

- [ ] T35 Wire all three views into `App.tsx` routes; verify nav links are active-highlighted via
      `NavLink` from `react-router-dom`.
- [ ] T36 Run `npm run build` — confirm zero TypeScript errors; check gzipped bundle size
      (`vite build --report`); fix if > 500 kB.
- [ ] T37 Run `VITE_API_BASE_URL=http://localhost:8000 npm run dev` — verify all three views
      load and all interactions work against the local API.

**Exit (Track B):** `npm run build` succeeds with no errors; bundle ≤ 500 kB gzipped; all views
render and interact correctly against local API; LockScreen blocks without token; 401 from API
triggers re-lock.

---

## Track C — Deployment & Integration

### Makefile & deploy

- [ ] T38 Add `make frontend-build` target — `cd frontend && VITE_API_BASE_URL=https://$(CLOUDFRONT_DOMAIN) npm run build`.
- [ ] T39 Add `make frontend-deploy` target — `make frontend-build && aws s3 sync frontend/dist/ s3://$(FRONTEND_BUCKET)/ --delete && make frontend-invalidate`.
- [ ] T40 Add `make frontend-invalidate` target — `aws cloudfront create-invalidation --distribution-id $(CF_DIST_ID) --paths "/*"`.
- [ ] T41 Document `CLOUDFRONT_DOMAIN`, `FRONTEND_BUCKET`, `CF_DIST_ID` in repo `README.md` or
      `deploy/aws/README.md` — how to read them from `terraform output`.

### Bootstrap & smoke checks

- [ ] T42 Bootstrap: set the Secrets Manager secret value out-of-band:
      `aws secretsmanager put-secret-value --secret-id analyst/frontend_api_token --secret-string "<token>"`.
      Verify ALB listener rule reloads (may need `terraform apply` refresh if value is plan-time injected).
- [ ] T43 Smoke check 1 — auth gate: `curl https://<cf_domain>/api/healthz` → 401;
      with correct header → 200.
- [ ] T44 Smoke check 2 — SPA served: `curl https://<cf_domain>/` returns `index.html` with `<div id="root">`.
- [ ] T45 Smoke check 3 — browser: open CloudFront URL; LockScreen appears; enter correct token;
      Run Manager loads; health dot is green.
- [ ] T46 Smoke check 4 — run lifecycle: submit `sample` handle → `run_id` banner; table shows
      `running` badge; after completion shows `done` badge.
- [ ] T47 Smoke check 5 — Ask: navigate to Query Interface; submit a question; answer + Cypher rendered.
- [ ] T48 Smoke check 6 — RAG: RAG tab; submit a question; answer + source chunks rendered.
- [ ] T49 Smoke check 7 — Dossier Browser: navigate; completed `sample` row appears; click → DossierCard
      renders all five sections.
- [ ] T50 Smoke check 8 — wrong token: enter wrong token on LockScreen; error state shown; no API call made.
- [ ] T51 Smoke check 9 — session scope: close tab, reopen → LockScreen reappears.

### Validate

- [ ] T52 Run `make validate` — confirm spec 0009 `metadata.yml` passes schema validation (status
      `accepted`, all required fields present).
- [ ] T53 Confirm `terraform plan` is still idempotent after Track A apply (no unexpected diffs).

**Exit (Track C):** All 9 smoke checks pass against the CloudFront domain; `make frontend-deploy`
completes in < 60 s; `make validate` is green; SPA is reachable and all features work end-to-end.

---

## Final handoff

All three tracks completed: Terraform provisions the S3 + CloudFront + ALB auth rule; the React app
is built and deployed; all smoke checks pass. No push to remote — branch stays local for review.
