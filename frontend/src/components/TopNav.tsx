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

const iconBtn =
  'inline-flex h-9 w-9 items-center justify-center rounded-xl border transition hover:opacity-90 disabled:opacity-45 sm:h-10 sm:w-10'

function sessionMeta(
  session: SessionStatus | null,
  refreshing: boolean,
): { label: string; color: string; title: string } {
  if (refreshing) {
    return { label: '…', color: 'var(--warning)', title: 'Odnawianie sesji Vinted…' }
  }
  if (!session) {
    return { label: '–', color: 'var(--muted)', title: 'Brak statusu sesji' }
  }
  if (!session.has_session) {
    return {
      label: 'brak',
      color: 'var(--danger)',
      title: 'Brak sesji — otwórz Chrome i zaloguj się na vinted.pl',
    }
  }
  const seconds = session.access_expires_in_seconds
  if (seconds !== null && seconds <= 0) {
    return { label: '0', color: 'var(--warning)', title: 'Sesja wygasła — odnów lub wklej cookies' }
  }
  return {
    label: formatDuration(seconds),
    color: 'var(--success)',
    title: [
      session.refresh_expires_at
        ? `Access: ${formatDuration(seconds)} · refresh do ${new Date(session.refresh_expires_at).toLocaleString('pl-PL')}`
        : `Access: ${formatDuration(seconds)}`,
      session.last_bootstrap_error ? `Ostatni błąd: ${session.last_bootstrap_error}` : '',
      session.browser_running
        ? session.cdp_ok === false
          ? 'Chrome CDP padł — restartuję w tle'
          : 'Chrome CDP utrzymuje sesję'
        : 'Chrome CDP nie działa — sprawdź logi',
    ]
      .filter(Boolean)
      .join(' — '),
  }
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
  const { logout } = useAuth()
  const atLimit = stats ? stats.active_threads >= stats.max_threads : false
  const sessionState = sessionMeta(session, refreshingSession)
  const telegramOk = Boolean(stats?.telegram_enabled)
  const vintedBlocked = Boolean(stats?.scraping_blocked)

  return (
    <header
      className="sticky top-0 z-20 border-b backdrop-blur"
      style={{ borderColor: 'var(--border)', background: 'rgba(10, 10, 10, 0.85)' }}
    >
      <nav className="mx-auto flex w-full max-w-6xl flex-wrap items-center gap-2 px-4 py-3 sm:px-6">
        <a href="#" className="flex items-center gap-2.5" aria-label="VintAgent">
          <BrandLogo size={32} />
          <span className="text-base font-semibold tracking-tight">VintAgent</span>
        </a>

        <div className="ml-auto flex flex-wrap items-center gap-1.5 sm:gap-2">
          {vintedBlocked && (
            <span
              className="inline-flex h-9 max-w-[11rem] items-center truncate rounded-xl border px-2.5 text-xs sm:h-10 sm:max-w-xs sm:px-3 sm:text-sm"
              style={{
                borderColor: 'rgba(239, 68, 68, 0.35)',
                background: 'rgba(239, 68, 68, 0.08)',
                color: 'var(--danger)',
              }}
              title={stats?.scraping_error ?? 'Vinted blokuje scraping'}
            >
              Vinted: 403
            </span>
          )}
          <span
            className="inline-flex h-9 items-center gap-1.5 rounded-xl border px-2.5 text-xs sm:h-10 sm:px-3 sm:text-sm"
            style={{
              ...pillStyle,
              color: atLimit ? 'var(--warning)' : 'var(--muted-light)',
            }}
            title="Aktywne wątki / limit"
          >
            <ThreadsIcon />
            <span className="tabular-nums">
              {stats ? `${stats.active_threads}/${stats.max_threads}` : '–'}
            </span>
          </span>

          <button
            type="button"
            onClick={onRefreshSession}
            disabled={refreshingSession}
            title={
              session?.last_bootstrap_error
                ? `Ostatni błąd: ${session.last_bootstrap_error}`
                : session?.browser_running
                  ? 'Wymuś synchronizację cookies z Chrome CDP'
                  : 'Chrome CDP nie działa'
            }
            className={`${iconBtn} gap-0 px-0 sm:w-auto sm:gap-1.5 sm:px-3`}
            style={{
              ...pillStyle,
              color: sessionState.color,
              borderColor: 'var(--border)',
            }}
            aria-label="Odśwież sesję Vinted"
          >
            <SessionIcon />
            <span className="hidden tabular-nums sm:inline sm:text-xs">{sessionState.label}</span>
          </button>

          <button
            type="button"
            onClick={onImportSession}
            title="Awaryjny import Cookie (DevTools)"
            className={iconBtn}
            style={{ ...pillStyle, color: 'var(--muted-light)', borderColor: 'var(--border)' }}
            aria-label="Wklej sesję"
          >
            <PasteIcon />
          </button>

          <button
            type="button"
            onClick={onTestTelegram}
            disabled={testingTelegram || !telegramOk}
            title={telegramOk ? 'Wyślij wiadomość testową' : 'Uzupełnij dane Telegrama w .env'}
            className={iconBtn}
            style={{
              ...pillStyle,
              color: telegramOk ? 'var(--success)' : 'var(--muted)',
              borderColor: 'var(--border)',
            }}
            aria-label="Test Telegram"
          >
            <TelegramIcon />
          </button>

          <button
            type="button"
            onClick={logout}
            title="Wyloguj"
            className={iconBtn}
            style={{
              borderColor: 'var(--border-strong)',
              background: 'var(--surface)',
              color: 'var(--muted-light)',
            }}
            aria-label="Wyloguj"
          >
            <LogoutIcon />
          </button>
        </div>
      </nav>
    </header>
  )
}

function iconClass() {
  return 'h-[18px] w-[18px]'
}

function ThreadsIcon() {
  return (
    <svg className={iconClass()} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M6 6.75h12M6 12h12M6 17.25h12"
      />
    </svg>
  )
}

function SessionIcon() {
  return (
    <svg className={iconClass()} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182"
      />
    </svg>
  )
}

function PasteIcon() {
  return (
    <svg className={iconClass()} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M15.666 3.888A2.25 2.25 0 0013.5 2.25h-3c-.966 0-1.814.608-2.166 1.638m7.332 0c.055.194.084.4.084.612v0a.75.75 0 01-.75.75H9.75a.75.75 0 01-.75-.75v0c0-.212.03-.418.084-.612m7.332 0c.646.049 1.288.11 1.927.184 1.1.128 1.907 1.077 1.907 2.185V19.5a2.25 2.25 0 01-2.25 2.25H6.75A2.25 2.25 0 014.5 19.5V6.257c0-1.108.806-2.057 1.907-2.185a48.208 48.208 0 011.927-.184"
      />
    </svg>
  )
}

function TelegramIcon() {
  return (
    <svg className={iconClass()} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M6 12L3.269 3.126A59.768 59.768 0 0121.485 12 59.77 59.77 0 013.27 20.876L5.999 12zm0 0h7.5"
      />
    </svg>
  )
}

function LogoutIcon() {
  return (
    <svg className={iconClass()} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M15.75 9V5.25A2.25 2.25 0 0013.5 3h-6a2.25 2.25 0 00-2.25 2.25v13.5A2.25 2.25 0 007.5 21h6a2.25 2.25 0 002.25-2.25V15M12 9l-3 3m0 0l3 3m-3-3h12.75"
      />
    </svg>
  )
}
