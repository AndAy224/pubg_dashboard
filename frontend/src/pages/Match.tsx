import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router'
import { apiBase, get } from '../api/client'
import type { KillRow, MatchDetail, ParticipantRow, TileInfo } from '../api/types'
import { KillMap } from '../components/KillMap'
import { Place, Skeleton } from '../components/ui'
import { dateTime, duration, gameMode, num, weaponName } from '../lib/format'
import { hex, teamColour } from '../lib/palette'

export function Match() {
  const { matchId = '' } = useParams()
  const [showBots, setShowBots] = useState(true)

  const match = useQuery({
    queryKey: ['match', matchId],
    queryFn: () => get<MatchDetail>(`/matches/${matchId}`),
  })
  const kills = useQuery({
    queryKey: ['kills', matchId],
    queryFn: () => get<KillRow[]>(`/matches/${matchId}/kills`),
    // A parsed match's kill list is derived from stored telemetry by a pinned
    // parser version, so it cannot change until the parser is bumped — and a
    // bump requeues the parse, which changes nothing the browser is holding
    // until a reload. Refetching it on every visit is pure waste.
    staleTime: match.data?.parsed ? Infinity : 30_000,
  })
  const tiles = useQuery({
    queryKey: ['tiles'],
    queryFn: () => get<Record<string, TileInfo>>('/tiles/manifest.json'),
    staleTime: 10 * 60_000,
  })

  const m = match.data
  useEffect(() => {
    document.title = m ? `${m.mapDisplay} · ${gameMode(m.gameMode)} · PUBG dashboard` : 'Match'
  }, [m])

  if (match.isLoading) {
    return (
      <div className="grid" style={{ gap: 16 }}>
        <Skeleton h={104} />
        <Skeleton h={520} />
      </div>
    )
  }
  if (!m) return <div className="empty">match not found</div>

  const info = tiles.data?.[m.mapName]
  const trackedRosters = m.rosters.filter((r) => r.participants.some((p) => p.tracked))

  return (
    <div className="grid" style={{ gap: 18 }}>
      <section className="hero">
        <div
          className="hero-bg"
          style={{ backgroundImage: `url(${apiBase}/tiles/${m.mapName}/1/0_1.webp)` }}
        />
        <div style={{ minWidth: 240 }}>
          <h1>
            {m.mapDisplay} <span className="faint">·</span> {gameMode(m.gameMode)}
          </h1>
          <div className="faint small">
            {/* telemetryT0 is the real start; playedAt is the API's ingest time. */}
            {dateTime(m.telemetryT0 ?? m.playedAt)} · {duration(m.durationS)}
            {m.weatherId && ` · ${m.weatherId}`}
            {m.numStartPlayers != null && ` · ${m.numStartPlayers} players`}
            {m.numStartTeams != null && ` in ${m.numStartTeams} teams`}
            {m.botCount != null && m.botCount > 0 && ` · ${m.botCount} bots`}
            {m.matchType !== 'official' && ` · ${m.matchType}`}
          </div>
        </div>

        <div className="spacer" />

        {trackedRosters.map((r) => (
          <div key={r.teamId} className="hero-result">
            <Place place={r.rank} of={m.numStartTeams} />
            <div className="faint small">
              {r.participants.filter((p) => p.tracked).map((p) => p.name).join(' · ')}
            </div>
          </div>
        ))}

        {m.hasReplay && (
          <Link to={`/matches/${matchId}/replay`}>
            <button className="on">▶ Watch replay</button>
          </Link>
        )}
      </section>

      {info && kills.data && kills.data.length > 0 && (
        <section className="card">
          <KillMap kills={kills.data} match={m} info={info} size={640} />
        </section>
      )}

      <div className="split">
        <section className="card scroll" style={{ maxHeight: 720 }}>
          <div className="row" style={{ marginBottom: 10 }}>
            <h3>Scoreboard</h3>
            <div className="spacer" />
            <button className={showBots ? '' : 'on'} onClick={() => setShowBots((v) => !v)}>
              {showBots ? 'hide bots' : 'bots hidden'}
            </button>
          </div>
          {/* Grouped by roster because that is the data model: participants
              carry no team id of their own, only the roster links them. */}
          {m.rosters
            .filter((r) => showBots || r.participants.some((p) => !p.isBot))
            .map((r) => (
              <div key={r.teamId} className="roster">
                <div className="roster-head">
                  <span className="swatch" style={{ background: hex(teamColour(r.teamId)) }} />
                  <Place place={r.rank} size="sm" />
                  <span className="faint">team {r.teamId}</span>
                  {r.won && <span className="tag win">winner</span>}
                </div>
                <table>
                  <thead>
                    <tr>
                      <th>Player</th>
                      <th className="r" title="kills (human-only)">K</th>
                      <th className="r" title="knocks">Kn</th>
                      <th className="r" title="assists">A</th>
                      <th className="r">Dmg</th>
                      <th className="r" title="headshot kills">HS</th>
                      <th className="r">Alive</th>
                    </tr>
                  </thead>
                  <tbody>
                    {r.participants
                      .filter((p) => showBots || !p.isBot)
                      .map((p) => (
                        <ScoreRow key={p.accountId} p={p} />
                      ))}
                  </tbody>
                </table>
              </div>
            ))}
        </section>

        <section className="card scroll" style={{ maxHeight: 720 }}>
          <h3 style={{ marginBottom: 10 }}>Kill feed ({kills.data?.length ?? 0})</h3>
          <table>
            <tbody>
              {kills.data?.map((k) => (
                <tr key={k.seq} className={k.isTeamKill ? 'teamkill' : ''}>
                  <td className="num faint">
                    {m.hasReplay ? (
                      <Link
                        to={`/matches/${matchId}/replay?t=${Math.floor(k.tS)}`}
                        title="jump to this moment in the replay"
                      >
                        {duration(k.tS)}
                      </Link>
                    ) : (
                      duration(k.tS)
                    )}
                  </td>
                  <td>
                    <span className={k.killerIsBot ? 'faint' : ''}>
                      {k.killerName ?? <span className="faint">{zoneCause(k)}</span>}
                    </span>
                    <span className="faint"> → </span>
                    <span className={k.victimIsBot ? 'faint' : ''}>{k.victimName ?? '?'}</span>
                    {k.damageReason === 'HeadShot' && (
                      <span className="hs-glyph" title="headshot"> ◎</span>
                    )}
                    {k.isTeamKill && <span className="tag bad-tag">team kill</span>}
                    {k.assists.length > 0 && (
                      <span className="faint small"> +{k.assists.join(', ')}</span>
                    )}
                  </td>
                  <td className="dim">{weaponName(k.weapon)}</td>
                  <td className="r num dim">
                    {k.distanceM !== null ? `${Math.round(k.distanceM)} m` : ''}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {kills.data?.length === 0 && (
            <div className="empty">
              {m.parsed ? 'no kills recorded' : 'not parsed yet'}
            </div>
          )}
        </section>
      </div>
    </div>
  )
}

function ScoreRow({ p }: { p: ParticipantRow }) {
  // `shotsFired === 0` means PUBG did not report weapon stats for this
  // account, not that they never fired — it populates them for ~2 accounts
  // per match. Showing "0%" would be a fabricated statistic.
  const accuracy =
    p.shotsFired && p.shotsFired > 0
      ? `${(((p.shotsHit ?? 0) / p.shotsFired) * 100).toFixed(0)}% of ${p.shotsFired} shots`
      : 'accuracy not reported'

  return (
    <tr className={p.tracked ? 'tracked' : ''}>
      <td>
        {p.tracked ? <Link to={`/players/${p.accountId}`}>{p.name}</Link> : p.name}
        {p.isBot && <span className="tag bot" style={{ marginLeft: 6 }}>bot</span>}
        {p.deathType === 'alive' && <span className="tag win" style={{ marginLeft: 6 }}>alive</span>}
      </td>
      <td className="r num" title={accuracy}>
        {p.killsHuman ?? p.kills}
        {p.killsHuman !== null && p.killsHuman !== p.kills && (
          <span className="faint"> ({p.kills})</span>
        )}
      </td>
      <td className="r num dim">{p.knocksHuman ?? p.dbnos}</td>
      <td className="r num dim">{p.assists}</td>
      <td className="r num dim">{num(p.damageDealt)}</td>
      <td className="r num dim">{p.headshotKills}</td>
      <td className="r num faint">{duration(p.timeSurvived)}</td>
    </tr>
  )
}

/** A null killer is a zone, fall or drown death — 2.9% of kills. */
function zoneCause(k: KillRow): string {
  if (k.isSuicide) return 'self'
  return 'zone/fall'
}
