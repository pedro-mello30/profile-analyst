import { useState } from 'react'
import { AskPanel } from '@/components/AskPanel'
import { RagPanel } from '@/components/RagPanel'

type Tab = 'ask' | 'rag'

const TABS: { id: Tab; label: string; sub: string }[] = [
  { id: 'ask', label: 'NL→Cypher', sub: 'Graph query' },
  { id: 'rag', label: 'RAG',       sub: 'Hybrid retrieval' },
]

export function QueryInterface() {
  const [tab, setTab] = useState<Tab>('ask')

  return (
    <div style={{ padding: 28 }}>
      <div className="section-label mb-6" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ width: 18, height: 1, background: 'var(--amber)', opacity: 0.5, display: 'inline-block' }} />
        Query Interface
      </div>

      {/* Tab bar */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 20 }}>
        {TABS.map((t) => (
          <button
            key={t.id}
            className={`query-tab ${tab === t.id ? 'active' : ''}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
            <span style={{ marginLeft: 6, opacity: 0.6, fontSize: 9 }}>— {t.sub}</span>
          </button>
        ))}
      </div>

      <div className="surface p-5 amber-glow" style={{ maxWidth: 760 }}>
        {tab === 'ask' ? <AskPanel /> : <RagPanel />}
      </div>
    </div>
  )
}
