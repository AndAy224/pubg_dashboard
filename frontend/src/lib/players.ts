import { useSyncExternalStore } from 'react'

/**
 * Identity colours for the tracked players.
 *
 * Assigned by sorted account id rather than by the order the API happens to
 * return, so a player's colour is stable across pages, across reloads, and
 * when a fourth player is added — a colour that shifts under you is worse
 * than no colour at all, because you have already learned to read it.
 */

const SLOTS = ['var(--p-1)', 'var(--p-2)', 'var(--p-3)', 'var(--p-4)'] as const

/** Hex equivalents of the CSS custom properties, for canvas and Pixi, which
 *  cannot resolve `var()`. Keep in step with `styles/tokens.css`. */
// Must stay parallel with --p-1..--p-4 in tokens.css — canvas and Pixi cannot
// resolve var(). Gold left this set deliberately: it now means winning, and
// nothing else. The trio is CVD-validated; see tokens.css for the derivation.
const SLOT_HEX = ['#1e9fd2', '#d84378', '#8a72e8', '#8f9a1f'] as const

let order: string[] = []
const listeners = new Set<() => void>()

/** Register the tracked roster. Idempotent; safe to call on every render. */
export function registerPlayers(accountIds: string[]): void {
  const next = [...new Set(accountIds)].sort()
  if (next.length !== order.length || next.some((a, i) => a !== order[i])) {
    order = next
    // Iterate a copy. A notified subscriber can detach another — React
    // unsubscribes on unmount, and this notification is what triggers the
    // re-render that unmounts things — and a live Set would skip whichever
    // listener that was if it had not been reached yet.
    // oxlint-disable-next-line no-useless-spread
    for (const notify of [...listeners]) notify()
  }
}

/**
 * Subscribe to the roster.
 *
 * `order` is module state that components read *during render* while every
 * `registerPlayers` call happens in an *effect* — which runs afterwards. So
 * the first render after the roster arrives read an empty `order`, got the
 * neutral fallback, and nothing ever told React to try again. The nav's three
 * player dots were grey permanently; every other surface got its colours only
 * because some unrelated re-render happened to come along later.
 *
 * That is exactly what `useSyncExternalStore` exists for. `getSnapshot`
 * returns the array itself, whose identity changes only when the roster
 * really changes, so subscribing cannot loop.
 */
export function subscribeToPlayers(notify: () => void): () => void {
  listeners.add(notify)
  return () => {
    listeners.delete(notify)
  }
}

export function getPlayerOrder(): string[] {
  return order
}

/** Re-render the caller whenever the tracked roster changes. */
export function useTrackedPlayers(): string[] {
  return useSyncExternalStore(subscribeToPlayers, getPlayerOrder, getPlayerOrder)
}

function slot(accountId: string): number {
  const i = order.indexOf(accountId)
  // An untracked account (an opponent) gets the neutral treatment rather than
  // borrowing a tracked player's colour.
  return i < 0 ? -1 : i % SLOTS.length
}

export function playerColour(accountId: string): string {
  const i = slot(accountId)
  return i < 0 ? 'var(--text-dim)' : SLOTS[i]!
}

export function playerColourHex(accountId: string): string {
  const i = slot(accountId)
  return i < 0 ? '#a4a28c' : SLOT_HEX[i]!
}

/** The same colour as a 0xRRGGBB number, for Pixi tints. */
export function playerColourInt(accountId: string): number {
  return Number.parseInt(playerColourHex(accountId).slice(1), 16)
}

export function isTracked(accountId: string): boolean {
  return order.includes(accountId)
}

/**
 * Placement grade, shared by every surface that renders a rank.
 *
 * `winPlace` has been observed above 100 (it ranks *participants*, not teams),
 * so nothing here assumes an upper bound.
 */
export type PlaceGrade = 'win' | 'top5' | 'top10' | 'rest'

export function placeGrade(place: number | null | undefined): PlaceGrade {
  if (place === 1) return 'win'
  if (place != null && place <= 5) return 'top5'
  if (place != null && place <= 10) return 'top10'
  return 'rest'
}
