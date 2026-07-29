import { describe, expect, it } from 'vitest'
import { caveat, engagementFindings } from './engagements'
import { rankFindings } from './findings'
import type { SquadEngagements } from '../api/types'

/**
 * The rules this module exists to enforce, tested as rules rather than as
 * outputs. `engagements.ts` states claims about a **modelled** quantity, which
 * `findings.ts` never does, so the two extra obligations — name the gap, never
 * quote one half of the first-hit split — are the tests that matter most.
 */

const rate = (n: number, total: number) => ({
  n,
  total,
  pct: total === 0 ? null : n / total,
})

function payload(over: Partial<SquadEngagements> = {}): SquadEngagements {
  return {
    gapSeconds: 20,
    thirdPartyRadiusM: 200,
    matches: 97,
    fights: 400,
    decided: 200,
    results: [
      { key: 'ours_only', label: 'only they lost someone', n: 110 },
      { key: 'theirs_only', label: 'only we lost someone', n: 70 },
      { key: 'both', label: 'both sides lost someone', n: 20 },
      { key: 'neither', label: 'nobody died', n: 200 },
    ],
    firstHitOurs: rate(120, 200),
    aheadWhenFirst: rate(90, 120),
    aheadWhenNotFirst: rate(20, 80),
    thirdParty: rate(52, 400),
    rangeBands: [
      { loM: 0, hiM: 25, fights: 100, weKilled: 60, weDied: 40 },
      { loM: 25, hiM: 75, fights: 80, weKilled: 30, weDied: 50 },
      { loM: 75, hiM: 150, fights: 20, weKilled: 5, weDied: 15 },
      { loM: 150, hiM: null, fights: 4, weKilled: 1, weDied: 3 },
    ],
    players: [
      {
        accountId: 'account.a',
        name: 'AndAy',
        fights: 60,
        damageDealtAvg: 55,
        damageTakenAvg: 80,
        knocked: rate(20, 60),
        died: rate(12, 60),
      },
      {
        accountId: 'account.b',
        name: 'SIERIUS_',
        fights: 50,
        damageDealtAvg: 60,
        damageTakenAvg: 40,
        knocked: rate(10, 50),
        died: rate(8, 50),
      },
    ],
    ...over,
  }
}

const ids = (e: SquadEngagements) => engagementFindings(e).map((f) => f.id)
const byId = (e: SquadEngagements, id: string) =>
  engagementFindings(e).find((f) => f.id === id)

// ---------------------------------------------------------------------------
// the gap is a choice, and every count of fights has to say so
// ---------------------------------------------------------------------------
describe('the modelling caveat', () => {
  it('names the actual gap, not a hard-coded one', () => {
    expect(caveat(30)).toContain('30 s')
    expect(caveat(20)).toContain('20 s')
  })

  it('reaches every sentence that quotes a count of fights', () => {
    const e = payload()
    const clause = caveat(e.gapSeconds)
    for (const f of engagementFindings(e)) {
      // A sentence quoting "fights" or "exchanges" as a population is making
      // a claim about the grouping and must carry it. `damage-taken-spread`
      // quotes a per-player fight count rather than a population, and the
      // third-party rate's denominator is stated in the section header.
      if (/\b(fights|exchanges)\b/.test(f.text) && !/damage|third team/.test(f.text)) {
        expect(f.text).toContain(clause)
        // ...and the marker always carries the number, never a bare word like
        // "grouped" that a reader cannot check against the parser.
        expect(f.text).toContain(`${e.gapSeconds} s`)
      }
    }
  })

  it('changes the printed clause when the parser changes the gap', () => {
    const at30 = byId(payload({ gapSeconds: 30 }), 'first-hit-share')
    expect(at30?.text).toContain('30 s')
    expect(at30?.text).not.toContain('20 s')
  })
})

// ---------------------------------------------------------------------------
// the first-hit split is a pair or it is nothing
// ---------------------------------------------------------------------------
describe('first-hit advantage', () => {
  it('states both halves in one sentence', () => {
    const f = byId(payload(), 'first-hit-advantage')
    expect(f?.text).toContain('90 of 120')
    expect(f?.text).toContain('20 of 80')
  })

  it('says nothing at all when only one half is measurable', () => {
    const e = payload({ aheadWhenNotFirst: rate(0, 0) })
    expect(ids(e)).not.toContain('first-hit-advantage')
  })

  it('says nothing when the two halves barely differ', () => {
    const e = payload({ aheadWhenFirst: rate(52, 100), aheadWhenNotFirst: rate(48, 100) })
    expect(ids(e)).not.toContain('first-hit-advantage')
  })

  it('flips tone when the advantage runs the other way', () => {
    const good = byId(payload(), 'first-hit-advantage')
    const bad = byId(
      payload({ aheadWhenFirst: rate(20, 120), aheadWhenNotFirst: rate(60, 80) }),
      'first-hit-advantage',
    )
    expect(good?.tone).toBe('good')
    expect(bad?.tone).toBe('bad')
  })

  it('never claims anyone "started" or "opened" a fight', () => {
    // `LogPlayerAttack` has no victim, so a shot that missed is attributable
    // to nobody. "First blow" is what the data supports; "opened the fight"
    // is not, and it is the exact overclaim this wording exists to avoid.
    const banned = /\b(opened?|started|initiated|engaged first)\b/i
    for (const f of engagementFindings(payload())) {
      expect(f.text).not.toMatch(banned)
    }
  })
})

// ---------------------------------------------------------------------------
// the shared rules, inherited from findings.ts
// ---------------------------------------------------------------------------
describe('claim discipline', () => {
  it('uses no causal or prescriptive language', () => {
    const banned = /\b(because|causes?|caused|therefore|you should|try to|improve|leads? to)\b/i
    for (const f of engagementFindings(payload())) {
      expect(f.text).not.toMatch(banned)
    }
  })

  it('never calls a fight won or lost', () => {
    // The database stores no verdict for a reason: a squad that killed two and
    // lost three to a third party did not obviously lose to the team named in
    // the row. The sentences must not reintroduce what the schema refused.
    for (const f of engagementFindings(payload())) {
      expect(f.text).not.toMatch(/\b(won|lost the|winning|losing)\b/i)
    }
  })

  it('carries a real n on every finding', () => {
    for (const f of engagementFindings(payload())) {
      expect(f.n).toBeGreaterThan(0)
      expect(Number.isFinite(f.n)).toBe(true)
    }
  })

  it('suppresses everything on an empty archive', () => {
    const empty = payload({
      fights: 0,
      decided: 0,
      firstHitOurs: rate(0, 0),
      aheadWhenFirst: rate(0, 0),
      aheadWhenNotFirst: rate(0, 0),
      thirdParty: rate(0, 0),
      results: [],
      rangeBands: [],
      players: [],
    })
    expect(rankFindings(engagementFindings(empty))).toHaveLength(0)
  })

  it('prints no percentage over an empty denominator', () => {
    const e = payload({ thirdParty: rate(0, 0) })
    expect(ids(e)).not.toContain('engagement-third-party')
  })
})

// ---------------------------------------------------------------------------
// range and per-player
// ---------------------------------------------------------------------------
describe('range bands', () => {
  it('picks the band with the worst trade, not the emptiest', () => {
    // 150 m+ has the worst ratio (1:3) but only 4 fights, so 75–150 m is the
    // honest answer. A band below MIN_N is dropped rather than hedged.
    const f = byId(payload(), 'engagement-worst-range')
    expect(f?.text).toContain('75–150 m')
  })

  it('says nothing when every band trades evenly or better', () => {
    const e = payload({
      rangeBands: [{ loM: 0, hiM: 25, fights: 100, weKilled: 60, weDied: 40 }],
    })
    expect(ids(e)).not.toContain('engagement-worst-range')
  })

  it('labels the open-ended band without inventing a ceiling', () => {
    const e = payload({
      rangeBands: [{ loM: 150, hiM: null, fights: 50, weKilled: 5, weDied: 45 }],
    })
    expect(byId(e, 'engagement-worst-range')?.text).toContain('beyond 150 m')
  })
})

describe('damage taken', () => {
  it('contrasts two players rather than judging one', () => {
    const f = byId(payload(), 'damage-taken-spread')
    expect(f?.text).toContain('AndAy')
    expect(f?.text).toContain('SIERIUS_')
    // Neutral on purpose: taking more damage is what an entry fragger does,
    // and nothing here says which of the two is playing badly.
    expect(f?.tone).toBe('neutral')
  })

  it('stays silent when the two are close', () => {
    const e = payload({
      players: payload().players.map((p) => ({ ...p, damageTakenAvg: 50 })),
    })
    expect(ids(e)).not.toContain('damage-taken-spread')
  })

  it('ignores players with too few fights to compare', () => {
    const e = payload({
      players: payload().players.map((p) => ({ ...p, fights: 3 })),
    })
    expect(ids(e)).not.toContain('damage-taken-spread')
  })
})

describe('ranking', () => {
  it('is a total order, stable across input permutations', () => {
    const forward = rankFindings(engagementFindings(payload())).map((f) => f.id)
    const reversed = rankFindings([...engagementFindings(payload())].reverse()).map((f) => f.id)
    expect(reversed).toEqual(forward)
  })
})
