/**
 * Grouping squad landings into drop spots, and naming them.
 *
 * Two rules do most of the work here, and both exist because the obvious
 * implementation is subtly wrong.
 *
 * **Clustering must be order-independent.** The natural version — walk the
 * points, attach each to the first cluster within a radius, otherwise start a
 * new one — gives a different answer depending on the order rows arrive in.
 * The API returns them newest-first, so adding one match tonight could
 * re-partition every cluster and silently change the numbers on the page.
 * Instead: snap to a fixed grid, merge adjacent occupied cells, and take the
 * centroid. The grid does not move, so the partition is a function of the
 * points alone.
 *
 * **Names come from PUBG, and "unnamed" is a real answer.** The gazetteer
 * covers ~9% of the map, because most of Erangel is fields. A cluster with no
 * named cell within range is rendered as "unnamed — 1.4 km NW of Gatka", never
 * as the nearest town, and never as a blank.
 */

import type { DropRow, Gazetteer, PlaceCell } from '../api/types'

/** Grid pitch for snapping, centimetres. 400 m: comfortably larger than a
 *  compound, comfortably smaller than the gap between two named towns. */
export const SNAP_CM = 40_000

/** How far from a cluster centroid a named cell may be and still name it.
 *  150 m — about five gazetteer cells on an 816 km map. */
export const LABEL_RADIUS_M = 150

export interface DropCluster {
  /** Stable identity: the snapped cell of the cluster's first seed, so a
   *  cluster keeps its React key as matches are added. */
  id: string
  x: number
  y: number
  drops: DropRow[]
}

export interface ClusterLabel {
  kind: 'named' | 'unnamed' | 'unknown'
  /** The place name when `kind` is 'named'. */
  name: string | null
  /** Nearest named place at any distance — the reference for the 'unnamed'
   *  rendering. Null when the map has no gazetteer at all ('unknown'). */
  nearest: string | null
  nearestDistanceM: number | null
  /** Compass bearing from the nearest place to the cluster, e.g. 'NW'. */
  bearing: string | null
}

export interface ClusterSummary {
  n: number
  places: number[]
  medianPlace: number
  bestPlace: number
  /** Mean survival in seconds across the cluster's drops. */
  meanSurvivalS: number
  killsPerDrop: number
  /** Share of drops with at least one enemy landing within 200 m. Null when no
   *  drop in the cluster has a measurable contested count. */
  contestedRate: number | null
  contestedN: number
  medianFirstWeaponS: number | null
  firstWeaponN: number
  /** Drops where the squad landed more than 200 m apart. */
  splitDrops: number
}

function cellKey(x: number, y: number): string {
  return `${Math.floor(x / SNAP_CM)},${Math.floor(y / SNAP_CM)}`
}

/**
 * Group drops into spots.
 *
 * Snap each drop to a `SNAP_CM` cell, then union cells that touch (including
 * diagonally) so a spot straddling a cell boundary does not come out as two.
 * That last part matters: the first measurement of this data reported Sosnovka
 * Military Base twice, as n=19 averaging place 25.7 and n=6 averaging 11.8,
 * purely because a grid line ran through it.
 *
 * Deterministic for a given set of drops, whatever order they arrive in.
 */
export function clusterDrops(rows: readonly DropRow[]): DropCluster[] {
  const byCell = new Map<string, DropRow[]>()
  for (const row of rows) {
    const key = cellKey(row.x, row.y)
    const bucket = byCell.get(key)
    if (bucket) bucket.push(row)
    else byCell.set(key, [row])
  }

  // Union-find over occupied cells, walking neighbours in a fixed order.
  const parent = new Map<string, string>()
  const find = (k: string): string => {
    let root = k
    while (parent.get(root) !== root) root = parent.get(root)!
    // Path compression, iteratively — these chains are short but the loop is
    // cheaper than recursion and cannot blow the stack on a pathological map.
    let cur = k
    while (parent.get(cur) !== root) {
      const next = parent.get(cur)!
      parent.set(cur, root)
      cur = next
    }
    return root
  }
  const union = (a: string, b: string) => {
    const ra = find(a)
    const rb = find(b)
    if (ra === rb) return
    // Smaller key becomes the root, so the result never depends on which cell
    // was visited first.
    if (ra < rb) parent.set(rb, ra)
    else parent.set(ra, rb)
  }

  const keys = [...byCell.keys()].sort()
  for (const key of keys) parent.set(key, key)
  for (const key of keys) {
    const [cx, cy] = key.split(',').map(Number) as [number, number]
    for (const dx of [-1, 0, 1]) {
      for (const dy of [-1, 0, 1]) {
        if (dx === 0 && dy === 0) continue
        const neighbour = `${cx + dx},${cy + dy}`
        if (byCell.has(neighbour)) union(key, neighbour)
      }
    }
  }

  const groups = new Map<string, DropRow[]>()
  for (const key of keys) {
    const root = find(key)
    const bucket = groups.get(root)
    if (bucket) bucket.push(...byCell.get(key)!)
    else groups.set(root, [...byCell.get(key)!])
  }

  const out: DropCluster[] = []
  for (const [id, drops] of groups) {
    const x = drops.reduce((s, d) => s + d.x, 0) / drops.length
    const y = drops.reduce((s, d) => s + d.y, 0) / drops.length
    out.push({ id, x, y, drops })
  }
  // Biggest first, then by id so equal-sized clusters have a stable order.
  return out.sort((a, b) => b.drops.length - a.drops.length || a.id.localeCompare(b.id))
}

const COMPASS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'] as const

/**
 * Compass direction from `(fromX, fromY)` to `(toX, toY)`.
 *
 * **`y` grows downward** — origin top-left, canvas handedness — so larger `y`
 * is South. Treating it as a maths plane would produce a page where every
 * bearing is mirrored north/south and nothing else would look wrong.
 */
export function bearing(fromX: number, fromY: number, toX: number, toY: number): string {
  const dx = toX - fromX
  const dy = toY - fromY
  // atan2(dx, -dy): 0 is North (negative y), increasing clockwise through East.
  const deg = (Math.atan2(dx, -dy) * 180) / Math.PI
  const index = Math.round(((deg + 360) % 360) / 45) % 8
  return COMPASS[index]!
}

/**
 * Name a cluster from the gazetteer.
 *
 * `kind` distinguishes three genuinely different states, and the UI must not
 * merge them: `named` (PUBG calls this place something), `unnamed` (this map
 * has names and none is near — open country), and `unknown` (no gazetteer
 * exists for this map at all). The last is a missing artifact, not a field.
 */
export function labelCluster(
  cluster: Pick<DropCluster, 'x' | 'y'>,
  gazetteer: Gazetteer | null | undefined,
  withinM = LABEL_RADIUS_M,
): ClusterLabel {
  if (!gazetteer || gazetteer.cells.length === 0) {
    return { kind: 'unknown', name: null, nearest: null, nearestDistanceM: null, bearing: null }
  }

  const cellM = gazetteer.worldSize / gazetteer.grid / 100
  const cx = cluster.x / 100
  const cy = cluster.y / 100

  let best: PlaceCell | null = null
  let bestD = Infinity
  for (const cell of gazetteer.cells) {
    // Cell centre in metres. Sub-cell precision would be invented — the
    // gazetteer's resolution is one cell.
    const px = (cell.gx + 0.5) * cellM
    const py = (cell.gy + 0.5) * cellM
    const d = Math.hypot(px - cx, py - cy)
    // Strict `<`, plus a support tiebreak, so ties resolve deterministically
    // rather than by array order.
    if (d < bestD || (d === bestD && best !== null && cell.support > best.support)) {
      bestD = d
      best = cell
    }
  }

  if (best === null) {
    return { kind: 'unknown', name: null, nearest: null, nearestDistanceM: null, bearing: null }
  }

  const px = (best.gx + 0.5) * cellM
  const py = (best.gy + 0.5) * cellM
  const dir = bearing(px, py, cx, cy)

  if (bestD <= withinM) {
    return {
      kind: 'named',
      name: best.name,
      nearest: best.name,
      nearestDistanceM: bestD,
      bearing: dir,
    }
  }
  return {
    kind: 'unnamed',
    name: null,
    nearest: best.name,
    nearestDistanceM: bestD,
    bearing: dir,
  }
}

/** Median of a non-empty numeric list. Even lengths take the lower middle, so
 *  a median placement is always a placement someone actually finished. */
function median(values: readonly number[]): number {
  const sorted = [...values].sort((a, b) => a - b)
  return sorted[Math.floor((sorted.length - 1) / 2)]!
}

/**
 * Summarise a cluster's record.
 *
 * Median placement rather than mean: placements are bounded and skewed, and one
 * match where the squad died 90th drags a mean far more than it should.
 *
 * Every "not measurable" count travels with its metric — `contestedN` and
 * `firstWeaponN` are the rows that actually had a value, which is not the
 * cluster size. A match parsed before v7 has no strategy row at all.
 */
export function summariseCluster(cluster: DropCluster): ClusterSummary {
  const drops = cluster.drops
  const places = drops.map((d) => d.winPlace).filter((p) => p > 0)
  const contested = drops.map((d) => d.contested).filter((c): c is number => c !== null)
  const firstWeapon = drops
    .map((d) => d.firstWeaponS)
    .filter((v): v is number => v !== null && Number.isFinite(v))

  return {
    n: drops.length,
    places,
    medianPlace: places.length ? median(places) : 0,
    bestPlace: places.length ? Math.min(...places) : 0,
    meanSurvivalS: drops.reduce((s, d) => s + d.timeSurvived, 0) / drops.length,
    killsPerDrop: drops.reduce((s, d) => s + d.kills, 0) / drops.length,
    contestedRate: contested.length
      ? contested.filter((c) => c > 0).length / contested.length
      : null,
    contestedN: contested.length,
    medianFirstWeaponS: firstWeapon.length ? median(firstWeapon) : null,
    firstWeaponN: firstWeapon.length,
    // 200 m apart is the same radius `hot_drop_n` calls "landing on top of
    // someone", so a squad spread wider than that did not share a drop.
    splitDrops: drops.filter((d) => d.spreadCm > 20_000).length,
  }
}
