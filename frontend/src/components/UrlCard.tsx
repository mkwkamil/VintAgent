import type { TrackedUrl } from '../api/client'
import StatusBadge from './StatusBadge'
import { formatNumber, formatRelative } from '../lib/format'

type Props = {
  item: TrackedUrl
  busy: boolean
  startDisabled: boolean
  onOpen: () => void
  onStart: () => void
  onStop: () => void
  onEdit: () => void
  onDelete: () => void
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="text-base font-semibold tabular-nums">{formatNumber(value)}</div>
      <div className="text-[11px]" style={{ color: 'var(--muted)' }}>
        {label}
      </div>
    </div>
  )
}

export default function UrlCard({ item, busy, startDisabled, onOpen, onStart, onStop, onEdit, onDelete }: Props) {
  const running = item.status === 'running'

  // Buttons live inside the clickable card, so every one of them stops the
  // bubble that would otherwise open the detail view.
  const isolate = (handler: () => void) => (event: React.MouseEvent) => {
    event.stopPropagation()
    handler()
  }

  return (
    <article
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          onOpen()
        }
      }}
      className="flex cursor-pointer flex-col overflow-hidden rounded-2xl border p-4 text-left transition-colors hover:border-white/20 sm:p-5"
      style={{ borderColor: 'var(--border)', background: 'var(--surface)' }}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-base font-semibold">{item.name}</h3>
          <p className="mt-0.5 text-xs" style={{ color: 'var(--muted)' }}>
            Sprawdzono {formatRelative(item.last_checked_at)}
            {item.telegram_topic_id != null ? ' · topic TG' : ''}
          </p>
        </div>
        <StatusBadge status={item.status} hasError={Boolean(item.last_error)} />
      </div>

      <div className="mt-4 grid grid-cols-3 gap-2">
        <Metric label="ostatnia doba" value={item.stats.found_last_24h} />
        <Metric label="łącznie" value={item.stats.found_total} />
        <Metric label="sprawdzeń" value={item.stats.checks} />
      </div>

      {item.last_error ? (
        <p
          className="mt-3 truncate rounded-lg border px-3 py-2 text-xs"
          title={item.last_error}
          style={{
            borderColor: 'rgba(245, 158, 11, 0.25)',
            background: 'rgba(245, 158, 11, 0.08)',
            color: 'var(--warning)',
          }}
        >
          {item.last_error}
        </p>
      ) : (
        running &&
        !item.thread_alive && (
          <p className="mt-3 text-xs" style={{ color: 'var(--warning)' }}>
            Wątek wstaje ponownie…
          </p>
        )
      )}

      <div className="mt-4 flex flex-wrap items-center gap-2 text-sm">
        {running ? (
          <button
            type="button"
            onClick={isolate(onStop)}
            disabled={busy}
            className="rounded-lg px-3.5 py-1.5 font-medium transition-opacity hover:opacity-85 disabled:opacity-45"
            style={{ background: 'var(--surface-raised)', border: '1px solid var(--border-strong)' }}
          >
            Zatrzymaj
          </button>
        ) : (
          <button
            type="button"
            onClick={isolate(onStart)}
            disabled={busy || startDisabled}
            title={startDisabled ? 'Osiągnięto limit aktywnych wątków' : undefined}
            className="rounded-lg px-3.5 py-1.5 font-medium text-white transition-opacity hover:opacity-85 disabled:opacity-45"
            style={{ background: 'var(--accent)' }}
          >
            Uruchom
          </button>
        )}

        <button
          type="button"
          onClick={isolate(onEdit)}
          disabled={busy}
          className="rounded-lg border px-3.5 py-1.5 transition-opacity hover:opacity-85 disabled:opacity-45"
          style={{ borderColor: 'var(--border-strong)' }}
        >
          Edytuj
        </button>

        <button
          type="button"
          onClick={isolate(onDelete)}
          disabled={busy}
          className="rounded-lg border px-3.5 py-1.5 transition-opacity hover:opacity-85 disabled:opacity-45"
          style={{ borderColor: 'rgba(239, 68, 68, 0.35)', color: 'var(--danger)' }}
        >
          Usuń
        </button>

        <span className="ml-auto text-xs" style={{ color: 'var(--muted)' }}>
          Statystyki →
        </span>
      </div>
    </article>
  )
}
