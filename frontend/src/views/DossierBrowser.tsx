import { useState } from 'react'
import { client } from '@/api/client'
import { DossierCard } from '@/components/DossierCard'
import type { RunEntry } from '@/hooks/useRuns'

interface Props { runs: RunEntry[] }

export function DossierBrowser({ runs }: Props) {
  const completed = runs.filter((r) => r.status === 'succeeded')
  const [selected, setSelected]   = useState<RunEntry | null>(null)
  const [manifest, setManifest]   = useState<Record<string, unknown> | null>(null)
  const [loading, setLoading]     = useState(false)

  async function handleSelect(run: RunEntry) {
    if (selected?.run_id === run.run_id) {
      setSelected(null)
      setManifest(null)
      return
    }
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
    <div style={{ padding: 28, display: 'flex', gap: 24, alignItems: 'flex-start' }}>
      {/* Left — table */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="section-label mb-5" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ width: 18, height: 1, background: 'var(--amber)', opacity: 0.5, display: 'inline-block' }} />
          Completed Dossiers
          {completed.length > 0 && (
            <span style={{
              fontFamily: 'JetBrains Mono', fontSize: 9, letterSpacing: '0.1em',
              background: 'var(--amber-dim)', color: 'var(--amber)',
              border: '1px solid var(--border-accent)', borderRadius: 3,
              padding: '1px 6px', marginLeft: 4,
            }}>
              {completed.length}
            </span>
          )}
        </div>

        <div className="surface overflow-hidden">
          {completed.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '56px 0', color: 'var(--text-muted)' }}>
              <div style={{ fontFamily: 'JetBrains Mono', fontSize: 32, marginBottom: 8, opacity: 0.3 }}>∅</div>
              <p style={{ fontFamily: 'JetBrains Mono', fontSize: 11, letterSpacing: '0.08em', textTransform: 'uppercase' }}>
                No completed runs in session
              </p>
              <p style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 6 }}>
                Run a pipeline from the Run Manager first.
              </p>
            </div>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border)' }}>
                  {['Handle', 'Stages', 'Completed'].map((h) => (
                    <th key={h} style={{
                      textAlign: 'left', padding: '10px 16px',
                      fontFamily: 'JetBrains Mono', fontSize: 9, fontWeight: 500,
                      letterSpacing: '0.12em', textTransform: 'uppercase',
                      color: 'var(--text-muted)',
                    }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {completed.map((run) => (
                  <tr
                    key={run.run_id}
                    onClick={() => handleSelect(run)}
                    style={{
                      borderBottom: '1px solid var(--border)',
                      cursor: 'pointer',
                      transition: 'background 0.1s',
                      background: selected?.run_id === run.run_id ? 'var(--amber-dim)' : 'transparent',
                    }}
                    onMouseEnter={(e) => { if (selected?.run_id !== run.run_id) (e.currentTarget as HTMLElement).style.background = 'var(--bg-elevated)' }}
                    onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = selected?.run_id === run.run_id ? 'var(--amber-dim)' : 'transparent' }}
                  >
                    <td style={{ padding: '11px 16px', fontFamily: 'JetBrains Mono', fontSize: 12, color: selected?.run_id === run.run_id ? 'var(--amber)' : 'var(--text-primary)' }}>
                      @{run.handle}
                    </td>
                    <td style={{ padding: '11px 16px', fontFamily: 'JetBrains Mono', fontSize: 11, color: 'var(--text-muted)' }}>
                      {run.stages}
                    </td>
                    <td style={{ padding: '11px 16px', fontFamily: 'JetBrains Mono', fontSize: 11, color: 'var(--text-muted)' }}>
                      {run.updated_at ? new Date(run.updated_at).toLocaleString() : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Right — detail panel */}
      {selected && (
        <div style={{ width: 360, flexShrink: 0 }} className="fade-in">
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
            <div className="section-label" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ width: 18, height: 1, background: 'var(--amber)', opacity: 0.5, display: 'inline-block' }} />
              @{selected.handle}
            </div>
            <button
              onClick={() => { setSelected(null); setManifest(null) }}
              style={{ background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--text-muted)', fontSize: 16, lineHeight: 1, padding: 4 }}
              aria-label="Close"
            >
              ✕
            </button>
          </div>
          {loading ? (
            <div className="surface p-6" style={{ textAlign: 'center', color: 'var(--text-muted)' }}>
              <p style={{ fontFamily: 'JetBrains Mono', fontSize: 11, letterSpacing: '0.08em' }} className="cursor-blink">
                Loading
              </p>
            </div>
          ) : (
            <DossierCard manifest={manifest as Parameters<typeof DossierCard>[0]['manifest']} />
          )}
        </div>
      )}
    </div>
  )
}
