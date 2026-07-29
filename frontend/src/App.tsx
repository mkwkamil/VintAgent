import { AuthProvider, useAuth } from './auth/AuthContext'
import Dashboard from './pages/Dashboard'
import Login from './pages/Login'
import RescuePage, { isRescueHash } from './pages/RescuePage'
import { useEffect, useState } from 'react'

function Routes() {
  const { username, ready } = useAuth()
  const [rescue, setRescue] = useState(() => isRescueHash())

  useEffect(() => {
    const sync = () => setRescue(isRescueHash())
    window.addEventListener('hashchange', sync)
    return () => window.removeEventListener('hashchange', sync)
  }, [])

  if (rescue) return <RescuePage />

  if (!ready) {
    return (
      <main className="grid min-h-screen place-items-center">
        <p style={{ color: 'var(--muted)' }}>Ładowanie…</p>
      </main>
    )
  }

  return username ? <Dashboard /> : <Login />
}

export default function App() {
  return (
    <AuthProvider>
      <Routes />
    </AuthProvider>
  )
}
