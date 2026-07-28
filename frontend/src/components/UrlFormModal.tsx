import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import type { TrackedUrl } from '../api/client'

type Props = {
  item: TrackedUrl | null
  onClose: () => void
  onSubmit: (name: string, url: string) => Promise<void>
}

export default function UrlFormModal({ item, onClose, onSubmit }: Props) {
  const [name, setName] = useState(item?.name ?? '')
  const [url, setUrl] = useState(item?.url ?? '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setSaving(true)
    setError(null)
    try {
      await onSubmit(name.trim(), url.trim())
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Nie udało się zapisać')
    } finally {
      setSaving(false)
    }
  }

  const fieldStyle = {
    borderColor: 'var(--border-strong)',
    background: 'var(--surface)',
    color: 'var(--ink)',
  }

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-end justify-center p-4 sm:items-center">
      <button
        type="button"
        aria-label="Zamknij"
        onClick={onClose}
        className="absolute inset-0 cursor-default"
        style={{ background: 'var(--overlay)', backdropFilter: 'blur(2px)' }}
      />
      <form
        onSubmit={submit}
        className="relative z-10 w-full max-w-md rounded-2xl border p-5 shadow-2xl"
        style={{ borderColor: 'var(--border-strong)', background: 'var(--surface-raised)' }}
      >
        <h2 className="text-lg font-semibold">{item ? 'Edytuj URL' : 'Nowy URL'}</h2>
        <p className="mt-1 text-xs" style={{ color: 'var(--muted)' }}>
          Wklej link z wyszukiwarki Vinted. Zmiana adresu resetuje historię ogłoszeń.
        </p>

        <label className="mt-4 block text-xs font-medium uppercase tracking-wide" style={{ color: 'var(--muted)' }}>
          Nazwa
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            required
            maxLength={80}
            placeholder="np. Nike rozmiar 42"
            className="mt-1.5 w-full rounded-lg border px-3 py-2 text-sm font-normal normal-case tracking-normal outline-none focus:border-[color:var(--accent)]"
            style={fieldStyle}
          />
        </label>

        <label className="mt-3 block text-xs font-medium uppercase tracking-wide" style={{ color: 'var(--muted)' }}>
          URL Vinted
          <input
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            required
            placeholder="https://www.vinted.pl/catalog?search_text=..."
            className="mt-1.5 w-full rounded-lg border px-3 py-2 text-sm font-normal normal-case tracking-normal outline-none focus:border-[color:var(--accent)]"
            style={fieldStyle}
          />
        </label>

        {error && (
          <p className="mt-3 text-sm" style={{ color: 'var(--danger)' }}>
            {error}
          </p>
        )}

        <div className="mt-5 flex justify-end gap-2 text-sm">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border px-4 py-2 transition-opacity hover:opacity-85"
            style={{ borderColor: 'var(--border-strong)' }}
          >
            Anuluj
          </button>
          <button
            type="submit"
            disabled={saving}
            className="rounded-lg px-4 py-2 font-medium text-white transition-opacity hover:opacity-85 disabled:opacity-45"
            style={{ background: 'var(--accent)' }}
          >
            {saving ? 'Zapisuję…' : 'Zapisz'}
          </button>
        </div>
      </form>
    </div>,
    document.body,
  )
}
