import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import type { Session } from '@supabase/supabase-js'
import { supabase } from './supabaseClient'
import { apiGetProfile } from './api'

interface AuthContextValue {
  /** Raw Supabase session; null when signed out. */
  session: Session | null
  /** Bearer token for the current session, or null when signed out. */
  token: string | null
  username: string | null
  isAdmin: boolean
  /** True until the initial `getSession()` call has resolved. */
  loading: boolean
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null)
  const [loading, setLoading] = useState(true)
  const [username, setUsername] = useState<string | null>(null)
  const [isAdmin, setIsAdmin] = useState(false)

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
        setUsername(null)
        setIsAdmin(false)
      }
    })

    return () => {
      cancelled = true
      subscription.unsubscribe()
    }
  }, [])

  // Once a session exists, fetch isAdmin (and username) once via the
  // backend profile endpoint — Supabase's session/JWT carries no
  // application-level username or admin-role data (Req 8.2).
  useEffect(() => {
    if (!session) return
    let cancelled = false

    apiGetProfile()
      .then(profile => {
        if (cancelled) return
        setUsername(profile.username)
        setIsAdmin(profile.is_admin)
      })
      .catch(() => {
        if (cancelled) return
        setUsername(null)
        setIsAdmin(false)
      })

    return () => {
      cancelled = true
    }
  }, [session])

  async function logout() {
    await supabase.auth.signOut()
  }

  const value: AuthContextValue = {
    session,
    token: session?.access_token ?? null,
    username,
    isAdmin,
    loading,
    logout,
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
