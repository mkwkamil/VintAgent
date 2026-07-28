import { useState } from 'react'

type Props = {
  onClose: () => void
  onSubmit: (cookie: string) => Promise<void>
}

export default function SessionImportModal({ onClose, onSubmit }: Props) {
  const [cookie, setCookie] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!cookie.trim()) {
      setError('Wklej nagłówek Cookie z przeglądarki')
      return
    }
    setSaving(true)
    setError(null)
    try {
      await onSubmit(cookie.trim())
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Import nie powiódł się')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-40 grid place-items-center p-4"
      style={{ background: 'var(--overlay)' }}
      onClick={onClose}
    >
      <form
        onClick={(event) => event.stopPropagation()}
        onSubmit={(event) => void submit(event)}
        className="w-full max-w-lg rounded-2xl border p-5 shadow-xl"
        style={{ borderColor: 'var(--border)', background: 'var(--surface)' }}
      >
        <h2 className="text-lg font-semibold">Wklej sesję Vinted</h2>
        <p className="mt-1 text-sm" style={{ color: 'var(--muted)' }}>
          Na IP datacenter (GCP) Cloudflare często nie wydaje tokenu headlessowi. Skopiuj Cookie z
          lokalnej przeglądarki (DevTools → Network → dowolne zapytanie do vinted.pl → Request
          Headers → Cookie) albo przenieś plik <code>session.json</code>.
        </p>

        <textarea
          value={cookie}
          onChange={(event) => setCookie(event.target.value)}
          rows={6}
          placeholder="access_token_web=...; refresh_token_web=...; anon_id=..."
          className="mt-4 w-full resize-y rounded-xl border px-3 py-2 font-mono text-xs outline-none"
          style={{ borderColor: 'var(--border-strong)', background: 'var(--bg)', color: 'var(--ink)' }}
          autoFocus
        />

        {error && (
          <p className="mt-3 text-sm" style={{ color: 'var(--danger)' }}>
            {error}
          </p>
        )}

        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border px-3.5 py-1.5 text-sm"
            style={{ borderColor: 'var(--border-strong)' }}
          >
            Anuluj
          </button>
          <button
            type="submit"
            disabled={saving}
            className="rounded-lg px-3.5 py-1.5 text-sm font-medium text-white disabled:opacity-45"
            style={{ background: 'var(--accent)' }}
          >
            {saving ? 'Zapisuję…' : 'Zapisz sesję'}
          </button>
        </div>
      </form>
    </div>
  )
}
