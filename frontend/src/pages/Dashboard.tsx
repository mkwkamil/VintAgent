import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type { SessionStatus, Stats, TrackedUrl } from '../api/client'
import TopNav from '../components/TopNav'
import UrlCard from '../components/UrlCard'
import UrlFormModal from '../components/UrlFormModal'
import SessionImportModal from '../components/SessionImportModal'
import UrlDetail from './UrlDetail'
import { useHashRoute } from '../lib/useHashRoute'

const REFRESH_MS = 10_000

export default function Dashboard() {
  const [urls, setUrls] = useState<TrackedUrl[]>([])
  const [stats, setStats] = useState<Stats | null>(null)
  const [session, setSession] = useState<SessionStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [notice, setNotice] = useState<{ kind: 'error' | 'info'; text: string } | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [modal, setModal] = useState<{ item: TrackedUrl | null } | null>(null)
  const [sessionModal, setSessionModal] = useState(false)
  const [testingTelegram, setTestingTelegram] = useState(false)
  const [refreshingSession, setRefreshingSession] = useState(false)
  const noticeTimer = useRef<number | null>(null)
  const { detailId, openDetail, goBack } = useHashRoute()

  const flash = useCallback((kind: 'error' | 'info', text: string) => {
    setNotice({ kind, text })
    if (noticeTimer.current) window.clearTimeout(noticeTimer.current)
    noticeTimer.current = window.setTimeout(() => setNotice(null), 6000)
  }, [])

  const refresh = useCallback(async () => {
    try {
      const [list, currentStats, currentSession] = await Promise.all([api.listUrls(), api.stats(), api.session()])
      setUrls(list)
      setStats(currentStats)
      setSession(currentSession)
    } catch (err) {
      flash('error', err instanceof Error ? err.message : 'Nie udało się pobrać danych')
    } finally {
      setLoading(false)
    }
  }, [flash])

  useEffect(() => {
    void refresh()
    const interval = window.setInterval(() => void refresh(), REFRESH_MS)
    return () => window.clearInterval(interval)
  }, [refresh])

  const runAction = async (id: string, action: () => Promise<unknown>, successText?: string) => {
    setBusyId(id)
    try {
      await action()
      if (successText) flash('info', successText)
      await refresh()
    } catch (err) {
      flash('error', err instanceof Error ? err.message : 'Operacja nie powiodła się')
    } finally {
      setBusyId(null)
    }
  }

  const testTelegram = async () => {
    setTestingTelegram(true)
    try {
      const result = await api.testTelegram()
      flash('info', result.detail)
    } catch (err) {
      flash('error', err instanceof Error ? err.message : 'Test Telegrama nie powiódł się')
    } finally {
      setTestingTelegram(false)
    }
  }

  const refreshSession = async () => {
    setRefreshingSession(true)
    flash('info', 'Odnawiam sesję Vinted w tle…')
    try {
      const result = await api.refreshSession()
      setSession(result)
      flash('info', 'Sesja Vinted odnowiona')
    } catch (err) {
      flash('error', err instanceof Error ? err.message : 'Nie udało się odnowić sesji')
    } finally {
      setRefreshingSession(false)
    }
  }

  const atLimit = stats ? stats.active_threads >= stats.max_threads : false
  const runningCount = urls.filter((item) => item.status === 'running').length
  const foundLast24h = urls.reduce((total, item) => total + item.stats.found_last_24h, 0)

  return (
    <div className="min-h-screen">
      <TopNav
        stats={stats}
        session={session}
        onTestTelegram={testTelegram}
        testingTelegram={testingTelegram}
        onRefreshSession={refreshSession}
        refreshingSession={refreshingSession}
        onImportSession={() => setSessionModal(true)}
      />

      <main className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-6">
        {notice && (
          <p
            className="mb-4 rounded-xl border px-4 py-2.5 text-sm"
            style={{
              borderColor: notice.kind === 'error' ? 'rgba(239, 68, 68, 0.35)' : 'rgba(34, 197, 94, 0.3)',
              background: notice.kind === 'error' ? 'rgba(239, 68, 68, 0.08)' : 'rgba(34, 197, 94, 0.08)',
              color: notice.kind === 'error' ? 'var(--danger)' : 'var(--success)',
            }}
          >
            {notice.text}
          </p>
        )}

        {detailId ? (
          <UrlDetail
            urlId={detailId}
            onBack={goBack}
            onEdit={(item) => setModal({ item })}
            onDeleted={() => {
              goBack()
              void refresh()
            }}
            startDisabled={atLimit}
            flash={flash}
          />
        ) : (
          <>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h1 className="text-xl font-semibold">Śledzone wyszukiwania</h1>
                <p className="mt-0.5 text-sm" style={{ color: 'var(--muted)' }}>
                  {urls.length} URL-i, {runningCount} aktywnych, {foundLast24h} znalezisk w ostatniej dobie.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setModal({ item: null })}
                className="rounded-lg px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-85"
                style={{ background: 'var(--accent)' }}
              >
                Dodaj URL
              </button>
            </div>

            {atLimit && (
              <p className="mt-4 text-sm" style={{ color: 'var(--warning)' }}>
                Limit {stats?.max_threads} aktywnych wątków osiągnięty. Zatrzymaj jeden, aby uruchomić kolejny.
              </p>
            )}

            <section className="mt-5 grid gap-3 md:grid-cols-2">
              {loading ? (
                <p style={{ color: 'var(--muted)' }}>Ładowanie…</p>
              ) : urls.length === 0 ? (
                <div
                  className="rounded-2xl border border-dashed px-6 py-12 text-center md:col-span-2"
                  style={{ borderColor: 'var(--border-strong)', color: 'var(--muted)' }}
                >
                  <p className="text-sm">Brak śledzonych URL-i.</p>
                  <p className="mt-1 text-xs">Dodaj pierwszy link z wyszukiwarki Vinted, aby zacząć.</p>
                </div>
              ) : (
                urls.map((item) => (
                  <UrlCard
                    key={item.id}
                    item={item}
                    busy={busyId === item.id}
                    startDisabled={atLimit}
                    onOpen={() => openDetail(item.id)}
                    onStart={() => runAction(item.id, () => api.startUrl(item.id), `Uruchomiono „${item.name}”`)}
                    onStop={() => runAction(item.id, () => api.stopUrl(item.id), `Zatrzymano „${item.name}”`)}
                    onEdit={() => setModal({ item })}
                    onDelete={() => {
                      if (window.confirm(`Usunąć „${item.name}”?`)) {
                        void runAction(item.id, () => api.deleteUrl(item.id), 'URL usunięty')
                      }
                    }}
                  />
                ))
              )}
            </section>
          </>
        )}
      </main>

      {modal && (
        <UrlFormModal
          item={modal.item}
          onClose={() => setModal(null)}
          onSubmit={async (name, url) => {
            if (modal.item) await api.updateUrl(modal.item.id, { name, url })
            else await api.createUrl(name, url)
            await refresh()
          }}
        />
      )}

      {sessionModal && (
        <SessionImportModal
          onClose={() => setSessionModal(false)}
          onSubmit={async (cookie) => {
            const result = await api.importSession(cookie)
            setSession(result)
            flash('info', 'Sesja Vinted zaimportowana')
            await refresh()
          }}
          onTestRescue={async () => {
            const result = await api.testRescueAlert()
            flash('info', result.detail)
          }}
        />
      )}
    </div>
  )
}
