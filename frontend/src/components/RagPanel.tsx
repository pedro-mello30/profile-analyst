import { useState } from 'react'
import { useRag } from '@/hooks/useRag'

export function RagPanel() {
  const [handle, setHandle]     = useState('')
  const [question, setQuestion] = useState('')
  const { mutate, data, error, isPending, reset } = useRag()

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!question.trim()) return
    reset()
    mutate({ question: question.trim(), handle: handle.trim() || undefined })
  }

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
            <input type="text" placeholder="Retrieve relevant context for…" value={question}
              onChange={(e) => setQuestion(e.target.value)} className="field" />
          </div>
        </div>
        <button type="submit" className="btn-primary self-start" disabled={isPending || !question.trim()}
          style={{ background: 'var(--teal)', color: '#090A0F' }}>
          {isPending ? 'Retrieving…' : 'RAG Search'}
        </button>
      </form>

      {error != null && (
        <div className="fade-in surface p-4" style={{ borderColor: 'rgba(248,113,113,0.2)' }}>
          <p style={{ fontFamily: 'JetBrains Mono', fontSize: 11, color: 'var(--red)' }}>
            ✕ RAG query failed — check API and pipeline status.
          </p>
        </div>
      )}

      {data && (
        <div className="flex flex-col gap-3 fade-in">
          {/* Answer */}
          <div className="surface p-4">
            <p className="section-label mb-2">Synthesised Answer</p>
            <p style={{ color: 'var(--text-primary)', lineHeight: 1.65, fontSize: 13 }}>{data.answer}</p>
          </div>

          {/* Source chunks */}
          {data.citations.length > 0 && (
            <div className="surface p-4">
              <div className="flex items-center justify-between mb-3">
                <p className="section-label">Source Chunks</p>
                {data.modes_run && (
                  <div className="flex gap-1">
                    {data.modes_run.map((m) => (
                      <span key={m} style={{
                        fontFamily: 'JetBrains Mono', fontSize: 9, letterSpacing: '0.1em',
                        textTransform: 'uppercase', color: 'var(--teal)', background: 'var(--teal-dim)',
                        border: '1px solid rgba(45,212,191,0.2)', borderRadius: 3, padding: '2px 6px',
                      }}>{m}</span>
                    ))}
                  </div>
                )}
              </div>
              <div className="flex flex-col gap-2">
                {data.citations.map((c, i) => (
                  <div
                    key={i}
                    className="fade-in"
                    style={{
                      animationDelay: `${i * 0.06}s`,
                      background: 'var(--bg-base)',
                      border: '1px solid var(--border)',
                      borderRadius: 6,
                      padding: '8px 12px',
                      fontFamily: 'JetBrains Mono',
                      fontSize: 11,
                      lineHeight: 1.6,
                      color: 'var(--text-secondary)',
                    }}
                  >
                    <span style={{ color: 'var(--text-muted)', marginRight: 8 }}>[{i + 1}]</span>
                    {c}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
