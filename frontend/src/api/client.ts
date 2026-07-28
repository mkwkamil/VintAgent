const TOKEN_KEY = 'vintagent_token'

export type StatsSummary = {
  found_total: number
  found_last_hour: number
  found_last_24h: number
  checks: number
  errors: number
  error_rate: number
  found_per_hour: number
  last_found_at: string | null
}

export type TrackedUrl = {
  id: string
  name: string
  url: string
  status: 'running' | 'stopped'
  created_at: string
  last_checked_at: string | null
  last_error: string | null
  thread_alive: boolean
  stats: StatsSummary
}

export type UrlStats = {
  summary: StatsSummary
  found_timeline: { hour: string; count: number }[]
  listed_by_hour_of_day: number[]
  found_by_hour_of_day: number[]
  timeline_hours: number
}

export type SessionStatus = {
  has_session: boolean
  cookie_count: number
  access_expires_at: string | null
  access_expires_in_seconds: number | null
  refresh_expires_at: string | null
  updated_at: string | null
  browser_available: boolean
  last_bootstrap_at: string | null
  last_bootstrap_error: string | null
}

export type Stats = {
  active_threads: number
  max_threads: number
  telegram_enabled: boolean
}

let onUnauthorized: (() => void) | null = null

export function setUnauthorizedHandler(handler: (() => void) | null) {
  onUnauthorized = handler
}

export function getToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string | null) {
  if (token) sessionStorage.setItem(TOKEN_KEY, token)
  else sessionStorage.removeItem(TOKEN_KEY)
}

async function readError(response: Response): Promise<string> {
  try {
    const body = await response.json()
    const detail = body?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail) && detail[0]?.msg) return String(detail[0].msg)
  } catch {
    /* fall through to the generic message */
  }
  return `Błąd serwera (HTTP ${response.status})`
}

async function request<T>(path: string, init: RequestInit & { auth?: boolean } = {}): Promise<T> {
  const { auth = true, ...rest } = init
  const headers = new Headers(rest.headers)
  if (rest.body) headers.set('Content-Type', 'application/json')

  if (auth) {
    const token = getToken()
    if (!token) {
      onUnauthorized?.()
      throw new Error('Wymagane logowanie')
    }
    headers.set('Authorization', `Bearer ${token}`)
  }

  const response = await fetch(path, { ...rest, headers })

  if (response.status === 401) {
    if (auth) {
      setToken(null)
      onUnauthorized?.()
    }
    throw new Error(await readError(response))
  }
  if (!response.ok) throw new Error(await readError(response))
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export const api = {
  login: (username: string, password: string) =>
    request<{ access_token: string; username: string }>('/api/auth/login', {
      auth: false,
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),

  me: () => request<{ username: string }>('/api/auth/me'),

  stats: () => request<Stats>('/api/stats'),

  session: () => request<SessionStatus>('/api/session'),

  refreshSession: () => request<SessionStatus>('/api/session/refresh', { method: 'POST' }),

  importSession: (cookie: string) =>
    request<SessionStatus>('/api/session/import', {
      method: 'POST',
      body: JSON.stringify({ cookie }),
    }),

  testTelegram: () => request<{ detail: string }>('/api/telegram/test', { method: 'POST' }),

  listUrls: () => request<TrackedUrl[]>('/api/urls'),

  getUrl: (id: string) => request<TrackedUrl>(`/api/urls/${id}`),

  urlStats: (id: string, hours: number) => {
    // The backend keeps buckets in UTC; send the browser offset so the
    // hour-of-day chart is drawn in the user's local time.
    const offset = -new Date().getTimezoneOffset()
    return request<UrlStats>(`/api/urls/${id}/stats?hours=${hours}&tz_offset_minutes=${offset}`)
  },

  resetUrlStats: (id: string) => request<{ detail: string }>(`/api/urls/${id}/stats/reset`, { method: 'POST' }),

  createUrl: (name: string, url: string) =>
    request<TrackedUrl>('/api/urls', { method: 'POST', body: JSON.stringify({ name, url }) }),

  updateUrl: (id: string, payload: { name?: string; url?: string }) =>
    request<TrackedUrl>(`/api/urls/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),

  deleteUrl: (id: string) => request<void>(`/api/urls/${id}`, { method: 'DELETE' }),

  startUrl: (id: string) => request<TrackedUrl>(`/api/urls/${id}/start`, { method: 'POST' }),

  stopUrl: (id: string) => request<TrackedUrl>(`/api/urls/${id}/stop`, { method: 'POST' }),
}
