/**
 * Table sorting, with the one rule that is easy to get wrong.
 *
 * **Nulls sort last in both directions.** Every numeric column on the strategy
 * tables has a real "not measurable" case — a solo match has no teammate
 * distance, an unparsed match has no metrics, a weapon nobody fired has no
 * accuracy — and `null` is deliberately not zero anywhere in this codebase.
 *
 * The default comparison would put nulls wherever the coercion happens to land
 * them: descending, `null` compares as 0 and sinks below every real value,
 * which looks correct; ascending, it rises to the top and the first row of
 * "worst accuracy" is a gun that was never fired. That is the shape of bug
 * this repo keeps finding — right-looking output, wrong in one direction only.
 */

export type SortDir = 'asc' | 'desc'

/**
 * Stable sort by a derived value, nulls always last.
 *
 * Stability matters: two matches with the same placement must not swap
 * between renders. `Array.prototype.sort` has been stable since ES2019, and
 * the input order is the caller's chosen tiebreak.
 */
export function sortRows<T>(
  rows: readonly T[],
  value: (row: T) => number | string | null | undefined,
  dir: SortDir,
): T[] {
  const sign = dir === 'asc' ? 1 : -1
  return [...rows].sort((a, b) => {
    const va = value(a)
    const vb = value(b)
    const na = va === null || va === undefined
    const nb = vb === null || vb === undefined
    // Checked before the direction is applied, so "last" means last on screen
    // rather than last in the comparator's own ordering.
    if (na && nb) return 0
    if (na) return 1
    if (nb) return -1
    if (typeof va === 'string' || typeof vb === 'string') {
      return sign * String(va).localeCompare(String(vb))
    }
    return sign * (va - vb)
  })
}

/**
 * The next sort state when a header is clicked.
 *
 * Clicking a new column starts at `desc`, because every sortable column here
 * is a quantity and "most first" is what a reader means by sorting one.
 * Clicking the active column flips it.
 */
export function nextSort(
  current: { key: string; dir: SortDir },
  key: string,
): { key: string; dir: SortDir } {
  if (current.key !== key) return { key, dir: 'desc' }
  return { key, dir: current.dir === 'desc' ? 'asc' : 'desc' }
}

/** The arrow to render beside a header, or '' when it is not the active one. */
export function sortGlyph(current: { key: string; dir: SortDir }, key: string): string {
  if (current.key !== key) return ''
  return current.dir === 'desc' ? ' ▾' : ' ▴'
}
