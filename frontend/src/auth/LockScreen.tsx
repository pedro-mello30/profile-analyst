import { useState, useEffect, useRef } from 'react'

interface Props { onUnlock: () => void }

const BOOT_LINES = [
  'ANALYST WORKSTATION v2.1',
  'Loading graph engine...',
  'Connecting to inference backend...',
  'RAG index warm.',
  'Ready.',
]

export function LockScreen({ onUnlock }: Props) {
  const [token, setToken] = useState('')
  const [bootStage, setBootStage] = useState(0)
  const [showInput, setShowInput] = useState(false)
  const [shake, setShake] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    let i = 0
    const tick = () => {
      i++
      setBootStage(i)
      if (i < BOOT_LINES.length) {
        setTimeout(tick, 280 + Math.random() * 180)
      } else {
        setTimeout(() => setShowInput(true), 350)
      }
    }
    setTimeout(tick, 400)
  }, [])

  useEffect(() => {
    if (showInput) inputRef.current?.focus()
  }, [showInput])

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!token.trim()) return
    sessionStorage.setItem('pa_token', token.trim())
    onUnlock()
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter') handleSubmit(e as unknown as React.FormEvent)
  }

  return (
    <div
      className="min-h-screen grid-bg flex items-center justify-center"
      style={{ background: 'var(--bg-base)' }}
    >
      {/* Vignette */}
      <div
        className="fixed inset-0 pointer-events-none"
        style={{ background: 'radial-gradient(ellipse at center, transparent 40%, rgba(9,10,15,0.8) 100%)' }}
      />

      <div className="relative w-full max-w-sm px-6 fade-in">
        {/* Logo mark */}
        <div className="mb-8 text-center">
          <div
            className="inline-flex items-center gap-2 mb-3"
            style={{ fontFamily: 'JetBrains Mono', fontSize: 10, letterSpacing: '0.2em', color: 'var(--amber)', textTransform: 'uppercase' }}
          >
            <span style={{ display: 'inline-block', width: 16, height: 1, background: 'var(--amber)', opacity: 0.5 }} />
            Anthropic Intelligence
            <span style={{ display: 'inline-block', width: 16, height: 1, background: 'var(--amber)', opacity: 0.5 }} />
          </div>
          <h1
            style={{ fontFamily: 'Syne', fontSize: 28, fontWeight: 800, color: 'var(--text-primary)', letterSpacing: '-0.02em', lineHeight: 1 }}
          >
            Profile Analyst
          </h1>
        </div>

        {/* Terminal boot log */}
        <div
          className="surface mb-6 p-4 overflow-hidden"
          style={{ fontFamily: 'JetBrains Mono', fontSize: 11, lineHeight: 1.8 }}
        >
          {BOOT_LINES.slice(0, bootStage).map((line, i) => (
            <div
              key={i}
              className="fade-in"
              style={{ animationDelay: `${i * 0.05}s`, color: i === bootStage - 1 ? 'var(--text-primary)' : 'var(--text-muted)' }}
            >
              <span style={{ color: 'var(--amber)', marginRight: 8 }}>›</span>
              {line}
            </div>
          ))}
          {bootStage < BOOT_LINES.length && (
            <div style={{ color: 'var(--text-muted)', minHeight: 20 }} className="cursor-blink" />
          )}
        </div>

        {/* Auth form */}
        <div
          className="surface amber-glow p-5"
          style={{
            transition: 'opacity 0.3s, transform 0.3s',
            opacity: showInput ? 1 : 0,
            transform: showInput ? 'none' : 'translateY(8px)',
          }}
        >
          <div className="section-label mb-3">Access Token</div>
          <form onSubmit={handleSubmit} className="flex flex-col gap-3">
            <input
              ref={inputRef}
              type="password"
              placeholder="Enter token to authenticate"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              onKeyDown={handleKeyDown}
              className="field"
              disabled={!showInput}
              style={shake ? { animation: 'shake 0.3s ease' } : {}}
              aria-label="Access token"
            />
            <button type="submit" className="btn-primary" disabled={!showInput || !token.trim()}>
              Authenticate
            </button>
          </form>
        </div>

        {/* Footer */}
        <p
          className="text-center mt-4"
          style={{ fontFamily: 'JetBrains Mono', fontSize: 9, letterSpacing: '0.12em', color: 'var(--text-muted)', textTransform: 'uppercase' }}
        >
          Internal use only · Not for public access
        </p>
      </div>

      <style>{`
        @keyframes shake {
          0%,100% { transform: translateX(0); }
          20%     { transform: translateX(-6px); }
          60%     { transform: translateX(6px); }
        }
      `}</style>
    </div>
  )
}
