import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import type { Session } from '@supabase/supabase-js'
import { useQueryClient } from '@tanstack/react-query'
import { supabase } from './supabaseClient'
import { ApiError, SESSION_STORAGE_KEYS_TO_CLEAR_ON_SIGNOUT, apiCompleteSignup, apiGetProfile } from './api'
import { useSession } from './sessionContext'

interface AuthContextValue {
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

const AuthContext = createContext<AuthContextValue | null>(null)

interface ProfileSetters {
  setUsername: (v: string | null) => void
  setIsAdmin: (v: boolean) => void
  setProvisioningError: (v: string | null) => void
}

/** Module-level (not a hook) so effects call a plain async function rather
 * than a component-scoped callback — fetches the profile and, on a 412
 * ("account setup incomplete"), retries provisioning once idempotently
 * before surfacing a recoverable error (security-remediation Req 21.4/21.5).
 * `isCancelled` guards against setting state after the caller has
 * unmounted/re-run. */
async function fetchProfileOrProvision(
  { setUsername, setIsAdmin, setProvisioningError }: ProfileSetters,
  isCancelled: () => boolean,
): Promise<void> {
  try {
    const profile = await apiGetProfile()
    if (isCancelled()) return
    setUsername(profile.username)
    setIsAdmin(profile.is_admin)
    setProvisioningError(null)
    return
  } catch (err) {
    if (isCancelled()) return
    if (!(err instanceof ApiError) || err.status !== 412) {
      setUsername(null)
      setIsAdmin(false)
      setProvisioningError(null)
      return
    }
  }

  try {
    await apiCompleteSignup()
    const profile = await apiGetProfile()
    if (isCancelled()) return
    setUsername(profile.username)
    setIsAdmin(profile.is_admin)
    setProvisioningError(null)
  } catch {
    if (isCancelled()) return
    setUsername(null)
    setIsAdmin(false)
    setProvisioningError('We could not finish setting up your account. Please try again.')
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null)
  const [loading, setLoading] = useState(true)
  const [username, setUsername] = useState<string | null>(null)
  const [isAdmin, setIsAdmin] = useState(false)
  const [provisioningError, setProvisioningError] = useState<string | null>(null)
  const queryClient = useQueryClient()
  const { resetSession } = useSession()

  // Establish the initial session on mount, then keep it in sync via
  // Supabase's auth-state listener (handles sign-in, sign-out, and the
  // automatic token-refresh Req 6.2 requires, none of which is hand-rolled
  // here the way the old localStorage-backed state was).
  useEffect(() => {
    let cancelled = false

    supabase.auth.getSession().then(({ data }) => {
      if (cancelled) return
      setSession(data.session)
      setLoading(false)
    })

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, newSession) => {
      setSession(newSession)
      setLoading(false)
      if (!newSession) {
        // deepsec-revalidation follow-up (Task 82): this listener is the
        // one trigger point that fires for *every* sign-out, including ones
        // neither logout() nor handleUnauthorized() initiate directly (a
        // sign-out in another tab, Supabase's own invalid-refresh-token
        // detection, etc.) — those paths previously left the QueryClient
        // cache, sessionId, and sessionStorage untouched. logout() and
        // handleUnauthorized() still clear these synchronously themselves
        // too (Req 20.2/20.3's race-window reasoning still holds: a fast
        // subsequent sign-in in the same tab can't wait on this async
        // callback), so this is a catch-all backstop, not a replacement.
        setUsername(null)
        setIsAdmin(false)
        setProvisioningError(null)
        queryClient.clear()
        resetSession()
        for (const key of SESSION_STORAGE_KEYS_TO_CLEAR_ON_SIGNOUT) {
          sessionStorage.removeItem(key)
        }
      }
    })

    return () => {
      cancelled = true
      subscription.unsubscribe()
    }
  }, [queryClient, resetSession])

  // Once a session exists, fetch isAdmin (and username) once via the
  // backend profile endpoint — Supabase's session/JWT carries no
  // application-level username or admin-role data (Req 8.2).
  useEffect(() => {
    if (!session) return
    let cancelled = false

    fetchProfileOrProvision(
      { setUsername, setIsAdmin, setProvisioningError },
      () => cancelled,
    ).catch(() => {})

    return () => {
      cancelled = true
    }
  }, [session])

  const retryProvisioning = useCallback(
    () => fetchProfileOrProvision({ setUsername, setIsAdmin, setProvisioningError }, () => false),
    [],
  )

  async function logout() {
    // security-remediation Req 20.2, 20.3, 20.4, 20.5: clear everything
    // synchronously, in this call, rather than waiting on the async
    // onAuthStateChange listener above to eventually reset username/isAdmin —
    // that gap is exactly what let a fast subsequent sign-in in the same tab
    // observe the previous account's cached data.
    queryClient.clear()
    resetSession()
    for (const key of SESSION_STORAGE_KEYS_TO_CLEAR_ON_SIGNOUT) {
      sessionStorage.removeItem(key)
    }
    setUsername(null)
    setIsAdmin(false)
    setProvisioningError(null)
    await supabase.auth.signOut()
  }

  const value: AuthContextValue = {
    session,
    token: session?.access_token ?? null,
    userId: session?.user?.id ?? null,
    username,
    isAdmin,
    loading,
    provisioningError,
    retryProvisioning,
    logout,
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
