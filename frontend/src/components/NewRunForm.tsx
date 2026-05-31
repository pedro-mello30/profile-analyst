import { useState } from 'react'
import { client } from '@/api/client'
import type { RunEntry } from '@/hooks/useRuns'

const STAGE_OPTIONS = [
  { label: 'All stages', value: 'all' },
  { label: '1→3  ingest · normalize · features', value: '1,2,3' },
  { label: '1→3 + 6  + dossier', value: '1,2,3,6' },
  { label: 'Custom', value: 'custom' },
]

interface Props { onRunCreated: (run: RunEntry) => void }

export function NewRunForm({ onRunCreated }: Props) {
  const [handle, setHandle]           = useState('')
  const [stages, setStages]           = useState('all')
  const [customStages, setCustomStages] = useState('')
  const [isPending, setIsPending]     = useState(false)
  const [error, setError]             = useState<string | null>(null)

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
      onRunCreated({ ...res.data, handle: handle.trim(), stages: stagesValue, created_at: new Date().toISOString() })
      setHandle('')
    } catch {
      setError('Failed to enqueue run — check API connectivity.')
    } finally {
      setIsPending(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-5">
      <div>
        <label className="section-label block mb-2">Handle</label>
        <input
          type="text"
          placeholder="instagram_handle"
          value={handle}
          onChange={(e) => setHandle(e.target.value)}
          pattern="[a-zA-Z0-9_]+"
          className="field"
          aria-label="Instagram handle"
        />
      </div>

      <div>
        <label className="section-label block mb-3">Pipeline stages</label>
        <div className="flex flex-col gap-2">
          {STAGE_OPTIONS.map((opt) => (
            <label
              key={opt.value}
              className="flex items-center gap-3 cursor-pointer"
              style={{ fontFamily: 'JetBrains Mono', fontSize: 11 }}
            >
              <span
                style={{
                  width: 14,
                  height: 14,
                  borderRadius: '50%',
                  border: `1px solid ${stages === opt.value ? 'var(--amber)' : 'rgba(255,255,255,0.15)'}`,
                  background: stages === opt.value ? 'var(--amber)' : 'transparent',
                  display: 'inline-block',
                  flexShrink: 0,
                  transition: 'all 0.15s',
                  position: 'relative',
                }}
              >
                <input
                  type="radio"
                  name="stages"
                  value={opt.value}
                  checked={stages === opt.value}
                  onChange={() => setStages(opt.value)}
                  style={{ position: 'absolute', opacity: 0, width: '100%', height: '100%', cursor: 'pointer' }}
                  aria-label={opt.label}
                />
              </span>
              <span style={{ color: stages === opt.value ? 'var(--text-primary)' : 'var(--text-muted)' }}>
                {opt.label}
              </span>
            </label>
          ))}
        </div>
        {stages === 'custom' && (
          <input
            type="text"
            placeholder="e.g. 1,2,3,7"
            value={customStages}
            onChange={(e) => setCustomStages(e.target.value)}
            className="field mt-3"
            style={{ fontSize: 12 }}
          />
        )}
      </div>

      {error && (
        <p style={{ fontFamily: 'JetBrains Mono', fontSize: 11, color: 'var(--red)', background: 'var(--red-dim)', border: '1px solid rgba(248,113,113,0.2)', borderRadius: 6, padding: '8px 12px' }}>
          ✕ {error}
        </p>
      )}

      <button type="submit" className="btn-primary" disabled={isPending || !handle.trim()}>
        {isPending ? 'Enqueuing…' : 'Run Pipeline'}
      </button>
    </form>
  )
}
