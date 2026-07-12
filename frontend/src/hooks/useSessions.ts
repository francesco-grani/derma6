import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiCreateSession, apiDeleteSession, apiGetSessions } from '@/lib/api'
import type { ChatSessionInfo } from '@/lib/api'
import { useAuth } from '@/lib/auth'

export function useSessions() {
  const { userId } = useAuth()
  // security-remediation Req 20.1: keyed by userId so a cached session list
  // can never be served to a different account.
  return useQuery<ChatSessionInfo[]>({
    queryKey: ['sessions', userId],
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
