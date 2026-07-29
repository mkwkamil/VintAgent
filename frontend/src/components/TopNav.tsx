import type { SessionStatus, Stats } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { formatDuration } from '../lib/format'
import BrandLogo from './BrandLogo'

type Props = {
  stats: Stats | null
  session: SessionStatus | null
  onTestTelegram: () => void
  testingTelegram: boolean
  onRefreshSession: () => void
  refreshingSession: boolean
  onImportSession: () => void
}


const pillStyle = {
  borderColor: 'var(--border)',
  background: 'var(--surface)',
} as const

function sessionLabel(session: SessionStatus | null, refreshing: boolean): { text: string; color: string } {
  if (refreshing) return { text: 'Sesja: odnawianie…', color: 'var(--warning)' }
  if (!session) return { text: 'Sesja: –', color: 'var(--muted)' }
  if (!session.has_session) {
    return {
      text: session.browser_available ? 'Sesja: pobieranie' : 'Sesja: brak',
      color: session.browser_available ? 'var(--warning)' : 'var(--danger)',
    }
  }
  const seconds = session.access_expires_in_seconds
  if (seconds !== null && seconds <= 0) return { text: 'Sesja: wygasła', color: 'var(--warning)' }
  return { text: `Sesja: ${formatDuration(seconds)}`, color: 'var(--success)' }
}

export default function TopNav({
  stats,
  session,
  onTestTelegram,
  testingTelegram,
  onRefreshSession,
  refreshingSession,
  onImportSession,
}: Props) {
  const { username, logout } = useAuth()
  const atLimit = stats ? stats.active_threads >= stats.max_threads : false
  const sessionState = sessionLabel(session, refreshingSession)

  return (
    <header
      className="sticky top-0 z-20 border-b backdrop-blur"
      style={{ borderColor: 'var(--border)', background: 'rgba(10, 10, 10, 0.85)' }}
    >
      <nav className="mx-auto flex w-full max-w-6xl flex-wrap items-center gap-2 px-4 py-3 sm:px-6">
        <a href="#" className="flex items-center gap-2.5">
          <BrandLogo size={32} />
          <span className="text-base font-semibold tracking-tight">VintAgent</span>
        </a>

        <div className="ml-auto flex flex-wrap items-center gap-2 text-xs sm:text-sm">
          <span
            className="rounded-full border px-3 py-1.5"
            style={{ ...pillStyle, color: atLimit ? 'var(--warning)' : 'var(--muted-light)' }}
          >
            Wątki: {stats ? `${stats.active_threads}/${stats.max_threads}` : '–'}
          </span>

          <div className="flex overflow-hidden rounded-full border" style={pillStyle}>
            <button
              type="button"
              onClick={onRefreshSession}
              disabled={refreshingSession || !session?.browser_available}
              title={
                session?.last_bootstrap_error
                  ? `Ostatni błąd: ${session.last_bootstrap_error}`
                  : session?.browser_available
                    ? 'Odnów cookies Vinted przeglądarką'
                    : 'Automatyczne odnawianie sesji jest niedostępne'
              }
              className="px-3 py-1.5 transition-colors disabled:opacity-45"
              style={{ color: sessionState.color }}
            >
              {sessionState.text}
            </button>
            <button
              type="button"
              onClick={onImportSession}
              title="Wklej cookies z lokalnej przeglądarki (gdy Cloudflare blokuje IP serwera)"
              className="border-l px-2.5 py-1.5 transition-colors hover:opacity-80"
              style={{ borderColor: 'var(--border)', color: 'var(--muted-light)' }}
            >
              Wklej
            </button>
          </div>

          <button
            type="button"
            onClick={onTestTelegram}
            disabled={testingTelegram || !stats?.telegram_enabled}
            title={stats?.telegram_enabled ? 'Wyślij wiadomość testową' : 'Uzupełnij dane Telegrama w .env'}
            className="rounded-full border px-3 py-1.5 transition-colors disabled:opacity-45"
            style={{ ...pillStyle, color: stats?.telegram_enabled ? 'var(--success)' : 'var(--muted)' }}
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
