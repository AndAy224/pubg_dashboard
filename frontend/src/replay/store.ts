/**
 * External store bridging the 60 Hz renderer to the DOM panels.
 *
 * The renderer writes on every frame; listeners are notified on a 100 ms
 * interval instead. React re-rendering a kill feed sixty times a second is
 * exactly the thing this architecture exists to avoid.
 */
export interface ReplayState {
  nowMs: number
  alive: number
  playing: boolean
  speed: number
}

/** `status[p]` — where player `p` stands right now. */
export const OUT = 0
export const ALIVE = 1
export const KNOCKED = 2

/**
 * Per-player health, kept apart from `ReplayState` on purpose.
 *
 * The main store notifies ten times a second because `nowMs` always moves, and
 * the team list is up to a hundred rows — re-rendering all of them at 10 Hz to
 * redraw bars that change every few seconds is exactly the cost this
 * architecture exists to avoid. Health gets its own subscription, notified
 * only when a value actually changed.
 *
 * The arrays are written in place by the renderer and never reallocated, so
 * consumers must treat them as a live view and read them during render rather
 * than storing them.
 */
export interface HealthState {
  hp: Uint8Array
  status: Uint8Array
  /** Bumped whenever `hp` or `status` changed. The only safe equality test. */
  version: number
}

let state: ReplayState = { nowMs: 0, alive: 0, playing: false, speed: 1 }
let pending: ReplayState = state
const listeners = new Set<() => void>()
let timer: ReturnType<typeof setInterval> | null = null

let health: HealthState = { hp: new Uint8Array(0), status: new Uint8Array(0), version: 0 }
let healthPublished = -1
const healthListeners = new Set<() => void>()

export function publish(next: ReplayState): void {
  pending = next
}

/**
 * Hand the renderer's live health arrays to the store.
 *
 * `version` is the renderer's own change counter — it knows which values it
 * just wrote, and comparing two hundred bytes here every tick to rediscover
 * that would be pure waste.
 */
export function publishHealth(hp: Uint8Array, status: Uint8Array, version: number): void {
  // A **new object only when the version moved**. `publishHealth` is called
  // from the 60 Hz frame loop, and `useSyncExternalStore` re-reads the
  // snapshot during render and compares identity — handing back a fresh object
  // every frame trips React's "getSnapshot should be cached" infinite loop.
  if (health.version === version && health.hp === hp) return
  health = { hp, status, version }
}

export function subscribeHealth(fn: () => void): () => void {
  healthListeners.add(fn)
  ensureTimer()
  return () => {
    healthListeners.delete(fn)
    maybeStopTimer()
  }
}

export function getHealthSnapshot(): HealthState {
  return health
}

function ensureTimer(): void {
  if (timer !== null) return
  timer = setInterval(() => {
    // Only notify when something actually moved — a paused replay should
    // cost nothing.
    if (
      pending.nowMs !== state.nowMs ||
      pending.alive !== state.alive ||
      pending.playing !== state.playing ||
      pending.speed !== state.speed
    ) {
      state = { ...pending }
      for (const l of listeners) l()
    }
    // Independent of the clock: health changes every few seconds, not every
    // tick, so its listeners stay idle while the playhead runs.
    if (health.version !== healthPublished) {
      healthPublished = health.version
      for (const l of healthListeners) l()
    }
  }, 100)
}

function maybeStopTimer(): void {
  if (listeners.size === 0 && healthListeners.size === 0 && timer !== null) {
    clearInterval(timer)
    timer = null
  }
}

export function subscribe(fn: () => void): () => void {
  listeners.add(fn)
  ensureTimer()
  return () => {
    listeners.delete(fn)
    maybeStopTimer()
  }
}

export function getSnapshot(): ReplayState {
  return state
}

export function reset(): void {
  state = { nowMs: 0, alive: 0, playing: false, speed: 1 }
  pending = state
  health = { hp: new Uint8Array(0), status: new Uint8Array(0), version: 0 }
  healthPublished = -1
}
