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
