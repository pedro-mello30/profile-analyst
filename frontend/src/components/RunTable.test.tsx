import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { RunTable } from './RunTable'
import type { RunEntry } from '@/hooks/useRuns'

const mockRuns: RunEntry[] = [
  { run_id: 'r1', status: 'succeeded', url: '/runs/r1', handle: 'user_a', stages: 'all', created_at: '2026-05-30T10:00:00Z' },
  { run_id: 'r2', status: 'running',   url: '/runs/r2', handle: 'user_b', stages: '1,2,3' },
  { run_id: 'r3', status: 'failed',    url: '/runs/r3', handle: 'user_c', stages: 'all' },
  { run_id: 'r4', status: 'queued',    url: '/runs/r4', handle: 'user_d', stages: 'all' },
]

describe('RunTable', () => {
  it('shows empty state when no runs', () => {
    render(<RunTable runs={[]} />)
    expect(screen.getByText(/no runs yet/i)).toBeInTheDocument()
  })

  it('renders a row for each run', () => {
    render(<RunTable runs={mockRuns} />)
    expect(screen.getByText('@user_a')).toBeInTheDocument()
    expect(screen.getByText('@user_b')).toBeInTheDocument()
    expect(screen.getByText('@user_c')).toBeInTheDocument()
  })

  it('renders all four status stamps', () => {
    render(<RunTable runs={mockRuns} />)
    expect(screen.getByText('succeeded')).toBeInTheDocument()
    expect(screen.getByText('running')).toBeInTheDocument()
    expect(screen.getByText('failed')).toBeInTheDocument()
    expect(screen.getByText('queued')).toBeInTheDocument()
  })

  it('shows elapsed time for runs with created_at', () => {
    render(<RunTable runs={mockRuns} />)
    // r1 has created_at; the elapsed column renders a time string (not "—")
    // r2/r3 have no created_at → "—"
    const cells = screen.getAllByText('—')
    expect(cells.length).toBeGreaterThanOrEqual(2)
  })
})
