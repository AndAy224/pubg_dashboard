import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router'
import { get } from '../api/client'
import type { KillRow, MatchDetail } from '../api/types'
import { dateTime, duration, gameMode, num, weaponName } from '../lib/format'
import { hex, teamColour } from '../lib/palette'

export function Match() {
  const { matchId = '' } = useParams()
  const match = useQuery({
    queryKey: ['match', matchId],
    queryFn: () => get<MatchDetail>(`/matches/${matchId}`),
  })
  const kills = useQuery({
    queryKey: ['kills', matchId],
    queryFn: () => get<KillRow[]>(`/matches/${matchId}/kills`),
  })

  const m = match.data
  if (match.isLoading) return <div className="empty">loading…</div>
  if (!m) return <div className="empty">match not found</div>

  return (
    <div className="grid" style={{ gap: 20 }}>
      <div className="row">
        <div>
          <h1>{m.mapDisplay} · {gameMode(m.gameMode)}</h1>
          <div className="faint small">
            {/* telemetryT0 is the real start; playedAt is the API's ingest time. */}
            {dateTime(m.telemetryT0 ?? m.playedAt)} · {duration(m.durationS)}
            {m.weatherId && ` · ${m.weatherId}`}
            {m.botCount !== null && ` · ${m.botCount} bots`}
            {m.matchType !== 'official' && ` · ${m.matchType}`}
          </div>
        </div>
        <div className="spacer" />
        {m.hasReplay && (
          <Link to={`/matches/${matchId}/replay`}>
            <button className="on">▶ Watch replay</button>
          </Link>
        )}
      </div>

      <div className="split">
        <section className="card scroll" style={{ maxHeight: 640 }}>
          <h3 style={{ marginBottom: 10 }}>Scoreboard</h3>
          {/* Grouped by roster because that is the data model: participants
              carry no team id of their own, only the roster links them. */}
          {m.rosters.map((r) => (
            <div key={r.teamId} className="roster">
              <div className="roster-head">
                <span className="swatch" style={{ background: hex(teamColour(r.teamId)) }} />
                <strong>#{r.rank}</strong>
                <span className="faint">team {r.teamId}</span>
                {r.won && <span className="tag win">winner</span>}
              </div>
              <table>
                <tbody>
                  {r.participants.map((p) => (
                    <tr key={p.accountId} className={p.tracked ? 'tracked' : ''}>
                      <td>
                        {p.tracked ? (
                          <Link to={`/players/${p.accountId}`}>{p.name}</Link>
                        ) : (
                          p.name
                        )}
                        {p.isBot && <span className="tag bot" style={{ marginLeft: 6 }}>bot</span>}
                      </td>
                      <td className="r num" title="kills (human-only)">
                        {p.kills}
                        {p.killsHuman !== null && p.killsHuman !== p.kills && (
                          <span className="faint"> ({p.killsHuman})</span>
                        )}
                      </td>
                      <td className="r num dim">{num(p.damageDealt)}</td>
                      <td className="r num faint">{duration(p.timeSurvived)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </section>

        <section className="card scroll" style={{ maxHeight: 640 }}>
          <h3 style={{ marginBottom: 10 }}>Kill feed ({kills.data?.length ?? 0})</h3>
          <table>
            <tbody>
              {kills.data?.map((k) => (
                <tr key={k.seq}>
                  <td className="num faint">{duration(k.tS)}</td>
                  <td>
                    {k.killerName ?? <span className="faint">{zoneCause(k)}</span>}
                    <span className="faint"> → </span>
                    <span className={k.victimIsBot ? 'faint' : ''}>{k.victimName ?? '?'}</span>
                  </td>
                  <td className="dim">{weaponName(k.weapon)}</td>
                  <td className="r num dim">
                    {k.distanceM !== null ? `${Math.round(k.distanceM)} m` : ''}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {kills.data?.length === 0 && <div className="empty">not parsed yet</div>}
        </section>
      </div>
    </div>
  )
}

/** A null killer is a zone, fall or drown death — 4% of kills. */
function zoneCause(k: KillRow): string {
  if (k.isSuicide) return 'self'
  return 'zone/fall'
}
