/**
 * Findings about how the squad dies, and the replay links to go and look.
 *
 * Third sibling of `findings.ts` and `engagements.ts`, under the same rules:
 * every claim carries its `n`, no p-values, no causal phrasing, and `null`
 * means "not measurable" rather than zero.
 *
 * One rule is specific to this module. **A rate about deaths is only a finding
 * if it differs from the rate when we are not dying.** `circleSentence()` is
 * the whole reason: 61% of the squad's deaths happen while they are outside
 * the last circle to close, which reads as a serious problem right up until
 * you measure how often they are outside it in general — 56%. Shipping the
 * first number alone would have been a confident, plausible, useless claim,
 * and it is exactly the kind this codebase keeps finding.
 *
 * So the comparison is stated as a pair, and when the two are close the
 * sentence says so in as many words instead of going quiet. A silent absence
 * would leave the reader to assume nobody had checked.
 */

import type { DeathListRow, Rate, SquadDeaths } from '../api/types'
import type { Finding } from './findings'
import { MIN_N, rateText } from './findings'

/** How far apart two rates must be before the difference is worth calling a
 *  difference. Six points separates the circle pair today, which is inside
 *  this — deliberately, because it is not a finding. */
const MIN_GAP = 0.1

/**
 * Where in the replay to go and watch a death happen.
 *
 * `?follow=` is parsed by `pages/Replay.tsx` and until now **nothing in the
 * app produced it**. A death row is the most useful thing that could: it is a
 * specific player at a specific second.
 *
 * The seek lands `LEAD_IN` seconds early on purpose. Arriving at the exact
 * instant of death shows a corpse; the question a review asks is what was
 * happening just before, and the fight that killed someone has usually been
 * running for a few seconds by then.
 */
export const LEAD_IN_S = 15

export function replayLink(row: DeathListRow): string {
  const t = Math.max(0, Math.round(row.tS - LEAD_IN_S))
  return `/matches/${row.matchId}/replay?t=${t}&follow=${encodeURIComponent(row.accountId)}`
}

/**
 * The circle comparison, always as a pair and never as one number.
 *
 * Returns a sentence in both cases — a difference and the absence of one —
 * because "we checked and it is the same" is information, and an empty space
 * where a claim would be is not.
 */
export function circleSentence(c: {
  atDeath: Rate
  baseline: Rate
}): { text: string; different: boolean } | null {
  const at = rateText(c.atDeath)
  const base = rateText(c.baseline)
  if (at === null || base === null) return null
  const gap = (c.atDeath.pct ?? 0) - (c.baseline.pct ?? 0)
  if (Math.abs(gap) < MIN_GAP) {
    return {
      text: `You were outside the last circle to close on ${at} of your deaths — against ${base} of every circle you were alive for. The same, so being out of the circle is not what is killing you.`,
      different: false,
    }
  }
  return {
    text:
      gap > 0
        ? `You were outside the last circle to close on ${at} of your deaths, against ${base} of every circle you were alive for.`
        : `You were outside the last circle to close on ${at} of your deaths — less often than the ${base} of circles you were alive for.`,
    different: true,
  }
}

/** Human label for one death row's flags, in a fixed order. */
export function tagsFor(row: DeathListRow): string[] {
  const out: string[] = []
  if (row.thirdPartied) out.push('third-partied')
  if (row.knockedFirst) out.push('knocked first')
  // `=== true`, not truthiness: null is "not measured" on a match parsed
  // before v17 and must not render as a claim either way.
  if (row.alone === true) out.push('last one up')
  else if (row.nearestTeammateM !== null && row.nearestTeammateM > 100) {
    out.push(`${Math.round(row.nearestTeammateM)} m from the squad`)
  }
  if (row.parachuting === true) out.push('still in the air')
  if (row.inVehicle === true) out.push('in a vehicle')
  if (row.killerIsBot === true) out.push('to a bot')
  return out
}

/**
 * The death findings, from one `/review/deaths` payload.
 *
 * Numbers in the comments are what the archive produced when each was
 * written, so a wildly different figure later is a signal rather than a
 * surprise.
 */
export function deathFindings(d: SquadDeaths): Finding[] {
  const out: Finding[] = []

  // --- alone ------------------------------------------------------------
  // Not a criticism. Somebody has to be the last one up, and in solo it is
  // everyone — which is why the sentence says what it is rather than what it
  // implies, and the tone stays neutral.
  const alone = rateText(d.alone)
  if (alone !== null && d.alone.total >= MIN_N) {
    out.push({
      id: 'died-alone',
      text: `${alone} of your deaths came with no teammate left in the match — the last of the squad up, or a solo match.`,
      n: d.alone.total,
      strength: 0.3,
      tone: 'neutral',
    })
  }

  // --- isolated ---------------------------------------------------------
  // The denominator is deaths where somebody *was* still alive. Over all
  // deaths it would be diluted by every solo match and read far lower.
  const isolated = rateText(d.isolated)
  if (isolated !== null && d.isolated.total >= MIN_N && d.isolated.pct !== null) {
    out.push({
      id: 'died-isolated',
      text: `When a teammate was still up, you died more than ${d.isolatedRadiusM} m from the nearest one ${isolated} times.`,
      n: d.isolated.total,
      strength: d.isolated.pct,
      tone: d.isolated.pct > 0.3 ? 'bad' : 'neutral',
    })
  }

  // --- third party ------------------------------------------------------
  // Measured 39 of 195 (20%) from the fight model. `findings.ts` states a
  // near-identical 44 of 195 (23%) from kill proximity — two independent
  // derivations, so the page shows both and says they are different measures
  // rather than picking one and hiding the other.
  const third = rateText(d.thirdPartied)
  if (third !== null && d.thirdPartied.total >= MIN_N) {
    out.push({
      id: 'death-third-party',
      text: `${third} of your deaths happened in a fight another team had joined.`,
      n: d.thirdPartied.total,
      strength: (d.thirdPartied.pct ?? 0) * 1.3,
      tone: (d.thirdPartied.pct ?? 0) > 0.25 ? 'bad' : 'neutral',
    })
  }

  return out
}
