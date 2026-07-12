import { useCallback, useState, type ReactNode } from 'react'
import { apiCreateSession, apiGetSessions } from '@/lib/api'
import type { ChatSessionInfo } from '@/lib/api'
import { SessionContext } from './sessionContext'

export function SessionProvider({ children }: { children: ReactNode }) {
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
