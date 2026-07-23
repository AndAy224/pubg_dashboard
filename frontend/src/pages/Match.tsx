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
          {/* ONE table for every roster, never one per roster — see SCORE_COLUMNS.
              Grouped by roster because that is the data model: participants
              carry no team id of their own, only the roster links them. */}
          <table className="scoreboard">
            <colgroup>
              {SCORE_COLUMNS.map((c) => (
                <col key={c.key} style={c.width ? { width: c.width } : undefined} />
              ))}
            </colgroup>
            <thead>
              <tr>
                {SCORE_COLUMNS.map((c) => (
                  <th key={c.key} className={c.width == null ? '' : 'r'} title={c.title}>
                    {c.label}
                  </th>
                ))}
              </tr>
            </thead>
            {m.rosters
              .filter((r) => showBots || r.participants.some((p) => !p.isBot))
              .map((r) => (
                <tbody key={r.teamId} className="roster">
                  <tr className="roster-row">
                    <td colSpan={SCORE_COLUMNS.length}>
                      <div className="roster-head">
                        <span className="swatch" style={{ background: hex(teamColour(r.teamId)) }} />
                        <Place place={r.rank} size="sm" />
                        <span className="faint">team {r.teamId}</span>
                        {r.won && <span className="tag win">winner</span>}
                      </div>
                    </td>
                  </tr>
                  {r.participants
                    .filter((p) => showBots || !p.isBot)
                    .map((p) => (
                      <ScoreRow key={p.accountId} p={p} />
                    ))}
                </tbody>
              ))}
          </table>
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

/**
 * One column geometry for the whole scoreboard.
 *
 * Every roster used to render its own `<table>`, and HTML sizes a table's
 * columns from *that table's* own content — so each team's Player column was
 * as wide as its own longest name, every numeric column landed somewhere
 * different, and nothing lined up down the page. One table with one `<thead>`
 * fixes that by construction (and stops N sticky headers fighting each other
 * inside the scroll container).
 *
 * `table-layout: fixed` plus this `<colgroup>` then pins the geometry so it
 * cannot drift with whoever happens to have the longest name in the lobby.
 * Widths live beside the labels so the `<col>` and the `<th>` cannot separate.
 * A column with no width is the flexible label column, and is left-aligned;
 * the fixed ones are numeric and right-aligned.
 */
const SCORE_COLUMNS: { key: string; label: string; width?: number; title?: string }[] = [
  { key: 'player', label: 'Player' },
  // Wide enough for `7 (13)` — kills carries a raw-total suffix when bot kills
  // make the two disagree.
  { key: 'k', label: 'K', width: 66, title: 'kills (human-only)' },
  { key: 'kn', label: 'Kn', width: 48, title: 'knocks' },
  { key: 'a', label: 'A', width: 46, title: 'assists' },
  { key: 'dmg', label: 'Dmg', width: 68 },
  { key: 'hs', label: 'HS', width: 46, title: 'headshot kills' },
  // `duration` renders `30m 00s` — seven monospace characters.
  { key: 'alive', label: 'Alive', width: 84 },
]

/** One participant. Its cells must stay in step with `SCORE_COLUMNS`. */
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
