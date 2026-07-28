import { AuthProvider, useAuth } from './auth/AuthContext'
import Dashboard from './pages/Dashboard'
import Login from './pages/Login'

function Routes() {
  const { username, ready } = useAuth()

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
