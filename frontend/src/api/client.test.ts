import { describe, it, expect, beforeEach } from 'vitest'
import { http, HttpResponse } from 'msw'
import { server } from '../test/server'

describe('API client', () => {
  beforeEach(() => {
    sessionStorage.clear()
    // reset module so interceptors re-read sessionStorage
    vi.resetModules()
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

  it('sends no Authorization header when token is absent', async () => {
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
