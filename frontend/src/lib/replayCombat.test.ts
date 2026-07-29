import { describe, expect, it } from 'vitest'
import {
  FIGHT_LEAD_IN_MS,
  damageLog,
  fightResult,
  fightsFor,
  seekFor,
  stepFight,
} from './replayCombat'
import type { Fight } from './replayCombat'
import type { MatchEngagements } from '../api/types'
import type { ReplayBundle } from './replayBundle'

/**
 * Hermetic, node, no DOM — the reason replay logic lives in `lib/`.
 *
 * The fixture is hand-built, so by this repo's own rule it is **not** evidence
 * about the wire format. What it is evidence about is the arithmetic: which
 * side of a hit the followed player is on, whether totals survive truncation,
 * and whether "our kills" flips when the team ordering does. Those are the
 * things that would still render a plausible panel while being wrong.
 * `replayBundle.corpus.test.ts` covers the decode against real bundles.
 */

const WORLD = 816_000
const TICK = 100

/** Quantise centimetres the way the bundle writer does. */
const q = (cm: number) => Math.round((cm / WORLD) * 65535)

function bundle(over: Partial<ReplayBundle['hits']> = {}): ReplayBundle {
  // Three hits: p0 hits p1 at 10 s from 100 m, p1 hits p0 at 12 s from 100 m,
  // p2 hits p3 at 14 s — a fight p0 is not in.
  const hits = {
    n: 3,
    t: new Uint16Array([100, 120, 140]),
    a: new Uint8Array([0, 1, 2]),
    v: new Uint8Array([1, 0, 3]),
    ax: new Uint16Array([q(0), q(10_000), q(0)]),
    ay: new Uint16Array([q(0), q(0), q(0)]),
    vx: new Uint16Array([q(10_000), q(0), q(50_000)]),
    vy: new Uint16Array([q(0), q(0), q(0)]),
    dmg: new Uint8Array([30, 45, 20]),
    dr: new Uint8Array([1, 2, 1]),
    w: new Uint16Array([1, 2, 1]),
    ...over,
  }
  return {
    tickMs: TICK,
    worldSize: WORLD,
    hits,
    dicts: {
      dmgReason: ['', 'HeadShot', 'TorsoShot'],
      weapons: ['', 'WeapAK47_C', 'WeapM416_C'],
    },
  } as unknown as ReplayBundle
}

// ---------------------------------------------------------------------------
// damage log
// ---------------------------------------------------------------------------
describe('damageLog', () => {
  it('splits hits by which end the followed player is on', () => {
    const { rows } = damageLog(bundle(), 0, 60_000)
    expect(rows).toHaveLength(2)
    // Newest first.
    expect(rows[0]!.dealt).toBe(false)
    expect(rows[0]!.damage).toBe(45)
    expect(rows[1]!.dealt).toBe(true)
    expect(rows[1]!.damage).toBe(30)
  })

  it('ignores hits the player was not part of', () => {
    const { rows, totals } = damageLog(bundle(), 0, 60_000)
    expect(rows.every((r) => r.other === 1)).toBe(true)
    expect(totals.dealt + totals.taken).toBe(75)
  })

  it('stops at the playhead', () => {
    // The section is sorted by t, so the loop breaks rather than filters —
    // a hit at 12 s must not appear at 11 s.
    expect(damageLog(bundle(), 0, 11_000).rows).toHaveLength(1)
    expect(damageLog(bundle(), 0, 9_000).rows).toHaveLength(0)
  })

  it('totals the whole match, not just the rows it returns', () => {
    // A panel showing twenty rows above a total covering only those twenty
    // would be answering a different question from the one it looks like.
    const { rows, totals } = damageLog(bundle(), 0, 60_000, 1)
    expect(rows).toHaveLength(1)
    expect(totals.dealt).toBe(30)
    expect(totals.taken).toBe(45)
    expect(totals.hitsDealt).toBe(1)
    expect(totals.hitsTaken).toBe(1)
  })

  it('computes range from both endpoints', () => {
    const { rows } = damageLog(bundle(), 0, 60_000)
    // 10,000 cm apart, quantised — 1 step is 12.5 cm on this world size.
    expect(rows[1]!.rangeM).toBeCloseTo(100, 0)
  })

  it('resolves the dictionaries rather than printing indices', () => {
    const { rows } = damageLog(bundle(), 0, 60_000)
    expect(rows[1]!.reason).toBe('HeadShot')
    expect(rows[1]!.weapon).toBe('WeapAK47_C')
  })

  it('is empty for a player with no attributed hits', () => {
    const { rows, totals } = damageLog(bundle(), 9, 60_000)
    expect(rows).toEqual([])
    expect(totals).toEqual({ dealt: 0, taken: 0, hitsDealt: 0, hitsTaken: 0 })
  })

  it('survives a bundle with no hits section at all', () => {
    // Parser versions before 4 have none, and `decodeBundle` substitutes an
    // empty one rather than undefined.
    const empty = bundle({ n: 0, t: new Uint16Array(0), a: new Uint8Array(0) })
    expect(damageLog(empty, 0, 60_000).rows).toEqual([])
  })
})

// ---------------------------------------------------------------------------
// fights
// ---------------------------------------------------------------------------
const engagements: MatchEngagements = {
  gapSeconds: 20,
  engagements: [
    {
      seq: 3,
      tStartS: 300,
      tEndS: 320,
      teamA: 4,
      teamB: 9,
      x: 0,
      y: 0,
      killsA: 1,
      killsB: 0,
      knocksA: 1,
      knocksB: 0,
      thirdPartyTeamId: null,
      accounts: ['account.me', 'account.them'],
    },
    {
      seq: 1,
      tStartS: 100,
      tEndS: 140,
      teamA: 4,
      teamB: 7,
      x: 0,
      y: 0,
      killsA: 0,
      killsB: 2,
      knocksA: 0,
      knocksB: 2,
      thirdPartyTeamId: 12,
      accounts: ['account.me'],
    },
    {
      seq: 2,
      tStartS: 200,
      tEndS: 210,
      teamA: 7,
      teamB: 9,
      x: 0,
      y: 0,
      killsA: 1,
      killsB: 0,
      knocksA: 0,
      knocksB: 0,
      thirdPartyTeamId: null,
      accounts: ['account.other'],
    },
  ],
}

describe('fightsFor', () => {
  it('keeps only the exchanges that account was in, in time order', () => {
    const f = fightsFor(engagements, 'account.me', 4)
    expect(f.map((x) => x.seq)).toEqual([1, 3])
  })

  it('resolves our side from the team, not from the column order', () => {
    // `team_a`/`team_b` are ordered low-first and mean nothing alone. Reading
    // `killsA` as "ours" swaps every result and still looks like a fight list.
    const ours = fightsFor(engagements, 'account.me', 4)
    expect(ours[0]).toMatchObject({ ours: 0, theirs: 2, opponentTeam: 7 })
    expect(ours[1]).toMatchObject({ ours: 1, theirs: 0, opponentTeam: 9 })

    const flipped = fightsFor(engagements, 'account.me', 7)
    expect(flipped[0]).toMatchObject({ ours: 2, theirs: 0, opponentTeam: 4 })
  })

  it('carries the third party through', () => {
    expect(fightsFor(engagements, 'account.me', 4)[0]!.thirdPartyTeam).toBe(12)
  })

  it('is empty rather than throwing on a match with no engagements', () => {
    // A match parsed before v16 has none, and the panel must render nothing
    // instead of an error.
    expect(fightsFor({ gapSeconds: 20, engagements: [] }, 'account.me', 4)).toEqual([])
    expect(fightsFor(undefined, 'account.me', 4)).toEqual([])
  })
})

const fights = (): Fight[] => fightsFor(engagements, 'account.me', 4)

describe('stepFight', () => {
  it('finds the next fight forward', () => {
    expect(stepFight(fights(), 0, 1)?.seq).toBe(1)
    expect(stepFight(fights(), 150_000, 1)?.seq).toBe(3)
  })

  it('finds the previous fight backward', () => {
    expect(stepFight(fights(), 400_000, -1)?.seq).toBe(3)
    expect(stepFight(fights(), 250_000, -1)?.seq).toBe(1)
  })

  it('returns null at the ends rather than wrapping', () => {
    // Wrapping in a scrubbing control reads as a seek failure: press next at
    // the last fight, land at the first, conclude the button is broken.
    expect(stepFight(fights(), 400_000, 1)).toBeNull()
    expect(stepFight(fights(), 0, -1)).toBeNull()
  })

  it('does not re-select the fight you just jumped to', () => {
    // `seekFor` lands before the start, so without a dead zone "next" would
    // immediately return the same fight.
    const f = fights()[0]!
    expect(stepFight(fights(), seekFor(f), 1)?.seq).toBe(f.seq)
    expect(stepFight(fights(), f.startMs, 1)?.seq).toBe(3)
  })

  it('handles an empty list', () => {
    expect(stepFight([], 0, 1)).toBeNull()
    expect(stepFight([], 0, -1)).toBeNull()
  })
})

describe('seekFor', () => {
  it('lands before the first blow, never on it', () => {
    expect(seekFor(fights()[0]!)).toBe(100_000 - FIGHT_LEAD_IN_MS)
  })

  it('never seeks negative', () => {
    expect(seekFor({ ...fights()[0]!, startMs: 1000 })).toBe(0)
  })
})

describe('fightResult', () => {
  const f = (over: Partial<Fight>): Fight => ({
    seq: 0,
    startMs: 0,
    endMs: 0,
    ours: 0,
    theirs: 0,
    knocksOurs: 0,
    knocksTheirs: 0,
    opponentTeam: 1,
    thirdPartyTeam: null,
    ...over,
  })

  it('describes the counts and never judges them', () => {
    // `engagements` stores no verdict on purpose. A fight where you killed two
    // and lost three to a third party is not obviously yours to have lost, and
    // the replay must not reintroduce what the schema refused.
    const texts = [
      fightResult(f({ ours: 2 })),
      fightResult(f({ theirs: 1 })),
      fightResult(f({ ours: 1, theirs: 1 })),
      fightResult(f({ knocksOurs: 1 })),
      fightResult(f({})),
    ]
    for (const t of texts) {
      expect(t).not.toMatch(/\b(won|win|defeat|beaten)\b/i)
    }
    expect(texts).toEqual(['2 down', 'lost 1', '1–1 traded', 'knocks only', 'no casualties'])
  })
})
