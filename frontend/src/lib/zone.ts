/**
 * Reading circle discipline out of the per-phase rates.
 *
 * Pure, so the wording rules are testable without a server — the same
 * discipline `findings.ts` uses, and for the same reason: this is the point
 * where numbers turn into a sentence someone might act on.
 */

import type { ZonePhaseRate } from '../api/types'

/** A share, or null when nothing was measurable. **Never 0** — a 0 is a
 *  measured claim that the squad was never in the circle. */
export function rateOf(hit: number, n: number): number | null {
  return n > 0 ? hit / n : null
}

/** Phases with fewer rows than this are not compared against the lobby. Late
 *  phases are reached rarely and a 4-of-6 rate is not a rate. */
export const MIN_PHASE_N = 15

export interface CircleGap {
  phase: number
  squad: number
  lobby: number
  /** Signed: negative means the squad is behind the lobby. */
  gap: number
  n: number
}

/**
 * Phases where the squad is measurably behind the rest of the lobby at the
 * deadline, worst first.
 *
 * Only the **close** is compared. Being outside when a circle is announced is
 * normal — most of the lobby is — so a gap there says nothing. The close is
 * the moment the blue starts moving, which is the one that costs games.
 *
 * `minGap` exists so a two-point difference on 20 rows does not become a
 * sentence. It is a display threshold, not a significance test, and the UI
 * prints the counts alongside so the reader can disagree.
 */
export function circleGaps(
  squad: readonly ZonePhaseRate[],
  lobby: readonly ZonePhaseRate[],
  minGap = 0.08,
): CircleGap[] {
  const byPhase = new Map(lobby.map((p) => [p.phase, p]))
  const out: CircleGap[] = []
  for (const phase of squad) {
    if (phase.closeN < MIN_PHASE_N) continue
    const other = byPhase.get(phase.phase)
    if (!other || other.closeN < MIN_PHASE_N) continue
    const a = rateOf(phase.closeIn, phase.closeN)
    const b = rateOf(other.closeIn, other.closeN)
    if (a === null || b === null) continue
    if (b - a >= minGap) {
      out.push({ phase: phase.phase, squad: a, lobby: b, gap: a - b, n: phase.closeN })
    }
  }
  return out.sort((x, y) => x.gap - y.gap)
}

/**
 * One sentence about the worst phases, or null when there is nothing to say.
 *
 * Null rather than "you're doing fine": the absence of a measurable gap is not
 * evidence of good discipline, and a reassuring sentence would claim it is.
 */
export function circleSentence(gaps: readonly CircleGap[]): string | null {
  if (gaps.length === 0) return null
  const worst = gaps.slice(0, 2)
  const parts = worst.map(
    (g) =>
      `phase ${g.phase} (${Math.round(g.squad * 100)}% of ${g.n} against ${Math.round(
        g.lobby * 100,
      )}% for the lobby)`,
  )
  return `You reach the circle less often than the rest of the lobby at ${parts.join(' and ')}.`
}
