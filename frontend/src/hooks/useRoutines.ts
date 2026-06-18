import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiDeleteRoutine, apiGetRoutines, apiRenameRoutine } from '@/lib/api'
import { useAuth } from '@/lib/auth'

export function useRoutines() {
  const { token } = useAuth()
  return useQuery({
    queryKey: ['routines'],
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
