/**
 * The followed player's combat, out of the replay bundle and the fight model.
 *
 * Two things the replay could not show before. `bundle.hits` has carried every
 * attributed hit — both endpoints, damage, body part, weapon — since parser v4,
 * and the renderer used it only to colour tracers, so the numbers were on the
 * wire and never on the screen. And a match's exchanges lived in SQL with no
 * way to jump to one.
 *
 * Pure, and tested in node with no DOM — the whole reason this repo puts replay
 * logic in `lib/` rather than in the panel that renders it.
 *
 * **Fights are not re-derived here.** They come from
 * `GET /matches/{id}/engagements`, which is the parser's own grouping at the
 * parser's own `gapSeconds`. Segmenting `bundle.hits` in the browser would have
 * been quicker and would have silently disagreed with `/review/engagements`
 * about how many fights a match contained — one model, one constant.
 */

import type { MatchEngagementRow, MatchEngagements } from '../api/types'
import type { ReplayBundle } from './replayBundle'
import { dictName, toCm } from './replayBundle'

/** One attributed hit involving the followed player. */
export interface DamageRow {
  tMs: number
  /** True when they landed it, false when they took it. */
  dealt: boolean
  /** Bundle index of the other end. */
  other: number
  /** Rounded to a byte by the bundle; real damage caps at 100. */
  damage: number
  /** HeadShot / TorsoShot / … — raw, since the caller formats. */
  reason: string
  weapon: string
  /** METRES between the two endpoints at the moment it landed. */
  rangeM: number
}

export interface DamageTotals {
  dealt: number
  taken: number
  hitsDealt: number
  hitsTaken: number
}

/**
 * Every hit involving `playerIndex` at or before `nowMs`, newest first.
 *
 * The whole section is scanned rather than cursored. It is ~550 entries per
 * match and this runs at the store's 10 Hz, not at 60 — a cursor would be the
 * kind of optimisation that outlives the reason for it and then breaks on a
 * seek backwards.
 *
 * `limit` truncates the returned rows but **not** the totals: a damage panel
 * that showed twenty rows and a total matching only those twenty would be
 * quietly answering a different question from the one it looks like it answers.
 */
export function damageLog(
  bundle: ReplayBundle,
  playerIndex: number,
  nowMs: number,
  limit = 40,
): { rows: DamageRow[]; totals: DamageTotals } {
  const h = bundle.hits
  const totals: DamageTotals = { dealt: 0, taken: 0, hitsDealt: 0, hitsTaken: 0 }
  const rows: DamageRow[] = []

  for (let i = 0; i < h.n; i++) {
    const tMs = h.t[i]! * bundle.tickMs
    if (tMs > nowMs) break // sorted by t, so nothing later can qualify
    const attacker = h.a[i]!
    const victim = h.v[i]!
    const dealt = attacker === playerIndex
    if (!dealt && victim !== playerIndex) continue

    const damage = h.dmg[i]!
    if (dealt) {
      totals.dealt += damage
      totals.hitsDealt += 1
    } else {
      totals.taken += damage
      totals.hitsTaken += 1
    }

    const ws = bundle.worldSize
    rows.push({
      tMs,
      dealt,
      other: dealt ? victim : attacker,
      damage,
      reason: dictName(bundle.dicts, 'dmgReason', h.dr[i]!),
      weapon: dictName(bundle.dicts, 'weapons', h.w[i]!),
      // Both endpoints are quantised to 65,535 steps across the world, so on
      // Erangel one step is 12.5 cm. Irrelevant at a range readout in metres,
      // and the only reason a tracer can be drawn at all.
      rangeM:
        Math.hypot(
          toCm(h.ax[i]!, ws) - toCm(h.vx[i]!, ws),
          toCm(h.ay[i]!, ws) - toCm(h.vy[i]!, ws),
        ) / 100,
    })
  }

  // Newest first, and truncated after the totals are complete.
  rows.reverse()
  return { rows: rows.slice(0, limit), totals }
}

/** One exchange the followed player was in, with their side resolved. */
export interface Fight {
  seq: number
  startMs: number
  endMs: number
  /** Kills their side made, and kills the other side made. */
  ours: number
  theirs: number
  knocksOurs: number
  knocksTheirs: number
  /** The team on the other side of this exchange. */
  opponentTeam: number
  thirdPartyTeam: number | null
}

/**
 * The exchanges one account was in, in time order.
 *
 * `teamId` is needed because `team_a`/`team_b` are ordered low-first and mean
 * nothing on their own — "our side" is whichever of the two the account is on,
 * exactly as `/review/engagements` resolves it server-side. Passing the wrong
 * team silently swaps every kill count, and the result still looks like a
 * plausible fight list.
 */
export function fightsFor(
  data: MatchEngagements | undefined,
  accountId: string,
  teamId: number,
): Fight[] {
  if (!data) return []
  return data.engagements
    .filter((e: MatchEngagementRow) => e.accounts.includes(accountId))
    .map((e) => {
      const weAreA = teamId === e.teamA
      return {
        seq: e.seq,
        startMs: Math.round(e.tStartS * 1000),
        endMs: Math.round(e.tEndS * 1000),
        ours: weAreA ? e.killsA : e.killsB,
        theirs: weAreA ? e.killsB : e.killsA,
        knocksOurs: weAreA ? e.knocksA : e.knocksB,
        knocksTheirs: weAreA ? e.knocksB : e.knocksA,
        opponentTeam: weAreA ? e.teamB : e.teamA,
        thirdPartyTeam: e.thirdPartyTeamId,
      }
    })
    .sort((a, b) => a.startMs - b.startMs || a.seq - b.seq)
}

/**
 * The fight to jump to from `nowMs`, in `dir` (+1 next, -1 previous).
 *
 * Returns null at either end rather than wrapping. Wrapping in a scrubbing
 * control is disorienting: pressing "next" at the last fight and landing back
 * at the first reads as a seek failure.
 *
 * "Next" is the first fight starting **after** now, with a small dead zone so
 * that pressing next immediately after a jump does not re-select the fight you
 * just landed on — the jump itself seeks a few seconds early, which would
 * otherwise leave `nowMs` before its own start.
 */
export function stepFight(fights: readonly Fight[], nowMs: number, dir: 1 | -1): Fight | null {
  const DEAD_ZONE_MS = 1000
  if (dir === 1) {
    return fights.find((f) => f.startMs > nowMs + DEAD_ZONE_MS) ?? null
  }
  for (let i = fights.length - 1; i >= 0; i--) {
    if (fights[i]!.startMs < nowMs - DEAD_ZONE_MS) return fights[i]!
  }
  return null
}

/** Where to seek for a fight — a few seconds before the first blow landed. */
export const FIGHT_LEAD_IN_MS = 4000

export function seekFor(fight: Fight): number {
  return Math.max(0, fight.startMs - FIGHT_LEAD_IN_MS)
}

/**
 * A short description of how a fight went, from the kill counts alone.
 *
 * **Never "won" or "lost".** `engagements` deliberately stores no verdict —
 * a fight where you killed two and lost three to a third party is not
 * obviously yours to have lost — and the replay must not reintroduce the
 * judgement the schema refused. These describe the counts.
 */
export function fightResult(f: Fight): string {
  if (f.ours && f.theirs) return `${f.ours}–${f.theirs} traded`
  if (f.ours) return `${f.ours} down`
  if (f.theirs) return `lost ${f.theirs}`
  if (f.knocksOurs || f.knocksTheirs) return 'knocks only'
  return 'no casualties'
}
