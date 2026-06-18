import { createContext, useContext, useState, type ReactNode } from 'react'
import { clearAuth, getToken, getUsername, setAuth } from './api'

interface AuthContextValue {
  token: string | null
  username: string | null
  login: (token: string, username: string) => void
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(getToken)
  const [username, setUsername] = useState<string | null>(getUsername)

  function login(t: string, u: string) {
    setAuth(t, u)
    setToken(t)
    setUsername(u)
  }

  function logout() {
    clearAuth()
    setToken(null)
    setUsername(null)
  }

  return (
    <AuthContext.Provider value={{ token, username, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
