import { useQuery } from '@tanstack/react-query'
import { apiGetProfile } from '@/lib/api'
import { useAuth } from '@/lib/auth'

export function useProfile() {
  const { token, userId } = useAuth()
  // security-remediation Req 20.1: keyed by userId (not a static ['profile']
  // key) so React Query can never serve a different account's cached profile.
  return useQuery({
    queryKey: ['profile', userId],
    queryFn: apiGetProfile,
    enabled: !!token,
    staleTime: 30_000,
  })
}
