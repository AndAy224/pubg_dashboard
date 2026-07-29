import { describe, expect, it } from 'vitest'
import { LEAD_IN_S, circleSentence, deathFindings, replayLink, tagsFor } from './deaths'
import { rankFindings } from './findings'
import type { DeathListRow, SquadDeaths } from '../api/types'

/**
 * The two things this module has to get right, and neither is arithmetic.
 *
 * **Null is not false.** `alone`, `inVehicle`, `parachuting` and `inCircle`
 * are all nullable because "not measured" is a real state — a match parsed
 * before v17, or a death before any circle closed. Rendering any of them as a
 * claim would be the API's 195-of-195 bug moved into the browser.
 *
 * **A death rate is only a finding if it differs from the not-dying rate.**
 * `circleSentence` exists because 61% looks alarming next to nothing and
 * unremarkable next to 56%.
 */

const rate = (n: number, total: number) => ({
  n,
  total,
  pct: total === 0 ? null : n / total,
})

function row(over: Partial<DeathListRow> = {}): DeathListRow {
  return {
    matchId: 'm1',
    seq: 12,
    playedAt: '2026-07-28T19:22:53Z',
    mapName: 'Baltic_Main',
    tS: 634.5,
    accountId: 'account.abc',
    name: 'AndAy',
    winPlace: 18,
    killerName: 'someone',
    killerIsBot: false,
    weapon: 'WeapM24_C',
    distanceM: 54.8,
    knockedFirst: false,
    thirdPartied: false,
    alone: false,
    nearestTeammateM: 42,
    inVehicle: false,
    inCircle: true,
    damageDealt: 30,
    damageTaken: 100,
    ...over,
  }
}

function payload(over: Partial<SquadDeaths> = {}): SquadDeaths {
  return {
    deaths: 195,
    isolatedRadiusM: 100,
    alone: rate(127, 195),
    isolated: rate(20, 68),
    thirdPartied: rate(39, 195),
    knockedFirst: rate(112, 195),
    circle: { atDeath: rate(76, 124), baseline: rate(240, 432) },
    inVehicle: 2,
    outsideAnyFight: 9,
    rows: [row()],
    ...over,
  }
}

const ids = (d: SquadDeaths) => deathFindings(d).map((f) => f.id)

// ---------------------------------------------------------------------------
// the comparison that stopped a bucket
// ---------------------------------------------------------------------------
describe('circleSentence', () => {
  it('always states the baseline beside the death rate', () => {
    const s = circleSentence(payload().circle)
    expect(s?.text).toContain('76 of 124')
    expect(s?.text).toContain('240 of 432')
  })

  it('says the two are the same rather than going quiet', () => {
    // Silence would read as "nobody checked". The real archive lands here:
    // 61% against 56% is six points, which is not a finding, and the page has
    // to say so out loud.
    const s = circleSentence(payload().circle)
    expect(s?.different).toBe(false)
    expect(s?.text).toMatch(/the same/i)
  })

  it('states a real gap when there is one', () => {
    const s = circleSentence({ atDeath: rate(90, 100), baseline: rate(30, 400) })
    expect(s?.different).toBe(true)
    expect(s?.text).not.toMatch(/the same/i)
  })

  it('handles the gap running the other way without claiming it is bad', () => {
    const s = circleSentence({ atDeath: rate(10, 100), baseline: rate(240, 400) })
    expect(s?.different).toBe(true)
    expect(s?.text).toContain('less often')
  })

  it('returns null rather than a percentage over an empty denominator', () => {
    expect(circleSentence({ atDeath: rate(0, 0), baseline: rate(240, 432) })).toBeNull()
    expect(circleSentence({ atDeath: rate(76, 124), baseline: rate(0, 0) })).toBeNull()
  })
})

// ---------------------------------------------------------------------------
// null is not false
// ---------------------------------------------------------------------------
describe('tags', () => {
  it('does not claim "last one up" when it was never measured', () => {
    // The API reported 195 of 195 deaths as alone on its first run, purely
    // because `teammates_alive` was NULL before the archive was reparsed.
    // The browser must not repeat it.
    expect(tagsFor(row({ alone: null, nearestTeammateM: null }))).not.toContain('last one up')
  })

  it('does claim it when it was measured', () => {
    expect(tagsFor(row({ alone: true, nearestTeammateM: null }))).toContain('last one up')
  })

  it('does not claim a vehicle on a null', () => {
    expect(tagsFor(row({ inVehicle: null }))).not.toContain('in a vehicle')
  })

  it('never claims a death happened in the air', () => {
    // Removed in v19. The tag came from a flag meaning "the match is in its
    // plane phase", not "this player is under a canopy", so it marked 42
    // already-landed deaths out of 62 — 4-metre firefights with 96 damage
    // dealt, labelled as parachute deaths. One death in 1,918 is genuinely
    // airborne. Pinned so nothing reintroduces it from the same flag.
    for (const r of [row(), row({ inVehicle: true }), row({ alone: true })]) {
      expect(tagsFor(r).join(' ')).not.toMatch(/air|parachut|sky/i)
    }
  })

  it('reports distance from the squad only past the radius', () => {
    expect(tagsFor(row({ nearestTeammateM: 42 })).join()).not.toMatch(/from the squad/)
    expect(tagsFor(row({ nearestTeammateM: 340 })).join()).toMatch(/340 m from the squad/)
  })

  it('prefers "last one up" over a distance, because they cannot both hold', () => {
    const tags = tagsFor(row({ alone: true, nearestTeammateM: 340 }))
    expect(tags).toContain('last one up')
    expect(tags.join()).not.toMatch(/from the squad/)
  })

  it('is empty for an unremarkable death', () => {
    expect(tagsFor(row())).toEqual([])
  })
})

// ---------------------------------------------------------------------------
// replay links — the first thing in the app to produce ?follow=
// ---------------------------------------------------------------------------
describe('replayLink', () => {
  it('carries both the time and the player to follow', () => {
    const url = replayLink(row({ tS: 634.5 }))
    expect(url).toContain('/matches/m1/replay')
    expect(url).toContain(`t=${634 - LEAD_IN_S + 1}`)
    expect(url).toContain('follow=account.abc')
  })

  it('seeks before the death, not to it', () => {
    // Arriving at the exact instant shows a corpse. The question is what was
    // happening just before.
    const url = new URL(replayLink(row({ tS: 600 })), 'http://x')
    expect(Number(url.searchParams.get('t'))).toBe(600 - LEAD_IN_S)
  })

  it('never seeks to a negative time', () => {
    const url = new URL(replayLink(row({ tS: 4 })), 'http://x')
    expect(Number(url.searchParams.get('t'))).toBe(0)
  })

  it('escapes the account id', () => {
    const url = new URL(replayLink(row({ accountId: 'a b&c' })), 'http://x')
    expect(url.searchParams.get('follow')).toBe('a b&c')
  })
})

// ---------------------------------------------------------------------------
// the shared claim rules
// ---------------------------------------------------------------------------
describe('claim discipline', () => {
  it('uses no causal or prescriptive language', () => {
    const banned = /\b(because|causes?|caused|therefore|you should|try to|improve|leads? to)\b/i
    for (const f of deathFindings(payload())) {
      expect(f.text).not.toMatch(banned)
    }
  })

  it('carries a real n on every finding', () => {
    for (const f of deathFindings(payload())) {
      expect(f.n).toBeGreaterThan(0)
    }
  })

  it('keeps "died alone" neutral', () => {
    // Somebody has to be the last one up, and in solo it is everyone. There
    // is no baseline that makes 65% good or bad.
    expect(deathFindings(payload()).find((f) => f.id === 'died-alone')?.tone).toBe('neutral')
  })

  it('uses the isolation denominator that means something', () => {
    // 20 of 68 deaths where a teammate was still up — not 20 of 195, which
    // would be diluted by every solo match and read as a third of the truth.
    const f = deathFindings(payload()).find((f) => f.id === 'died-isolated')
    expect(f?.text).toContain('20 of 68')
    expect(f?.n).toBe(68)
  })

  it('names the radius it used', () => {
    const f = deathFindings(payload({ isolatedRadiusM: 250 })).find(
      (x) => x.id === 'died-isolated',
    )
    expect(f?.text).toContain('250 m')
  })

  it('suppresses everything on an empty archive', () => {
    const empty = payload({
      deaths: 0,
      alone: rate(0, 0),
      isolated: rate(0, 0),
      thirdPartied: rate(0, 0),
      knockedFirst: rate(0, 0),
      rows: [],
    })
    expect(rankFindings(deathFindings(empty))).toHaveLength(0)
  })

  it('says nothing about isolation when nobody was ever up', () => {
    // Every death in solo. The denominator is zero and the claim is not
    // available — 0% would be a measured-looking answer to an unasked
    // question.
    expect(ids(payload({ isolated: rate(0, 0) }))).not.toContain('died-isolated')
  })
})
