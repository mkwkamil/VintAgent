import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { api, getToken, setToken, setUnauthorizedHandler } from '../api/client'

type AuthState = {
  username: string | null
  ready: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [username, setUsername] = useState<string | null>(null)
  const [ready, setReady] = useState(false)

  const logout = useCallback(() => {
    setToken(null)
    setUsername(null)
  }, [])

  useEffect(() => {
    setUnauthorizedHandler(logout)
    return () => setUnauthorizedHandler(null)
  }, [logout])

  useEffect(() => {
    if (!getToken()) {
      setReady(true)
      return
    }
    api
      .me()
      .then((user) => setUsername(user.username))
      .catch(() => setToken(null))
      .finally(() => setReady(true))
  }, [])

  const login = useCallback(async (user: string, password: string) => {
    const result = await api.login(user, password)
    setToken(result.access_token)
    setUsername(result.username)
  }, [])

  const value = useMemo<AuthState>(
    () => ({ username, ready, login, logout }),
    [username, ready, login, logout],
  )

  return <AuthContext value={value}>{children}</AuthContext>
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside AuthProvider')
  return context
}
