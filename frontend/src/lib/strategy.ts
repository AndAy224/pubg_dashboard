/**
 * Best-vs-worst placement contrast — the analysis behind the Strategy page.
 *
 * Pure functions, deliberately: with a few dozen matches per player the
 * honest claim is "in your best matches this number looked like X, in your
 * worst like Y", and that arithmetic should be testable without a server.
 *
 * Nulls are "not measurable", never zero — a solo match has no teammate
 * distance, an early death has no rotation lag. They are excluded per side,
 * and the per-side `n` reports what actually went into each mean, because a
 * mean of 3 values presented like a mean of 10 is how small-sample analysis
 * lies without anyone typing a false number.
 */

export interface PlacedRow {
  winPlace: number
}

export interface ContrastSide {
  mean: number | null
  /** How many rows had a measurable value — NOT the group size. */
  n: number
}

export interface Contrast {
  best: ContrastSide
  worst: ContrastSide
  /** Rows per side before null-filtering (ties included). */
  groupSize: number
}

/**
 * Contrast a metric between the best-placed and worst-placed matches.
 *
 * Sides are `n` matches each (default 10), shrunk to half the data when there
 * is less of it, with **ties at the boundary included** — cutting a group at
 * "the first ten rows" when rows 9–12 all placed #14 would make the answer
 * depend on sort stability.
 */
export function contrastByPlacement<T extends PlacedRow>(
  rows: readonly T[],
  pick: (row: T) => number | null,
  n = 10,
): Contrast | null {
  if (rows.length < 4) return null
  const side = Math.min(n, Math.floor(rows.length / 2))
  const sorted = [...rows].sort((a, b) => a.winPlace - b.winPlace)

  const bestCut = sorted[side - 1]!.winPlace
  const best = sorted.filter((r) => r.winPlace <= bestCut)
  const worstCut = sorted[sorted.length - side]!.winPlace
  const worst = sorted.filter((r) => r.winPlace >= worstCut)

  return {
    best: meanOf(best, pick),
    worst: meanOf(worst, pick),
    groupSize: side,
  }
}

function meanOf<T>(rows: readonly T[], pick: (row: T) => number | null): ContrastSide {
  const values = rows.map(pick).filter((v): v is number => v !== null && Number.isFinite(v))
  if (values.length === 0) return { mean: null, n: 0 }
  return { mean: values.reduce((a, b) => a + b, 0) / values.length, n: values.length }
}

export interface WeaponTotals {
  weapon: string
  kills: number
  headshots: number
  longestM: number
  avgDistanceM: number
}

/**
 * Merge per-player weapon tables into one squad table.
 *
 * Kills and headshots sum; longest is a max; average range is weighted by
 * kills — an unweighted mean would let one Winchester kill at 7 m drag a
 * hundred M24 kills toward it.
 */
export function mergeWeapons(lists: readonly (readonly WeaponTotals[])[]): WeaponTotals[] {
  const byWeapon = new Map<string, WeaponTotals & { rangeKills: number }>()
  for (const list of lists) {
    for (const w of list) {
      const cur = byWeapon.get(w.weapon)
      if (cur === undefined) {
        byWeapon.set(w.weapon, { ...w, rangeKills: w.kills })
      } else {
        cur.avgDistanceM =
          cur.rangeKills + w.kills > 0
            ? (cur.avgDistanceM * cur.rangeKills + w.avgDistanceM * w.kills) /
              (cur.rangeKills + w.kills)
            : cur.avgDistanceM
        cur.rangeKills += w.kills
        cur.kills += w.kills
        cur.headshots += w.headshots
        cur.longestM = Math.max(cur.longestM, w.longestM)
      }
    }
  }
  return [...byWeapon.values()]
    .map(({ rangeKills: _unused, ...w }) => w)
    .sort((a, b) => b.kills - a.kills)
}
