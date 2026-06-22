import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiAnalyzeSkin, apiDeleteSkinAnalysis, apiGetSkinAnalyses, apiSaveMedicalFlag } from '@/lib/api'
import type { SkinAnalysisResult } from '@/lib/api'

export function useAnalyzeSkin() {
  const qc = useQueryClient()
  return useMutation<SkinAnalysisResult, Error, File>({
    mutationFn: (file: File) => apiAnalyzeSkin(file),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['skin-analyses'] })
    },
  })
}

export function useSkinAnalyses() {
  return useQuery({
    queryKey: ['skin-analyses'],
    queryFn: apiGetSkinAnalyses,
  })
}

export function useDeleteSkinAnalysis() {
  const qc = useQueryClient()
  return useMutation<void, Error, number>({
    mutationFn: (id: number) => apiDeleteSkinAnalysis(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['skin-analyses'] })
    },
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
