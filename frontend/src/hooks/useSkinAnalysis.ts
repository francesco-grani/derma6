import { useMutation, useQueryClient } from '@tanstack/react-query'
import { apiAnalyzeSkin, apiSaveMedicalFlag } from '@/lib/api'
import type { SkinAnalysisResult } from '@/lib/api'

export function useAnalyzeSkin() {
  return useMutation<SkinAnalysisResult, Error, File>({
    mutationFn: (file: File) => apiAnalyzeSkin(file),
  })
}

export function useSaveMedicalFlag() {
  const qc = useQueryClient()
  return useMutation<void, Error, string>({
    mutationFn: (condition: string) => apiSaveMedicalFlag(condition),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['profile'] })
    },
  })
}
