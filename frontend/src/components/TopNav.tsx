import type { Stats } from '../api/client'
import { useAuth } from '../auth/AuthContext'

type Props = {
  stats: Stats | null
  onTestTelegram: () => void
  testingTelegram: boolean
}

export default function TopNav({ stats, onTestTelegram, testingTelegram }: Props) {
  const { username, logout } = useAuth()
  const atLimit = stats ? stats.active_threads >= stats.max_threads : false

  return (
    <header
      className="sticky top-0 z-20 border-b backdrop-blur"
      style={{ borderColor: 'var(--border)', background: 'rgba(10, 10, 10, 0.85)' }}
    >
      <nav className="mx-auto flex w-full max-w-6xl flex-wrap items-center gap-3 px-4 py-3 sm:px-6">
        <div className="flex items-center gap-2">
          <span
            className="grid size-8 place-items-center rounded-lg text-sm font-bold"
            style={{ background: 'var(--accent)', color: '#fff' }}
          >
            V
          </span>
          <span className="text-base font-semibold">VintAgent</span>
        </div>

        <div className="ml-auto flex flex-wrap items-center gap-2 text-xs sm:text-sm">
          <span
            className="rounded-full border px-3 py-1.5"
            style={{
              borderColor: 'var(--border)',
              background: 'var(--surface)',
              color: atLimit ? 'var(--warning)' : 'var(--muted-light)',
            }}
          >
            Wątki: {stats ? `${stats.active_threads}/${stats.max_threads}` : '–'}
          </span>

          <button
            type="button"
            onClick={onTestTelegram}
            disabled={testingTelegram || !stats?.telegram_enabled}
            title={stats?.telegram_enabled ? 'Wyślij wiadomość testową' : 'Uzupełnij dane Telegrama w .env'}
            className="rounded-full border px-3 py-1.5 transition-colors disabled:opacity-45"
            style={{
              borderColor: 'var(--border)',
              background: 'var(--surface)',
              color: stats?.telegram_enabled ? 'var(--success)' : 'var(--muted)',
            }}
          >
            Telegram: {stats?.telegram_enabled ? 'gotowy' : 'brak konfiguracji'}
          </button>

          <span className="hidden sm:inline" style={{ color: 'var(--muted)' }}>
            {username}
          </span>

          <button
            type="button"
            onClick={logout}
            className="rounded-full border px-3 py-1.5 transition-colors hover:opacity-80"
            style={{ borderColor: 'var(--border-strong)', background: 'var(--surface)' }}
          >
            Wyloguj
          </button>
        </div>
      </nav>
    </header>
  )
}
