import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * CSS from a lazily-loaded route must not leak into the rest of the app.
 *
 * Vite injects a lazy chunk's stylesheet when the chunk first loads and
 * **never removes it**. So a page-level stylesheet is global from the moment
 * that page is first visited — for the rest of the session, on every other
 * route.
 *
 * That broke the home page: `.feed-row` was declared in both
 * `pages/Replay.css` and `components/MatchFeed.css`, and the replay's
 * `display: grid; grid-template-columns: 42px 1fr auto 1fr` landed on the
 * match feed's five-column rows. A fresh load was fine, because Replay.css
 * had not loaded yet — the collision only appeared after opening a replay and
 * navigating back, which is exactly the shape of bug that survives casual
 * testing.
 *
 * Scoping every selector under the page root makes it structurally
 * impossible. This test is what keeps it that way.
 */

const SRC = new URL('..', import.meta.url).pathname

/** Page stylesheets and the root class each must be scoped under. */
const PAGE_SCOPES: Record<string, { prefix: string; unscoped: string[] }> = {
  'Replay.css': {
    prefix: '.replay',
    // Rendered *instead of* `.replay`, so it cannot live inside it.
    unscoped: ['.replay-error'],
  },
  'Strategy.css': {
    prefix: '.strategy',
    unscoped: [],
  },
}

/** Strip comments, then yield every selector in the sheet. */
function selectorsOf(css: string): string[] {
  const withoutComments = css.replace(/\/\*[\s\S]*?\*\//g, '')
  const out: string[] = []
  for (const block of withoutComments.split('}')) {
    const head = block.split('{')[0]
    if (head === undefined) continue
    const selector = head.trim()
    if (!selector || selector.startsWith('@')) continue
    for (const part of selector.split(',')) {
      const s = part.trim()
      if (s) out.push(s)
    }
  }
  return out
}

/** Does `selector` sit under `prefix`? `.replay-error` does not. */
function isScopedUnder(selector: string, prefix: string): boolean {
  if (selector === prefix) return true
  // The lookahead stops `.replay-error` from passing as `.replay`.
  return new RegExp(`^${prefix.replace('.', '\\.')}(?![\\w-])`).test(selector)
}

describe('page stylesheets are scoped to their page', () => {
  const pagesDir = join(SRC, 'pages')
  const sheets = readdirSync(pagesDir).filter((f) => f.endsWith('.css'))

  it('every page stylesheet has a declared scope', () => {
    // A new page stylesheet must opt in deliberately, rather than silently
    // becoming global the first time someone visits that route.
    expect(sheets.sort()).toEqual(Object.keys(PAGE_SCOPES).sort())
  })

  for (const sheet of sheets) {
    const scope = PAGE_SCOPES[sheet]
    if (!scope) continue

    it(`${sheet}: every selector is under ${scope.prefix}`, () => {
      const leaked = selectorsOf(readFileSync(join(pagesDir, sheet), 'utf8')).filter(
        (s) => !isScopedUnder(s, scope.prefix) && !scope.unscoped.includes(s),
      )
      expect(leaked, `these would style the whole app once ${sheet} loads`).toEqual([])
    })
  }
})

describe('no class is declared globally by two stylesheets', () => {
  /**
   * The leading class of every unscoped selector, per file. Two files owning
   * the same leading class means whichever loads last silently wins — which
   * is only observable after a specific navigation order.
   */
  function globalLeadingClasses(css: string): Set<string> {
    const out = new Set<string>()
    for (const selector of selectorsOf(css)) {
      const first = selector.split(/[\s>+~]/)[0] ?? ''
      const match = /^\.([a-zA-Z][\w-]*)/.exec(first)
      if (match?.[1]) out.add(match[1])
    }
    return out
  }

  function cssFiles(dir: string): string[] {
    const out: string[] = []
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = join(dir, entry.name)
      if (entry.isDirectory()) out.push(...cssFiles(full))
      else if (entry.name.endsWith('.css')) out.push(full)
    }
    return out
  }

  it('finds no cross-file collisions', () => {
    const owners = new Map<string, string[]>()
    for (const file of cssFiles(SRC)) {
      const short = file.slice(SRC.length)
      for (const cls of globalLeadingClasses(readFileSync(file, 'utf8'))) {
        owners.set(cls, [...(owners.get(cls) ?? []), short])
      }
    }

    const collisions = [...owners.entries()]
      .filter(([, files]) => files.length > 1)
      .map(([cls, files]) => `.${cls} in ${files.join(' and ')}`)

    expect(collisions).toEqual([])
  })
})
