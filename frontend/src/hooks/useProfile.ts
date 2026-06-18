import { useQuery } from '@tanstack/react-query'
import { apiGetProfile } from '@/lib/api'
import { useAuth } from '@/lib/auth'

export function useProfile() {
  const { token } = useAuth()
  return useQuery({
    queryKey: ['profile'],
    queryFn: apiGetProfile,
    enabled: !!token,
    staleTime: 30_000,
  })
}
