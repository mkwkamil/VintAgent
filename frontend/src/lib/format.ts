const RELATIVE_STEPS: [limit: number, divisor: number, unit: Intl.RelativeTimeFormatUnit][] = [
  [60, 1, 'second'],
  [3600, 60, 'minute'],
  [86400, 3600, 'hour'],
  [Infinity, 86400, 'day'],
]

const relativeFormatter = new Intl.RelativeTimeFormat('pl-PL', { numeric: 'auto' })

export function formatRelative(value: string | null | undefined): string {
  if (!value) return 'nigdy'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value

  const seconds = (date.getTime() - Date.now()) / 1000
  const magnitude = Math.abs(seconds)
  if (magnitude < 5) return 'przed chwilą'

  const [, divisor, unit] = RELATIVE_STEPS.find(([limit]) => magnitude < limit)!
  return relativeFormatter.format(Math.round(seconds / divisor), unit)
}

const numberFormatter = new Intl.NumberFormat('pl-PL', { maximumFractionDigits: 2 })

export function formatNumber(value: number): string {
  return numberFormatter.format(value)
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('pl-PL', { dateStyle: 'short', timeStyle: 'short' })
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return '—'
  if (seconds <= 0) return 'wygasł'
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`
  const hours = seconds / 3600
  if (hours < 48) return `${hours.toFixed(hours < 10 ? 1 : 0)} h`
  return `${Math.round(hours / 24)} dni`
}
