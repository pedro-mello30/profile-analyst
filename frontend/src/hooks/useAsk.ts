import { useMutation } from '@tanstack/react-query'
import { client } from '@/api/client'

export interface AskRequest { question: string; handle?: string }
export interface AskResponse {
  answer: string
  manifest_path: string
  cypher?: string
  row_count?: number
}

export function useAsk() {
  return useMutation<AskResponse, unknown, AskRequest>({
    mutationFn: (req) => client.post<AskResponse>('/ask', req).then((r) => r.data),
  })
}
