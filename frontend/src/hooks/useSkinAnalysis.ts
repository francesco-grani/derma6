import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiAnalyzeSkin, apiDeleteSkinAnalysis, apiGetSkinAnalyses, apiSaveMedicalFlag } from '@/lib/api'
import type { SkinAnalysisResult } from '@/lib/api'
import { useAuth } from '@/lib/auth'

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
  const { userId } = useAuth()
  // security-remediation Req 20.1: keyed by userId so cached skin-analysis
  // results (medical/photo data) can never be served to a different account.
  return useQuery({
    queryKey: ['skin-analyses', userId],
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
