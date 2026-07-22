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

let state: ReplayState = { nowMs: 0, alive: 0, playing: false, speed: 1 }
let pending: ReplayState = state
const listeners = new Set<() => void>()
let timer: ReturnType<typeof setInterval> | null = null

export function publish(next: ReplayState): void {
  pending = next
}

export function subscribe(fn: () => void): () => void {
  listeners.add(fn)
  if (timer === null) {
    timer = setInterval(() => {
      // Only notify when something actually moved — a paused replay should
      // cost nothing.
      if (
        pending.nowMs === state.nowMs &&
        pending.alive === state.alive &&
        pending.playing === state.playing &&
        pending.speed === state.speed
      ) {
        return
      }
      state = { ...pending }
      for (const l of listeners) l()
    }, 100)
  }
  return () => {
    listeners.delete(fn)
    if (listeners.size === 0 && timer !== null) {
      clearInterval(timer)
      timer = null
    }
  }
}

export function getSnapshot(): ReplayState {
  return state
}

export function reset(): void {
  state = { nowMs: 0, alive: 0, playing: false, speed: 1 }
  pending = state
}
