import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'
import { get } from '../api/client'
import type { PlayerCard, PlayerStats, RecentMatch } from '../api/types'
import { ago, dateTime, duration, gameMode, num } from '../lib/format'

function StatTile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="tile">
      <div className="tile-label">{label}</div>
      <div className="tile-value num">{value}</div>
      {sub && <div className="tile-sub faint">{sub}</div>}
    </div>
  )
}

function PlayerSummary({ player }: { player: PlayerCard }) {
  const { data, isError } = useQuery({
    queryKey: ['stats', player.accountId],
    queryFn: () => get<PlayerStats>(`/players/${player.accountId}/stats`),
  })

  return (
    <div className="card player-card">
      <div className="row">
        <Link to={`/players/${player.accountId}`}>
          <h2>{player.name}</h2>
        </Link>
        <div className="spacer" />
        <span className="faint" title={`last polled ${ago(player.lastPolledAt)}`}>
          {player.matches} matches
        </span>
      </div>
      {isError && <div className="faint">no career matches yet</div>}
      {data && (
        <>
          <div className="tiles">
            {/* Human-only is the headline: bots are just over half of these
                players' kills, so the raw figure roughly doubles the K/D. */}
            <StatTile
              label="K/D"
              value={data.kdHuman.toFixed(2)}
              sub={`${data.kd.toFixed(2)} with bots`}
            />
            <StatTile label="Wins" value={num(data.wins)} sub={`${(data.winRate * 100).toFixed(0)}% of ${data.matches}`} />
            <StatTile label="Top 10" value={num(data.top10)} sub={`avg #${data.avgPlace.toFixed(1)}`} />
            <StatTile label="Avg dmg" value={num(data.avgDamage)} />
          </div>
          <div className="faint small">
            {num(data.killsHuman)} human kills of {num(data.kills)} · longest{' '}
            {num(data.longestKillM)} m · official matches only
          </div>
        </>
      )}
    </div>
  )
}

export function Home() {
  const players = useQuery({
    queryKey: ['players', 'tracked'],
    queryFn: () => get<PlayerCard[]>('/players', { tracked: true }),
  })
  const recent = useQuery({
    queryKey: ['matches', 'recent'],
    queryFn: () => get<RecentMatch[]>('/matches', { limit: 15 }),
  })

  return (
    <div className="grid" style={{ gap: 22 }}>
      <h1>Overview</h1>

      <section className="grid cards">
        {players.data?.map((p) => <PlayerSummary key={p.accountId} player={p} />)}
        {players.isLoading && <div className="empty">loading players…</div>}
      </section>

      <section className="card">
        <h3 style={{ marginBottom: 10 }}>Recent matches</h3>
        <table>
          <thead>
            <tr>
              <th>Played</th><th>Map</th><th>Mode</th><th>Type</th>
              <th className="r">Duration</th><th />
            </tr>
          </thead>
          <tbody>
            {recent.data?.map((m) => (
              <tr key={m.matchId}>
                <td><Link to={`/matches/${m.matchId}`}>{dateTime(m.playedAt)}</Link></td>
                <td>{m.mapDisplay}</td>
                <td className="dim">{gameMode(m.gameMode)}</td>
                <td>{m.matchType !== 'official' && <span className="tag">{m.matchType}</span>}</td>
                <td className="r num dim">{duration(m.durationS)}</td>
                <td className="r">
                  {m.hasReplay && <Link to={`/matches/${m.matchId}/replay`}>replay →</Link>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {recent.data?.length === 0 && <div className="empty">no matches ingested yet</div>}
      </section>
    </div>
  )
}
