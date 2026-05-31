import { useQuery } from '@tanstack/react-query'
import { client } from '@/api/client'

interface HealthResponse { status: string; neo4j: string; ollama: string }

export function useHealth() {
  const { data, isLoading, isError } = useQuery<HealthResponse>({
    queryKey: ['health'],
    queryFn: () => client.get<HealthResponse>('/healthz').then((r) => r.data),
    refetchInterval: 30_000,
    staleTime: 25_000,
    retry: 1,
  })
  return {
    isHealthy: !isLoading && !isError && data?.status === 'ok',
    isLoading,
    data,
  }
}
