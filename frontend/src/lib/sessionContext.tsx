import { createContext, useCallback, useContext, useState } from 'react'
import { apiCreateSession, apiGetSessions } from '@/lib/api'
import type { ChatSessionInfo } from '@/lib/api'

interface SessionContextValue {
  sessionId: string | null
  setSessionId: (id: string) => void
  /** Load most recent session or create a new one if none exist. */
  resumeOrCreate: () => Promise<string>
  /** Always create a fresh session and switch to it. */
  startNewSession: () => Promise<string>
  /** Clear the in-memory sessionId (security-remediation Req 20.5) — called on
   * logout so a subsequent sign-in in the same tab never resumes a session
   * belonging to the account that just signed out. */
  resetSession: () => void
}

const SessionContext = createContext<SessionContextValue | null>(null)

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [sessionId, setSessionId] = useState<string | null>(null)

  const resumeOrCreate = useCallback(async (): Promise<string> => {
    const sessions: ChatSessionInfo[] = await apiGetSessions()
    if (sessions.length > 0) {
      setSessionId(sessions[0].session_id)
      return sessions[0].session_id
    }
    const created = await apiCreateSession()
    setSessionId(created.session_id)
    return created.session_id
  }, [])

  const startNewSession = useCallback(async (): Promise<string> => {
    const created = await apiCreateSession()
    setSessionId(created.session_id)
    return created.session_id
  }, [])

  const resetSession = useCallback(() => {
    setSessionId(null)
  }, [])

  return (
    <SessionContext.Provider
      value={{ sessionId, setSessionId, resumeOrCreate, startNewSession, resetSession }}
    >
      {children}
    </SessionContext.Provider>
  )
}

export function useSession() {
  const ctx = useContext(SessionContext)
  if (!ctx) throw new Error('useSession must be used inside SessionProvider')
  return ctx
}
