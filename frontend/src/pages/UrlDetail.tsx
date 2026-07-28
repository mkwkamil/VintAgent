import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { TrackedUrl, UrlStats } from '../api/client'
import BarChart from '../components/BarChart'
import StatusBadge from '../components/StatusBadge'
import { formatDateTime, formatNumber, formatRelative } from '../lib/format'

type Props = {
  urlId: string
  onBack: () => void
  onEdit: (item: TrackedUrl) => void
  onDeleted: () => void
  startDisabled: boolean
  flash: (kind: 'error' | 'info', text: string) => void
}

const REFRESH_MS = 15_000
const RANGES = [
  { hours: 6, label: '6 h' },
  { hours: 24, label: '24 h' },
  { hours: 72, label: '3 dni' },
  { hours: 168, label: '7 dni' },
]

function Tile({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <div className="rounded-xl border p-3" style={{ borderColor: 'var(--border)', background: 'var(--surface)' }}>
      <div className="text-xs" style={{ color: 'var(--muted)' }}>
        {label}
      </div>
      <div className="mt-1 text-xl font-semibold tabular-nums">
        {typeof value === 'number' ? formatNumber(value) : value}
      </div>
      {hint && (
        <div className="mt-0.5 text-[11px]" style={{ color: 'var(--muted)' }}>
          {hint}
        </div>
      )}
    </div>
  )
}

function Panel({ title, subtitle, children }: { title: string; subtitle: string; children: React.ReactNode }) {
  return (
    <section
      className="rounded-2xl border p-4 sm:p-5"
      style={{ borderColor: 'var(--border)', background: 'var(--surface)' }}
    >
      <h3 className="text-sm font-semibold">{title}</h3>
      <p className="mt-0.5 mb-4 text-xs" style={{ color: 'var(--muted)' }}>
        {subtitle}
      </p>
      {children}
    </section>
  )
}

export default function UrlDetail({ urlId, onBack, onEdit, onDeleted, startDisabled, flash }: Props) {
  const [item, setItem] = useState<TrackedUrl | null>(null)
  const [stats, setStats] = useState<UrlStats | null>(null)
  const [hours, setHours] = useState(24)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      const [detail, series] = await Promise.all([api.getUrl(urlId), api.urlStats(urlId, hours)])
      setItem(detail)
      setStats(series)
    } catch (err) {
      flash('error', err instanceof Error ? err.message : 'Nie udało się pobrać statystyk')
      onBack()
    } finally {
      setLoading(false)
    }
  }, [urlId, hours, flash, onBack])

  useEffect(() => {
    void load()
    const interval = window.setInterval(() => void load(), REFRESH_MS)
    return () => window.clearInterval(interval)
  }, [load])

  const act = async (action: () => Promise<unknown>, successText: string) => {
    setBusy(true)
    try {
      await action()
      flash('info', successText)
      await load()
    } catch (err) {
      flash('error', err instanceof Error ? err.message : 'Operacja nie powiodła się')
    } finally {
      setBusy(false)
    }
  }

  if (loading || !item || !stats) {
    return <p style={{ color: 'var(--muted)' }}>Ładowanie…</p>
  }

  const running = item.status === 'running'
  const summary = stats.summary
  const timelineBars = stats.found_timeline.map((point) => {
    const date = new Date(point.hour)
    const label = date.toLocaleTimeString('pl-PL', { hour: '2-digit' })
    return {
      label,
      value: point.count,
      title: `${date.toLocaleString('pl-PL', { dateStyle: 'short', timeStyle: 'short' })}: ${point.count}`,
    }
  })
  const currentHour = new Date().getHours()
  const dayBars = stats.listed_by_hour_of_day.map((count, hour) => ({
    label: String(hour).padStart(2, '0'),
    value: count,
    title: `${String(hour).padStart(2, '0')}:00–${String(hour).padStart(2, '0')}:59 — ${count} ogłoszeń`,
    highlight: hour === currentHour,
  }))
  const bestHour = stats.listed_by_hour_of_day.indexOf(Math.max(...stats.listed_by_hour_of_day))
  const hasListedData = stats.listed_by_hour_of_day.some((count) => count > 0)

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start gap-3">
        <button
          type="button"
          onClick={onBack}
          className="rounded-lg border px-3 py-1.5 text-sm transition-opacity hover:opacity-80"
          style={{ borderColor: 'var(--border-strong)', background: 'var(--surface)' }}
        >
          ← Wróć
        </button>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="truncate text-xl font-semibold">{item.name}</h1>
            <StatusBadge status={item.status} hasError={Boolean(item.last_error)} />
          </div>
          <a
            href={item.url}
            target="_blank"
            rel="noreferrer"
            title={item.url}
            className="mt-1 block truncate text-xs hover:underline"
            style={{ color: 'var(--muted)' }}
          >
            {item.url}
          </a>
        </div>
      </div>

      <div className="flex flex-wrap gap-2 text-sm">
        {running ? (
          <button
            type="button"
            onClick={() => act(() => api.stopUrl(item.id), `Zatrzymano „${item.name}”`)}
            disabled={busy}
            className="rounded-lg px-3.5 py-1.5 font-medium transition-opacity hover:opacity-85 disabled:opacity-45"
            style={{ background: 'var(--surface-raised)', border: '1px solid var(--border-strong)' }}
          >
            Stop
          </button>
        ) : (
          <button
            type="button"
            onClick={() => act(() => api.startUrl(item.id), `Uruchomiono „${item.name}”`)}
            disabled={busy || startDisabled}
            title={startDisabled ? 'Osiągnięto limit aktywnych wątków' : undefined}
            className="rounded-lg px-3.5 py-1.5 font-medium text-white transition-opacity hover:opacity-85 disabled:opacity-45"
            style={{ background: 'var(--accent)' }}
          >
            Start
          </button>
        )}

        <button
          type="button"
          onClick={() => onEdit(item)}
          className="rounded-lg border px-3.5 py-1.5 transition-opacity hover:opacity-85"
          style={{ borderColor: 'var(--border-strong)' }}
        >
          Edytuj
        </button>

        <button
          type="button"
          onClick={() => {
            if (window.confirm('Wyczyścić statystyki tego linku?')) {
              void act(() => api.resetUrlStats(item.id), 'Statystyki wyczyszczone')
            }
          }}
          className="rounded-lg border px-3.5 py-1.5 transition-opacity hover:opacity-85"
          style={{ borderColor: 'var(--border-strong)' }}
        >
          Wyczyść statystyki
        </button>

        <button
          type="button"
          onClick={async () => {
            if (!window.confirm(`Usunąć „${item.name}”?`)) return
            await act(() => api.deleteUrl(item.id), 'URL usunięty')
            onDeleted()
          }}
          className="ml-auto rounded-lg border px-3.5 py-1.5 transition-opacity hover:opacity-85"
          style={{ borderColor: 'rgba(239, 68, 68, 0.35)', color: 'var(--danger)' }}
        >
          Usuń
        </button>
      </div>

      {item.last_error && (
        <p
          className="rounded-xl border px-4 py-2.5 text-sm"
          style={{
            borderColor: 'rgba(245, 158, 11, 0.25)',
            background: 'rgba(245, 158, 11, 0.08)',
            color: 'var(--warning)',
          }}
        >
          {item.last_error}
        </p>
      )}

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <Tile label="Znalezione łącznie" value={summary.found_total} />
        <Tile label="Ostatnia doba" value={summary.found_last_24h} hint={`${summary.found_last_hour} w tej godzinie`} />
        <Tile label="Średnio na godzinę" value={summary.found_per_hour} hint="w godzinach z aktywnością" />
        <Tile label="Sprawdzenia" value={summary.checks} hint={`${formatNumber(summary.errors)} błędów`} />
        <Tile label="Ostatnie znalezisko" value={formatRelative(summary.last_found_at)} />
      </div>

      <Panel
        title="Znalezione ogłoszenia w czasie"
        subtitle={`Ile nowych ofert wyłapał agent w kolejnych godzinach (ostatnie ${
          RANGES.find((range) => range.hours === hours)?.label ?? `${hours} h`
        })`}
      >
        <div className="mb-4 flex gap-1.5 text-xs">
          {RANGES.map((range) => (
            <button
              key={range.hours}
              type="button"
              onClick={() => setHours(range.hours)}
              className="rounded-lg border px-2.5 py-1 transition-opacity hover:opacity-80"
              style={{
                borderColor: hours === range.hours ? 'var(--accent)' : 'var(--border)',
                color: hours === range.hours ? 'var(--accent-soft)' : 'var(--muted)',
              }}
            >
              {range.label}
            </button>
          ))}
        </div>
        <BarChart
          bars={timelineBars}
          labelEvery={Math.max(1, Math.round(timelineBars.length / 12))}
          emptyText="Brak znalezisk w tym okresie"
        />
      </Panel>

      <Panel
        title="O której godzinie wystawiane są ogłoszenia"
        subtitle={
          hasListedData
            ? `Rozkład dobowy z ostatnich 7 dni, czas lokalny. Szczyt: ${String(bestHour).padStart(2, '0')}:00`
            : 'Rozkład dobowy z ostatnich 7 dni, czas lokalny'
        }
      >
        <BarChart bars={dayBars} labelEvery={2} emptyText="Za mało danych, agent zbiera je z każdym znaleziskiem" />
      </Panel>

      <p className="text-xs" style={{ color: 'var(--muted)' }}>
        Śledzony od {formatDateTime(item.created_at)} · ostatnie sprawdzenie {formatRelative(item.last_checked_at)}
      </p>
    </div>
  )
}
