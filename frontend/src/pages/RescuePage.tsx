import { useEffect, useMemo, useState } from 'react'
import BrandLogo from '../components/BrandLogo'

type RescueInfo = {
  valid: boolean
  expires_in_seconds: number
  reason: string
  vinted_url: string
  public_base_url: string | null
  bookmarklet: string | null
}

function parseHash(): { token: string | null; ok: boolean; err: string | null } {
  const hash = window.location.hash
  if (!hash.includes('/rescue')) {
    return { token: null, ok: false, err: null }
  }
  const queryIndex = hash.indexOf('?')
  const params = new URLSearchParams(queryIndex >= 0 ? hash.slice(queryIndex + 1) : '')
  return {
    token: params.get('t'),
    ok: params.get('ok') === '1',
    err: params.get('err'),
  }
}

export function isRescueHash(hash = window.location.hash): boolean {
  return hash.includes('/rescue')
}

export default function RescuePage() {
  const initial = useMemo(() => parseHash(), [])
  const [token, setToken] = useState(initial.token)
  const [done, setDone] = useState(initial.ok)
  const [info, setInfo] = useState<RescueInfo | null>(null)
  const [error, setError] = useState<string | null>(
    initial.err === 'expired'
      ? 'Link wygasł lub został już użyty.'
      : initial.err === 'missing'
        ? 'Brak access_token_web — otwórz vinted.pl i spróbuj ponownie.'
        : null,
  )
  const [cookie, setCookie] = useState('')
  const [busy, setBusy] = useState(false)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    const onHash = () => {
      const next = parseHash()
      setToken(next.token)
      if (next.ok) setDone(true)
      if (next.err === 'expired') setError('Link wygasł lub został już użyty.')
      if (next.err === 'missing') setError('Brak access_token_web — otwórz vinted.pl i spróbuj ponownie.')
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  useEffect(() => {
    if (!token || done) return
    let cancelled = false
    ;(async () => {
      try {
        const response = await fetch(`/api/session/rescue/${encodeURIComponent(token)}`)
        const body = await response.json().catch(() => ({}))
        if (!response.ok) {
          if (!cancelled) setError(typeof body.detail === 'string' ? body.detail : 'Link nieaktywny')
          return
        }
        if (!cancelled) {
          setInfo(body as RescueInfo)
          setError(null)
        }
      } catch {
        if (!cancelled) setError('Nie udało się połączyć z serwerem')
      }
    })()
    return () => {
      cancelled = true
    }
  }, [token, done])

  const submitPaste = async () => {
    if (!token || !cookie.trim()) {
      setError('Wklej nagłówek Cookie z vinted.pl')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const response = await fetch(`/api/session/rescue/${encodeURIComponent(token)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cookie: cookie.trim() }),
      })
      const body = await response.json().catch(() => ({}))
      if (!response.ok) {
        setError(typeof body.detail === 'string' ? body.detail : 'Import nie powiódł się')
        return
      }
      setDone(true)
      window.location.hash = '#/rescue?ok=1'
    } catch {
      setError('Nie udało się wysłać cookies')
    } finally {
      setBusy(false)
    }
  }

  const copyBookmarklet = async () => {
    if (!info?.bookmarklet) return
    try {
      await navigator.clipboard.writeText(info.bookmarklet)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      setError('Nie udało się skopiować — przytrzymaj link „Wyślij cookies” i dodaj do zakładek')
    }
  }

  const minutesLeft = info ? Math.max(1, Math.ceil(info.expires_in_seconds / 60)) : null

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-lg flex-col justify-center px-4 py-10">
      <div className="rounded-2xl border p-5 sm:p-6" style={{ borderColor: 'var(--border)', background: 'var(--surface)' }}>
        <div className="flex items-center gap-3">
          <BrandLogo size={40} />
          <div>
            <h1 className="text-lg font-semibold tracking-tight">Odnów sesję Vinted</h1>
            <p className="text-xs" style={{ color: 'var(--muted)' }}>
              Link jednorazowy · bez logowania do panelu
            </p>
          </div>
        </div>

        {done ? (
          <div className="mt-6 space-y-3">
            <p className="text-sm" style={{ color: 'var(--success)' }}>
              Sesja zapisana. Scraping wraca do normalnej pracy — możesz zamknąć tę stronę.
            </p>
            <a href="#" className="text-sm underline" style={{ color: 'var(--accent-soft)' }}>
              Otwórz panel
            </a>
          </div>
        ) : (
          <>
            {error && (
              <p className="mt-4 rounded-xl border px-3 py-2 text-sm" style={{ borderColor: 'rgba(239,68,68,0.35)', color: 'var(--danger)' }}>
                {error}
              </p>
            )}

            {!token && (
              <p className="mt-4 text-sm" style={{ color: 'var(--muted-light)' }}>
                Brak tokenu w linku. Otwórz przycisk <b>Odnów sesję</b> z wiadomości Telegram.
              </p>
            )}

            {token && info && (
              <div className="mt-5 space-y-5 text-sm">
                <p style={{ color: 'var(--muted-light)' }}>
                  {info.reason || 'Serwer potrzebuje świeżych cookies z Twojej sieci (telefon / dom).'}
                  {minutesLeft != null && (
                    <>
                      {' '}
                      Link ważny jeszcze ok. <b>{minutesLeft} min</b>.
                    </>
                  )}
                </p>

                <ol className="list-decimal space-y-2 pl-5" style={{ color: 'var(--ink)' }}>
                  <li>
                    Dodaj zakładkę{' '}
                    {info.bookmarklet ? (
                      <a
                        href={info.bookmarklet}
                        className="font-medium underline"
                        style={{ color: 'var(--accent-soft)' }}
                        onClick={(event) => {
                          // Prevent accidental run on this origin; user should drag to bookmarks.
                          event.preventDefault()
                          void copyBookmarklet()
                        }}
                      >
                        Wyślij cookies
                      </a>
                    ) : (
                      <b>Wyślij cookies</b>
                    )}{' '}
                    (skopiuj / przeciągnij do paska zakładek).
                    {copied && (
                      <span className="ml-2" style={{ color: 'var(--success)' }}>
                        skopiowano
                      </span>
                    )}
                  </li>
                  <li>
                    Otwórz{' '}
                    <a href={info.vinted_url} target="_blank" rel="noreferrer" className="underline" style={{ color: 'var(--accent-soft)' }}>
                      {info.vinted_url.replace(/^https?:\/\//, '')}
                    </a>{' '}
                    w tej samej przeglądarce (nie w apce).
                  </li>
                  <li>Na stronie Vinted kliknij zakładkę — cookies wrócą na serwer automatycznie.</li>
                </ol>

                <div className="border-t pt-4" style={{ borderColor: 'var(--border)' }}>
                  <p className="mb-2 text-xs font-medium uppercase tracking-wide" style={{ color: 'var(--muted)' }}>
                    Albo wklej ręcznie
                  </p>
                  <textarea
                    value={cookie}
                    onChange={(event) => setCookie(event.target.value)}
                    rows={4}
                    placeholder="Cookie: access_token_web=…; refresh_token_web=…; …"
                    className="w-full rounded-xl border px-3 py-2 text-xs outline-none"
                    style={{ borderColor: 'var(--border-strong)', background: 'var(--bg)', color: 'var(--ink)' }}
                  />
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void submitPaste()}
                    className="mt-3 w-full rounded-xl px-3 py-2.5 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-45"
                    style={{ background: 'var(--accent)' }}
                  >
                    {busy ? 'Zapisuję…' : 'Zapisz sesję'}
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </main>
  )
}
