import { useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router'
import { get } from '../api/client'
import type { MatchDetail, MatchFeedRow } from '../api/types'
import { dateTime, duration, gameMode, num, weaponName } from '../lib/format'
import { KillChip, MapThumb, Place } from './ui'
import './MatchFeed.css'

/**
 * The match feed.
 *
 * The point of this component is everything the old feed left out: **who
 * played and where they finished**. A row that says only "Erangel · Duo FPP ·
 * 22m" describes a match nobody can identify.
 *
 * Kills shown per player are human-only (`killsHuman`), falling back to the
 * raw count on an unparsed match — bots are just over half of these players'
 * kills, so the raw number roughly doubles the figure.
 */
export function MatchFeed({
  rows,
  emptyLabel = 'no matches yet',
}: {
  rows: MatchFeedRow[]
  emptyLabel?: string
}) {
  if (rows.length === 0) return <div className="empty">{emptyLabel}</div>
  return (
    <div className="feed-list">
      {rows.map((m) => (
        <MatchRow key={m.matchId} m={m} />
      ))}
    </div>
  )
}

function MatchRow({ m }: { m: MatchFeedRow }) {
  const qc = useQueryClient()

  // The real match start when it is known; `playedAt` is the API's ingest
  // time and runs a few minutes late.
  const when = m.telemetryT0 ?? m.playedAt

  /**
   * Warm the match page on hover.
   *
   * A parsed match's scoreboard is immutable, so this is `staleTime:
   * Infinity` — the prefetch is the only fetch, and clicking through lands on
   * a rendered page rather than a spinner. Unparsed matches are left alone:
   * their detail still changes when the worker gets to them.
   */
  const prefetch = () => {
    if (!m.parsed) return
    qc.prefetchQuery({
      queryKey: ['match', m.matchId],
      queryFn: () => get<MatchDetail>(`/matches/${m.matchId}`),
      staleTime: Infinity,
    })
  }

  return (
    <div className="feed-row" onMouseEnter={prefetch} onFocus={prefetch}>
      <Link to={`/matches/${m.matchId}`} className="feed-main">
        <MapThumb mapName={m.mapName} size={44} />

        <div className="feed-when">
          <div className="feed-time">{dateTime(when)}</div>
          <div className="faint small">{gameMode(m.gameMode)}</div>
        </div>

        <div className="feed-place">
          <Place place={m.winPlace} of={m.numStartTeams} />
        </div>

        <div className="feed-players">
          {m.results.map((r) => (
            <KillChip
              key={r.accountId}
              accountId={r.accountId}
              name={r.name}
              kills={r.killsHuman ?? r.kills}
              title={
                `${r.name}: ${r.killsHuman ?? r.kills} human kills` +
                (r.killsHuman !== null && r.killsHuman !== r.kills
                  ? ` (${r.kills} incl. bots)`
                  : '') +
                ` · ${Math.round(r.damageDealt)} damage · ${r.knocks} knocks` +
                (r.killedBy ? ` · killed by ${r.killedBy}` : '') +
                (r.deathWeapon ? ` (${weaponName(r.deathWeapon)})` : '')
              }
            />
          ))}
          {m.results.length === 0 && <span className="faint small">no tracked player</span>}
        </div>

        <div className="feed-meta faint small">
          {m.matchType !== 'official' && <span className="tag">{m.matchType}</span>}
          {m.weatherId && <span>{m.weatherId}</span>}
          <span className="num">{duration(m.durationS)}</span>
          {m.botCount != null && m.botCount > 0 && (
            <span title={`${m.botCount} bots of ${m.numStartPlayers ?? '?'} players`}>
              {num(m.botCount)} bots
            </span>
          )}
        </div>
      </Link>

      <div className="feed-actions">
        {m.hasReplay ? (
          <Link to={`/matches/${m.matchId}/replay`} className="replay-btn" title="watch replay">
            ▶
          </Link>
        ) : (
          <span className="replay-btn disabled" title="not parsed yet">
            ▷
          </span>
        )}
      </div>
    </div>
  )
}
