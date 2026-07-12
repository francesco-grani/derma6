import { createContext, useContext } from 'react'

export interface SessionContextValue {
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

export const SessionContext = createContext<SessionContextValue | null>(null)

export function useSession() {
  const ctx = useContext(SessionContext)
  if (!ctx) throw new Error('useSession must be used inside SessionProvider')
  return ctx
}
