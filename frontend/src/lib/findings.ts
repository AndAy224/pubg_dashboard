/**
 * Turning counts into sentences, without claiming more than the data supports.
 *
 * The Strategy page already contrasts eleven metrics between good and bad
 * placements, and the reader is left to infer what any of it means. This module
 * is the missing half: it states findings in words. That is a much easier place
 * to overclaim, so the rules are enforced here rather than left to whoever
 * writes the next card.
 *
 * **Every finding carries its `n`, and `n` is not optional.** With 41-93
 * matches per player and a 195-death archive, the sample is the part most
 * likely to make a claim worthless, and a percentage that has shed its
 * denominator cannot be argued with.
 *
 * **No p-values, no significance stars, no confidence intervals.** At ten
 * matches a side an interval would be so wide it would either be ignored or
 * misread as precision. `strength` exists only to order the list and is never
 * rendered.
 *
 * **No causal phrasing.** "In your best ten finishes, rotation lag averaged
 * 22 s; in your worst ten, 71 s" is the ceiling. "Rotate earlier to place
 * better" is not available from 40 observational matches, and writing it would
 * make the page confidently wrong in the one way that actually changes what
 * someone does in a match.
 *
 * `null` means "not measurable" everywhere, never 0 — inherited from
 * `strategy.ts`, and the distinction that keeps "we never did this" separate
 * from "we cannot tell".
 */

import type { Rate, SquadReview } from '../api/types'

/** How few observations is too few to say anything at all.
 *
 *  Below this a finding is dropped rather than hedged. A sentence with a
 *  caveat still gets read as a finding; an absent sentence does not. */
export const MIN_N = 8

export type Tone = 'good' | 'bad' | 'neutral'

export interface Finding {
  id: string
  /** The claim, already carrying its numbers. Rendered verbatim. */
  text: string
  /** Observations behind it. Never optional, never inferred by the caller. */
  n: number
  /** Ranking only — never rendered, never described to the reader as a
   *  strength, a confidence or a significance. */
  strength: number
  tone: Tone
}

/**
 * Format a rate as "122 of 200 (61%)".
 *
 * Returns null when the denominator is empty, so a caller cannot accidentally
 * print "0 of 0 (0%)" — three numbers, none of them measured.
 */
export function rateText(rate: Rate): string | null {
  if (rate.total === 0 || rate.pct === null) return null
  return `${rate.n} of ${rate.total} (${Math.round(rate.pct * 100)}%)`
}

/**
 * Order findings for display and drop the ones too thin to state.
 *
 * Sorting is by `strength` descending with `id` as a tiebreak, so the order is
 * total and stable — two findings with equal strength must not swap between
 * renders depending on array order.
 *
 * The ordering itself is a browsing aid, not a result: on samples this size the
 * rank order is noisy, and the UI says so next to the list rather than letting
 * position imply importance.
 */
export function rankFindings(findings: readonly Finding[], minN = MIN_N): Finding[] {
  return findings
    .filter((f) => f.n >= minN)
    .sort((a, b) => b.strength - a.strength || a.id.localeCompare(b.id))
}

/**
 * How far a rate sits from an even split, scaled to [0, 1].
 *
 * A 50% rate is unremarkable; 90% or 10% is worth reading first. This is a
 * display ordering heuristic and nothing more — deliberately not a test
 * statistic, because anything that looked like one would get quoted as one.
 */
function lopsidedness(rate: Rate): number {
  if (rate.pct === null) return 0
  return Math.abs(rate.pct - 0.5) * 2
}

/**
 * The squad findings, built from one `/review/squad` payload.
 *
 * Every sentence here was checked against the archive before it was written;
 * the numbers in the comments are what it produced at 97 matches, so a wildly
 * different figure later is a signal rather than a surprise.
 */
export function squadFindings(review: SquadReview): Finding[] {
  const out: Finding[] = []

  // --- knock conversion, both directions --------------------------------
  // Measured 122/200 (61.0%) and 112/182 (61.5%). These came out almost
  // identical, which is itself the finding: an earlier time-window derivation
  // suggested an asymmetry that did not survive using PUBG's own knock-to-kill
  // link. Do not write "we are worse at finishing than they are" unless the
  // numbers actually say so.
  const made = rateText(review.knocks.made)
  const taken = rateText(review.knocks.taken)
  if (made !== null && taken !== null) {
    const gap = (review.knocks.made.pct ?? 0) - (review.knocks.taken.pct ?? 0)
    const sameish = Math.abs(gap) < 0.05
    out.push({
      id: 'knock-conversion',
      text: sameish
        ? `You finish ${made} of the knocks you land. Opponents finish ${taken} of the knocks they land on you — the same rate, within noise.`
        : gap > 0
          ? `You finish ${made} of the knocks you land, against ${taken} for opponents knocking you. You convert more of your knocks than they do.`
          : `You finish ${made} of the knocks you land, against ${taken} for opponents knocking you. They convert more of their knocks than you do.`,
      n: review.knocks.made.total + review.knocks.taken.total,
      strength: sameish ? 0.25 : Math.abs(gap) * 2,
      tone: sameish ? 'neutral' : gap > 0 ? 'good' : 'bad',
    })
  }

  // Survived knocks — the complement, stated directly because "61% became
  // deaths" and "39% got back up" land very differently on a reader.
  //
  // Tone is **neutral regardless of the number**. There is no baseline
  // anywhere for what a good revive rate is, so colouring 38% red would be
  // inventing a standard and then failing the squad against it. Tone is only
  // used where the data itself says which way is better — a losing trade
  // ratio, or a side-by-side comparison.
  if (review.knocks.taken.total > 0 && review.knocks.taken.pct !== null) {
    const survived = review.knocks.taken.total - review.knocks.taken.n
    const pct = 1 - review.knocks.taken.pct
    out.push({
      id: 'knock-survival',
      text: `You got back up from ${survived} of ${review.knocks.taken.total} knocks against you (${Math.round(pct * 100)}%).`,
      n: review.knocks.taken.total,
      strength: lopsidedness(review.knocks.taken) * 0.8,
      tone: 'neutral',
    })
  }

  // --- third party ------------------------------------------------------
  // Measured 44 of 195 (23%). The thresholds travel with the claim because
  // they are a choice, not a wire fact.
  const third = rateText(review.thirdParty)
  if (third !== null) {
    out.push({
      id: 'third-party',
      text: `${third} of your deaths had another team's kill within ${review.thirdPartyRadiusM} m in the ${review.thirdPartyWindowS} s beforehand — a fight you were probably not the only party to.`,
      n: review.thirdParty.total,
      strength: (review.thirdParty.pct ?? 0) * 1.5,
      tone: (review.thirdParty.pct ?? 0) > 0.25 ? 'bad' : 'neutral',
    })
  }

  // --- how deaths arrive -------------------------------------------------
  const byCause = new Map(review.deathCauses.map((c) => [c.cause, c]))
  const knockedFirst = byCause.get('knocked_first')
  if (knockedFirst && review.deaths > 0) {
    const pct = knockedFirst.n / review.deaths
    out.push({
      id: 'knocked-first',
      text: `${knockedFirst.n} of your ${review.deaths} deaths were a knock that got finished (${Math.round(pct * 100)}%); the rest were outright kills.`,
      n: review.deaths,
      strength: 0.4,
      tone: 'neutral',
    })
  }

  const early = byCause.get('early')
  if (early && review.deaths > 0) {
    const pct = early.n / review.deaths
    out.push({
      id: 'early-deaths',
      text: `${early.n} of ${review.deaths} deaths came ${early.label} — drop fights rather than rotations (${Math.round(pct * 100)}%).`,
      n: review.deaths,
      strength: pct,
      tone: pct > 0.35 ? 'bad' : 'neutral',
    })
  }

  // A genuinely measured zero is worth stating once. It is also the only
  // place in this module where 0 is printed as a result rather than
  // suppressed — because the denominator is large and the claim is about
  // absence, not about missing data.
  const toBot = byCause.get('to_bot')
  if (toBot && review.deaths >= MIN_N && toBot.n === 0) {
    out.push({
      id: 'no-bot-deaths',
      text: `No bot has ever killed you: 0 of ${review.deaths} deaths.`,
      n: review.deaths,
      strength: 0.15,
      tone: 'good',
    })
  }

  // --- who goes down first ----------------------------------------------
  // Measured DaddyGainz 32/71, SIERIUS_ 28/71, AndAy 11/38. Stated as a
  // share, because the three players have different match counts and raw
  // counts would rank whoever plays most.
  const eligible = review.firstDeaths.filter((r) => r.squadMatches >= MIN_N)
  if (eligible.length >= 2) {
    const shares = eligible.map((r) => ({ ...r, share: r.diedFirst / r.squadMatches }))
    shares.sort((a, b) => b.share - a.share)
    const top = shares[0]!
    const bottom = shares[shares.length - 1]!
    if (top.share - bottom.share > 0.1) {
      out.push({
        id: 'first-death',
        text: `${top.name} is first of the squad to go down in ${top.diedFirst} of ${top.squadMatches} shared matches (${Math.round(top.share * 100)}%), against ${Math.round(bottom.share * 100)}% for ${bottom.name}.`,
        n: shares.reduce((sum, r) => sum + r.squadMatches, 0),
        strength: (top.share - bottom.share) * 1.2,
        tone: 'neutral',
      })
    }
  }

  // --- range ------------------------------------------------------------
  // Where the squad's fights actually happen, and where they go badly.
  // Bands above 150 m carry single-digit counts, so each band states its own
  // totals and no trend is drawn across them.
  const bands = review.rangeBands.filter((b) => b.weKilled + b.weDied >= MIN_N)
  const worst = [...bands].sort(
    (a, b) => a.weKilled / (a.weKilled + a.weDied) - b.weKilled / (b.weKilled + b.weDied),
  )[0]
  if (worst) {
    const total = worst.weKilled + worst.weDied
    const span = worst.hiM === null ? `beyond ${worst.loM} m` : `${worst.loM}-${worst.hiM} m`
    const ratio = worst.weKilled / total
    if (ratio < 0.5) {
      out.push({
        id: 'worst-range',
        text: `At ${span} you trade worst: ${worst.weKilled} kills against ${worst.weDied} deaths.`,
        n: total,
        strength: (0.5 - ratio) * 2,
        tone: 'bad',
      })
    }
  }

  const busiest = [...review.rangeBands].sort(
    (a, b) => b.weKilled + b.weDied - (a.weKilled + a.weDied),
  )[0]
  if (busiest) {
    const total = busiest.weKilled + busiest.weDied
    const span = busiest.hiM === null ? `beyond ${busiest.loM} m` : `${busiest.loM}-${busiest.hiM} m`
    out.push({
      id: 'busiest-range',
      text: `Most of your fights are at ${span}: ${total} of your kills and deaths combined.`,
      n: total,
      strength: 0.3,
      tone: 'neutral',
    })
  }

  return out
}
