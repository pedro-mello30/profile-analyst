import { useState } from 'react'
import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom'
import { LockScreen } from '@/auth/LockScreen'
import { HealthDot } from '@/components/HealthDot'
import { RunManager } from '@/views/RunManager'
import { QueryInterface } from '@/views/QueryInterface'
import { DossierBrowser } from '@/views/DossierBrowser'
import { useRuns } from '@/hooks/useRuns'

const NAV = [
  { to: '/',         label: 'Runs',     end: true },
  { to: '/query',    label: 'Query',    end: false },
  { to: '/dossiers', label: 'Dossiers', end: false },
]

function TopNav() {
  return (
    <header style={{
      height: 48,
      borderBottom: '1px solid var(--border)',
      background: 'var(--bg-surface)',
      display: 'flex',
      alignItems: 'center',
      paddingInline: 24,
      gap: 0,
      flexShrink: 0,
    }}>
      {/* Logo */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginRight: 32 }}>
        <div style={{
          width: 22, height: 22, borderRadius: 4,
          background: 'var(--amber)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
            <circle cx="6" cy="6" r="2" fill="#090A0F" />
            <circle cx="6" cy="6" r="5" stroke="#090A0F" strokeWidth="1.5" />
          </svg>
        </div>
        <span style={{
          fontFamily: 'Syne', fontSize: 13, fontWeight: 700,
          color: 'var(--text-primary)', letterSpacing: '-0.01em',
        }}>
          Profile Analyst
        </span>
      </div>

      {/* Nav */}
      <nav style={{ display: 'flex', gap: 2, flex: 1 }}>
        {NAV.map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.end}
            className={({ isActive }) => `nav-tab ${isActive ? 'active' : ''}`}
          >
            {n.label}
          </NavLink>
        ))}
      </nav>

      {/* Right side */}
      <HealthDot />
    </header>
  )
}

function AppShell() {
  const { runs, addRun, updateRunStatus } = useRuns()

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: 'var(--bg-base)' }}>
      <TopNav />
      <main style={{ flex: 1, overflow: 'auto' }} className="grid-bg">
        <Routes>
          <Route path="/"         element={<RunManager />} />
          <Route path="/query"    element={<QueryInterface />} />
          <Route path="/dossiers" element={<DossierBrowser runs={runs} />} />
        </Routes>
      </main>
    </div>
  )
}

export function App() {
  const [unlocked, setUnlocked] = useState(!!sessionStorage.getItem('pa_token'))

  if (!unlocked) return <LockScreen onUnlock={() => setUnlocked(true)} />

  return (
    <BrowserRouter>
      <AppShell />
    </BrowserRouter>
  )
}
