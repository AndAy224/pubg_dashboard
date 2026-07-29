/**
 * Findings about fights — and the one place in this app that has to say
 * "we made this number up a bit".
 *
 * `findings.ts` states claims built on wire facts: a kill happened, a knock
 * became a death, a player was inside a circle PUBG named them in. Everything
 * here is built on `engagements`, whose rows are a **grouping the parser
 * invents** by cutting the stream of cross-team blows at a silence of
 * `gapSeconds`. The sweep behind that constant found no knee anywhere from 5 s
 * to 120 s, so the count of fights is a modelling choice and every rate over
 * it inherits that.
 *
 * Two rules follow, and both are tested:
 *
 * 1. **Every sentence that quotes a fight count names the gap.** `caveat()`
 *    builds that clause once so no card can forget it.
 * 2. **The first-hit rates are only ever stated as a pair.** "We end ahead in
 *    76% of the fights we open" is meaningless without "and 24% of the ones we
 *    do not", because a fight has one first hit and the two rates are two views
 *    of the same split. Quoting one alone reads as an effect and is a base
 *    rate.
 *
 * The same `Finding` shape and the same `MIN_N` suppression as `findings.ts` —
 * see that module for why n is never optional and why there are no p-values.
 */

import type { Finding } from './findings'
import { MIN_N, rateText } from './findings'
import type { EngagementRangeRow, Rate, SquadEngagements } from '../api/types'

/**
 * The marker that has to travel with any count of fights.
 *
 * Deliberately terse. The section header spells the choice out in full; five
 * findings each ending in "grouped by a 20 s silence between the same two
 * teams" was the first draft and it buried the findings under the disclaimer,
 * which is its own kind of dishonesty — a caveat nobody finishes reading is
 * not a caveat. This is short enough to survive being read every time and
 * still carries the number, which is the part that has to be there.
 */
export function caveat(gapSeconds: number): string {
  return `grouped at a ${gapSeconds} s gap`
}

/** How far apart two rates must be before the difference is worth a sentence.
 *
 *  Ten points on samples of a few hundred fights. Below it the pair is still
 *  shown in the table — this only governs whether a *claim* gets made. */
const MIN_GAP = 0.1

function bandLabel(b: EngagementRangeRow): string {
  return b.hiM === null ? `beyond ${b.loM} m` : `${b.loM}–${b.hiM} m`
}

/** Null unless both rates are measurable, so a caller cannot compare against
 *  a missing denominator and get a confident zero. */
function gapBetween(a: Rate, b: Rate): number | null {
  if (a.pct === null || b.pct === null) return null
  return a.pct - b.pct
}

/**
 * The fight findings, from one `/review/engagements` payload.
 *
 * The numbers in the comments are what the corpus produced when each sentence
 * was written, so a wildly different figure later is a signal rather than a
 * surprise.
 */
export function engagementFindings(e: SquadEngagements): Finding[] {
  const out: Finding[] = []
  const note = caveat(e.gapSeconds)

  // --- landing the first blow -------------------------------------------
  // Measured across the corpus: the side that lands the first hit ends ahead
  // on kills in 76% of decided fights. Stated as the pair, never as one rate.
  //
  // **"First hit", never "opened the fight".** `LogPlayerAttack` carries no
  // victim, so a shot that missed belongs to nobody — a team that fired first
  // and missed appears in this data as the team that got shot at. The wording
  // is the entire mitigation and no sentence here may loosen it.
  const gap = gapBetween(e.aheadWhenFirst, e.aheadWhenNotFirst)
  const first = rateText(e.aheadWhenFirst)
  const notFirst = rateText(e.aheadWhenNotFirst)
  if (gap !== null && first !== null && notFirst !== null && Math.abs(gap) > MIN_GAP) {
    out.push({
      id: 'first-hit-advantage',
      text: `When you land the first blow you end a fight ahead on kills ${first}; when the other side does, ${notFirst}. (${note}.)`,
      n: e.aheadWhenFirst.total + e.aheadWhenNotFirst.total,
      strength: Math.abs(gap) * 1.5,
      tone: gap > 0 ? 'good' : 'bad',
    })
  }

  // How often we are the ones landing it. A separate question from whether it
  // helps, and the one that is actually about how the squad plays.
  const ours = rateText(e.firstHitOurs)
  if (ours !== null && e.firstHitOurs.pct !== null) {
    const pct = e.firstHitOurs.pct
    out.push({
      id: 'first-hit-share',
      text: `You land the first blow in ${ours} of the fights that someone dies in. (${note}.)`,
      n: e.firstHitOurs.total,
      // Distance from an even split. A squad that opens half its fights is
      // unremarkable; one that opens a fifth of them is the finding.
      strength: Math.abs(pct - 0.5) * 2,
      tone: pct > 0.55 ? 'good' : pct < 0.45 ? 'bad' : 'neutral',
    })
  }

  // --- third parties ------------------------------------------------------
  // A different measure from `findings.ts`'s third-party rate, and the page
  // has to keep them apart: that one is "another team's kill near our death",
  // this one is "another team's fight overlapping ours", so the denominators
  // are deaths and fights respectively.
  const third = rateText(e.thirdParty)
  if (third !== null) {
    out.push({
      id: 'engagement-third-party',
      text: `${third} of your fights had a third team fighting one of the two sides at the same time, within ${e.thirdPartyRadiusM} m.`,
      n: e.thirdParty.total,
      strength: (e.thirdParty.pct ?? 0) * 1.2,
      tone: (e.thirdParty.pct ?? 0) > 0.25 ? 'bad' : 'neutral',
    })
  }

  // --- how they end -------------------------------------------------------
  const byKey = new Map(e.results.map((r) => [r.key, r]))
  const oursOnly = byKey.get('ours_only')?.n ?? 0
  const theirsOnly = byKey.get('theirs_only')?.n ?? 0
  const decided = oursOnly + theirsOnly
  if (decided >= MIN_N) {
    const share = oursOnly / decided
    out.push({
      id: 'one-sided-fights',
      text: `Of the ${decided} fights where only one side lost anyone, ${oursOnly} went your way and ${theirsOnly} did not. (${note}.)`,
      n: decided,
      strength: Math.abs(share - 0.5) * 2,
      tone: share > 0.55 ? 'good' : share < 0.45 ? 'bad' : 'neutral',
    })
  }

  // A fact worth stating because the word "fight" oversells these rows:
  // measured, a third of exchanges are one side landing a couple of hits at
  // range and nothing coming of it.
  const neither = byKey.get('neither')?.n ?? 0
  if (e.fights >= MIN_N && neither > 0) {
    out.push({
      id: 'undecided-fights',
      text: `${neither} of your ${e.fights} exchanges ended with nobody dying — most contact is a few shots at range, not a fight. (${note}.)`,
      n: e.fights,
      strength: 0.2,
      tone: 'neutral',
    })
  }

  // --- range --------------------------------------------------------------
  // Bucketed by where the *first blow landed*, which is the only range an
  // exchange has that is not an average over a moving fight.
  const bands = e.rangeBands.filter((b) => b.fights >= MIN_N && b.weKilled + b.weDied >= MIN_N)
  const worst = [...bands].sort(
    (a, b) => a.weKilled / (a.weKilled + a.weDied) - b.weKilled / (b.weKilled + b.weDied),
  )[0]
  if (worst) {
    const total = worst.weKilled + worst.weDied
    const ratio = worst.weKilled / total
    if (ratio < 0.5) {
      out.push({
        id: 'engagement-worst-range',
        text: `Fights whose first blow lands ${bandLabel(worst)} go worst: ${worst.weKilled} kills against ${worst.weDied} deaths across ${worst.fights} of them. (${note}.)`,
        n: total,
        strength: (0.5 - ratio) * 1.8,
        tone: 'bad',
      })
    }
  }

  // --- who takes the damage ----------------------------------------------
  // `damageTakenAvg` has no counterpart anywhere else in the app. Stated only
  // as a contrast between two players, and only when they are far enough
  // apart to be worth a sentence — a single player's average has no baseline
  // to be good or bad against, which is the same reason the revive rate in
  // `findings.ts` is toned neutral.
  const players = e.players.filter((p) => p.fights >= MIN_N)
  if (players.length >= 2) {
    const sorted = [...players].sort((a, b) => b.damageTakenAvg - a.damageTakenAvg)
    const most = sorted[0]!
    const least = sorted[sorted.length - 1]!
    if (most.damageTakenAvg > least.damageTakenAvg * 1.25) {
      out.push({
        id: 'damage-taken-spread',
        text: `${most.name} takes ${Math.round(most.damageTakenAvg)} damage in the average fight against ${Math.round(least.damageTakenAvg)} for ${least.name}, over ${most.fights} and ${least.fights} fights.`,
        n: most.fights + least.fights,
        strength: Math.min(1, most.damageTakenAvg / Math.max(1, least.damageTakenAvg) - 1),
        // Neutral: taking more damage is what an entry fragger does on
        // purpose. Nothing in the data says which of the two is playing badly.
        tone: 'neutral',
      })
    }
  }

  return out
}
