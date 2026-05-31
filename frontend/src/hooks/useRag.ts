import { useMutation } from '@tanstack/react-query'
import { client } from '@/api/client'

export interface RagRequest { question: string; handle?: string; modes?: string[] }
export interface RagResponse {
  answer: string
  citations: string[]
  manifest_path: string
  modes_run?: string[]
}

export function useRag() {
  return useMutation<RagResponse, unknown, RagRequest>({
    mutationFn: (req) => client.post<RagResponse>('/rag', req).then((r) => r.data),
  })
}
