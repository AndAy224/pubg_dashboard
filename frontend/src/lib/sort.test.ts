import { describe, expect, it } from 'vitest'
import { nextSort, sortGlyph, sortRows } from './sort'

/**
 * The null rule is the reason this module exists, so it is most of the file.
 *
 * Descending, a null coerced to 0 sinks harmlessly below every real value and
 * the table looks right. Ascending, it rises to the top and "worst accuracy"
 * is headed by a gun nobody ever fired. One direction correct and one wrong is
 * exactly the failure that survives a glance.
 */

type Row = { name: string; v: number | null }

const rows: Row[] = [
  { name: 'a', v: 3 },
  { name: 'b', v: null },
  { name: 'c', v: 1 },
  { name: 'd', v: 10 },
]

const order = (dir: 'asc' | 'desc') =>
  sortRows(rows, (r) => r.v, dir).map((r) => r.name)

describe('sortRows', () => {
  it('sorts descending with nulls last', () => {
    expect(order('desc')).toEqual(['d', 'a', 'c', 'b'])
  })

  it('sorts ascending with nulls **still** last', () => {
    // Not ['b', 'c', 'a', 'd'] — a "not measurable" row must never lead a
    // column that is being read as "the worst ones".
    expect(order('asc')).toEqual(['c', 'a', 'd', 'b'])
  })

  it('treats undefined the same as null', () => {
    const withUndef = [{ v: 1 }, { v: undefined }, { v: 2 }]
    expect(sortRows(withUndef, (r) => r.v, 'asc').map((r) => r.v)).toEqual([1, 2, undefined])
  })

  it('keeps every row — sorting is not filtering', () => {
    expect(sortRows(rows, (r) => r.v, 'desc')).toHaveLength(rows.length)
  })

  it('does not mutate the input', () => {
    const before = rows.map((r) => r.name)
    sortRows(rows, (r) => r.v, 'asc')
    expect(rows.map((r) => r.name)).toEqual(before)
  })

  it('is stable, so equal rows keep their given order', () => {
    // Two matches with the same placement must not swap between renders.
    const ties = [
      { name: 'first', v: 5 },
      { name: 'second', v: 5 },
      { name: 'third', v: 5 },
    ]
    expect(sortRows(ties, (r) => r.v, 'desc').map((r) => r.name)).toEqual([
      'first',
      'second',
      'third',
    ])
  })

  it('sorts strings by locale, not by code point', () => {
    const names = [{ n: 'beryl' }, { n: 'AKM' }, { n: 'M416' }]
    expect(sortRows(names, (r) => r.n, 'asc').map((r) => r.n)).toEqual(['AKM', 'beryl', 'M416'])
  })

  it('handles an all-null column without reordering anything', () => {
    const all = [{ v: null }, { v: null }]
    expect(sortRows(all, (r) => r.v, 'asc')).toHaveLength(2)
  })

  it('handles an empty list', () => {
    expect(sortRows([], (r: Row) => r.v, 'desc')).toEqual([])
  })
})

describe('nextSort', () => {
  it('starts a new column at descending', () => {
    // Every sortable column here is a quantity, and "most first" is what
    // clicking one means.
    expect(nextSort({ key: 'a', dir: 'asc' }, 'b')).toEqual({ key: 'b', dir: 'desc' })
  })

  it('flips the active column', () => {
    expect(nextSort({ key: 'a', dir: 'desc' }, 'a')).toEqual({ key: 'a', dir: 'asc' })
    expect(nextSort({ key: 'a', dir: 'asc' }, 'a')).toEqual({ key: 'a', dir: 'desc' })
  })
})

describe('sortGlyph', () => {
  it('marks only the active column', () => {
    expect(sortGlyph({ key: 'a', dir: 'desc' }, 'a')).toBe(' ▾')
    expect(sortGlyph({ key: 'a', dir: 'asc' }, 'a')).toBe(' ▴')
    expect(sortGlyph({ key: 'a', dir: 'asc' }, 'b')).toBe('')
  })
})
