import { useEffect, useMemo, useState } from 'react'
import { useQueries, useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'
import {
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
} from 'recharts'
import { get } from '../api/client'
import type { PlayerCard, PlayerStats } from '../api/types'
import { Skeleton } from '../components/ui'
import { duration, num } from '../lib/format'
import { playerColourHex, registerPlayers } from '../lib/players'

/**
 * The radar axes.
 *
 * Every axis is normalised to the best value across the compared players, so
 * the shape shows *relative* standing — an absolute scale would need a
 * ceiling for "good K/D" that nobody can defend. `avgPlace` is inverted
 * because a lower rank is a better one.
 */
const AXES: { key: string; label: string; pick: (s: PlayerStats) => number; invert?: boolean }[] = [
  { key: 'kd', label: 'K/D', pick: (s) => s.kdHuman },
  { key: 'dmg', label: 'Avg dmg', pick: (s) => s.avgDamage },
  { key: 'win', label: 'Win %', pick: (s) => s.winRate },
  { key: 'top10', label: 'Top 10 %', pick: (s) => (s.matches ? s.top10 / s.matches : 0) },
  { key: 'place', label: 'Placement', pick: (s) => s.avgPlace, invert: true },
  { key: 'survive', label: 'Survival', pick: (s) => s.avgSurvivedS },
]

export function Compare() {
  const [selected, setSelected] = useState<string[]>([])

  useEffect(() => {
    document.title = 'Compare · PUBG dashboard'
  }, [])

  const players = useQuery({
    queryKey: ['players', 'tracked'],
    queryFn: () => get<PlayerCard[]>('/players', { tracked: true }),
    staleTime: 5 * 60_000,
  })

  useEffect(() => {
    if (!players.data) return
    registerPlayers(players.data.map((p) => p.accountId))
    // Default to everyone tracked — with three players that is the comparison
    // people actually want, and an empty page would just need three clicks.
    setSelected((cur) => (cur.length ? cur : players.data.map((p) => p.accountId)))
  }, [players.data])

  const statQueries = useQueries({
    queries: selected.map((id) => ({
      queryKey: ['stats', id, false, {}],
      queryFn: () => get<PlayerStats>(`/players/${id}/stats`),
      retry: false,
    })),
  })

  const stats = statQueries
    .map((q) => q.data)
    .filter((s): s is PlayerStats => s !== undefined)

  const radar = useMemo(() => {
    if (stats.length === 0) return []
    return AXES.map((axis) => {
      const raw = stats.map((s) => axis.pick(s))
      const best = axis.invert ? Math.min(...raw) : Math.max(...raw)
      const row: Record<string, string | number> = { axis: axis.label }
      stats.forEach((s, i) => {
        const v = raw[i]!
        // Guard the degenerate case: if the best value is 0 nothing can be
        // scaled against it, and every player scores 0 rather than NaN.
        row[s.name] = best === 0 ? 0 : Math.round((axis.invert ? best / v : v / best) * 100)
      })
      return row
    })
  }, [stats])

  const toggle = (id: string) =>
    setSelected((cur) => (cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]))

  return (
    <div className="grid" style={{ gap: 16 }}>
      <h1>Compare</h1>

      <div className="filters">
        <label>Players</label>
        {players.data?.map((p) => (
          <button
            key={p.accountId}
            className={selected.includes(p.accountId) ? 'on' : ''}
            onClick={() => toggle(p.accountId)}
          >
            {p.name}
          </button>
        ))}
        <div className="spacer" />
        <span className="faint small">official matches only</span>
      </div>

      {statQueries.some((q) => q.isLoading) && <Skeleton h={280} />}

      {stats.length > 0 && (
        <section className="split">
          <div className="card">
            <h3 style={{ marginBottom: 10 }}>Head to head</h3>
            <table>
              <thead>
                <tr>
                  <th>Stat</th>
                  {stats.map((s) => (
                    <th key={s.accountId} className="r">
                      <Link to={`/players/${s.accountId}`} style={{ color: playerColourHex(s.accountId) }}>
                        {s.name}
                      </Link>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <CompareRow label="Matches" stats={stats} pick={(s) => num(s.matches)} />
                <CompareRow label="K/D (human)" stats={stats} pick={(s) => s.kdHuman.toFixed(2)} best={(s) => s.kdHuman} />
                <CompareRow label="K/D (with bots)" stats={stats} pick={(s) => s.kd.toFixed(2)} best={(s) => s.kd} />
                <CompareRow label="Human kills" stats={stats} pick={(s) => num(s.killsHuman)} best={(s) => s.killsHuman} />
                <CompareRow label="Wins" stats={stats} pick={(s) => `${s.wins} (${(s.winRate * 100).toFixed(0)}%)`} best={(s) => s.winRate} />
                <CompareRow label="Top 10" stats={stats} pick={(s) => num(s.top10)} best={(s) => s.top10} />
                <CompareRow label="Avg placement" stats={stats} pick={(s) => `#${s.avgPlace.toFixed(1)}`} best={(s) => -s.avgPlace} />
                <CompareRow label="Best placement" stats={stats} pick={(s) => `#${s.bestPlace}`} best={(s) => -s.bestPlace} />
                <CompareRow label="Avg damage" stats={stats} pick={(s) => num(s.avgDamage)} best={(s) => s.avgDamage} />
                <CompareRow label="Headshot rate" stats={stats} pick={(s) => `${(s.headshotRate * 100).toFixed(0)}%`} best={(s) => s.headshotRate} />
                <CompareRow label="Knocks" stats={stats} pick={(s) => num(s.knocksHuman)} best={(s) => s.knocksHuman} />
                <CompareRow label="Longest kill" stats={stats} pick={(s) => `${num(s.longestKillM)} m`} best={(s) => s.longestKillM} />
                <CompareRow label="Avg survived" stats={stats} pick={(s) => duration(s.avgSurvivedS)} best={(s) => s.avgSurvivedS} />
                <CompareRow label="Revives" stats={stats} pick={(s) => num(s.revives)} best={(s) => s.revives} />
                <CompareRow label="Distance walked" stats={stats} pick={(s) => `${num(s.walkDistanceM / 1000, 1)} km`} />
              </tbody>
            </table>
          </div>

          <div className="card">
            <h3 style={{ marginBottom: 10 }}>Shape</h3>
            <p className="faint small" style={{ margin: '0 0 6px' }}>
              Each axis is scaled to the best of the selected players, so 100
              means "leads this group" — not an absolute rating.
            </p>
            <ResponsiveContainer width="100%" height={300}>
              <RadarChart data={radar}>
                <PolarGrid stroke="#232a34" />
                <PolarAngleAxis dataKey="axis" tick={{ fill: '#97a3b4', fontSize: 11 }} />
                <PolarRadiusAxis domain={[0, 100]} tick={{ fill: '#5d6875', fontSize: 10 }} />
                {stats.map((s) => (
                  <Radar
                    key={s.accountId}
                    name={s.name}
                    dataKey={s.name}
                    stroke={playerColourHex(s.accountId)}
                    fill={playerColourHex(s.accountId)}
                    fillOpacity={0.14}
                    strokeWidth={2}
                  />
                ))}
                <Tooltip
                  contentStyle={{
                    background: '#0a0d11',
                    border: '1px solid #232a34',
                    borderRadius: 6,
                    fontSize: 12,
                  }}
                />
              </RadarChart>
            </ResponsiveContainer>
          </div>
        </section>
      )}

      {selected.length === 0 && <div className="card empty">pick at least one player</div>}
    </div>
  )
}

function CompareRow({
  label,
  stats,
  pick,
  best,
}: {
  label: string
  stats: PlayerStats[]
  pick: (s: PlayerStats) => string
  /** Higher wins. Omit for stats where "best" is meaningless. */
  best?: (s: PlayerStats) => number
}) {
  const winner =
    best && stats.length > 1
      ? stats.reduce((a, b) => (best(b) > best(a) ? b : a)).accountId
      : null
  return (
    <tr>
      <td className="dim">{label}</td>
      {stats.map((s) => (
        <td key={s.accountId} className={`r num ${s.accountId === winner ? 'lead' : ''}`}>
          {pick(s)}
        </td>
      ))}
    </tr>
  )
}
