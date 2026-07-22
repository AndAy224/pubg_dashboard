const BASE = import.meta.env.VITE_API_BASE_URL ?? '/api'

export class ApiError extends Error {
  // Explicit fields rather than constructor parameter properties:
  // `erasableSyntaxOnly` forbids the shorthand, because it cannot be removed
  // by a type-stripping runtime.
  readonly status: number
  readonly detail: string

  constructor(status: number, detail: string) {
    super(`${status}: ${detail}`)
    this.status = status
    this.detail = detail
  }
}

function qs(params?: Record<string, unknown>): string {
  if (!params) return ''
  const sp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue
    sp.set(k, String(v))
  }
  const s = sp.toString()
  return s ? `?${s}` : ''
}

export async function get<T>(path: string, params?: Record<string, unknown>): Promise<T> {
  const r = await fetch(`${BASE}${path}${qs(params)}`)
  if (!r.ok) {
    let detail = r.statusText
    try {
      detail = (await r.json()).detail ?? detail
    } catch {
      /* the body was not JSON; the status line is all we have */
    }
    throw new ApiError(r.status, detail)
  }
  return (await r.json()) as T
}

export async function post<T>(path: string, params?: Record<string, unknown>): Promise<T> {
  const r = await fetch(`${BASE}${path}${qs(params)}`, { method: 'POST' })
  if (!r.ok) throw new ApiError(r.status, r.statusText)
  return (await r.json()) as T
}

/**
 * Fetch the replay bundle as raw bytes.
 *
 * `fetch` transparently decodes `Content-Encoding: gzip`, so what lands here
 * is already MessagePack — the same as a browser does for any gzipped
 * response. Do not try to gunzip it again.
 */
export async function getBytes(path: string): Promise<ArrayBuffer> {
  const r = await fetch(`${BASE}${path}`)
  if (!r.ok) throw new ApiError(r.status, r.statusText)
  return await r.arrayBuffer()
}

export const apiBase = BASE
