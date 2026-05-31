# Frontend Dashboard Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a React + Vite SPA dashboard that wraps the existing profile-analyst API (spec 0008 ALB) in three views: Run Manager (trigger + monitor batch runs), Query Interface (/ask and /rag), and Dossier Browser.

**Architecture:** Static SPA under `frontend/`; served by S3 + CloudFront in prod (two origins: S3 for assets, ALB for `/api/*`); Vite proxy rewrites `/api/*` → `localhost:8000` in dev. Auth via shared Bearer token stored in `sessionStorage`, enforced by an ALB listener rule. React Query handles all server state. No new backend code.

**Tech Stack:** React 18, React Router v6, @tanstack/react-query v5, axios, Tailwind CSS v3, Vite 5, TypeScript 5 — tested with Vitest + @testing-library/react + msw v2.

**Spec:** `specs/0009-frontend-dashboard/` — read `spec.md` before touching any file.

---

## API Reference (exact shapes)

```ts
// POST /ask
Request:  { question: string; handle?: string }
Response: { answer: string; manifest_path: string; cypher?: string; row_count?: number }

// POST /rag
Request:  { question: string; handle?: string; modes?: string[] }
Response: { answer: string; citations: string[]; manifest_path: string; modes_run?: string[] }

// POST /runs
Request:  { handle: string; stages?: string }   // stages default "all"
Response: { run_id: string; status: string; url: string }

// GET /runs/{run_id}?handle=<h>
Response: { run_id: string; status: string; created_at: string; updated_at?: string }

// GET /healthz
Response: { status: string; neo4j: string; ollama: string }
```

Status values: `"queued"` | `"running"` | `"succeeded"` | `"failed"`

---

## Task 1: Scaffold — package.json and config files

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/tailwind.config.ts`
- Create: `frontend/postcss.config.js`
- Create: `frontend/index.html`

**Step 1: Create `frontend/package.json`**

```json
{
  "name": "profile-analyst-frontend",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview",
    "test": "vitest",
    "test:ui": "vitest --ui",
    "test:coverage": "vitest run --coverage"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.26.1",
    "@tanstack/react-query": "^5.56.2",
    "axios": "^1.7.7"
  },
  "devDependencies": {
    "@types/react": "^18.3.5",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.1",
    "typescript": "^5.5.3",
    "vite": "^5.4.2",
    "tailwindcss": "^3.4.11",
    "postcss": "^8.4.45",
    "autoprefixer": "^10.4.20",
    "vitest": "^2.0.5",
    "@testing-library/react": "^16.0.1",
    "@testing-library/jest-dom": "^6.5.0",
    "@testing-library/user-event": "^14.5.2",
    "msw": "^2.4.1",
    "jsdom": "^25.0.0",
    "@vitest/coverage-v8": "^2.0.5"
  }
}
```

**Step 2: Create `frontend/vite.config.ts`**

```ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': '/src' },
  },
  server: {
    proxy: {
      '/api': {
        target: process.env.VITE_API_BASE_URL ?? 'http://localhost:8000',
        rewrite: (path) => path.replace(/^\/api/, ''),
        changeOrigin: true,
      },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    coverage: { provider: 'v8' },
  },
})
```

**Step 3: Create `frontend/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "baseUrl": ".",
    "paths": { "@/*": ["src/*"] }
  },
  "include": ["src"]
}
```

**Step 4: Create `frontend/tailwind.config.ts`**

```ts
import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: { extend: {} },
  plugins: [],
} satisfies Config
```

**Step 5: Create `frontend/postcss.config.js`**

```js
export default {
  plugins: { tailwindcss: {}, autoprefixer: {} },
}
```

**Step 6: Create `frontend/index.html`**

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Profile Analyst</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

**Step 7: Install dependencies and verify**

```bash
cd frontend && npm install
```

Expected: `node_modules/` created, no errors.

**Step 8: Commit**

```bash
git add frontend/
git commit -m "feat(frontend): scaffold React+Vite project with Tailwind + Vitest"
```

---

## Task 2: Test setup + API client

**Files:**
- Create: `frontend/src/test/setup.ts`
- Create: `frontend/src/test/server.ts`
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/api/client.test.ts`

**Step 1: Create `frontend/src/test/setup.ts`**

```ts
import '@testing-library/jest-dom'
import { afterAll, afterEach, beforeAll } from 'vitest'
import { server } from './server'

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => server.resetHandlers())
afterAll(() => server.close())
```

**Step 2: Create `frontend/src/test/server.ts`** (MSW mock server used by all tests)

```ts
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'

export const handlers = [
  http.get('/api/healthz', () =>
    HttpResponse.json({ status: 'ok', neo4j: 'ok', ollama: 'ok' })
  ),
  http.post('/api/ask', () =>
    HttpResponse.json({ answer: 'mock answer', manifest_path: '/tmp/x', cypher: 'MATCH (n) RETURN n', row_count: 1 })
  ),
  http.post('/api/rag', () =>
    HttpResponse.json({ answer: 'mock rag answer', citations: ['chunk 1'], manifest_path: '/tmp/y', modes_run: ['vector'] })
  ),
  http.post('/api/runs', () =>
    HttpResponse.json({ run_id: 'abc123', status: 'queued', url: '/runs/abc123' })
  ),
  http.get('/api/runs/:run_id', () =>
    HttpResponse.json({ run_id: 'abc123', status: 'succeeded', created_at: '2026-05-30T10:00:00Z', updated_at: '2026-05-30T10:01:00Z' })
  ),
]

export const server = setupServer(...handlers)
```

**Step 3: Write failing test for API client**

Create `frontend/src/api/client.test.ts`:

```ts
import { describe, it, expect, beforeEach } from 'vitest'
import { http, HttpResponse } from 'msw'
import { server } from '../test/server'

describe('API client', () => {
  beforeEach(() => {
    sessionStorage.clear()
  })

  it('attaches Bearer token from sessionStorage', async () => {
    sessionStorage.setItem('pa_token', 'test-secret')
    let capturedHeader: string | null = null

    server.use(
      http.get('/api/healthz', ({ request }) => {
        capturedHeader = request.headers.get('Authorization')
        return HttpResponse.json({ status: 'ok', neo4j: 'ok', ollama: 'ok' })
      })
    )

    const { client } = await import('./client')
    await client.get('/healthz')
    expect(capturedHeader).toBe('Bearer test-secret')
  })

  it('sends no Authorization header when token absent', async () => {
    let capturedHeader: string | null = 'initial'

    server.use(
      http.get('/api/healthz', ({ request }) => {
        capturedHeader = request.headers.get('Authorization')
        return HttpResponse.json({ status: 'ok', neo4j: 'ok', ollama: 'ok' })
      })
    )

    const { client } = await import('./client')
    await client.get('/healthz')
    expect(capturedHeader).toBeNull()
  })
})
```

**Step 4: Run to confirm it fails**

```bash
cd frontend && npm test -- client.test.ts
```

Expected: FAIL — module `./client` not found.

**Step 5: Create `frontend/src/api/client.ts`**

```ts
import axios from 'axios'

export const client = axios.create({ baseURL: '/api' })

client.interceptors.request.use((config) => {
  const token = sessionStorage.getItem('pa_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

client.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      sessionStorage.removeItem('pa_token')
      window.location.reload()
    }
    return Promise.reject(err)
  }
)
```

**Step 6: Run tests — expect pass**

```bash
cd frontend && npm test -- client.test.ts
```

Expected: PASS (2 tests).

**Step 7: Commit**

```bash
git add frontend/src/
git commit -m "feat(frontend): API client with Bearer token interceptor"
```

---

## Task 3: LockScreen + main entry + App shell skeleton

**Files:**
- Create: `frontend/src/auth/LockScreen.tsx`
- Create: `frontend/src/auth/LockScreen.test.tsx`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/index.css`

**Step 1: Write failing test for LockScreen**

Create `frontend/src/auth/LockScreen.test.tsx`:

```tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { LockScreen } from './LockScreen'

describe('LockScreen', () => {
  it('renders password input and unlock button', () => {
    render(<LockScreen onUnlock={vi.fn()} />)
    expect(screen.getByPlaceholderText('Enter access token')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /unlock/i })).toBeInTheDocument()
  })

  it('stores token in sessionStorage and calls onUnlock', async () => {
    const onUnlock = vi.fn()
    render(<LockScreen onUnlock={onUnlock} />)
    await userEvent.type(screen.getByPlaceholderText('Enter access token'), 'my-secret')
    await userEvent.click(screen.getByRole('button', { name: /unlock/i }))
    expect(sessionStorage.getItem('pa_token')).toBe('my-secret')
    expect(onUnlock).toHaveBeenCalledOnce()
  })

  it('does not call onUnlock when input is empty', async () => {
    const onUnlock = vi.fn()
    render(<LockScreen onUnlock={onUnlock} />)
    await userEvent.click(screen.getByRole('button', { name: /unlock/i }))
    expect(onUnlock).not.toHaveBeenCalled()
  })
})
```

**Step 2: Run — expect FAIL**

```bash
cd frontend && npm test -- LockScreen.test.tsx
```

Expected: FAIL — module not found.

**Step 3: Create `frontend/src/auth/LockScreen.tsx`**

```tsx
import { useState } from 'react'

interface Props { onUnlock: () => void }

export function LockScreen({ onUnlock }: Props) {
  const [token, setToken] = useState('')

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!token.trim()) return
    sessionStorage.setItem('pa_token', token.trim())
    onUnlock()
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="bg-white rounded-xl shadow-md p-8 w-80">
        <h1 className="text-2xl font-bold text-gray-800 mb-6 text-center">Profile Analyst</h1>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <input
            type="password"
            placeholder="Enter access token"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            className="border border-gray-300 rounded-lg px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <button
            type="submit"
            className="bg-blue-600 text-white rounded-lg py-2 text-sm font-medium hover:bg-blue-700 transition-colors"
          >
            Unlock
          </button>
        </form>
      </div>
    </div>
  )
}
```

**Step 4: Run — expect PASS**

```bash
cd frontend && npm test -- LockScreen.test.tsx
```

Expected: PASS (3 tests).

**Step 5: Create `frontend/src/index.css`**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;
```

**Step 6: Create `frontend/src/main.tsx`**

```tsx
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import './index.css'
import { App } from './App'

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1 } },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>
)
```

**Step 7: Commit**

```bash
git add frontend/src/
git commit -m "feat(frontend): LockScreen component + main entry point"
```

---

## Task 4: useHealth hook + HealthDot component

**Files:**
- Create: `frontend/src/hooks/useHealth.ts`
- Create: `frontend/src/hooks/useHealth.test.ts`
- Create: `frontend/src/components/HealthDot.tsx`
- Create: `frontend/src/components/HealthDot.test.tsx`

**Step 1: Write failing test for useHealth**

Create `frontend/src/hooks/useHealth.test.ts`:

```ts
import { describe, it, expect } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createElement } from 'react'
import { useHealth } from './useHealth'

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return createElement(QueryClientProvider, { client: qc }, children)
}

describe('useHealth', () => {
  it('returns isHealthy=true when API returns status ok', async () => {
    const { result } = renderHook(() => useHealth(), { wrapper })
    await waitFor(() => expect(result.current.isLoading).toBe(false))
    expect(result.current.isHealthy).toBe(true)
  })
})
```

**Step 2: Run — expect FAIL**

```bash
cd frontend && npm test -- useHealth.test.ts
```

**Step 3: Create `frontend/src/hooks/useHealth.ts`**

```ts
import { useQuery } from '@tanstack/react-query'
import { client } from '@/api/client'

interface HealthResponse {
  status: string
  neo4j: string
  ollama: string
}

export function useHealth() {
  const { data, isLoading, isError } = useQuery<HealthResponse>({
    queryKey: ['health'],
    queryFn: () => client.get<HealthResponse>('/healthz').then((r) => r.data),
    refetchInterval: 30_000,
    staleTime: 25_000,
  })

  return {
    isHealthy: !isLoading && !isError && data?.status === 'ok',
    isLoading,
    data,
  }
}
```

**Step 4: Run — expect PASS**

```bash
cd frontend && npm test -- useHealth.test.ts
```

**Step 5: Write failing test for HealthDot**

Create `frontend/src/components/HealthDot.test.tsx`:

```tsx
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { HealthDot } from './HealthDot'

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

describe('HealthDot', () => {
  it('renders a coloured circle', async () => {
    render(<HealthDot />, { wrapper })
    // The dot element should exist immediately (loading state = grey)
    const dot = screen.getByRole('status')
    expect(dot).toBeInTheDocument()
  })
})
```

**Step 6: Create `frontend/src/components/HealthDot.tsx`**

```tsx
import { useHealth } from '@/hooks/useHealth'

export function HealthDot() {
  const { isHealthy, isLoading } = useHealth()
  const colour = isLoading
    ? 'bg-gray-400'
    : isHealthy
    ? 'bg-green-500'
    : 'bg-red-500'
  const label = isLoading ? 'Checking API…' : isHealthy ? 'API healthy' : 'API unreachable'

  return (
    <span
      role="status"
      aria-label={label}
      title={label}
      className={`inline-block w-2.5 h-2.5 rounded-full ${colour}`}
    />
  )
}
```

**Step 7: Run all tests — expect PASS**

```bash
cd frontend && npm test
```

**Step 8: Commit**

```bash
git add frontend/src/
git commit -m "feat(frontend): useHealth hook + HealthDot component"
```

---

## Task 5: useRuns, useAsk, useRag hooks

**Files:**
- Create: `frontend/src/hooks/useRuns.ts`
- Create: `frontend/src/hooks/useRuns.test.ts`
- Create: `frontend/src/hooks/useAsk.ts`
- Create: `frontend/src/hooks/useRag.ts`

**Step 1: Write failing test for useRuns**

Create `frontend/src/hooks/useRuns.test.ts`:

```ts
import { describe, it, expect } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { useRuns } from './useRuns'

describe('useRuns', () => {
  it('starts with an empty runs list', () => {
    const { result } = renderHook(() => useRuns())
    expect(result.current.runs).toHaveLength(0)
  })

  it('addRun appends to the list', () => {
    const { result } = renderHook(() => useRuns())
    act(() => {
      result.current.addRun({ run_id: 'r1', status: 'queued', url: '/runs/r1', handle: 'sample', stages: 'all' })
    })
    expect(result.current.runs).toHaveLength(1)
    expect(result.current.runs[0].run_id).toBe('r1')
  })
})
```

**Step 2: Run — expect FAIL**

```bash
cd frontend && npm test -- useRuns.test.ts
```

**Step 3: Create `frontend/src/hooks/useRuns.ts`**

```ts
import { useCallback, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { client } from '@/api/client'

export interface RunEntry {
  run_id: string
  status: string
  url: string
  handle: string
  stages: string
  created_at?: string
  updated_at?: string
}

interface RunStatus {
  run_id: string
  status: string
  created_at: string
  updated_at?: string
}

export function useRuns() {
  const [runs, setRuns] = useState<RunEntry[]>([])

  const addRun = useCallback((run: RunEntry) => {
    setRuns((prev) => [run, ...prev])
  }, [])

  const updateRunStatus = useCallback((run_id: string, updates: Partial<RunEntry>) => {
    setRuns((prev) => prev.map((r) => (r.run_id === run_id ? { ...r, ...updates } : r)))
  }, [])

  return { runs, addRun, updateRunStatus }
}

export function useRunPoller(
  run_id: string,
  handle: string,
  onUpdate: (run_id: string, updates: Partial<RunEntry>) => void
) {
  const isActive = true

  return useQuery<RunStatus>({
    queryKey: ['run', run_id],
    queryFn: () =>
      client
        .get<RunStatus>(`/runs/${run_id}`, { params: { handle } })
        .then((r) => r.data),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      if (status === 'succeeded' || status === 'failed') return false
      return 5_000
    },
    enabled: isActive,
    select: (data) => {
      onUpdate(run_id, { status: data.status, updated_at: data.updated_at })
      return data
    },
  })
}
```

**Step 4: Run — expect PASS**

```bash
cd frontend && npm test -- useRuns.test.ts
```

**Step 5: Create `frontend/src/hooks/useAsk.ts`**

```ts
import { useMutation } from '@tanstack/react-query'
import { client } from '@/api/client'

export interface AskRequest { question: string; handle?: string }
export interface AskResponse {
  answer: string
  manifest_path: string
  cypher?: string
  row_count?: number
}

export function useAsk() {
  return useMutation<AskResponse, { response?: { data?: { detail?: unknown } } }, AskRequest>({
    mutationFn: (req) => client.post<AskResponse>('/ask', req).then((r) => r.data),
  })
}
```

**Step 6: Create `frontend/src/hooks/useRag.ts`**

```ts
import { useMutation } from '@tanstack/react-query'
import { client } from '@/api/client'

export interface RagRequest { question: string; handle?: string; modes?: string[] }
export interface RagResponse {
  answer: string
  citations: string[]
  manifest_path: string
  modes_run?: string[]
}

export function useRag() {
  return useMutation<RagResponse, { response?: { data?: { detail?: unknown } } }, RagRequest>({
    mutationFn: (req) => client.post<RagResponse>('/rag', req).then((r) => r.data),
  })
}
```

**Step 7: Run all tests**

```bash
cd frontend && npm test
```

Expected: PASS.

**Step 8: Commit**

```bash
git add frontend/src/
git commit -m "feat(frontend): useRuns, useAsk, useRag hooks"
```

---

## Task 6: NewRunForm component

**Files:**
- Create: `frontend/src/components/NewRunForm.tsx`
- Create: `frontend/src/components/NewRunForm.test.tsx`

**Step 1: Write failing test**

Create `frontend/src/components/NewRunForm.test.tsx`:

```tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { NewRunForm } from './NewRunForm'

function wrapper({ children }: { children: React.ReactNode }) {
  return <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>
}

describe('NewRunForm', () => {
  it('renders handle input and stages options', () => {
    render(<NewRunForm onRunCreated={vi.fn()} />, { wrapper })
    expect(screen.getByPlaceholderText('instagram_handle')).toBeInTheDocument()
    expect(screen.getByLabelText(/all stages/i)).toBeInTheDocument()
  })

  it('calls onRunCreated with run data after successful submit', async () => {
    const onRunCreated = vi.fn()
    render(<NewRunForm onRunCreated={onRunCreated} />, { wrapper })

    await userEvent.type(screen.getByPlaceholderText('instagram_handle'), 'sample')
    await userEvent.click(screen.getByRole('button', { name: /run pipeline/i }))

    // MSW handler returns { run_id: 'abc123', status: 'queued', url: '/runs/abc123' }
    await vi.waitFor(() => expect(onRunCreated).toHaveBeenCalledOnce())
    expect(onRunCreated).toHaveBeenCalledWith(
      expect.objectContaining({ run_id: 'abc123', handle: 'sample' })
    )
  })

  it('does not submit when handle is empty', async () => {
    const onRunCreated = vi.fn()
    render(<NewRunForm onRunCreated={onRunCreated} />, { wrapper })
    await userEvent.click(screen.getByRole('button', { name: /run pipeline/i }))
    expect(onRunCreated).not.toHaveBeenCalled()
  })
})
```

**Step 2: Run — expect FAIL**

```bash
cd frontend && npm test -- NewRunForm.test.tsx
```

**Step 3: Create `frontend/src/components/NewRunForm.tsx`**

```tsx
import { useState } from 'react'
import { client } from '@/api/client'
import type { RunEntry } from '@/hooks/useRuns'

const STAGE_OPTIONS = [
  { label: 'All stages', value: 'all' },
  { label: '1,2,3 (ingest → features)', value: '1,2,3' },
  { label: '1,2,3,6 (+ dossier)', value: '1,2,3,6' },
  { label: 'Custom', value: 'custom' },
]

interface Props { onRunCreated: (run: RunEntry) => void }

export function NewRunForm({ onRunCreated }: Props) {
  const [handle, setHandle] = useState('')
  const [stages, setStages] = useState('all')
  const [customStages, setCustomStages] = useState('')
  const [isPending, setIsPending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!handle.trim()) return
    const stagesValue = stages === 'custom' ? customStages.trim() || 'all' : stages
    setIsPending(true)
    setError(null)
    try {
      const res = await client.post<{ run_id: string; status: string; url: string }>(
        '/runs',
        { handle: handle.trim(), stages: stagesValue }
      )
      onRunCreated({ ...res.data, handle: handle.trim(), stages: stagesValue })
      setHandle('')
    } catch (err: unknown) {
      setError('Failed to enqueue run. Is the API reachable?')
    } finally {
      setIsPending(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4">
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Handle</label>
        <input
          type="text"
          placeholder="instagram_handle"
          value={handle}
          onChange={(e) => setHandle(e.target.value)}
          pattern="[a-zA-Z0-9_]+"
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">Stages</label>
        <div className="flex flex-col gap-2">
          {STAGE_OPTIONS.map((opt) => (
            <label key={opt.value} className="flex items-center gap-2 text-sm cursor-pointer">
              <input
                type="radio"
                name="stages"
                value={opt.value}
                checked={stages === opt.value}
                onChange={() => setStages(opt.value)}
                aria-label={opt.label}
              />
              {opt.label}
            </label>
          ))}
        </div>
        {stages === 'custom' && (
          <input
            type="text"
            placeholder="e.g. 1,2,3,7"
            value={customStages}
            onChange={(e) => setCustomStages(e.target.value)}
            className="mt-2 w-full border border-gray-300 rounded px-3 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        )}
      </div>

      {error && <p className="text-red-600 text-sm">{error}</p>}

      <button
        type="submit"
        disabled={isPending}
        className="bg-blue-600 text-white rounded-lg py-2 text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors"
      >
        {isPending ? 'Submitting…' : 'Run Pipeline'}
      </button>
    </form>
  )
}
```

**Step 4: Run — expect PASS**

```bash
cd frontend && npm test -- NewRunForm.test.tsx
```

**Step 5: Commit**

```bash
git add frontend/src/
git commit -m "feat(frontend): NewRunForm component"
```

---

## Task 7: RunTable component

**Files:**
- Create: `frontend/src/components/RunTable.tsx`
- Create: `frontend/src/components/RunTable.test.tsx`

**Step 1: Write failing test**

Create `frontend/src/components/RunTable.test.tsx`:

```tsx
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { RunTable } from './RunTable'
import type { RunEntry } from '@/hooks/useRuns'

const mockRuns: RunEntry[] = [
  { run_id: 'r1', status: 'succeeded', url: '/runs/r1', handle: 'user_a', stages: 'all', created_at: '2026-05-30T10:00:00Z' },
  { run_id: 'r2', status: 'running', url: '/runs/r2', handle: 'user_b', stages: '1,2,3', created_at: '2026-05-30T10:05:00Z' },
  { run_id: 'r3', status: 'failed', url: '/runs/r3', handle: 'user_c', stages: 'all', created_at: '2026-05-30T10:10:00Z' },
]

describe('RunTable', () => {
  it('shows empty state when no runs', () => {
    render(<RunTable runs={[]} />)
    expect(screen.getByText(/no runs yet/i)).toBeInTheDocument()
  })

  it('renders a row for each run', () => {
    render(<RunTable runs={mockRuns} />)
    expect(screen.getByText('user_a')).toBeInTheDocument()
    expect(screen.getByText('user_b')).toBeInTheDocument()
    expect(screen.getByText('user_c')).toBeInTheDocument()
  })

  it('shows coloured status badges', () => {
    render(<RunTable runs={mockRuns} />)
    expect(screen.getByText('succeeded')).toBeInTheDocument()
    expect(screen.getByText('running')).toBeInTheDocument()
    expect(screen.getByText('failed')).toBeInTheDocument()
  })
})
```

**Step 2: Run — expect FAIL**

```bash
cd frontend && npm test -- RunTable.test.tsx
```

**Step 3: Create `frontend/src/components/RunTable.tsx`**

```tsx
import type { RunEntry } from '@/hooks/useRuns'

const STATUS_STYLES: Record<string, string> = {
  queued: 'bg-gray-200 text-gray-700',
  running: 'bg-blue-100 text-blue-700 animate-pulse',
  succeeded: 'bg-green-100 text-green-700',
  failed: 'bg-red-100 text-red-700',
}

function elapsed(created_at?: string) {
  if (!created_at) return '—'
  const secs = Math.floor((Date.now() - new Date(created_at).getTime()) / 1000)
  if (secs < 60) return `${secs}s`
  return `${Math.floor(secs / 60)}m ${secs % 60}s`
}

interface Props { runs: RunEntry[] }

export function RunTable({ runs }: Props) {
  if (runs.length === 0) {
    return (
      <p className="text-sm text-gray-500 text-center py-8">
        No runs yet — submit one using the form.
      </p>
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-gray-500 border-b border-gray-200">
            <th className="pb-2 pr-4 font-medium">Handle</th>
            <th className="pb-2 pr-4 font-medium">Stages</th>
            <th className="pb-2 pr-4 font-medium">Status</th>
            <th className="pb-2 font-medium">Elapsed</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.run_id} className="border-b border-gray-100 last:border-0">
              <td className="py-2 pr-4 font-mono text-xs">{run.handle}</td>
              <td className="py-2 pr-4 text-gray-600">{run.stages}</td>
              <td className="py-2 pr-4">
                <span
                  className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${STATUS_STYLES[run.status] ?? 'bg-gray-100 text-gray-600'}`}
                >
                  {run.status}
                </span>
              </td>
              <td className="py-2 text-gray-500">{elapsed(run.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
```

**Step 4: Run — expect PASS**

```bash
cd frontend && npm test -- RunTable.test.tsx
```

**Step 5: Commit**

```bash
git add frontend/src/
git commit -m "feat(frontend): RunTable component with status badges"
```

---

## Task 8: AskPanel + RagPanel components

**Files:**
- Create: `frontend/src/components/AskPanel.tsx`
- Create: `frontend/src/components/AskPanel.test.tsx`
- Create: `frontend/src/components/RagPanel.tsx`
- Create: `frontend/src/components/RagPanel.test.tsx`

**Step 1: Write failing test for AskPanel**

Create `frontend/src/components/AskPanel.test.tsx`:

```tsx
import { describe, it, expect } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AskPanel } from './AskPanel'

function wrapper({ children }: { children: React.ReactNode }) {
  return <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>
}

describe('AskPanel', () => {
  it('renders handle input, question textarea, and submit button', () => {
    render(<AskPanel />, { wrapper })
    expect(screen.getByPlaceholderText('instagram_handle')).toBeInTheDocument()
    expect(screen.getByPlaceholderText(/ask a question/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /ask/i })).toBeInTheDocument()
  })

  it('renders answer and cypher after successful query', async () => {
    render(<AskPanel />, { wrapper })
    await userEvent.type(screen.getByPlaceholderText('instagram_handle'), 'sample')
    await userEvent.type(screen.getByPlaceholderText(/ask a question/i), 'list creators')
    await userEvent.click(screen.getByRole('button', { name: /ask/i }))
    await waitFor(() => expect(screen.getByText('mock answer')).toBeInTheDocument())
    expect(screen.getByText(/MATCH/)).toBeInTheDocument()
  })
})
```

**Step 2: Run — expect FAIL**

```bash
cd frontend && npm test -- AskPanel.test.tsx
```

**Step 3: Create `frontend/src/components/AskPanel.tsx`**

```tsx
import { useState } from 'react'
import { useAsk } from '@/hooks/useAsk'

export function AskPanel() {
  const [handle, setHandle] = useState('')
  const [question, setQuestion] = useState('')
  const { mutate, data, error, isPending } = useAsk()

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!question.trim()) return
    mutate({ question: question.trim(), handle: handle.trim() || undefined })
  }

  const rejection = error && (error as { response?: { data?: { detail?: unknown } } }).response?.data?.detail

  return (
    <div className="flex flex-col gap-4">
      <form onSubmit={handleSubmit} className="flex flex-col gap-3">
        <input
          type="text"
          placeholder="instagram_handle"
          value={handle}
          onChange={(e) => setHandle(e.target.value)}
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <textarea
          placeholder="Ask a question about this creator…"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          rows={3}
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
        />
        <button
          type="submit"
          disabled={isPending}
          className="bg-blue-600 text-white rounded-lg py-2 text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors self-start px-6"
        >
          {isPending ? 'Asking…' : 'Ask'}
        </button>
      </form>

      {rejection && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-3">
          <p className="text-sm font-medium text-red-700 mb-1">Query rejected</p>
          <ul className="list-disc list-inside text-sm text-red-600">
            {Array.isArray(rejection)
              ? rejection.map((r, i) => <li key={i}>{String(r)}</li>)
              : <li>{String(rejection)}</li>}
          </ul>
        </div>
      )}

      {data && (
        <div className="flex flex-col gap-3">
          <div className="bg-gray-50 rounded-lg p-4">
            <p className="text-sm font-medium text-gray-700 mb-1">Answer</p>
            <p className="text-sm text-gray-800">{data.answer}</p>
          </div>
          {data.cypher && (
            <div className="bg-gray-900 rounded-lg p-4">
              <p className="text-xs font-medium text-gray-400 mb-2">Cypher</p>
              <pre className="text-xs text-green-400 whitespace-pre-wrap overflow-auto">{data.cypher}</pre>
            </div>
          )}
          {data.row_count != null && (
            <span className="text-xs text-gray-500">{data.row_count} row{data.row_count !== 1 ? 's' : ''} returned</span>
          )}
        </div>
      )}
    </div>
  )
}
```

**Step 4: Run AskPanel test — expect PASS**

```bash
cd frontend && npm test -- AskPanel.test.tsx
```

**Step 5: Create `frontend/src/components/RagPanel.tsx`**

```tsx
import { useState } from 'react'
import { useRag } from '@/hooks/useRag'

export function RagPanel() {
  const [handle, setHandle] = useState('')
  const [question, setQuestion] = useState('')
  const { mutate, data, error, isPending } = useRag()

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!question.trim()) return
    mutate({ question: question.trim(), handle: handle.trim() || undefined })
  }

  return (
    <div className="flex flex-col gap-4">
      <form onSubmit={handleSubmit} className="flex flex-col gap-3">
        <input
          type="text"
          placeholder="instagram_handle"
          value={handle}
          onChange={(e) => setHandle(e.target.value)}
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <textarea
          placeholder="Ask a question — RAG will retrieve relevant context…"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          rows={3}
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
        />
        <button
          type="submit"
          disabled={isPending}
          className="bg-purple-600 text-white rounded-lg py-2 text-sm font-medium hover:bg-purple-700 disabled:opacity-50 transition-colors self-start px-6"
        >
          {isPending ? 'Retrieving…' : 'Search'}
        </button>
      </form>

      {error && (
        <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded p-3">
          RAG query failed. Check the API and try again.
        </p>
      )}

      {data && (
        <div className="flex flex-col gap-3">
          <div className="bg-gray-50 rounded-lg p-4">
            <p className="text-sm font-medium text-gray-700 mb-1">Answer</p>
            <p className="text-sm text-gray-800">{data.answer}</p>
          </div>
          {data.citations.length > 0 && (
            <div>
              <p className="text-xs font-medium text-gray-500 mb-2">
                Source chunks ({data.modes_run?.join(', ') ?? 'all modes'})
              </p>
              <div className="flex flex-col gap-1">
                {data.citations.map((c, i) => (
                  <p key={i} className="text-xs text-gray-600 bg-gray-100 rounded px-2 py-1">
                    {c}
                  </p>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
```

**Step 6: Create basic test for RagPanel**

Create `frontend/src/components/RagPanel.test.tsx`:

```tsx
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RagPanel } from './RagPanel'

function wrapper({ children }: { children: React.ReactNode }) {
  return <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>
}

describe('RagPanel', () => {
  it('renders form', () => {
    render(<RagPanel />, { wrapper })
    expect(screen.getByRole('button', { name: /search/i })).toBeInTheDocument()
  })
})
```

**Step 7: Run all tests**

```bash
cd frontend && npm test
```

Expected: PASS.

**Step 8: Commit**

```bash
git add frontend/src/
git commit -m "feat(frontend): AskPanel and RagPanel components"
```

---

## Task 9: DossierCard component

**Files:**
- Create: `frontend/src/components/DossierCard.tsx`
- Create: `frontend/src/components/DossierCard.test.tsx`

**Step 1: Write failing test**

Create `frontend/src/components/DossierCard.test.tsx`:

```tsx
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { DossierCard } from './DossierCard'

const mockManifest = {
  handle: 'sample_creator',
  platform: 'instagram',
  follower_count: 12500,
  niche: 'fitness',
  niche_confidence: 0.91,
  engagement_rate: 4.2,
  avg_likes: 520,
  avg_comments: 31,
  sponsored_post_count: 2,
  ftc_disclosure_status: 'partial',
  flagged_posts: ['post_abc', 'post_def'],
  compliance_flags: [
    { label: 'Art.9 risk: health inference', severity: 'art9' },
    { label: 'FTC: undisclosed #ad', severity: 'ftc' },
  ],
  brand_affinities: ['Nike', 'Whey Protein Co'],
  content_attributes: [
    { label: 'Outdoor sports', confidence: 0.85 },
    { label: 'Nutrition', confidence: 0.72 },
  ],
}

describe('DossierCard', () => {
  it('renders null state when no manifest', () => {
    render(<DossierCard manifest={null} />)
    expect(screen.getByText(/no dossier data/i)).toBeInTheDocument()
  })

  it('renders profile section with handle and niche', () => {
    render(<DossierCard manifest={mockManifest} />)
    expect(screen.getByText('sample_creator')).toBeInTheDocument()
    expect(screen.getByText('fitness')).toBeInTheDocument()
    expect(screen.getByText('12,500')).toBeInTheDocument()
  })

  it('renders engagement metrics', () => {
    render(<DossierCard manifest={mockManifest} />)
    expect(screen.getByText('4.2%')).toBeInTheDocument()
  })

  it('highlights Art.9 and FTC compliance flags with colours', () => {
    render(<DossierCard manifest={mockManifest} />)
    const art9 = screen.getByText('Art.9 risk: health inference')
    expect(art9.closest('div')).toHaveClass('bg-amber-50')
    const ftc = screen.getByText('FTC: undisclosed #ad')
    expect(ftc.closest('div')).toHaveClass('bg-red-50')
  })
})
```

**Step 2: Run — expect FAIL**

```bash
cd frontend && npm test -- DossierCard.test.tsx
```

**Step 3: Create `frontend/src/components/DossierCard.tsx`**

```tsx
interface ComplianceFlag { label: string; severity: 'art9' | 'ftc' | 'info' }
interface Attribute { label: string; confidence: number }

interface DossierManifest {
  handle: string
  platform?: string
  follower_count?: number
  niche?: string
  niche_confidence?: number
  engagement_rate?: number
  avg_likes?: number
  avg_comments?: number
  sponsored_post_count?: number
  ftc_disclosure_status?: string
  flagged_posts?: string[]
  compliance_flags?: ComplianceFlag[]
  brand_affinities?: string[]
  content_attributes?: Attribute[]
}

interface Props { manifest: DossierManifest | null }

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4">
      <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">{title}</h3>
      {children}
    </div>
  )
}

function ConfidenceBar({ value }: { value: number }) {
  return (
    <div className="w-full bg-gray-100 rounded-full h-1.5">
      <div className="bg-blue-500 h-1.5 rounded-full" style={{ width: `${Math.round(value * 100)}%` }} />
    </div>
  )
}

const SEVERITY_STYLES: Record<string, string> = {
  art9: 'bg-amber-50 border-amber-200 text-amber-800',
  ftc: 'bg-red-50 border-red-200 text-red-800',
  info: 'bg-gray-50 border-gray-200 text-gray-700',
}

export function DossierCard({ manifest }: Props) {
  if (!manifest) {
    return <p className="text-sm text-gray-400 text-center py-8">No dossier data available.</p>
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Profile */}
      <Section title="Profile">
        <div className="flex items-start justify-between">
          <div>
            <p className="text-lg font-semibold text-gray-800">@{manifest.handle}</p>
            <p className="text-sm text-gray-500">{manifest.platform ?? 'instagram'}</p>
          </div>
          {manifest.follower_count != null && (
            <div className="text-right">
              <p className="text-xl font-bold text-gray-800">{manifest.follower_count.toLocaleString()}</p>
              <p className="text-xs text-gray-500">followers</p>
            </div>
          )}
        </div>
        {manifest.niche && (
          <div className="mt-3">
            <div className="flex items-center justify-between mb-1">
              <span className="text-sm font-medium text-gray-700">{manifest.niche}</span>
              {manifest.niche_confidence != null && (
                <span className="text-xs text-gray-500">{Math.round(manifest.niche_confidence * 100)}%</span>
              )}
            </div>
            {manifest.niche_confidence != null && <ConfidenceBar value={manifest.niche_confidence} />}
          </div>
        )}
      </Section>

      {/* Engagement */}
      <Section title="Engagement">
        <div className="grid grid-cols-3 gap-4">
          {manifest.engagement_rate != null && (
            <div className="text-center">
              <p className="text-lg font-bold text-gray-800">{manifest.engagement_rate}%</p>
              <p className="text-xs text-gray-500">ER by Followers</p>
            </div>
          )}
          {manifest.avg_likes != null && (
            <div className="text-center">
              <p className="text-lg font-bold text-gray-800">{manifest.avg_likes.toLocaleString()}</p>
              <p className="text-xs text-gray-500">Avg Likes</p>
            </div>
          )}
          {manifest.avg_comments != null && (
            <div className="text-center">
              <p className="text-lg font-bold text-gray-800">{manifest.avg_comments.toLocaleString()}</p>
              <p className="text-xs text-gray-500">Avg Comments</p>
            </div>
          )}
        </div>
      </Section>

      {/* Sponsored Posts */}
      <Section title="Sponsored Posts">
        <div className="flex items-center gap-4 mb-2">
          <span className="text-2xl font-bold text-gray-800">{manifest.sponsored_post_count ?? 0}</span>
          <div>
            <p className="text-xs text-gray-500">detected</p>
            {manifest.ftc_disclosure_status && (
              <span className={`text-xs px-2 py-0.5 rounded font-medium ${manifest.ftc_disclosure_status === 'compliant' ? 'bg-green-100 text-green-700' : 'bg-orange-100 text-orange-700'}`}>
                FTC: {manifest.ftc_disclosure_status}
              </span>
            )}
          </div>
        </div>
        {manifest.flagged_posts && manifest.flagged_posts.length > 0 && (
          <ul className="text-xs text-gray-600 list-disc list-inside">
            {manifest.flagged_posts.map((p) => <li key={p} className="font-mono">{p}</li>)}
          </ul>
        )}
      </Section>

      {/* Compliance */}
      {manifest.compliance_flags && manifest.compliance_flags.length > 0 && (
        <Section title="Compliance">
          <div className="flex flex-col gap-2">
            {manifest.compliance_flags.map((flag, i) => (
              <div key={i} className={`border rounded px-3 py-2 text-xs ${SEVERITY_STYLES[flag.severity] ?? SEVERITY_STYLES.info}`}>
                {flag.label}
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* Attributes */}
      {(manifest.brand_affinities?.length || manifest.content_attributes?.length) && (
        <Section title="Attributes">
          {manifest.brand_affinities && manifest.brand_affinities.length > 0 && (
            <div className="mb-3">
              <p className="text-xs text-gray-500 mb-1">Brand affinities</p>
              <div className="flex flex-wrap gap-1">
                {manifest.brand_affinities.map((b) => (
                  <span key={b} className="bg-blue-50 text-blue-700 text-xs px-2 py-0.5 rounded">{b}</span>
                ))}
              </div>
            </div>
          )}
          {manifest.content_attributes && manifest.content_attributes.length > 0 && (
            <div>
              <p className="text-xs text-gray-500 mb-2">Content attributes</p>
              <div className="flex flex-col gap-2">
                {manifest.content_attributes.map((attr) => (
                  <div key={attr.label}>
                    <div className="flex justify-between text-xs mb-1">
                      <span className="text-gray-700">{attr.label}</span>
                      <span className="text-gray-500">{Math.round(attr.confidence * 100)}%</span>
                    </div>
                    <ConfidenceBar value={attr.confidence} />
                  </div>
                ))}
              </div>
            </div>
          )}
        </Section>
      )}
    </div>
  )
}
```

**Step 4: Run — expect PASS**

```bash
cd frontend && npm test -- DossierCard.test.tsx
```

**Step 5: Commit**

```bash
git add frontend/src/
git commit -m "feat(frontend): DossierCard with 5 structured sections"
```

---

## Task 10: Three views + App shell

**Files:**
- Create: `frontend/src/views/RunManager.tsx`
- Create: `frontend/src/views/QueryInterface.tsx`
- Create: `frontend/src/views/DossierBrowser.tsx`
- Create: `frontend/src/App.tsx`

**Step 1: Create `frontend/src/views/RunManager.tsx`**

```tsx
import { useState, useCallback } from 'react'
import { NewRunForm } from '@/components/NewRunForm'
import { RunTable } from '@/components/RunTable'
import { useRuns, useRunPoller, type RunEntry } from '@/hooks/useRuns'

function RunPoller({ run, onUpdate }: { run: RunEntry; onUpdate: (id: string, u: Partial<RunEntry>) => void }) {
  useRunPoller(run.run_id, run.handle, onUpdate)
  return null
}

export function RunManager() {
  const { runs, addRun, updateRunStatus } = useRuns()
  const [banner, setBanner] = useState<string | null>(null)
  const activeRuns = runs.filter((r) => r.status === 'queued' || r.status === 'running')

  const handleRunCreated = useCallback((run: RunEntry) => {
    addRun({ ...run, created_at: new Date().toISOString() })
    setBanner(run.run_id)
    setTimeout(() => setBanner(null), 5000)
  }, [addRun])

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold text-gray-800 mb-6">Run Manager</h1>

      {banner && (
        <div className="mb-4 bg-green-50 border border-green-200 rounded-lg px-4 py-3 text-sm text-green-700">
          Run <span className="font-mono font-medium">{banner}</span> enqueued successfully.
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <h2 className="text-sm font-semibold text-gray-600 mb-4">New Run</h2>
          <NewRunForm onRunCreated={handleRunCreated} />
        </div>

        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <h2 className="text-sm font-semibold text-gray-600 mb-4">Recent Runs</h2>
          <RunTable runs={runs} />
        </div>
      </div>

      {/* Invisible polling components for active runs */}
      {activeRuns.map((run) => (
        <RunPoller key={run.run_id} run={run} onUpdate={updateRunStatus} />
      ))}
    </div>
  )
}
```

**Step 2: Create `frontend/src/views/QueryInterface.tsx`**

```tsx
import { useState } from 'react'
import { AskPanel } from '@/components/AskPanel'
import { RagPanel } from '@/components/RagPanel'

type Tab = 'ask' | 'rag'

export function QueryInterface() {
  const [tab, setTab] = useState<Tab>('ask')

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold text-gray-800 mb-6">Query Interface</h1>

      <div className="flex gap-2 mb-6">
        {(['ask', 'rag'] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 rounded-full text-sm font-medium transition-colors ${
              tab === t
                ? 'bg-blue-600 text-white'
                : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
            }`}
          >
            {t === 'ask' ? 'Ask (NL→Cypher)' : 'RAG (Hybrid)'}
          </button>
        ))}
      </div>

      <div className="bg-white rounded-xl border border-gray-200 p-5 max-w-2xl">
        {tab === 'ask' ? <AskPanel /> : <RagPanel />}
      </div>
    </div>
  )
}
```

**Step 3: Create `frontend/src/views/DossierBrowser.tsx`**

```tsx
import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { client } from '@/api/client'
import { DossierCard } from '@/components/DossierCard'
import type { RunEntry } from '@/hooks/useRuns'

interface Props { runs: RunEntry[] }

export function DossierBrowser({ runs }: Props) {
  const completedRuns = runs.filter((r) => r.status === 'succeeded')
  const [selected, setSelected] = useState<RunEntry | null>(null)
  const [manifest, setManifest] = useState<Record<string, unknown> | null>(null)
  const [loading, setLoading] = useState(false)

  async function handleSelect(run: RunEntry) {
    setSelected(run)
    setLoading(true)
    try {
      const res = await client.get(`/runs/${run.run_id}`, { params: { handle: run.handle } })
      setManifest(res.data)
    } catch {
      setManifest(null)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold text-gray-800 mb-6">Dossier Browser</h1>

      <div className="flex gap-6">
        {/* Runs table */}
        <div className="flex-1 bg-white rounded-xl border border-gray-200 overflow-hidden">
          {completedRuns.length === 0 ? (
            <p className="text-sm text-gray-400 text-center py-12">No completed runs yet.</p>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-gray-50">
                <tr className="text-left text-gray-500 text-xs">
                  <th className="px-4 py-3 font-medium">Handle</th>
                  <th className="px-4 py-3 font-medium">Stages</th>
                  <th className="px-4 py-3 font-medium">Completed</th>
                </tr>
              </thead>
              <tbody>
                {completedRuns.map((run) => (
                  <tr
                    key={run.run_id}
                    onClick={() => handleSelect(run)}
                    className={`border-t border-gray-100 cursor-pointer hover:bg-blue-50 transition-colors ${selected?.run_id === run.run_id ? 'bg-blue-50' : ''}`}
                  >
                    <td className="px-4 py-3 font-mono text-xs">{run.handle}</td>
                    <td className="px-4 py-3 text-gray-600">{run.stages}</td>
                    <td className="px-4 py-3 text-gray-500">
                      {run.updated_at ? new Date(run.updated_at).toLocaleString() : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Detail panel */}
        {selected && (
          <div className="w-96 flex-shrink-0">
            <div className="flex items-center justify-between mb-3">
              <p className="text-sm font-semibold text-gray-700">@{selected.handle}</p>
              <button onClick={() => setSelected(null)} className="text-gray-400 hover:text-gray-600 text-lg leading-none">✕</button>
            </div>
            {loading ? (
              <p className="text-sm text-gray-400 text-center py-8">Loading…</p>
            ) : (
              <DossierCard manifest={manifest as Parameters<typeof DossierCard>[0]['manifest']} />
            )}
          </div>
        )}
      </div>
    </div>
  )
}
```

**Step 4: Create `frontend/src/App.tsx`**

```tsx
import { useState } from 'react'
import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom'
import { LockScreen } from '@/auth/LockScreen'
import { HealthDot } from '@/components/HealthDot'
import { RunManager } from '@/views/RunManager'
import { QueryInterface } from '@/views/QueryInterface'
import { DossierBrowser } from '@/views/DossierBrowser'
import { useRuns } from '@/hooks/useRuns'

const NAV_LINK_BASE = 'text-sm font-medium px-3 py-1.5 rounded-lg transition-colors'
const NAV_ACTIVE = 'bg-gray-100 text-gray-900'
const NAV_INACTIVE = 'text-gray-500 hover:text-gray-700'

function NavBar() {
  return (
    <nav className="bg-white border-b border-gray-200 px-6 py-3 flex items-center justify-between">
      <div className="flex items-center gap-6">
        <span className="text-sm font-bold text-gray-800">Profile Analyst</span>
        <div className="flex gap-1">
          <NavLink to="/" end className={({ isActive }) => `${NAV_LINK_BASE} ${isActive ? NAV_ACTIVE : NAV_INACTIVE}`}>
            Runs
          </NavLink>
          <NavLink to="/query" className={({ isActive }) => `${NAV_LINK_BASE} ${isActive ? NAV_ACTIVE : NAV_INACTIVE}`}>
            Query
          </NavLink>
          <NavLink to="/dossiers" className={({ isActive }) => `${NAV_LINK_BASE} ${isActive ? NAV_ACTIVE : NAV_INACTIVE}`}>
            Dossiers
          </NavLink>
        </div>
      </div>
      <HealthDot />
    </nav>
  )
}

function AppShell() {
  const { runs, addRun, updateRunStatus } = useRuns()

  return (
    <div className="min-h-screen bg-gray-50">
      <NavBar />
      <main>
        <Routes>
          <Route path="/" element={<RunManager />} />
          <Route path="/query" element={<QueryInterface />} />
          <Route path="/dossiers" element={<DossierBrowser runs={runs} />} />
        </Routes>
      </main>
    </div>
  )
}

export function App() {
  const [unlocked, setUnlocked] = useState(!!sessionStorage.getItem('pa_token'))

  if (!unlocked) {
    return <LockScreen onUnlock={() => setUnlocked(true)} />
  }

  return (
    <BrowserRouter>
      <AppShell />
    </BrowserRouter>
  )
}
```

**Step 5: Run full test suite**

```bash
cd frontend && npm test
```

Expected: all tests PASS.

**Step 6: Build check**

```bash
cd frontend && npm run build 2>&1 | tail -20
```

Expected: no TypeScript errors; `dist/` created.

**Step 7: Check bundle size**

```bash
cd frontend && npm run build -- --report 2>&1 | grep "gzip"
```

Expected: total gzipped < 500 kB.

**Step 8: Commit**

```bash
git add frontend/src/
git commit -m "feat(frontend): three views + App shell with router and lock screen gate"
```

---

## Task 11: Terraform — frontend.tf (Track A)

**Files:**
- Create: `deploy/aws/terraform/frontend.tf`
- Modify: `deploy/aws/terraform/outputs.tf`

**Step 1: Create `deploy/aws/terraform/frontend.tf`**

```hcl
# ── S3 bucket ──────────────────────────────────────────────────────────────────
resource "aws_s3_bucket" "frontend" {
  bucket = "${var.app_name}-${var.env}-frontend"
  tags   = { Name = "${var.app_name}-frontend" }
}

resource "aws_s3_bucket_versioning" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_public_access_block" "frontend" {
  bucket                  = aws_s3_bucket.frontend.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ── CloudFront OAC ─────────────────────────────────────────────────────────────
resource "aws_cloudfront_origin_access_control" "frontend" {
  name                              = "${var.app_name}-${var.env}-frontend-oac"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# Allow CloudFront to read from S3
resource "aws_s3_bucket_policy" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowCloudFrontServicePrincipal"
      Effect    = "Allow"
      Principal = { Service = "cloudfront.amazonaws.com" }
      Action    = "s3:GetObject"
      Resource  = "${aws_s3_bucket.frontend.arn}/*"
      Condition = {
        StringEquals = {
          "AWS:SourceArn" = aws_cloudfront_distribution.frontend.arn
        }
      }
    }]
  })
}

# ── CloudFront distribution ────────────────────────────────────────────────────
locals {
  s3_origin_id  = "S3FrontendOrigin"
  alb_origin_id = "ALBApiOrigin"
}

resource "aws_cloudfront_distribution" "frontend" {
  enabled             = true
  default_root_object = "index.html"
  comment             = "${var.app_name} frontend dashboard"
  price_class         = "PriceClass_100"

  # Origin 1 — S3 (static assets)
  origin {
    domain_name              = aws_s3_bucket.frontend.bucket_regional_domain_name
    origin_id                = local.s3_origin_id
    origin_access_control_id = aws_cloudfront_origin_access_control.frontend.id
  }

  # Origin 2 — ALB (API calls)
  origin {
    domain_name = aws_alb.main.dns_name
    origin_id   = local.alb_origin_id
    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  # Default behaviour — S3
  default_cache_behavior {
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = local.s3_origin_id
    viewer_protocol_policy = "redirect-to-https"
    cache_policy_id        = "658327ea-f89d-4fab-a63d-7e88639e58f6" # CachingOptimized managed
    compress               = true
  }

  # /api/* behaviour — ALB (no caching)
  ordered_cache_behavior {
    path_pattern           = "/api/*"
    allowed_methods        = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = local.alb_origin_id
    viewer_protocol_policy = "redirect-to-https"
    cache_policy_id        = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad" # CachingDisabled managed
    origin_request_policy_id = "b689b0a8-53d0-40ab-baf2-68738e2966ac" # AllViewerExceptHostHeader

    # strip /api prefix before forwarding to ALB
    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.strip_api_prefix.arn
    }
  }

  # SPA routing — 404 → index.html
  custom_error_response {
    error_code         = 404
    response_code      = 200
    response_page_path = "/index.html"
  }

  restrictions {
    geo_restriction { restriction_type = "none" }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

# CloudFront Function to strip /api prefix before forwarding to ALB
resource "aws_cloudfront_function" "strip_api_prefix" {
  name    = "${var.app_name}-${var.env}-strip-api-prefix"
  runtime = "cloudfront-js-2.0"
  publish = true
  code    = <<-EOT
    function handler(event) {
      var request = event.request;
      request.uri = request.uri.replace(/^\/api/, '') || '/';
      return request;
    }
  EOT
}

# ── Secrets Manager — frontend API token ───────────────────────────────────────
resource "aws_secretsmanager_secret" "frontend_api_token" {
  name        = "analyst/frontend_api_token"
  description = "Shared Bearer token for the profile-analyst frontend dashboard"
}

# ── ALB listener rule — enforce token on /api/* ────────────────────────────────
# NOTE: Set the secret value out-of-band after apply:
#   aws secretsmanager put-secret-value \
#     --secret-id analyst/frontend_api_token \
#     --secret-string "<your-token>"
# Then re-run terraform apply so the data source picks up the value.

data "aws_secretsmanager_secret_version" "frontend_api_token" {
  secret_id = aws_secretsmanager_secret.frontend_api_token.id
  depends_on = [aws_secretsmanager_secret.frontend_api_token]
}

resource "aws_alb_listener_rule" "frontend_auth" {
  listener_arn = aws_alb_listener.https.arn
  priority     = 1

  condition {
    path_pattern { values = ["/api/*"] }
  }

  condition {
    http_header {
      http_header_name = "Authorization"
      values           = ["Bearer ${data.aws_secretsmanager_secret_version.frontend_api_token.secret_string}"]
    }
  }

  action {
    type = "forward"
    target_group_arn = aws_alb_target_group.api.arn
  }
}

# Catch-all rule: reject /api/* without valid token
resource "aws_alb_listener_rule" "frontend_auth_reject" {
  listener_arn = aws_alb_listener.https.arn
  priority     = 2

  condition {
    path_pattern { values = ["/api/*"] }
  }

  action {
    type = "fixed-response"
    fixed_response {
      content_type = "application/json"
      message_body = "{\"error\":\"unauthorized\"}"
      status_code  = "401"
    }
  }
}
```

**Step 2: Append to `deploy/aws/terraform/outputs.tf`**

Add at the end of the file:

```hcl
output "cloudfront_domain" {
  description = "CloudFront distribution domain for the frontend"
  value       = aws_cloudfront_distribution.frontend.domain_name
}

output "frontend_bucket_name" {
  description = "S3 bucket name for frontend static assets"
  value       = aws_s3_bucket.frontend.bucket
}

output "cloudfront_distribution_id" {
  description = "CloudFront distribution ID (used for cache invalidation)"
  value       = aws_cloudfront_distribution.frontend.id
}

output "frontend_token_secret_arn" {
  description = "ARN of the Secrets Manager secret holding the frontend API token"
  value       = aws_secretsmanager_secret.frontend_api_token.arn
}
```

**Step 3: Validate Terraform**

```bash
cd deploy/aws/terraform && terraform validate
```

Expected: `Success! The configuration is valid.`

**Step 4: Review plan (do NOT apply — user must bootstrap secret first)**

```bash
cd deploy/aws/terraform && terraform plan -out=tfplan-frontend 2>&1 | tail -20
```

Review what will be created. Do not apply until the ALB listener names (`aws_alb_listener.https`, `aws_alb_target_group.api`) match what exists in `alb.tf`.

**Step 5: Commit**

```bash
cd /home/pedro/profile-analyst
git add deploy/aws/terraform/frontend.tf deploy/aws/terraform/outputs.tf
git commit -m "feat(infra): Terraform S3+CloudFront+ALB auth rule for frontend (spec 0009 Track A)"
```

---

## Task 12: Makefile targets + local dev verification (Track C)

**Files:**
- Modify: `Makefile`

**Step 1: Add targets to Makefile**

Find the block after `aws-smoke` (or after the last target) and add:

```makefile
# ── Frontend (spec 0009) ───────────────────────────────────────────────────────
# Usage: make frontend-build CLOUDFRONT_DOMAIN=<domain>
frontend-build:
	@test -n "$(CLOUDFRONT_DOMAIN)" || (echo "Usage: make frontend-build CLOUDFRONT_DOMAIN=<domain>"; exit 1)
	cd frontend && VITE_API_BASE_URL=https://$(CLOUDFRONT_DOMAIN) npm run build

# Usage: make frontend-deploy CLOUDFRONT_DOMAIN=<domain> FRONTEND_BUCKET=<bucket> CF_DIST_ID=<id>
frontend-deploy: frontend-build
	@test -n "$(FRONTEND_BUCKET)" || (echo "FRONTEND_BUCKET not set"; exit 1)
	@test -n "$(CF_DIST_ID)" || (echo "CF_DIST_ID not set"; exit 1)
	aws s3 sync frontend/dist/ s3://$(FRONTEND_BUCKET)/ --delete
	make frontend-invalidate CF_DIST_ID=$(CF_DIST_ID)

# Usage: make frontend-invalidate CF_DIST_ID=<id>
frontend-invalidate:
	@test -n "$(CF_DIST_ID)" || (echo "CF_DIST_ID not set"; exit 1)
	aws cloudfront create-invalidation --distribution-id $(CF_DIST_ID) --paths "/*"

# Usage: make frontend-dev (runs local dev server against localhost:8000)
frontend-dev:
	cd frontend && VITE_API_BASE_URL=http://localhost:8000 npm run dev

# Usage: make frontend-test
frontend-test:
	cd frontend && npm test -- --run
```

**Step 2: Verify dev server starts**

In one terminal, start the API:
```bash
make app ARGS="--handle sample --stage all" 2>/dev/null || true
# Or just ensure the API is running: uvicorn api.main:app --port 8000
```

In another terminal:
```bash
make frontend-dev
```

Expected: Vite dev server starts on `http://localhost:5173`.

**Step 3: Run frontend test suite via Makefile**

```bash
make frontend-test
```

Expected: all tests PASS.

**Step 4: Final build check**

```bash
make frontend-build CLOUDFRONT_DOMAIN=placeholder.cloudfront.net
ls -lh frontend/dist/assets/*.js | head -5
```

Expected: `dist/` created, no TypeScript errors.

**Step 5: Commit**

```bash
git add Makefile
git commit -m "feat(infra): Makefile targets for frontend build, deploy, dev, test"
```

---

## Task 13: Final validation + branch commit

**Step 1: Run full test suite**

```bash
cd frontend && npm test -- --run
```

Expected: all tests PASS, no failures.

**Step 2: Run make validate**

```bash
make validate
```

Expected: `All checks passed.`

**Step 3: Run make frontend-test**

```bash
make frontend-test
```

Expected: PASS.

**Step 4: Verify spec acceptance criteria**

Manually verify against `specs/0009-frontend-dashboard/metadata.yml`:
- **A1:** `npm run build` passes, check bundle size in step below.
- **A10:** `make frontend-dev` starts; proxy rewrites `/api/*` (open browser, check Network tab).

```bash
cd frontend && npm run build 2>&1 | grep -E "error|warning|gzip|kB"
```

**Step 5: Final commit**

```bash
git add -A
git commit -m "feat(frontend): spec 0009 implementation complete — all tracks A/B/C"
```

---

## Smoke Checks (Track C — after Terraform apply)

These are manual checks run against the deployed CloudFront domain. Run after:
1. `terraform apply` succeeds
2. Token bootstrapped: `aws secretsmanager put-secret-value --secret-id analyst/frontend_api_token --secret-string "<token>"`
3. `make frontend-deploy CLOUDFRONT_DOMAIN=... FRONTEND_BUCKET=... CF_DIST_ID=...`

```bash
CF=<your-cloudfront-domain>
TOKEN=<your-token>

# 1. Auth gate
curl -s -o /dev/null -w "%{http_code}" https://$CF/api/healthz
# Expected: 401

# 2. Valid token
curl -s https://$CF/api/healthz -H "Authorization: Bearer $TOKEN"
# Expected: {"status":"ok","neo4j":"ok","ollama":"ok"}

# 3. SPA served
curl -s https://$CF/ | grep 'id="root"'
# Expected: match

# 4–10: Open browser, follow smoke checks in tasks.md
```
