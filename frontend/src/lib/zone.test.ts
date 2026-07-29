import { describe, expect, it } from 'vitest'
import type { ZonePhaseRate } from '../api/types'
import { MIN_PHASE_N, circleGaps, circleSentence, rateOf } from './zone'

function phase(over: Partial<ZonePhaseRate> = {}): ZonePhaseRate {
  return {
    phase: 4,
    announceIn: 19,
    announceN: 58,
    closeIn: 24,
    closeN: 58,
    medianEdgeM: 83,
    ...over,
  }
}

describe('rateOf', () => {
  it('returns null on an empty denominator rather than 0', () => {
    // A 0 draws an empty bar labelled "0%", which is a measured claim that the
    // squad was never in the circle — not an absence of data.
    expect(rateOf(0, 0)).toBeNull()
  })

  it('computes a share when there is one', () => {
    expect(rateOf(3, 4)).toBe(0.75)
    expect(rateOf(0, 4)).toBe(0)
  })
})

describe('circleGaps', () => {
  // Measured shape at 68 matches: squad 41% at phase 4 against 47% lobby,
  // 34% at phase 5 against 52%.
  const squad = [
    phase({ phase: 4, closeIn: 24, closeN: 58 }),
    phase({ phase: 5, closeIn: 12, closeN: 35 }),
    phase({ phase: 3, closeIn: 46, closeN: 75 }),
  ]
  const lobby = [
    phase({ phase: 4, closeIn: 851, closeN: 1821 }),
    phase({ phase: 5, closeIn: 593, closeN: 1147 }),
    phase({ phase: 3, closeIn: 1122, closeN: 2492 }),
  ]

  it('finds the phases where the squad is behind, worst first', () => {
    // Phase 5 is 34% against 52% — an 18-point gap. Phase 4 is 41% against
    // 47%, only 5 points, which is below the default threshold and stays out
    // deliberately: a five-point difference on 58 rows is not a finding.
    const gaps = circleGaps(squad, lobby)
    expect(gaps.map((g) => g.phase)).toEqual([5])
    expect(circleGaps(squad, lobby, 0.04).map((g) => g.phase)).toEqual([5, 4])
  })

  it('ignores phases where the squad is ahead', () => {
    // Phase 3 is 61% against 45% — the squad leads, so it is not a gap.
    expect(circleGaps(squad, lobby).find((g) => g.phase === 3)).toBeUndefined()
  })

  it('ignores phases with too few rows to compare', () => {
    const thin = [phase({ phase: 9, closeIn: 0, closeN: MIN_PHASE_N - 1 })]
    const wide = [phase({ phase: 9, closeIn: 500, closeN: 900 })]
    expect(circleGaps(thin, wide)).toEqual([])
  })

  it('ignores a phase the lobby barely reached either', () => {
    const s = [phase({ phase: 9, closeIn: 2, closeN: 40 })]
    const l = [phase({ phase: 9, closeIn: 8, closeN: MIN_PHASE_N - 1 })]
    expect(circleGaps(s, l)).toEqual([])
  })

  it('ignores a gap too small to be worth a sentence', () => {
    const s = [phase({ phase: 4, closeIn: 49, closeN: 100 })]
    const l = [phase({ phase: 4, closeIn: 52, closeN: 1000 })]
    expect(circleGaps(s, l)).toEqual([])
  })

  it('respects a caller-supplied threshold', () => {
    const s = [phase({ phase: 4, closeIn: 49, closeN: 100 })]
    const l = [phase({ phase: 4, closeIn: 520, closeN: 1000 })]
    expect(circleGaps(s, l)).toEqual([])
    expect(circleGaps(s, l, 0.01)).toHaveLength(1)
  })

  it('handles a lobby with no matching phase', () => {
    expect(circleGaps(squad, [])).toEqual([])
  })

  it('never divides by zero', () => {
    const s = [phase({ phase: 4, closeIn: 0, closeN: 0 })]
    const l = [phase({ phase: 4, closeIn: 0, closeN: 0 })]
    expect(circleGaps(s, l)).toEqual([])
  })
})

describe('circleSentence', () => {
  it('carries both rates and the squad n', () => {
    const text = circleSentence([
      { phase: 5, squad: 0.34, lobby: 0.52, gap: -0.18, n: 35 },
      { phase: 4, squad: 0.41, lobby: 0.47, gap: -0.06, n: 58 },
    ])
    expect(text).toContain('phase 5')
    expect(text).toContain('34% of 35')
    expect(text).toContain('52% for the lobby')
  })

  it('mentions at most two phases', () => {
    const many = [1, 2, 3, 4].map((p) => ({
      phase: p,
      squad: 0.2,
      lobby: 0.5,
      gap: -0.3,
      n: 40,
    }))
    const text = circleSentence(many) ?? ''
    expect(text).not.toContain('phase 3')
  })

  it('returns null rather than reassuring anyone', () => {
    // No measurable gap is not evidence of good discipline, and a sentence
    // saying otherwise would claim it is.
    expect(circleSentence([])).toBeNull()
  })
})
