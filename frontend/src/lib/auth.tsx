import { createContext, useContext } from 'react'
import type { Session } from '@supabase/supabase-js'

export interface AuthContextValue {
  /** Raw Supabase session; null when signed out. */
  session: Session | null
  /** Bearer token for the current session, or null when signed out. */
  token: string | null
  /** Supabase-issued user UUID (session.user.id), or null when signed out.
   * Stable across token refreshes — use this, not `token`, to scope
   * per-user caches (security-remediation Req 20.1). */
  userId: string | null
  username: string | null
  isAdmin: boolean
  /** True until the initial `getSession()` call has resolved. */
  loading: boolean
  /** Set when a verified session's local signup provisioning hasn't
   * completed and an automatic retry (security-remediation Req 21.4/21.5)
   * also failed — non-null means the UI should present a recovery action
   * bound to `retryProvisioning()` rather than proceeding as if the account
   * were ready. */
  provisioningError: string | null
  /** Retries provisioning idempotently against the current session. Safe to
   * call repeatedly (`complete-signup` is idempotent) — used both by the
   * automatic first-attempt retry and by a manual "Retry" action. */
  retryProvisioning: () => Promise<void>
  logout: () => Promise<void>
}

export const AuthContext = createContext<AuthContextValue | null>(null)

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
