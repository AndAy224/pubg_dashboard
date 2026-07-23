import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'
import { get } from '../api/client'
import type { Overview, PlayerSummary, SessionSummary } from '../api/types'
import { FormStrip, Skeleton, Sparkline, Tile } from '../components/ui'
import { MatchFeed } from '../components/MatchFeed'
import { ago, dateTime, duration, num } from '../lib/format'
import { playerColour, playerColourHex, registerPlayers } from '../lib/players'

export function Home() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['overview'],
    queryFn: () => get<Overview>('/overview'),
  })

  // Identity colours are assigned from the tracked roster, so it has to be
  // registered before anything renders a dot.
  useEffect(() => {
    if (data) registerPlayers(data.players.map((p) => p.card.accountId))
  }, [data])

  useEffect(() => {
    document.title = 'PUBG dashboard'
  }, [])

  if (isError) {
    return <div className="card empty">could not reach the API — is it running?</div>
  }

  return (
    <div className="grid" style={{ gap: 20 }}>
      <div className="row">
        <h1>Overview</h1>
        <div className="spacer" />
        {data && (
          <span className="faint small">
            {num(data.health.matches)} matches archived · polled {ago(data.players[0]?.card.lastPolledAt)}
          </span>
        )}
      </div>

      {isLoading && (
        <>
          <Skeleton h={64} />
          <div className="cards grid">
            <Skeleton h={168} /><Skeleton h={168} /><Skeleton h={168} />
          </div>
          <Skeleton h={340} />
        </>
      )}

      {data?.session && <SessionBar session={data.session} />}

      <section className="cards grid">
        {data?.players.map((p) => <PlayerCardView key={p.card.accountId} summary={p} />)}
      </section>

      {data && (
        <section className="card">
          <div className="row" style={{ marginBottom: 12 }}>
            <h3>Recent matches</h3>
            <div className="spacer" />
            <Link className="linkish small" to="/matches">
              full archive →
            </Link>
          </div>
          <MatchFeed rows={data.matches} />
        </section>
      )}
    </div>
  )
}

/**
 * The most recent play session.
 *
 * A session, not "today": these three play into the small hours, and a
 * calendar day would cut an evening in half at midnight.
 */
function SessionBar({ session }: { session: SessionSummary }) {
  const label = sessionLabel(session.endedAt)
  return (
    <section className="session-bar">
      <div className="session-when">
        <div className="session-label">{label}</div>
        <div className="faint small">
          {dateTime(session.startedAt)} — {new Date(session.endedAt).toLocaleTimeString('en-GB', {
            hour: '2-digit',
            minute: '2-digit',
          })}
        </div>
      </div>
      <div className="session-stats">
        <SessionStat label="Matches" value={num(session.matches)} />
        <SessionStat
          label="Best"
          value={session.bestPlace ? `#${session.bestPlace}` : '—'}
          accent={session.bestPlace === 1}
        />
        <SessionStat label="Wins" value={num(session.wins)} accent={session.wins > 0} />
        <SessionStat label="Kills" value={num(session.killsHuman)} sub="human" />
        <SessionStat label="Damage" value={num(session.damage)} />
        <SessionStat label="Span" value={duration(session.spanS)} />
      </div>
    </section>
  )
}

function SessionStat({
  label,
  value,
  sub,
  accent,
}: {
  label: string
  value: string
  sub?: string
  accent?: boolean
}) {
  return (
    <div className="session-stat">
      <div className={`session-value num ${accent ? 'accent' : ''}`}>{value}</div>
      <div className="session-stat-label">
        {label}
        {sub && <span className="faint"> {sub}</span>}
      </div>
    </div>
  )
}

/** "Tonight" if it ended today, "Last night" if it ran past midnight. */
function sessionLabel(endedAt: string): string {
  const end = new Date(endedAt)
  const days = Math.floor((Date.now() - end.getTime()) / 86_400_000)
  if (days === 0) return 'Latest session'
  if (days === 1) return 'Yesterday'
  return `${days} days ago`
}

function PlayerCardView({ summary }: { summary: PlayerSummary }) {
  const { card, stats, form, recent, previous } = summary
  const colour = playerColour(card.accountId)

  // Only compare windows that both exist. A missing window means "no matches
  // then", which is not a decline to zero.
  const kdDelta =
    recent && previous ? recent.kdHuman - previous.kdHuman : null
  const dmgDelta =
    recent && previous ? recent.avgDamage - previous.avgDamage : null

  return (
    <div className="card player-card" style={{ borderTopColor: colour }}>
      <div className="row">
        <span className="dot-lg" style={{ background: colour }} />
        <Link to={`/players/${card.accountId}`}>
          <h2 className="name">{card.name}</h2>
        </Link>
        <div className="spacer" />
        <span className="faint small">{num(card.matches)} matches</span>
      </div>

      {stats ? (
        <>
          <FormStrip form={form} />
          <div className="tiles">
            {/* Human-only is the headline: bots are just over half of these
                players' kills, so the raw figure roughly doubles the K/D. */}
            <Tile
              label="K/D"
              value={stats.kdHuman.toFixed(2)}
              sub={`${stats.kd.toFixed(2)} with bots`}
              delta={kdDelta}
            />
            <Tile
              label="Wins"
              value={num(stats.wins)}
              sub={`${(stats.winRate * 100).toFixed(0)}% of ${stats.matches}`}
            />
            <Tile
              label="Avg place"
              value={`#${stats.avgPlace.toFixed(1)}`}
              sub={`best #${stats.bestPlace}`}
            />
            <Tile
              label="Avg dmg"
              value={num(stats.avgDamage)}
              delta={dmgDelta}
            />
          </div>
          <div className="row" style={{ gap: 8 }}>
            <Sparkline
              values={form.map((f) => f.kills)}
              colour={playerColourHex(card.accountId)}
            />
            <span className="faint small">
              {num(stats.killsHuman)} human kills · {(stats.headshotRate * 100).toFixed(0)}% headshots
            </span>
          </div>
        </>
      ) : (
        <div className="faint small">no official matches yet</div>
      )}
    </div>
  )
}
