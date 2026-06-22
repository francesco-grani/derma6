import { createContext, useContext, useState, type ReactNode } from 'react'
import { clearAuth, getIsAdmin, getToken, getUsername, setAuth } from './api'

interface AuthContextValue {
  token: string | null
  username: string | null
  isAdmin: boolean
  login: (token: string, username: string, isAdmin: boolean) => void
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(getToken)
  const [username, setUsername] = useState<string | null>(getUsername)
  const [isAdmin, setIsAdmin] = useState<boolean>(getIsAdmin)

  function login(t: string, u: string, admin: boolean) {
    setAuth(t, u, admin)
    setToken(t)
    setUsername(u)
    setIsAdmin(admin)
  }

  function logout() {
    clearAuth()
    setToken(null)
    setUsername(null)
    setIsAdmin(false)
  }

  return (
    <AuthContext.Provider value={{ token, username, isAdmin, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
