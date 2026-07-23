import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { apiBase, get } from '../api/client'
import type {
  MapInfo,
  MatchSummary,
  Nemesis,
  PlacementBucket,
  PlayerStats,
  TimeseriesPoint,
  WeaponStat,
} from '../api/types'
import { MapThumb, Place, Skeleton, Tile } from '../components/ui'
import { dateTime, duration, gameMode, num, weaponName } from '../lib/format'
import { playerColourHex } from '../lib/players'

const MODES = ['squad-fpp', 'duo-fpp', 'solo-fpp', 'squad', 'duo', 'solo']

/** Bar fills for the placement histogram, matching the grading everywhere else. */
const BUCKET_FILL: Record<string, string> = {
  '#1': '#f0b429',
  '2-5': '#d8dee6',
  '6-10': '#6cb6ff',
  '11-25': '#3f4a57',
  '26+': '#2a323c',
}

export function Player() {
  const { accountId = '' } = useParams()
  const [includeBots, setIncludeBots] = useState(false)
  const [mode, setMode] = useState('')
  const [mapName, setMapName] = useState('')
  const colour = playerColourHex(accountId)

  const filters = { gameMode: mode || undefined, mapName: mapName || undefined }

  const stats = useQuery({
    queryKey: ['stats', accountId, includeBots, filters],
    queryFn: () => get<PlayerStats>(`/players/${accountId}/stats`, { includeBots, ...filters }),
    retry: false,
  })
  const matches = useQuery({
    queryKey: ['matches', accountId, filters],
    queryFn: () =>
      get<MatchSummary[]>(`/players/${accountId}/matches`, { limit: 60, ...filters }),
  })
  const weapons = useQuery({
    queryKey: ['weapons', accountId, includeBots],
    queryFn: () => get<WeaponStat[]>(`/players/${accountId}/weapons`, { includeBots, limit: 12 }),
  })
  const placements = useQuery({
    queryKey: ['placements', accountId, mode],
    queryFn: () =>
      get<PlacementBucket[]>(`/players/${accountId}/placements`, {
        gameMode: mode || undefined,
      }),
  })
  const nemeses = useQuery({
    queryKey: ['nemeses', accountId],
    queryFn: () => get<Nemesis[]>(`/players/${accountId}/nemeses`, { limit: 8 }),
  })
  const trendKills = useQuery({
    queryKey: ['ts', accountId, 'kills', includeBots, mode],
    queryFn: () =>
      get<TimeseriesPoint[]>(`/players/${accountId}/timeseries`, {
        metric: 'kills',
        includeBots,
        days: 30,
        gameMode: mode || undefined,
      }),
  })
  const trendDamage = useQuery({
    queryKey: ['ts', accountId, 'damage', mode],
    queryFn: () =>
      get<TimeseriesPoint[]>(`/players/${accountId}/timeseries`, {
        metric: 'damage',
        days: 30,
        gameMode: mode || undefined,
      }),
  })

  const s = stats.data
  useEffect(() => {
    document.title = s ? `${s.name} · PUBG dashboard` : 'PUBG dashboard'
  }, [s])

  const maps = useQuery({
    queryKey: ['maps', 'played'],
    queryFn: () => get<MapInfo[]>('/maps/played'),
    staleTime: 10 * 60_000,
  })

  const heroMap = matches.data?.[0]?.mapName
  const trend = useMemo(
    () =>
      (trendKills.data ?? []).map((k, i) => ({
        day: k.day.slice(5),
        kills: k.value,
        matches: k.matches,
        damage: trendDamage.data?.[i]?.value ?? 0,
      })),
    [trendKills.data, trendDamage.data],
  )

  return (
    <div className="grid" style={{ gap: 18 }}>
      <section className="hero" style={{ borderTopColor: colour, borderTop: `2px solid ${colour}` }}>
        {heroMap && (
          <div
            className="hero-bg"
            style={{ backgroundImage: `url(${apiBase}/tiles/${heroMap}/1/1_1.webp)` }}
          />
        )}
        <div style={{ minWidth: 200 }}>
          <h1>{s?.name ?? accountId}</h1>
          {s && (
            <div className="faint small">
              {num(s.matches)} official matches · best <Place place={s.bestPlace} size="sm" /> ·{' '}
              {duration(s.timeSurvivedS)} survived
            </div>
          )}
        </div>
        <div className="spacer" />
        <button className={includeBots ? 'on' : ''} onClick={() => setIncludeBots((v) => !v)}>
          {includeBots ? 'bots included' : 'humans only'}
        </button>
      </section>

      <div className="filters">
        <label>Mode</label>
        <select value={mode} onChange={(e) => setMode(e.target.value)}>
          <option value="">all modes</option>
          {MODES.map((m) => <option key={m} value={m}>{gameMode(m)}</option>)}
        </select>
        <label>Map</label>
        <select value={mapName} onChange={(e) => setMapName(e.target.value)}>
          <option value="">all maps</option>
          {maps.data?.map((m) => <option key={m.mapName} value={m.mapName}>{m.display}</option>)}
        </select>
        <div className="spacer" />
        <span className="faint small">career stats count `official` matches only</span>
      </div>

      {stats.isLoading && <Skeleton h={92} />}
      {stats.isError && (
        <div className="card empty">no official matches with these filters</div>
      )}

      {s && (
        <>
          <section className="tiles wide">
            {/* The pair is always shown: `kills` is the raw API stat and
                `killsHuman` excludes bots. The toggle picks the headline, it
                does not change what either number means. */}
            <Tile
              label="K/D"
              value={(includeBots ? s.kd : s.kdHuman).toFixed(2)}
              sub={includeBots ? `${s.kdHuman.toFixed(2)} human-only` : `${s.kd.toFixed(2)} with bots`}
            />
            <Tile
              label="Kills"
              value={num(includeBots ? s.kills : s.killsHuman)}
              sub={`${num(s.kills - s.killsHuman)} bots of ${num(s.kills)}`}
            />
            <Tile label="Matches" value={num(s.matches)} sub="official only" />
            <Tile label="Wins" value={num(s.wins)} sub={`${(s.winRate * 100).toFixed(1)}%`} />
            <Tile label="Top 10" value={num(s.top10)} sub={`avg place #${s.avgPlace.toFixed(1)}`} />
            <Tile label="Avg damage" value={num(s.avgDamage)} sub={`${num(s.damageDealt)} total`} />
            <Tile label="Longest kill" value={`${num(s.longestKillM)} m`} />
            <Tile
              label="Headshots"
              value={`${(s.headshotRate * 100).toFixed(0)}%`}
              sub={`${num(s.headshotKills)} of ${num(s.kills)} kills`}
            />
            <Tile label="Knocks" value={num(s.knocksHuman)} sub={`${num(s.knocks)} incl. bots`} />
            <Tile
              label="Avg survived"
              value={duration(s.avgSurvivedS)}
              sub={`${num(s.assists)} assists · ${num(s.revives)} revives`}
            />
            {/* Accuracy is shown only when PUBG actually reported it. It
                populates `allWeaponStats` for ~2 accounts per match, so for
                these three it exists in a handful of matches; a headline 0%
                would read as a bug rather than as missing data. */}
            {s.shotsFired > 0 ? (
              <Tile
                label="Accuracy"
                value={`${(s.accuracy * 100).toFixed(1)}%`}
                sub={`${num(s.shotsHit)} of ${num(s.shotsFired)} shots`}
              />
            ) : (
              <Tile label="Accuracy" value="—" sub="not reported by PUBG" />
            )}
            <Tile
              label="Distance"
              value={`${num(s.walkDistanceM / 1000, 1)} km`}
              sub={`${num(s.rideDistanceM / 1000, 1)} km driven`}
            />
          </section>

          <section className="charts">
            <div className="card chart-card">
              <h3 style={{ marginBottom: 10 }}>Kills &amp; damage · last 30 days</h3>
              {trend.length === 0 ? (
                <div className="empty">no matches in the window</div>
              ) : (
                <ResponsiveContainer width="100%" height={190}>
                  <LineChart data={trend} margin={{ top: 4, right: 8, bottom: 0, left: -18 }}>
                    <CartesianGrid stroke="#232a34" vertical={false} />
                    <XAxis dataKey="day" stroke="#5d6875" fontSize={11} tickLine={false} />
                    <YAxis stroke="#5d6875" fontSize={11} tickLine={false} axisLine={false} />
                    <Tooltip
                      contentStyle={{
                        background: '#0a0d11',
                        border: '1px solid #232a34',
                        borderRadius: 6,
                        fontSize: 12,
                      }}
                      labelStyle={{ color: '#97a3b4' }}
                    />
                    <Line
                      type="monotone" dataKey="kills" stroke={colour}
                      strokeWidth={2} dot={{ r: 2 }} name="kills"
                    />
                  </LineChart>
                </ResponsiveContainer>
              )}
            </div>

            <div className="card chart-card">
              <h3 style={{ marginBottom: 10 }}>Placement distribution</h3>
              {placements.data && placements.data.some((b) => b.matches > 0) ? (
                <ResponsiveContainer width="100%" height={190}>
                  <BarChart
                    data={placements.data}
                    margin={{ top: 4, right: 8, bottom: 0, left: -18 }}
                  >
                    <CartesianGrid stroke="#232a34" vertical={false} />
                    <XAxis dataKey="label" stroke="#5d6875" fontSize={11} tickLine={false} />
                    <YAxis stroke="#5d6875" fontSize={11} tickLine={false} axisLine={false} allowDecimals={false} />
                    <Tooltip
                      cursor={{ fill: '#1a2028' }}
                      contentStyle={{
                        background: '#0a0d11',
                        border: '1px solid #232a34',
                        borderRadius: 6,
                        fontSize: 12,
                      }}
                    />
                    <Bar dataKey="matches" radius={[3, 3, 0, 0]}>
                      {placements.data.map((b) => (
                        <Cell key={b.label} fill={BUCKET_FILL[b.label] ?? '#3f4a57'} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <div className="empty">no career matches</div>
              )}
            </div>
          </section>

          <section className="split">
            <div className="card">
              <h3 style={{ marginBottom: 10 }}>Weapons</h3>
              <table>
                <thead>
                  <tr>
                    <th>Weapon</th><th className="r">Kills</th><th className="r">HS</th>
                    <th className="r">Longest</th><th className="r">Avg</th>
                  </tr>
                </thead>
                <tbody>
                  {weapons.data?.map((w) => (
                    <tr key={w.weapon}>
                      <td>{weaponName(w.weapon)}</td>
                      <td className="r num">{w.kills}</td>
                      <td className="r num dim">
                        {w.headshots}
                        {w.kills > 0 && (
                          <span className="faint"> {Math.round((w.headshots / w.kills) * 100)}%</span>
                        )}
                      </td>
                      <td className="r num">{num(w.longestM)} m</td>
                      <td className="r num dim">{num(w.avgDistanceM)} m</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {weapons.data?.length === 0 && <div className="empty">no kills recorded</div>}
            </div>

            <div className="card">
              <h3 style={{ marginBottom: 10 }}>Nemeses</h3>
              <p className="faint small" style={{ margin: '0 0 8px' }}>
                Humans only — bot ids are recycled between matches, so grouping
                by one would invent a single arch-enemy out of dozens.
              </p>
              <table>
                <thead>
                  <tr>
                    <th>Player</th>
                    <th className="r" title="times they killed you">Killed you</th>
                    <th className="r" title="times you killed them">You killed</th>
                  </tr>
                </thead>
                <tbody>
                  {nemeses.data?.map((n) => (
                    <tr key={n.accountId}>
                      <td>{n.name}</td>
                      <td className={`r num ${n.killedBy > n.killed ? 'bad' : 'dim'}`}>{n.killedBy}</td>
                      <td className={`r num ${n.killed > n.killedBy ? 'good' : 'dim'}`}>{n.killed}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {nemeses.data?.length === 0 && (
                <div className="empty">no repeat opponents yet</div>
              )}
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
              <th className="r">Knocks</th><th className="r">Damage</th>
              <th className="r">Survived</th><th>Killed by</th><th />
            </tr>
          </thead>
          <tbody>
            {matches.data?.map((m) => (
              <tr key={m.matchId}>
                <td>
                  <Link to={`/matches/${m.matchId}`}>{dateTime(m.playedAt)}</Link>
                </td>
                <td>
                  <span className="row" style={{ gap: 7 }}>
                    <MapThumb mapName={m.mapName} size={20} />
                    {m.mapDisplay}
                    {m.matchType !== 'official' && (
                      <span className="tag">{m.matchType}</span>
                    )}
                  </span>
                </td>
                <td className="dim">{gameMode(m.gameMode)}</td>
                <td className="r"><Place place={m.winPlace} of={m.numStartTeams} size="sm" /></td>
                <td className="r num">
                  {m.killsHuman ?? m.kills}
                  {m.killsHuman !== null && m.killsHuman !== m.kills && (
                    <span className="faint"> ({m.kills})</span>
                  )}
                </td>
                <td className="r num dim">{m.knocks}</td>
                <td className="r num dim">{num(m.damageDealt)}</td>
                <td className="r num dim">{duration(m.timeSurvived)}</td>
                <td className="dim small">
                  {m.deathType === 'alive' ? (
                    <span className="good">survived</span>
                  ) : m.killedBy ? (
                    <>
                      <span className={m.killedByIsBot ? 'faint' : ''}>{m.killedBy}</span>
                      {m.deathWeapon && (
                        <span className="faint"> · {weaponName(m.deathWeapon)}</span>
                      )}
                    </>
                  ) : (
                    <span className="faint">{m.deathType}</span>
                  )}
                </td>
                <td className="r">
                  {m.hasReplay && <Link to={`/matches/${m.matchId}/replay`}>▶</Link>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {matches.isLoading && <Skeleton h={200} />}
      </section>
    </div>
  )
}

