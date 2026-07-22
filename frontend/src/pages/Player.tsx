import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router'
import { get } from '../api/client'
import type { MatchSummary, PlayerStats, WeaponStat } from '../api/types'
import { dateTime, duration, gameMode, num, weaponName } from '../lib/format'

export function Player() {
  const { accountId = '' } = useParams()
  const [includeBots, setIncludeBots] = useState(false)

  const stats = useQuery({
    queryKey: ['stats', accountId, includeBots],
    queryFn: () => get<PlayerStats>(`/players/${accountId}/stats`, { includeBots }),
  })
  const matches = useQuery({
    queryKey: ['matches', accountId],
    queryFn: () => get<MatchSummary[]>(`/players/${accountId}/matches`, { limit: 50 }),
  })
  const weapons = useQuery({
    queryKey: ['weapons', accountId, includeBots],
    queryFn: () => get<WeaponStat[]>(`/players/${accountId}/weapons`, { includeBots, limit: 12 }),
  })

  const s = stats.data
  return (
    <div className="grid" style={{ gap: 22 }}>
      <div className="row">
        <h1>{s?.name ?? accountId}</h1>
        <div className="spacer" />
        <button className={includeBots ? 'on' : ''} onClick={() => setIncludeBots((v) => !v)}>
          {includeBots ? 'bots included' : 'humans only'}
        </button>
      </div>

      {stats.isError && <div className="card empty">no career matches (official only)</div>}

      {s && (
        <>
          <section className="tiles wide">
            {/* The pair is always shown: `kills` is the raw API stat and
                `killsHuman` excludes bots. The toggle picks the headline, it
                does not change what either number means. */}
            <Tile label="K/D" value={(includeBots ? s.kd : s.kdHuman).toFixed(2)}
                  sub={includeBots ? `${s.kdHuman.toFixed(2)} human-only` : `${s.kd.toFixed(2)} with bots`} />
            <Tile label="Kills" value={num(includeBots ? s.kills : s.killsHuman)}
                  sub={`${num(s.kills - s.killsHuman)} bots of ${num(s.kills)}`} />
            <Tile label="Matches" value={num(s.matches)} sub="official only" />
            <Tile label="Wins" value={num(s.wins)} sub={`${(s.winRate * 100).toFixed(1)}%`} />
            <Tile label="Top 10" value={num(s.top10)} sub={`avg place #${s.avgPlace.toFixed(1)}`} />
            <Tile label="Avg damage" value={num(s.avgDamage)} sub={`${num(s.damageDealt)} total`} />
            <Tile label="Longest kill" value={`${num(s.longestKillM)} m`} />
            <Tile label="Headshots" value={num(s.headshotKills)} sub={`${num(s.assists)} assists · ${num(s.revives)} revives`} />
          </section>

          <section className="split">
            <div className="card">
              <h3 style={{ marginBottom: 10 }}>Weapons</h3>
              <table>
                <thead>
                  <tr><th>Weapon</th><th className="r">Kills</th><th className="r">HS</th><th className="r">Longest</th><th className="r">Avg</th></tr>
                </thead>
                <tbody>
                  {weapons.data?.map((w) => (
                    <tr key={w.weapon}>
                      <td>{weaponName(w.weapon)}</td>
                      <td className="r num">{w.kills}</td>
                      <td className="r num dim">{w.headshots}</td>
                      <td className="r num">{num(w.longestM)} m</td>
                      <td className="r num dim">{num(w.avgDistanceM)} m</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {weapons.data?.length === 0 && <div className="empty">no kills recorded</div>}
            </div>

            <div className="card">
              <h3 style={{ marginBottom: 10 }}>Distance & survival</h3>
              <dl className="kv">
                <dt>Time survived</dt><dd className="num">{duration(s.timeSurvivedS)}</dd>
                <dt>On foot</dt><dd className="num">{num(s.walkDistanceM / 1000, 1)} km</dd>
                <dt>In vehicles</dt><dd className="num">{num(s.rideDistanceM / 1000, 1)} km</dd>
                <dt>Knocks</dt><dd className="num">{num(s.knocks)}</dd>
              </dl>
            </div>
          </section>
        </>
      )}

      <section className="card">
        <h3 style={{ marginBottom: 10 }}>Match history</h3>
        <table>
          <thead>
            <tr>
              <th>Played</th><th>Map</th><th>Mode</th>
              <th className="r">Place</th><th className="r">Kills</th>
              <th className="r">Damage</th><th className="r">Survived</th><th />
            </tr>
          </thead>
          <tbody>
            {matches.data?.map((m) => (
              <tr key={m.matchId}>
                <td><Link to={`/matches/${m.matchId}`}>{dateTime(m.playedAt)}</Link></td>
                <td>{m.mapDisplay}{m.matchType !== 'official' && <span className="tag" style={{ marginLeft: 6 }}>{m.matchType}</span>}</td>
                <td className="dim">{gameMode(m.gameMode)}</td>
                <td className="r num">
                  {m.winPlace === 1 ? <span className="tag win">#1</span> : `#${m.winPlace}`}
                </td>
                <td className="r num">
                  {m.killsHuman ?? m.kills}
                  {m.killsHuman !== null && m.killsHuman !== m.kills && (
                    <span className="faint"> ({m.kills})</span>
                  )}
                </td>
                <td className="r num dim">{num(m.damageDealt)}</td>
                <td className="r num dim">{duration(m.timeSurvived)}</td>
                <td className="r">{m.hasReplay && <Link to={`/matches/${m.matchId}/replay`}>▶</Link>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  )
}

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="tile">
      <div className="tile-label">{label}</div>
      <div className="tile-value num">{value}</div>
      {sub && <div className="tile-sub faint">{sub}</div>}
    </div>
  )
}
