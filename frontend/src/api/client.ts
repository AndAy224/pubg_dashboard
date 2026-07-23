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
    if (Array.isArray(v)) {
      // A **repeated key** — `a=1&a=2` — which is what FastAPI reads back into
      // a list. `String(['a','b'])` is `"a,b"`, so the default path below would
      // send one parameter whose value happens to contain a comma, and the
      // server would look up an account id that cannot exist and answer with a
      // perfectly well-formed empty heatmap.
      for (const item of v) {
        if (item === undefined || item === null || item === '') continue
        sp.append(k, String(item))
      }
      continue
    }
    sp.set(k, String(v))
  }
  const s = sp.toString()
  return s ? `?${s}` : ''
}

/**
 * The server's own explanation of a failure, or the status line if it had none.
 *
 * FastAPI puts it in `detail`, and it is usually the only thing that says what
 * to do about the error — "no player named 'chocotaco'; names are
 * CASE-SENSITIVE" versus the bare words "Not Found".
 */
async function errorFrom(r: Response): Promise<ApiError> {
  let detail = r.statusText
  try {
    detail = (await r.json()).detail ?? detail
  } catch {
    /* the body was not JSON; the status line is all we have */
  }
  return new ApiError(r.status, detail)
}

export async function get<T>(path: string, params?: Record<string, unknown>): Promise<T> {
  const r = await fetch(`${BASE}${path}${qs(params)}`)
  if (!r.ok) throw await errorFrom(r)
  return (await r.json()) as T
}

export async function post<T>(path: string, params?: Record<string, unknown>): Promise<T> {
  const r = await fetch(`${BASE}${path}${qs(params)}`, { method: 'POST' })
  // Shares `errorFrom` with `get` deliberately. This used to throw
  // `r.statusText` and discard the body, so every mutation failure reached the
  // user as "Not Found" or "Bad Request" — the two words least likely to be the
  // reason.
  if (!r.ok) throw await errorFrom(r)
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
