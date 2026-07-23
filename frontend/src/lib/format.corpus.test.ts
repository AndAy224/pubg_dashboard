import { describe, expect, it } from 'vitest'
import { weaponName } from './format'

/**
 * `weaponName` against **every** damage causer in the archive.
 *
 * The unit tests in `format.test.ts` pin the ids that exist today, but this
 * project's standing rule is that a fixture you wrote yourself is not evidence
 * about a wire format. Those ids were copied out of the corpus by hand, and a
 * hand-copied list goes stale the moment PUBG ships a patch.
 *
 * So this one asks the running API for the real thing. It mirrors the
 * convention in `replayBundle.corpus.test.ts` and the backend's `tests/`:
 * reach the service, and **skip cleanly when it is absent**, so a source-only
 * checkout stays green.
 *
 * Point it elsewhere with `PUBGD_API_BASE`.
 */
// Reached through `globalThis` rather than a bare `process` so the app's
// tsconfig keeps `types: ["vite/client"]` and nothing in `src/` can quietly
// start depending on Node globals that do not exist in the browser.
const BASE =
  (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env
    ?.PUBGD_API_BASE ?? 'http://127.0.0.1:8000'

/**
 * Markers of an id that leaked to the screen without being named.
 *
 * These are all *internal* class-name decoration — `BP_` for a blueprint,
 * `Pawn` for a character actor, `EffectActor` for an environmental damage
 * source. No real weapon renders with any of them, so a hit here means a
 * causer arrived that nothing has a label for.
 */
const UNNAMED = /(_C$|^BP |EffectActor|Debuff|Projectile|^Proj|Pawn|^Player|^None$)/

async function apiReachable(): Promise<boolean> {
  try {
    const r = await fetch(`${BASE}/api/health`, { signal: AbortSignal.timeout(2000) })
    return r.ok
  } catch {
    return false
  }
}

describe('weaponName over the whole archive', () => {
  it('leaves no raw internal id on screen', async ({ skip }) => {
    if (!(await apiReachable())) skip('no API reachable; start pubgd-api or set PUBGD_API_BASE')

    const matches = (await (
      await fetch(`${BASE}/api/matches?limit=100&trackedOnly=false`)
    ).json()) as { matchId: string }[]
    expect(matches.length, 'no matches to check').toBeGreaterThan(0)

    const seen = new Map<string, string>()
    for (const { matchId } of matches) {
      const kills = (await (
        await fetch(`${BASE}/api/matches/${matchId}/kills`)
      ).json()) as { weapon: string | null }[]
      for (const k of kills) seen.set(k.weapon ?? '<null>', weaponName(k.weapon))
    }

    // Worth asserting: an empty map would make the check below vacuous.
    expect(seen.size, 'no causers found in any match').toBeGreaterThan(5)

    const unnamed = [...seen].filter(([, shown]) => UNNAMED.test(shown))
    expect(
      unnamed.map(([raw, shown]) => `${raw} -> "${shown}"`),
      'these causers reach the kill feed as raw internal ids; add them to CAUSERS/VEHICLES in format.ts',
    ).toEqual([])
  })

  /**
   * The kill feed's weapon column is a fixed 120px, i.e. 100px of text. The
   * widest causer in the archive renders as "vz61Skorpion" — 12 characters,
   * measured at 96px in the browser — so 13 is the bound with a character of
   * headroom.
   *
   * A character count is a proxy for a pixel width, and an imperfect one. It
   * is here because the thing it actually guards is cheap to break and
   * invisible when broken: an id that falls through unlabelled ("Dacia A 03
   * v2 Esports") carries no internal marker for the check above to catch, and
   * silently ellipsises in the column instead.
   */
  it('renders every causer short enough for the column it lives in', async ({ skip }) => {
    if (!(await apiReachable())) skip('no API reachable; start pubgd-api or set PUBGD_API_BASE')

    const matches = (await (
      await fetch(`${BASE}/api/matches?limit=100&trackedOnly=false`)
    ).json()) as { matchId: string }[]

    const tooLong = new Set<string>()
    for (const { matchId } of matches) {
      const kills = (await (
        await fetch(`${BASE}/api/matches/${matchId}/kills`)
      ).json()) as { weapon: string | null }[]
      for (const k of kills) {
        const shown = weaponName(k.weapon)
        if (shown.length > 13) tooLong.add(`${k.weapon} -> "${shown}" (${shown.length})`)
      }
    }
    expect(
      [...tooLong],
      'these ellipsise in the kill feed; give them a label in CAUSERS/VEHICLES in format.ts',
    ).toEqual([])
  })

  it('never renders an empty cell for a causer that exists', async ({ skip }) => {
    if (!(await apiReachable())) skip('no API reachable; start pubgd-api or set PUBGD_API_BASE')

    const matches = (await (
      await fetch(`${BASE}/api/matches?limit=20&trackedOnly=false`)
    ).json()) as { matchId: string }[]

    for (const { matchId } of matches) {
      const kills = (await (
        await fetch(`${BASE}/api/matches/${matchId}/kills`)
      ).json()) as { weapon: string | null }[]
      for (const k of kills) expect(weaponName(k.weapon), `${matchId} ${k.weapon}`).not.toBe('')
    }
  })
})
