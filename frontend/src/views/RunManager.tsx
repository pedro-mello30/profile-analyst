import { useCallback } from 'react'
import { NewRunForm } from '@/components/NewRunForm'
import { RunTable } from '@/components/RunTable'
import { useRuns, useRunPoller, type RunEntry } from '@/hooks/useRuns'

function RunPoller({ run, onUpdate }: { run: RunEntry; onUpdate: (id: string, u: Partial<RunEntry>) => void }) {
  useRunPoller(run.run_id, run.handle, onUpdate)
  return null
}

export function RunManager() {
  const { runs, addRun, updateRunStatus } = useRuns()
  const activeRuns = runs.filter((r) => r.status === 'queued' || r.status === 'running')

  const handleRunCreated = useCallback((run: RunEntry) => {
    addRun(run)
  }, [addRun])

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '340px 1fr', gap: 24, padding: 28, height: '100%', alignItems: 'start' }}>
      {/* Left — form */}
      <div>
        <div className="section-label mb-5" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ width: 18, height: 1, background: 'var(--amber)', opacity: 0.5, display: 'inline-block' }} />
          New Run
        </div>
        <div className="surface p-5 amber-glow">
          <NewRunForm onRunCreated={handleRunCreated} />
        </div>
      </div>

      {/* Right — table */}
      <div>
        <div className="section-label mb-5" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ width: 18, height: 1, background: 'var(--amber)', opacity: 0.5, display: 'inline-block' }} />
          Pipeline Runs
          {runs.length > 0 && (
            <span style={{
              fontFamily: 'JetBrains Mono', fontSize: 9, letterSpacing: '0.1em',
              background: 'var(--amber-dim)', color: 'var(--amber)',
              border: '1px solid var(--border-accent)', borderRadius: 3,
              padding: '1px 6px', marginLeft: 4,
            }}>
              {runs.length}
            </span>
          )}
        </div>
        <div className="surface p-5">
          <RunTable runs={runs} />
        </div>
      </div>

      {activeRuns.map((run) => (
        <RunPoller key={run.run_id} run={run} onUpdate={updateRunStatus} />
      ))}
    </div>
  )
}
