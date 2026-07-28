import { describe, expect, it } from 'vitest'
import { interpolateAt, markerRadius, markersAt, trailPoints } from './markers'
import type { PosArrays } from './markers'
import { FLAG_ALIVE, FLAG_DBNO } from '../../lib/replayBundle'
import type { BundleEvent } from '../../lib/replayBundle'

/**
 * Build a CSR position block for `rows` players.
 *
 * Hand-built rather than decoded from a bundle on purpose: these tests are
 * about the arithmetic, and the corpus test in `lib/replayBundle.corpus.test.ts`
 * is what checks the arithmetic against real data.
 */
function pos(rows: number[][][], flags?: number[][]): PosArrays {
  const off = new Uint32Array(rows.length + 1)
  let n = 0
  for (let i = 0; i < rows.length; i++) {
    off[i] = n
    n += rows[i]!.length
  }
  off[rows.length] = n

  const t = new Uint16Array(n)
  const x = new Uint16Array(n)
  const y = new Uint16Array(n)
  const hp = new Uint8Array(n)
  const f = new Uint8Array(n)
  let k = 0
  for (let p = 0; p < rows.length; p++) {
    for (let i = 0; i < rows[p]!.length; i++) {
      const [tt, xx, yy] = rows[p]![i]!
      t[k] = tt!
      x[k] = xx!
      y[k] = yy!
      hp[k] = 100
      f[k] = flags?.[p]?.[i] ?? FLAG_ALIVE
      k++
    }
  }
  return { n, off, t, x, y, hp, flags: f }
}

describe('interpolateAt', () => {
  it('interpolates between samples', () => {
    const p = pos([[[0, 0, 0], [10, 100, 200]]])
    expect(interpolateAt(p, 0, 0)).toMatchObject({ x: 0, y: 0 })
    expect(interpolateAt(p, 0, 5)).toMatchObject({ x: 50, y: 100 })
    expect(interpolateAt(p, 0, 10)).toMatchObject({ x: 100, y: 200 })
  })

  it('holds the last sample after the end of the row', () => {
    const p = pos([[[0, 0, 0], [10, 100, 200]]])
    expect(interpolateAt(p, 0, 999)).toMatchObject({ x: 100, y: 200 })
  })

  it('is null before a player appears, and for an empty row', () => {
    const p = pos([[[50, 10, 10]], []])
    expect(interpolateAt(p, 0, 49)).toBeNull()
    expect(interpolateAt(p, 1, 100)).toBeNull()
  })

  it('reads the right CSR row for every player, not row 0', () => {
    // The bug HANDOFF §21 records: a zero-seeded cursor sits inside player 0's
    // row, so every player read player 0. A hundred dots stacked on one player
    // looks like a quiet map, not a broken one — so this is asserted directly.
    const p = pos([
      [[0, 10, 10]],
      [[0, 20, 20]],
      [[0, 30, 30]],
    ])
    expect(interpolateAt(p, 0, 0)!.x).toBe(10)
    expect(interpolateAt(p, 1, 0)!.x).toBe(20)
    expect(interpolateAt(p, 2, 0)!.x).toBe(30)
  })

  it('gives the same answer with any valid cursor hint', () => {
    const p = pos([[[0, 0, 0], [10, 100, 100], [20, 200, 200], [30, 300, 300]]])
    const truth = interpolateAt(p, 0, 25)
    for (const hint of [0, 1, 2]) {
      expect(interpolateAt(p, 0, 25, hint)).toEqual(truth)
    }
  })
})

describe('trailPoints', () => {
  it('ends at exactly the position the dot is drawn at', () => {
    // The two must agree by construction — a trail that ends somewhere other
    // than its own dot is the visible symptom of reading a different row, and
    // at a hundred trails it reads as a rendering style rather than a fault.
    const p = pos([[[0, 0, 0], [10, 100, 100], [20, 300, 50]]])
    for (const tick of [0, 3, 10, 14.5, 20, 40]) {
      const here = interpolateAt(p, 0, tick)
      const pts = trailPoints(p, 0, tick, 100)
      if (here === null) {
        expect(pts).toEqual([])
        continue
      }
      expect(pts.slice(-2)).toEqual([here.x, here.y])
    }
  })

  it('drops samples older than the window', () => {
    const p = pos([[[0, 0, 0], [10, 10, 10], [20, 20, 20], [30, 30, 30]]])
    // Window of 15 ticks at tick 30 keeps samples at t=20 and t=30.
    const pts = trailPoints(p, 0, 30, 15)
    expect(pts).toEqual([20, 20, 30, 30, 30, 30])
  })

  it('is empty for a player who has left the match', () => {
    // FLAG_ALIVE means "still in the match", knocked included (parser v5). A
    // corpse must not keep a trail across the rest of the game.
    const p = pos([[[0, 0, 0], [10, 100, 100]]], [[FLAG_ALIVE, 0]])
    expect(trailPoints(p, 0, 10, 100)).toEqual([])
  })

  it('keeps a trail for a knocked player', () => {
    const p = pos([[[0, 0, 0], [10, 100, 100]]], [[FLAG_ALIVE, FLAG_ALIVE | FLAG_DBNO]])
    expect(trailPoints(p, 0, 10, 100).length).toBeGreaterThan(0)
  })

  it('does not assume a fixed point count', () => {
    // Measured on a live bundle: inter-sample gaps are median 1.0 s, p90 10.0 s,
    // max 197.8 s. A player holding a building produces a handful of points
    // over the same window in which a sprinting one produces dozens.
    const sprinter = pos([Array.from({ length: 30 }, (_, i) => [i, i * 10, 0])])
    const camper = pos([[[0, 0, 0], [29, 5, 5]]])
    expect(trailPoints(sprinter, 0, 29, 30).length).toBeGreaterThan(
      trailPoints(camper, 0, 29, 30).length,
    )
  })
})

describe('markersAt', () => {
  const events: BundleEvent[] = [
    { t: 10, k: 'kill', v: 1, vx: 100, vy: 200 },
    { t: 20, k: 'cp', x: 300, y: 400, land: 50, rare: true },
    { t: 30, k: 'leave', p: 2, x: 500, y: 600 },
    { t: 90, k: 'kill', v: 3, vx: 700, vy: 800 },
  ]

  it('draws nothing at tick 0 — which is the whole bug', () => {
    // `drawEvents()` was called exactly once, from ReplayCanvas, at nowMs === 0.
    // This is what it saw. Nothing ever called it again, so kill crosses and
    // crates were invisible for the entire life of the replay.
    expect(markersAt(events, 0, 100)).toEqual({ kills: [], crates: [], vehicles: [] })
  })

  it('accumulates markers as the match runs', () => {
    expect(markersAt(events, 15, 100).kills).toHaveLength(1)
    expect(markersAt(events, 95, 100).kills).toHaveLength(2)
  })

  it('shows a crate as falling until it lands', () => {
    // Spawn and landing are ~30 s apart. Drawn from `t` alone, a crate appeared
    // on the map half a minute before it existed.
    expect(markersAt(events, 25, 100).crates[0]!.falling).toBe(true)
    expect(markersAt(events, 49, 100).crates[0]!.falling).toBe(true)
    expect(markersAt(events, 50, 100).crates[0]!.falling).toBe(false)
  })

  it('marks the red box, and defaults to ordinary on a pre-v12 bundle', () => {
    expect(markersAt(events, 60, 100).crates[0]!.rare).toBe(true)
  })

  it('treats a crate with no landing tick as landed rather than dropping it', () => {
    const old: BundleEvent[] = [{ t: 10, k: 'cp', x: 1, y: 2 }]
    expect(markersAt(old, 20, 100).crates).toEqual([{ x: 1, y: 2, falling: false, rare: false }])
  })

  it('fades an abandoned vehicle out and then stops drawing it', () => {
    expect(markersAt(events, 30, 100).vehicles[0]!.age).toBeCloseTo(1)
    expect(markersAt(events, 80, 100).vehicles[0]!.age).toBeCloseTo(0.5)
    expect(markersAt(events, 130, 100).vehicles).toHaveLength(0)
  })

  it('ignores event kinds it does not draw', () => {
    const noisy: BundleEvent[] = [
      { t: 1, k: 'knock', v: 0 },
      { t: 2, k: 'revive', v: 0 },
      { t: 3, k: 'phase', ph: 1 },
      { t: 4, k: 'ride', p: 0, x: 1, y: 1 },
    ]
    expect(markersAt(noisy, 100, 100)).toEqual({ kills: [], crates: [], vehicles: [] })
  })
})

describe('markerRadius', () => {
  it('renders the same on-screen size at every zoom', () => {
    // The reason the old kill cross was invisible even when it was drawn: ±4
    // *world* units at Erangel fit scale (~0.11) is 0.44 px, and "drawn
    // sub-pixel" is the same picture as "not drawn". Every marker in the
    // renderer lives inside the scaled world container, so this has to hold.
    for (const scale of [0.11, 0.5, 1, 2.4, 8]) {
      expect(markerRadius(5, scale) * scale).toBeCloseTo(5, 10)
    }
  })
})
