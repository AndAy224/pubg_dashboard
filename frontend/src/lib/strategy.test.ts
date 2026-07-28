import { describe, expect, it } from 'vitest'
import { contrastByPlacement, mergeWeapons } from './strategy'

interface Row {
  winPlace: number
  metric: number | null
}

const row = (winPlace: number, metric: number | null): Row => ({ winPlace, metric })
const pick = (r: Row) => r.metric

describe('contrastByPlacement', () => {
  it('contrasts the best and worst sides', () => {
    const rows = [row(1, 10), row(2, 20), row(30, 100), row(40, 200)]
    const c = contrastByPlacement(rows, pick, 2)
    expect(c).not.toBeNull()
    expect(c!.best.mean).toBe(15)
    expect(c!.worst.mean).toBe(150)
    expect(c!.best.n).toBe(2)
  })

  it('includes ties at the boundary instead of cutting mid-placement', () => {
    // Three matches share the boundary placement #5; an arbitrary cut at
    // "two rows" would make the mean depend on sort stability.
    const rows = [row(1, 0), row(5, 10), row(5, 20), row(5, 30), row(50, 99), row(60, 99)]
    const c = contrastByPlacement(rows, pick, 2)
    expect(c!.best.n).toBe(4)
    expect(c!.best.mean).toBe(15)
  })

  it('excludes nulls per side and reports the real n', () => {
    const rows = [row(1, null), row(2, 8), row(30, null), row(40, null)]
    const c = contrastByPlacement(rows, pick, 2)
    expect(c!.best).toEqual({ mean: 8, n: 1 })
    // A side can be entirely unmeasurable; that is not a zero.
    expect(c!.worst).toEqual({ mean: null, n: 0 })
  })

  it('shrinks the sides rather than overlapping them on small archives', () => {
    const rows = [row(1, 1), row(2, 2), row(3, 3), row(10, 10), row(20, 20)]
    const c = contrastByPlacement(rows, pick, 10)
    expect(c!.groupSize).toBe(2)
    expect(c!.best.mean).toBe(1.5)
    expect(c!.worst.mean).toBe(15)
  })

  it('declines to contrast fewer than four matches', () => {
    expect(contrastByPlacement([row(1, 1), row(2, 2), row(3, 3)], pick)).toBeNull()
  })
})

describe('mergeWeapons', () => {
  const w = (
    weapon: string,
    kills: number,
    avgDistanceM: number,
    longestM = 100,
    shots = 0,
    shotsLanded = 0,
  ) => ({
    weapon,
    kills,
    headshots: 1,
    longestM,
    avgDistanceM,
    shots,
    shotsLanded,
    hitEvents: shotsLanded,
    accuracy: shots > 0 ? shotsLanded / shots : null,
  })

  it('sums kills, maxes longest, and kill-weights the average range', () => {
    const merged = mergeWeapons([
      [w('Item_Weapon_M24_C', 9, 100, 300)],
      [w('Item_Weapon_M24_C', 1, 10, 50)],
    ])
    expect(merged).toHaveLength(1)
    expect(merged[0]!.kills).toBe(10)
    expect(merged[0]!.headshots).toBe(2)
    expect(merged[0]!.longestM).toBe(300)
    expect(merged[0]!.avgDistanceM).toBeCloseTo(91)
  })

  it('sorts the squad table by kills', () => {
    const merged = mergeWeapons([[w('A', 1, 10)], [w('B', 5, 10)]])
    expect(merged.map((m) => m.weapon)).toEqual(['B', 'A'])
  })

  it('keeps a zero-kill weapon without dividing by zero', () => {
    const merged = mergeWeapons([[w('A', 0, 0)], [w('A', 0, 0)]])
    expect(merged[0]!.avgDistanceM).toBe(0)
  })

  it('recomputes accuracy from summed totals rather than averaging percentages', () => {
    // 1/1 = 100% and 10/100 = 10%. Averaging the two percentages gives 55%,
    // which is what a three-shot cameo does to a three-hundred-shot game.
    // The honest answer is 11 of 101.
    const merged = mergeWeapons([[w('A', 0, 0, 0, 1, 1)], [w('A', 0, 0, 0, 100, 10)]])
    expect(merged[0]!.shots).toBe(101)
    expect(merged[0]!.shotsLanded).toBe(11)
    expect(merged[0]!.accuracy).toBeCloseTo(11 / 101)
  })

  it('leaves accuracy null for a weapon nobody fired', () => {
    // Not 0 — "never fired" and "fired and missed everything" are different
    // statements, and this table has both.
    expect(mergeWeapons([[w('A', 3, 50)]])[0]!.accuracy).toBeNull()
  })

  it('sorts by shots when kills tie, so a fired-but-killless weapon still ranks', () => {
    const merged = mergeWeapons([[w('A', 0, 0, 0, 5, 1)], [w('B', 0, 0, 0, 50, 9)]])
    expect(merged.map((m) => m.weapon)).toEqual(['B', 'A'])
  })
})
