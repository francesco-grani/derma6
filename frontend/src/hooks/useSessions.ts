import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiCreateSession, apiDeleteSession, apiGetSessions } from '@/lib/api'
import type { ChatSessionInfo } from '@/lib/api'

export function useSessions() {
  return useQuery<ChatSessionInfo[]>({
    queryKey: ['sessions'],
    queryFn: apiGetSessions,
    staleTime: 10_000,
  })
}

export function useCreateSession() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: apiCreateSession,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['sessions'] }),
  })
}

export function useDeleteSession() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (session_id: string) => apiDeleteSession(session_id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['sessions'] }),
  })
}
