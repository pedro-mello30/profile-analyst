import type { RunEntry } from '@/hooks/useRuns'

function elapsed(created_at?: string) {
  if (!created_at) return '—'
  const s = Math.floor((Date.now() - new Date(created_at).getTime()) / 1000)
  if (s < 60) return `${s}s`
  return `${Math.floor(s / 60)}m ${s % 60}s`
}

function StatusStamp({ status }: { status: string }) {
  const dot = status === 'running'
    ? <span className="pulse-dot" />
    : <span style={{ width: 5, height: 5, borderRadius: '50%', display: 'inline-block', background: 'currentColor', opacity: 0.7 }} />

  return (
    <span className={`stamp stamp-${status}`}>
      {dot}
      {status}
    </span>
  )
}

interface Props { runs: RunEntry[] }

export function RunTable({ runs }: Props) {
  if (runs.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12" style={{ color: 'var(--text-muted)' }}>
        <div style={{ fontFamily: 'JetBrains Mono', fontSize: 28, marginBottom: 8, opacity: 0.3 }}>∅</div>
        <p style={{ fontFamily: 'JetBrains Mono', fontSize: 11, letterSpacing: '0.08em', textTransform: 'uppercase' }}>
          No runs yet
        </p>
      </div>
    )
  }

  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr style={{ borderBottom: '1px solid var(--border)' }}>
            {['Handle', 'Stages', 'Status', 'Elapsed'].map((h) => (
              <th key={h} style={{
                textAlign: 'left',
                paddingBottom: 10,
                paddingRight: 16,
                fontFamily: 'JetBrains Mono',
                fontSize: 9,
                fontWeight: 500,
                letterSpacing: '0.12em',
                textTransform: 'uppercase',
                color: 'var(--text-muted)',
              }}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {runs.map((run, i) => (
            <tr
              key={run.run_id}
              className="fade-in"
              style={{
                borderBottom: '1px solid var(--border)',
                animationDelay: `${i * 0.04}s`,
              }}
            >
              <td style={{ padding: '10px 16px 10px 0', fontFamily: 'JetBrains Mono', fontSize: 12, color: 'var(--text-primary)' }}>
                @{run.handle}
              </td>
              <td style={{ padding: '10px 16px 10px 0', fontFamily: 'JetBrains Mono', fontSize: 11, color: 'var(--text-muted)' }}>
                {run.stages}
              </td>
              <td style={{ padding: '10px 16px 10px 0' }}>
                <StatusStamp status={run.status} />
              </td>
              <td style={{ padding: '10px 0', fontFamily: 'JetBrains Mono', fontSize: 11, color: 'var(--text-muted)' }}>
                {elapsed(run.created_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
