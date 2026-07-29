import { describe, expect, it } from 'vitest'
import type { Rate, SquadReview } from '../api/types'
import { MIN_N, rankFindings, rateText, squadFindings } from './findings'
import type { Finding } from './findings'

function rate(n: number, total: number): Rate {
  return { n, total, pct: total === 0 ? null : n / total }
}

/** A payload shaped like the live one, with the numbers measured at 97
 *  matches. Deliberately not a captured fixture: the point of these tests is
 *  the arithmetic and the wording rules, and a fixture would drift. */
function review(over: Partial<SquadReview> = {}): SquadReview {
  return {
    matches: 83,
    deaths: 195,
    thirdParty: rate(44, 195),
    thirdPartyRadiusM: 200,
    thirdPartyWindowS: 30,
    knocks: { made: rate(122, 200), taken: rate(112, 182) },
    firstDeaths: [
      { accountId: 'account.a', name: 'DaddyGainz', diedFirst: 32, squadMatches: 71 },
      { accountId: 'account.b', name: 'SIERIUS_', diedFirst: 28, squadMatches: 71 },
      { accountId: 'account.c', name: 'AndAy', diedFirst: 11, squadMatches: 38 },
    ],
    rangeBands: [
      { loM: 0, hiM: 10, weKilled: 51, weDied: 42 },
      { loM: 10, hiM: 50, weKilled: 111, weDied: 86 },
      { loM: 50, hiM: 100, weKilled: 33, weDied: 26 },
      { loM: 100, hiM: 200, weKilled: 34, weDied: 21 },
      { loM: 200, hiM: null, weKilled: 9, weDied: 14 },
    ],
    deathCauses: [
      { cause: 'knocked_first', n: 112, label: 'knocked, then finished' },
      { cause: 'outright', n: 83, label: 'killed outright' },
      { cause: 'third_partied', n: 44, label: 'third-partied' },
      { cause: 'early', n: 63, label: 'in the first 5 minutes' },
      { cause: 'to_bot', n: 0, label: 'to a bot' },
    ],
    zoneDeaths: 6,
    ...over,
  }
}

describe('rateText', () => {
  it('prints both halves, never a bare percentage', () => {
    expect(rateText(rate(122, 200))).toBe('122 of 200 (61%)')
  })

  it('returns null on an empty denominator rather than "0 of 0 (0%)"', () => {
    // Three numbers, none of them measured. The null forces the caller to
    // omit the sentence instead of printing a confident nothing.
    expect(rateText(rate(0, 0))).toBeNull()
  })

  it('returns null when pct is null even if total looks usable', () => {
    expect(rateText({ n: 0, total: 5, pct: null })).toBeNull()
  })

  it('prints a genuine zero numerator', () => {
    expect(rateText(rate(0, 195))).toBe('0 of 195 (0%)')
  })
})

describe('rankFindings', () => {
  const f = (id: string, n: number, strength: number): Finding => ({
    id,
    text: id,
    n,
    strength,
    tone: 'neutral',
  })

  it('drops findings below the minimum n instead of hedging them', () => {
    const ranked = rankFindings([f('thin', MIN_N - 1, 0.9), f('solid', MIN_N, 0.1)])
    expect(ranked.map((r) => r.id)).toEqual(['solid'])
  })

  it('keeps a finding exactly at the threshold', () => {
    expect(rankFindings([f('edge', MIN_N, 0.5)])).toHaveLength(1)
  })

  it('orders by strength descending', () => {
    const ranked = rankFindings([f('low', 20, 0.1), f('high', 20, 0.9), f('mid', 20, 0.5)])
    expect(ranked.map((r) => r.id)).toEqual(['high', 'mid', 'low'])
  })

  it('is a total order — equal strengths never depend on input order', () => {
    const a = rankFindings([f('b', 20, 0.5), f('a', 20, 0.5)])
    const b = rankFindings([f('a', 20, 0.5), f('b', 20, 0.5)])
    expect(a.map((r) => r.id)).toEqual(['a', 'b'])
    expect(b.map((r) => r.id)).toEqual(['a', 'b'])
  })

  it('honours a caller-supplied threshold', () => {
    expect(rankFindings([f('x', 10, 1)], 20)).toHaveLength(0)
  })

  it('does not mutate its input', () => {
    const input = [f('b', 20, 0.1), f('a', 20, 0.9)]
    rankFindings(input)
    expect(input.map((r) => r.id)).toEqual(['b', 'a'])
  })
})

describe('squadFindings', () => {
  it('carries an n on every finding', () => {
    for (const finding of squadFindings(review())) {
      expect(finding.n, finding.id).toBeGreaterThan(0)
    }
  })

  it('never states a conclusion without its numbers', () => {
    // Every sentence must contain a digit. A finding with no figures in it is
    // an opinion, and this page does not have opinions.
    for (const finding of squadFindings(review())) {
      expect(finding.text, finding.id).toMatch(/\d/)
    }
  })

  it('uses no causal or prescriptive phrasing', () => {
    // The ceiling is "in these matches, X looked like Y". Anything telling the
    // reader what to do is a claim 40 observational matches cannot support.
    const banned = /\b(because|causes?|caused|therefore|you should|try to|improve|leads? to)\b/i
    for (const finding of squadFindings(review())) {
      expect(finding.text, finding.id).not.toMatch(banned)
    }
  })

  it('calls near-equal knock conversion the same rate rather than an asymmetry', () => {
    // 61.0% vs 61.5% is not a difference. An earlier time-window derivation
    // made these look asymmetric and they were not, which is exactly the
    // reading this guard exists to prevent.
    const f = squadFindings(review()).find((x) => x.id === 'knock-conversion')
    expect(f?.text).toContain('the same rate, within noise')
    expect(f?.tone).toBe('neutral')
  })

  it('reports a real conversion gap when there is one', () => {
    const f = squadFindings(
      review({ knocks: { made: rate(180, 200), taken: rate(90, 180) } }),
    ).find((x) => x.id === 'knock-conversion')
    expect(f?.text).toContain('You convert more of your knocks')
    expect(f?.tone).toBe('good')
  })

  it('states knock survival as the complement, not as the death rate', () => {
    const f = squadFindings(review()).find((x) => x.id === 'knock-survival')
    // 182 - 112 = 70 survived, 38%.
    expect(f?.text).toContain('70 of 182')
    expect(f?.text).toContain('38%')
  })

  it('names the third-party thresholds in the sentence', () => {
    const f = squadFindings(review()).find((x) => x.id === 'third-party')
    expect(f?.text).toContain('200 m')
    expect(f?.text).toContain('30 s')
  })

  it('emits nothing for a rate with an empty denominator', () => {
    const findings = squadFindings(
      review({ knocks: { made: rate(0, 0), taken: rate(0, 0) } }),
    )
    expect(findings.find((f) => f.id === 'knock-conversion')).toBeUndefined()
    expect(findings.find((f) => f.id === 'knock-survival')).toBeUndefined()
  })

  it('states a measured zero as a result', () => {
    // The one place 0 is printed rather than suppressed: the denominator is
    // large and the claim is about absence, not about missing data.
    const f = squadFindings(review()).find((x) => x.id === 'no-bot-deaths')
    expect(f?.text).toContain('0 of 195')
  })

  it('does not claim "no bot has killed you" on a tiny sample', () => {
    const findings = squadFindings(
      review({ deaths: 3, deathCauses: [{ cause: 'to_bot', n: 0, label: 'to a bot' }] }),
    )
    expect(findings.find((f) => f.id === 'no-bot-deaths')).toBeUndefined()
  })

  it('compares first-death as a share, not a raw count', () => {
    // AndAy has the fewest shared matches; a raw-count ranking would put
    // whoever plays most at the top regardless of how often they go down.
    const f = squadFindings(review()).find((x) => x.id === 'first-death')
    expect(f?.text).toContain('DaddyGainz')
    expect(f?.text).toContain('45%') // 32/71
    expect(f?.text).toContain('29%') // 11/38
  })

  it('ignores players with too few shared matches to rank', () => {
    const findings = squadFindings(
      review({
        firstDeaths: [
          { accountId: 'a', name: 'Solo', diedFirst: 2, squadMatches: 2 },
          { accountId: 'b', name: 'AlsoSolo', diedFirst: 0, squadMatches: 3 },
        ],
      }),
    )
    expect(findings.find((f) => f.id === 'first-death')).toBeUndefined()
  })

  it('says nothing about first deaths when the squad is evenly matched', () => {
    const findings = squadFindings(
      review({
        firstDeaths: [
          { accountId: 'a', name: 'A', diedFirst: 20, squadMatches: 40 },
          { accountId: 'b', name: 'B', diedFirst: 21, squadMatches: 40 },
        ],
      }),
    )
    expect(findings.find((f) => f.id === 'first-death')).toBeUndefined()
  })

  it('picks the worst-trading band by ratio, not by volume', () => {
    // The 200m+ band is 9-14 — the only losing band — while 10-50m has far
    // more events and a winning ratio.
    const f = squadFindings(review()).find((x) => x.id === 'worst-range')
    expect(f?.text).toContain('beyond 200 m')
    expect(f?.text).toContain('9 kills against 14 deaths')
  })

  it('skips range bands too thin to state', () => {
    const findings = squadFindings(
      review({
        rangeBands: [
          { loM: 0, hiM: 10, weKilled: 1, weDied: 3 },
          { loM: 10, hiM: null, weKilled: 2, weDied: 1 },
        ],
      }),
    )
    expect(findings.find((f) => f.id === 'worst-range')).toBeUndefined()
  })

  it('reports no worst band when every band trades favourably', () => {
    const findings = squadFindings(
      review({
        rangeBands: [
          { loM: 0, hiM: 10, weKilled: 30, weDied: 10 },
          { loM: 10, hiM: null, weKilled: 40, weDied: 20 },
        ],
      }),
    )
    expect(findings.find((f) => f.id === 'worst-range')).toBeUndefined()
  })

  it('names the busiest band by combined volume', () => {
    const f = squadFindings(review()).find((x) => x.id === 'busiest-range')
    expect(f?.text).toContain('10-50 m')
    expect(f?.text).toContain('197') // 111 + 86
  })

  it('produces a stable, non-empty ranked list from real numbers', () => {
    const ranked = rankFindings(squadFindings(review()))
    expect(ranked.length).toBeGreaterThan(3)
    expect(rankFindings(squadFindings(review())).map((f) => f.id)).toEqual(
      ranked.map((f) => f.id),
    )
  })

  it('survives an archive with no deaths at all', () => {
    // A fresh install with matches but no parsed kills must render an empty
    // page, not throw.
    const empty = review({
      deaths: 0,
      thirdParty: rate(0, 0),
      knocks: { made: rate(0, 0), taken: rate(0, 0) },
      deathCauses: [],
      firstDeaths: [],
      rangeBands: [],
    })
    expect(() => squadFindings(empty)).not.toThrow()
    expect(rankFindings(squadFindings(empty))).toEqual([])
  })
})

describe('tone is only claimed where the data says which way is better', () => {
  it('never colours the revive rate, at any value', () => {
    // There is no baseline for a good revive rate anywhere in this app, so a
    // red 38% would be inventing a standard and then failing the squad
    // against it.
    for (const taken of [rate(20, 182), rate(112, 182), rate(175, 182)]) {
      const f = squadFindings(review({ knocks: { made: rate(122, 200), taken } })).find(
        (x) => x.id === 'knock-survival',
      )
      expect(f?.tone, `taken ${taken.n}/${taken.total}`).toBe('neutral')
    }
  })

  it('does colour a losing trade, which is self-evident from the counts', () => {
    const f = squadFindings(review()).find((x) => x.id === 'worst-range')
    expect(f?.tone).toBe('bad')
  })
})
