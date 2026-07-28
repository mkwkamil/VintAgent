type Props = {
  status: 'running' | 'stopped'
  hasError: boolean
}

export default function StatusBadge({ status, hasError }: Props) {
  const running = status === 'running'
  const color = !running ? 'var(--muted)' : hasError ? 'var(--warning)' : 'var(--success)'
  const label = !running ? 'Zatrzymany' : hasError ? 'Ponawia' : 'Aktywny'

  return (
    <span
      className="inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-1 text-xs font-medium"
      style={{ borderColor: 'var(--border)', background: 'var(--surface-raised)', color }}
    >
      <span
        className={`size-1.5 rounded-full ${running ? 'animate-pulse-dot' : ''}`}
        style={{ background: color }}
      />
      {label}
    </span>
  )
}
