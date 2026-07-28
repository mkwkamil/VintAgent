import { useState } from 'react'
import { useAuth } from '../auth/AuthContext'

export default function Login() {
  const { login } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(username.trim(), password)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Logowanie nie powiodło się')
    } finally {
      setBusy(false)
    }
  }

  const fieldStyle = {
    borderColor: 'var(--border-strong)',
    background: 'var(--surface)',
    color: 'var(--ink)',
  }

  return (
    <main className="grid min-h-screen place-items-center px-4">
      <form
        onSubmit={submit}
        className="w-full max-w-sm rounded-2xl border p-6"
        style={{ borderColor: 'var(--border)', background: 'var(--surface)' }}
      >
        <div className="flex items-center gap-2">
          <span
            className="grid size-9 place-items-center rounded-lg text-base font-bold"
            style={{ background: 'var(--accent)', color: '#fff' }}
          >
            V
          </span>
          <div>
            <h1 className="text-lg font-semibold">VintAgent</h1>
            <p className="text-xs" style={{ color: 'var(--muted)' }}>
              Panel administratora
            </p>
          </div>
        </div>

        <label className="mt-6 block text-xs font-medium uppercase tracking-wide" style={{ color: 'var(--muted)' }}>
          Login
          <input
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            required
            autoFocus
            autoComplete="username"
            className="mt-1.5 w-full rounded-lg border px-3 py-2 text-sm font-normal normal-case tracking-normal outline-none focus:border-[color:var(--accent)]"
            style={fieldStyle}
          />
        </label>

        <label className="mt-3 block text-xs font-medium uppercase tracking-wide" style={{ color: 'var(--muted)' }}>
          Hasło
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
            autoComplete="current-password"
            className="mt-1.5 w-full rounded-lg border px-3 py-2 text-sm font-normal normal-case tracking-normal outline-none focus:border-[color:var(--accent)]"
            style={fieldStyle}
          />
        </label>

        {error && (
          <p className="mt-3 text-sm" style={{ color: 'var(--danger)' }}>
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={busy}
          className="mt-5 w-full rounded-lg px-4 py-2.5 text-sm font-medium text-white transition-opacity hover:opacity-85 disabled:opacity-45"
          style={{ background: 'var(--accent)' }}
        >
          {busy ? 'Loguję…' : 'Zaloguj'}
        </button>
      </form>
    </main>
  )
}
