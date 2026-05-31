import { useCallback, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { client } from '@/api/client'

export interface RunEntry {
  run_id: string
  status: string
  url: string
  handle: string
  stages: string
  created_at?: string
  updated_at?: string
}

interface RunStatus {
  run_id: string
  status: string
  created_at: string
  updated_at?: string
}

export function useRuns() {
  const [runs, setRuns] = useState<RunEntry[]>([])

  const addRun = useCallback((run: RunEntry) => {
    setRuns((prev) => [run, ...prev])
  }, [])

  const updateRunStatus = useCallback((run_id: string, updates: Partial<RunEntry>) => {
    setRuns((prev) => prev.map((r) => (r.run_id === run_id ? { ...r, ...updates } : r)))
  }, [])

  return { runs, addRun, updateRunStatus }
}

export function useRunPoller(
  run_id: string,
  handle: string,
  onUpdate: (run_id: string, updates: Partial<RunEntry>) => void
) {
  return useQuery<RunStatus>({
    queryKey: ['run', run_id],
    queryFn: () =>
      client.get<RunStatus>(`/runs/${run_id}`, { params: { handle } }).then((r) => r.data),
    refetchInterval: (query) => {
      const s = query.state.data?.status
      if (s === 'succeeded' || s === 'failed') return false
      return 5_000
    },
    select: (data) => {
      onUpdate(run_id, { status: data.status, updated_at: data.updated_at })
      return data
    },
  })
}
