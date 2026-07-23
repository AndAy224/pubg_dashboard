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
const SLOT_HEX = ['#f0b429', '#4cc9f0', '#b388ff', '#56d364'] as const

let order: string[] = []

/** Register the tracked roster. Idempotent; safe to call on every render. */
export function registerPlayers(accountIds: string[]): void {
  const next = [...new Set(accountIds)].sort()
  if (next.length !== order.length || next.some((a, i) => a !== order[i])) {
    order = next
  }
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
  return i < 0 ? '#97a3b4' : SLOT_HEX[i]!
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
