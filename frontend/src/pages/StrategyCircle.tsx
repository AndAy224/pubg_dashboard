import { useQuery } from '@tanstack/react-query'
import { get } from '../api/client'
import type { ZonePhaseRate, ZonePlaySummary } from '../api/types'
import { Skeleton } from '../components/ui'
import { num } from '../lib/format'
import { circleGaps, circleSentence, rateOf } from '../lib/zone'

/**
 * Circle discipline: were we inside the next zone when it mattered.
 *
 * This is the one metric on the page that involves **no heuristic at all**.
 * `LogPhaseChange` carries `playersInWhiteCircle` — PUBG's own roster of who
 * was inside — so "were we in the circle" needs no geometry, no radius maths
 * and no threshold. `strategy_metrics.rotate_lag_s` answers a nearby question
 * by inference from position samples; this answers the sharper one exactly.
 *
 * Two instants per phase, and they are different questions:
 *
 * * **announced** — the white circle has appeared. Being outside is normal;
 *   most of the lobby is.
 * * **blue moves** — the blue has started closing on it. This is the
 *   rotation deadline, and being outside here is what costs a squad the game.
 */
export function StrategyCircle({
  scope,
  scopeKey,
}: {
  /** `?map=` / `?gameMode=`, from the page-level filter. */
  scope: Record<string, string>
  /** Part of the query key, or React Query serves the unfiltered answer from
   *  cache and the panel silently ignores the filter above it. */
  scopeKey: string
}) {
  const zone = useQuery({
    queryKey: ['strategy', 'zone-play', scopeKey],
    queryFn: () => get<ZonePlaySummary>('/strategy/zone-play', scope),
    staleTime: 5 * 60_000,
  })

  if (zone.isPending) return <Skeleton h={220} />
  if (zone.isError || !zone.data) return null

  const { squad, lobby, matches } = zone.data
  const lobbyByPhase = new Map(lobby.map((p) => [p.phase, p]))
  // Phases where the squad was alive often enough to say anything. Late
  // phases are reached rarely, and a 1-of-1 rate rendered as "100%" next to a
  // 60-of-71 rate invites reading them as comparable.
  const shown = squad.filter((p) => p.closeN >= 5 || p.announceN >= 5)
  // Stated in words because eight panels of bars is where a real gap goes
  // unnoticed. Null when there is nothing measurable to say — the absence of
  // a gap is not evidence of good discipline, so it gets no sentence.
  const gapText = circleSentence(circleGaps(squad, lobby))

  if (shown.length === 0) {
    return (
      <section className="card circle">
        <h3>Circle discipline</h3>
        <div className="empty">
          no circle data yet — it appears once matches are parsed by parser v15
          (reparse from settings)
        </div>
      </section>
    )
  }

  return (
    <section className="card circle">
      <div className="row" style={{ marginBottom: 8 }}>
        <h3>Circle discipline</h3>
        <span className="spacer" />
        <span className="faint small">{matches} matches</span>
      </div>

      <p className="note">
        Straight from PUBG’s own <code>playersInWhiteCircle</code> — no geometry
        and no threshold. Each phase fires twice: once when the next circle is{' '}
        <strong>announced</strong>, and again when the{' '}
        <strong>blue starts closing</strong> on it. The second is the deadline;
        being outside when the circle first appears is normal and is where most
        of the lobby starts every phase. Only players alive at that moment
        count — the dead are out of the match, not out of position.
      </p>

      {gapText !== null && <p className="circle-finding">{gapText}</p>}

      <div className="phase-strip">
        {shown.map((p) => (
          <PhasePanel key={p.phase} squad={p} lobby={lobbyByPhase.get(p.phase)} />
        ))}
      </div>

      <div className="circle-legend faint">
        <span>
          <i className="circle-sw announce" />
          when announced
        </span>
        <span>
          <i className="circle-sw close" />
          when the blue moves
        </span>
        <span>
          <i className="circle-sw lobby" />
          rest of the lobby, at the deadline
        </span>
      </div>
    </section>
  )
}

function Bar({ label, value, n, tone }: { label: string; value: number | null; n: number; tone: string }) {
  return (
    <div className="pbar-row">
      <span className="pbar-label faint">{label}</span>
      <span className="pbar-track">
        <span className={`pbar-fill ${tone}`} style={{ width: `${(value ?? 0) * 100}%` }} />
      </span>
      <span className="pbar-value num">
        {value === null ? '—' : `${Math.round(value * 100)}%`}
        <span className="faint"> /{n}</span>
      </span>
    </div>
  )
}

function PhasePanel({ squad, lobby }: { squad: ZonePhaseRate; lobby: ZonePhaseRate | undefined }) {
  const announce = rateOf(squad.announceIn, squad.announceN)
  const close = rateOf(squad.closeIn, squad.closeN)
  const lobbyClose = lobby ? rateOf(lobby.closeIn, lobby.closeN) : null

  return (
    <div className="phase-panel">
      <h4>
        Phase {squad.phase}
        {squad.medianEdgeM !== null && (
          <span className="faint edge">
            {/* Negative is inside. Rendered as words rather than a signed
                number, because "-142 m from the edge" reads as a distance
                outside it to about half of everyone. */}
            {squad.medianEdgeM <= 0
              ? `${num(Math.abs(squad.medianEdgeM))} m inside`
              : `${num(squad.medianEdgeM)} m outside`}
          </span>
        )}
      </h4>
      <Bar label="announced" value={announce} n={squad.announceN} tone="announce" />
      <Bar label="blue moves" value={close} n={squad.closeN} tone="close" />
      {lobby && <Bar label="lobby" value={lobbyClose} n={lobby.closeN} tone="lobby" />}
    </div>
  )
}
