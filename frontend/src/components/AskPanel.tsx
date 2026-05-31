import { useState } from 'react'
import { useAsk } from '@/hooks/useAsk'

export function AskPanel() {
  const [handle, setHandle]     = useState('')
  const [question, setQuestion] = useState('')
  const { mutate, data, error, isPending, reset } = useAsk()

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!question.trim()) return
    reset()
    mutate({ question: question.trim(), handle: handle.trim() || undefined })
  }

  const rejection = error
    ? ((error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail ?? null)
    : null

  return (
    <div className="flex flex-col gap-5">
      <form onSubmit={handleSubmit} className="flex flex-col gap-3">
        <div className="flex gap-2">
          <div style={{ flex: '0 0 160px' }}>
            <label className="section-label block mb-2">Handle</label>
            <input type="text" placeholder="instagram_handle" value={handle}
              onChange={(e) => setHandle(e.target.value)} className="field" />
          </div>
          <div style={{ flex: 1 }}>
            <label className="section-label block mb-2">Question</label>
            <input type="text" placeholder="Ask anything about this creator…" value={question}
              onChange={(e) => setQuestion(e.target.value)} className="field" />
          </div>
        </div>
        <button type="submit" className="btn-primary self-start" disabled={isPending || !question.trim()}>
          {isPending ? 'Querying…' : 'Execute Query'}
        </button>
      </form>

      {rejection != null && (
        <div className="fade-in surface p-4" style={{ borderColor: 'rgba(248,113,113,0.2)' }}>
          <p className="section-label mb-2" style={{ color: 'var(--red)' }}>Query Rejected</p>
          <ul style={{ fontFamily: 'JetBrains Mono', fontSize: 11, color: 'var(--red)', listStyle: 'none', padding: 0 }}>
            {(Array.isArray(rejection) ? rejection as unknown[] : [rejection]).map((r, i) => (
              <li key={i} style={{ marginBottom: 4 }}>› {String(r)}</li>
            ))}
          </ul>
        </div>
      )}

      {data && (
        <div className="flex flex-col gap-3 fade-in">
          {/* Answer */}
          <div className="surface p-4">
            <p className="section-label mb-2">Answer</p>
            <p style={{ color: 'var(--text-primary)', lineHeight: 1.65, fontSize: 13 }}>{data.answer}</p>
            {data.row_count != null && (
              <p style={{ fontFamily: 'JetBrains Mono', fontSize: 10, color: 'var(--text-muted)', marginTop: 10, letterSpacing: '0.08em' }}>
                {data.row_count} ROW{data.row_count !== 1 ? 'S' : ''} RETURNED
              </p>
            )}
          </div>

          {/* Cypher */}
          {data.cypher && (
            <div style={{ background: 'var(--bg-base)', border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
              <div style={{
                padding: '8px 14px',
                borderBottom: '1px solid var(--border)',
                fontFamily: 'JetBrains Mono',
                fontSize: 9,
                letterSpacing: '0.12em',
                color: 'var(--amber)',
                textTransform: 'uppercase',
                display: 'flex',
                alignItems: 'center',
                gap: 8,
              }}>
                <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--amber)', opacity: 0.7, display: 'inline-block' }} />
                Cypher
              </div>
              <pre style={{
                padding: 16,
                fontFamily: 'JetBrains Mono',
                fontSize: 12,
                lineHeight: 1.6,
                color: '#A3E6A3',
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
                margin: 0,
                overflowX: 'auto',
              }}>
                {data.cypher}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
