type Props = {
  size?: number
  className?: string
}

/** VA mark on a dark plate — wrapper clips corners so no white fringe. */
export default function BrandLogo({ size = 32, className = '' }: Props) {
  const pad = Math.round(size * 0.1)

  return (
    <span
      className={`inline-flex shrink-0 overflow-hidden rounded-lg ${className}`.trim()}
      style={{ width: size, height: size, background: 'var(--bg)' }}
      aria-hidden
    >
      <img
        src="/logo-mark.png"
        alt=""
        width={size}
        height={size}
        className="block h-full w-full object-contain"
        style={{ padding: pad }}
        draggable={false}
      />
    </span>
  )
}
