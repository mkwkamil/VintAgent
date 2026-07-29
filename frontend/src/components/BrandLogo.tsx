type Props = {
  size?: number
  className?: string
}

/** Brand mark from /logo.png — square VA glyph on black. */
export default function BrandLogo({ size = 32, className = '' }: Props) {
  return (
    <img
      src="/logo.png"
      alt="VintAgent"
      width={size}
      height={size}
      className={`shrink-0 rounded-lg object-cover ${className}`.trim()}
      draggable={false}
    />
  )
}
