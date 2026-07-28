type Bar = {
  label: string
  value: number
  /** Longer description shown on hover. */
  title?: string
  highlight?: boolean
}

type Props = {
  bars: Bar[]
  /** Show every n-th label; keeps a 24-bar axis readable on narrow cards. */
  labelEvery?: number
  height?: number
  emptyText?: string
}

/**
 * Bar chart drawn as plain SVG. A charting library would add ~100 kB to a bundle
 * that only ever needs bars, and the container is memory-budgeted.
 */
export default function BarChart({ bars, labelEvery = 1, height = 160, emptyText }: Props) {
  const max = Math.max(...bars.map((bar) => bar.value), 1)
  const isEmpty = bars.every((bar) => bar.value === 0)

  return (
    <div className="relative">
      <div className="flex items-end gap-[3px]" style={{ height }}>
        {bars.map((bar, index) => {
          const ratio = bar.value / max
          return (
            <div key={`${bar.label}-${index}`} className="group flex h-full flex-1 flex-col justify-end">
              <div
                title={bar.title ?? `${bar.label}: ${bar.value}`}
                className="w-full rounded-t transition-all group-hover:opacity-80"
                style={{
                  // A hairline keeps empty buckets visible as a baseline.
                  height: `${Math.max(ratio * 100, bar.value > 0 ? 4 : 1.5)}%`,
                  background: bar.value === 0
                    ? 'var(--border-strong)'
                    : bar.highlight
                      ? 'var(--accent-soft)'
                      : 'var(--accent)',
                  opacity: bar.value === 0 ? 0.5 : bar.highlight ? 1 : 0.75,
                }}
              />
            </div>
          )
        })}
      </div>

      <div className="mt-2 flex gap-[3px] text-[10px]" style={{ color: 'var(--muted)' }}>
        {bars.map((bar, index) => (
          <span key={`label-${bar.label}-${index}`} className="flex-1 truncate text-center">
            {index % labelEvery === 0 ? bar.label : ''}
          </span>
        ))}
      </div>

      {isEmpty && emptyText && (
        <p
          className="pointer-events-none absolute inset-0 flex items-center justify-center text-xs"
          style={{ color: 'var(--muted)' }}
        >
          {emptyText}
        </p>
      )}
    </div>
  )
}
