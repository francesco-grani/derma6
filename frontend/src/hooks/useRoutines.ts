import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiDeleteRoutine, apiGetRoutines, apiRenameRoutine } from '@/lib/api'
import { useAuth } from '@/lib/auth'

export function useRoutines() {
  const { token, userId } = useAuth()
  // security-remediation Req 20.1: keyed by userId so a cached routine list
  // can never be served to a different account. invalidateQueries({queryKey:
  // ['routines']}) below still matches this via React Query's prefix rule.
  return useQuery({
    queryKey: ['routines', userId],
    queryFn: apiGetRoutines,
    enabled: !!token,
  })
}

export function useDeleteRoutine() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (name: string) => apiDeleteRoutine(name),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['routines'] }),
  })
}

export function useRenameRoutine() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ oldName, newName }: { oldName: string; newName: string }) =>
      apiRenameRoutine(oldName, newName),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['routines'] }),
  })
}
