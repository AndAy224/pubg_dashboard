import { describe, expect, it } from 'vitest'
import type { DropRow, Gazetteer } from '../api/types'
import {
  LABEL_RADIUS_M,
  SNAP_CM,
  bearing,
  clusterDrops,
  labelCluster,
  summariseCluster,
} from './drops'

let seq = 0
function drop(over: Partial<DropRow> = {}): DropRow {
  seq += 1
  return {
    matchId: `m${seq}`,
    playedAt: '2026-07-28T19:22:53Z',
    mapName: 'Baltic_Main',
    gameMode: 'squad-fpp',
    teamId: 1,
    x: 0,
    y: 0,
    spreadCm: 1000,
    landedAtS: 60,
    winPlace: 20,
    kills: 1,
    timeSurvived: 600,
    contested: 0,
    firstWeaponS: 8,
    names: ['AndAy'],
    ...over,
  }
}

/** A gazetteer on the real Erangel geometry, with two towns far apart. */
function gazetteer(over: Partial<Gazetteer> = {}): Gazetteer {
  return {
    mapName: 'Baltic_Main',
    grid: 256,
    worldSize: 816_000,
    // 816000 cm / 256 = 3187.5 cm per cell = 31.875 m.
    // Cell 113,126 centre ~= (3618, 4036) m — Pochinki.
    cells: [
      { gx: 113, gy: 126, name: 'pochinki', support: 900 },
      { gx: 56, gy: 82, name: 'georgopol', support: 800 },
    ],
    matches: 61,
    samples: 1_325_503,
    modalPurity: 0.9847,
    ...over,
  }
}

describe('clusterDrops', () => {
  it('is order-independent', () => {
    // The whole reason this is grid-snap rather than greedy-nearest: the API
    // returns newest-first, so one new match must not re-partition the page.
    const rows = [
      drop({ x: 100_000, y: 100_000 }),
      drop({ x: 105_000, y: 103_000 }),
      drop({ x: 500_000, y: 500_000 }),
      drop({ x: 118_000, y: 112_000 }),
    ]
    const forward = clusterDrops(rows).map((c) => c.drops.length)
    const reversed = clusterDrops([...rows].reverse()).map((c) => c.drops.length)
    const shuffled = clusterDrops([rows[2]!, rows[0]!, rows[3]!, rows[1]!]).map(
      (c) => c.drops.length,
    )
    expect(forward).toEqual(reversed)
    expect(forward).toEqual(shuffled)
  })

  it('assigns every drop to exactly one cluster', () => {
    const rows = Array.from({ length: 40 }, (_, i) =>
      drop({ x: (i % 7) * 90_000, y: Math.floor(i / 7) * 90_000 }),
    )
    const clusters = clusterDrops(rows)
    const total = clusters.reduce((s, c) => s + c.drops.length, 0)
    expect(total).toBe(rows.length)
    const ids = new Set(clusters.flatMap((c) => c.drops.map((d) => d.matchId)))
    expect(ids.size).toBe(rows.length)
  })

  it('merges a spot that straddles a grid line', () => {
    // The bug this exists to prevent: Sosnovka came out as two clusters,
    // n=19 averaging place 25.7 and n=6 averaging 11.8, because a grid line
    // ran through it. Two points either side of a boundary are one spot.
    const left = drop({ x: SNAP_CM - 100, y: 5_000 })
    const right = drop({ x: SNAP_CM + 100, y: 5_000 })
    expect(clusterDrops([left, right])).toHaveLength(1)
  })

  it('merges diagonally adjacent cells too', () => {
    const a = drop({ x: SNAP_CM - 100, y: SNAP_CM - 100 })
    const b = drop({ x: SNAP_CM + 100, y: SNAP_CM + 100 })
    expect(clusterDrops([a, b])).toHaveLength(1)
  })

  it('keeps genuinely distant drops apart', () => {
    const a = drop({ x: 100_000, y: 100_000 })
    const b = drop({ x: 600_000, y: 600_000 })
    expect(clusterDrops([a, b])).toHaveLength(2)
  })

  it('sorts biggest first with a stable tiebreak', () => {
    const clusters = clusterDrops([
      drop({ x: 600_000, y: 600_000 }),
      drop({ x: 100_000, y: 100_000 }),
      drop({ x: 101_000, y: 101_000 }),
    ])
    expect(clusters[0]!.drops).toHaveLength(2)
    expect(clusters.map((c) => c.id)).toEqual(
      clusterDrops([
        drop({ x: 100_000, y: 100_000 }),
        drop({ x: 101_000, y: 101_000 }),
        drop({ x: 600_000, y: 600_000 }),
      ])
        .map((c) => c.id)
        .slice(0, clusters.length),
    )
  })

  it('returns nothing for no drops', () => {
    expect(clusterDrops([])).toEqual([])
  })

  it('puts the centroid inside the cluster', () => {
    const [cluster] = clusterDrops([
      drop({ x: 100_000, y: 100_000 }),
      drop({ x: 120_000, y: 120_000 }),
    ])
    expect(cluster!.x).toBe(110_000)
    expect(cluster!.y).toBe(110_000)
  })
})

describe('bearing', () => {
  it('treats larger y as South, because y grows downward', () => {
    // Origin top-left, canvas handedness. Reading this as a maths plane would
    // mirror every bearing north/south and nothing else would look wrong.
    expect(bearing(0, 0, 0, 100)).toBe('S')
    expect(bearing(0, 100, 0, 0)).toBe('N')
  })

  it('gets the cardinal and intercardinal directions right', () => {
    expect(bearing(0, 0, 100, 0)).toBe('E')
    expect(bearing(0, 0, -100, 0)).toBe('W')
    expect(bearing(0, 0, 100, -100)).toBe('NE')
    expect(bearing(0, 0, -100, 100)).toBe('SW')
    expect(bearing(0, 0, 100, 100)).toBe('SE')
    expect(bearing(0, 0, -100, -100)).toBe('NW')
  })
})

describe('labelCluster', () => {
  const POCHINKI_CM = { x: 361_800, y: 403_600 }

  it('names a cluster sitting on a named cell', () => {
    const label = labelCluster(POCHINKI_CM, gazetteer())
    expect(label.kind).toBe('named')
    expect(label.name).toBe('pochinki')
  })

  it('reports open country as unnamed, with a usable reference', () => {
    // Most of Erangel is fields — ~9% of the grid is named — so this is the
    // normal case, not an error. Returning the nearest town as if it were the
    // place would relabel a field as a town.
    const label = labelCluster({ x: 10_000, y: 10_000 }, gazetteer())
    expect(label.kind).toBe('unnamed')
    expect(label.name).toBeNull()
    expect(label.nearest).not.toBeNull()
    expect(label.nearestDistanceM).toBeGreaterThan(LABEL_RADIUS_M)
    expect(label.bearing).not.toBeNull()
  })

  it('distinguishes "no gazetteer" from "no name nearby"', () => {
    // A missing artifact and open country are different problems: one is fixed
    // by running a script, the other is just how the map is.
    expect(labelCluster(POCHINKI_CM, null).kind).toBe('unknown')
    expect(labelCluster(POCHINKI_CM, gazetteer({ cells: [] })).kind).toBe('unknown')
    expect(labelCluster({ x: 10_000, y: 10_000 }, gazetteer()).kind).toBe('unnamed')
  })

  it('honours a widened radius', () => {
    const far = labelCluster({ x: 10_000, y: 10_000 }, gazetteer(), 1_000_000)
    expect(far.kind).toBe('named')
  })

  it('picks the nearer of two towns', () => {
    const nearGeorgopol = { x: 180_600, y: 262_900 }
    expect(labelCluster(nearGeorgopol, gazetteer()).name).toBe('georgopol')
  })

  it('resolves a tie deterministically rather than by array order', () => {
    const cells = [
      { gx: 100, gy: 100, name: 'alpha', support: 10 },
      { gx: 102, gy: 100, name: 'beta', support: 999 },
    ]
    const midpoint = { x: 101 * 3187.5 + 1593.75, y: 100 * 3187.5 + 1593.75 }
    const a = labelCluster(midpoint, gazetteer({ cells }))
    const b = labelCluster(midpoint, gazetteer({ cells: [...cells].reverse() }))
    expect(a.name).toBe(b.name)
  })
})

describe('summariseCluster', () => {
  const cluster = (drops: DropRow[]) => ({ id: 'c', x: 0, y: 0, drops })

  it('uses a median placement, not a mean', () => {
    // One 90th-place match should not drag the spot's record with it.
    const s = summariseCluster(
      cluster([
        drop({ winPlace: 5 }),
        drop({ winPlace: 6 }),
        drop({ winPlace: 7 }),
        drop({ winPlace: 90 }),
      ]),
    )
    expect(s.medianPlace).toBe(6)
    expect(s.bestPlace).toBe(5)
  })

  it('counts measurable rows per metric, not cluster size', () => {
    // A match parsed before v7 has no strategy row at all, so `contested` and
    // `firstWeaponS` are null. Reporting the cluster size as the n for those
    // would overstate both.
    const s = summariseCluster(
      cluster([
        drop({ contested: 3, firstWeaponS: 5 }),
        drop({ contested: null, firstWeaponS: null }),
        drop({ contested: 0, firstWeaponS: 11 }),
      ]),
    )
    expect(s.n).toBe(3)
    expect(s.contestedN).toBe(2)
    expect(s.firstWeaponN).toBe(2)
    expect(s.contestedRate).toBe(0.5)
  })

  it('returns null rather than 0 when nothing is measurable', () => {
    const s = summariseCluster(
      cluster([drop({ contested: null, firstWeaponS: null })]),
    )
    expect(s.contestedRate).toBeNull()
    expect(s.medianFirstWeaponS).toBeNull()
    expect(s.contestedN).toBe(0)
  })

  it('counts split drops', () => {
    const s = summariseCluster(
      cluster([drop({ spreadCm: 1_000 }), drop({ spreadCm: 90_000 })]),
    )
    expect(s.splitDrops).toBe(1)
  })

  it('averages kills and survival across the cluster', () => {
    const s = summariseCluster(
      cluster([
        drop({ kills: 2, timeSurvived: 100 }),
        drop({ kills: 4, timeSurvived: 300 }),
      ]),
    )
    expect(s.killsPerDrop).toBe(3)
    expect(s.meanSurvivalS).toBe(200)
  })

  it('survives a placement of 0, which means unplaced rather than first', () => {
    const s = summariseCluster(cluster([drop({ winPlace: 0 }), drop({ winPlace: 12 })]))
    expect(s.places).toEqual([12])
    expect(s.bestPlace).toBe(12)
  })
})
