import type { TrackedUrl } from '../api/client'
import StatusBadge from './StatusBadge'

type Props = {
  item: TrackedUrl
  busy: boolean
  startDisabled: boolean
  onStart: () => void
  onStop: () => void
  onEdit: () => void
  onDelete: () => void
}

function formatTime(value: string | null): string {
  if (!value) return 'nigdy'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('pl-PL', { dateStyle: 'short', timeStyle: 'medium' })
}

export default function UrlCard({ item, busy, startDisabled, onStart, onStop, onEdit, onDelete }: Props) {
  const running = item.status === 'running'

  return (
    <article
      className="overflow-hidden rounded-2xl border p-4 transition-colors sm:p-5"
      style={{ borderColor: 'var(--border)', background: 'var(--surface)' }}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-base font-semibold">{item.name}</h3>
          <a
            href={item.url}
            target="_blank"
            rel="noreferrer"
            title={item.url}
            className="mt-1 block max-w-full truncate text-xs hover:underline"
            style={{ color: 'var(--muted)' }}
          >
            {item.url}
          </a>
        </div>
        <StatusBadge status={item.status} hasError={Boolean(item.last_error)} />
      </div>

      <dl className="mt-4 flex flex-wrap gap-x-6 gap-y-1 text-xs" style={{ color: 'var(--muted)' }}>
        <div className="flex gap-1.5">
          <dt>Ostatnie sprawdzenie:</dt>
          <dd style={{ color: 'var(--muted-light)' }}>{formatTime(item.last_checked_at)}</dd>
        </div>
        {running && !item.thread_alive && (
          <div style={{ color: 'var(--warning)' }}>Wątek wstaje ponownie…</div>
        )}
      </dl>

      {item.last_error && (
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
      )}

      <div className="mt-4 flex flex-wrap gap-2 text-sm">
        {running ? (
          <button
            type="button"
            onClick={onStop}
            disabled={busy}
            className="rounded-lg px-3.5 py-1.5 font-medium transition-opacity hover:opacity-85 disabled:opacity-45"
            style={{ background: 'var(--surface-raised)', border: '1px solid var(--border-strong)' }}
          >
            Stop
          </button>
        ) : (
          <button
            type="button"
            onClick={onStart}
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
          onClick={onEdit}
          disabled={busy}
          className="rounded-lg border px-3.5 py-1.5 transition-opacity hover:opacity-85 disabled:opacity-45"
          style={{ borderColor: 'var(--border-strong)' }}
        >
          Edytuj
        </button>

        <button
          type="button"
          onClick={onDelete}
          disabled={busy}
          className="ml-auto rounded-lg border px-3.5 py-1.5 transition-opacity hover:opacity-85 disabled:opacity-45"
          style={{ borderColor: 'rgba(239, 68, 68, 0.35)', color: 'var(--danger)' }}
        >
          Usuń
        </button>
      </div>
    </article>
  )
}
