import { useEffect, useMemo, useState } from 'react'
import { useQueries, useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'
import { get } from '../api/client'
import type { PlayerCard, SquadMatchRow, StrategyMatchRow, WeaponStat } from '../api/types'
import { Place, Skeleton } from '../components/ui'
import { dateTime, distance, duration, gameMode, num, weaponName } from '../lib/format'
import { contrastByPlacement, mergeWeapons, type Contrast } from '../lib/strategy'
import { playerColourHex, registerPlayers } from '../lib/players'
import './Strategy.css'

/** The "everyone together" selection. Not an account id, so it cannot collide. */
const COMBINED = 'combined'

/** A strategy row tagged with whose match it was — the API returns rows per
 * player, and the combined view pools them, so attribution must ride along. */
type Row = StrategyMatchRow & { accountId: string }

/**
 * The metrics the page contrasts, in display order.
 *
 * `fmt` renders a mean, so it must tolerate fractional values of counters
 * (an average of 2.4 pickups is meaningful; "2.4" is the honest rendering).
 */
const METRICS: {
  key: string
  label: string
  hint: string
  pick: (r: StrategyMatchRow) => number | null
  fmt: (v: number) => string
}[] = [
  {
    key: 'blue',
    label: 'Life spent in the blue zone',
    // A share, not raw seconds: placing well means surviving longer, and
    // longer survival means more chances to touch the blue — raw seconds
    // would "reward" the best matches with more blue time purely through
    // that confound.
    hint: '% of your time alive spent inside the damaging circle',
    pick: (r) =>
      r.blueS === null || r.timeSurvived <= 0 ? null : (r.blueS / r.timeSurvived) * 100,
    fmt: (v) => `${num(v, 1)}%`,
  },
  {
    key: 'blueDmg',
    label: 'Zone damage taken',
    hint: 'health burned by the blue zone',
    pick: (r) => r.blueDamage,
    fmt: (v) => num(v),
  },
  {
    key: 'rotate',
    label: 'Rotation lag',
    hint: 'circle announced → you were inside it (mean per phase)',
    pick: (r) => r.rotateLagS,
    fmt: duration,
  },
  {
    key: 'mateDist',
    label: 'Distance to squad',
    hint: 'mean distance to your nearest living teammate',
    pick: (r) => (r.teammateDistAvgCm === null ? null : r.teammateDistAvgCm / 100),
    fmt: distance,
  },
  {
    key: 'mateNear',
    label: 'Time within 100 m of squad',
    hint: 'share of the match spent near a living teammate',
    pick: (r) => (r.teammateNearPct === null ? null : r.teammateNearPct * 100),
    fmt: (v) => `${num(v)}%`,
  },
  {
    key: 'hot',
    label: 'Contested drop',
    hint: 'enemies landing within 200 m and ±60 s of you',
    pick: (r) => r.hotDropN,
    fmt: (v) => num(v, 1),
  },
  {
    key: 'firstFight',
    label: 'First fight',
    hint: 'first hit, knock or kill you were on either end of',
    pick: (r) => r.firstEngageS,
    fmt: duration,
  },
  {
    key: 'earlyDmg',
    label: 'Damage dealt in first 8 min',
    hint: 'aggression while the lobby is still full',
    pick: (r) => r.dmgDealtEarly,
    fmt: (v) => num(v),
  },
  {
    key: 'firstWeapon',
    label: 'Landing → first weapon',
    hint: 'seconds from touchdown to a gun in a slot',
    pick: (r) => r.firstWeaponS,
    fmt: duration,
  },
  {
    key: 'pickups',
    label: 'Pickups in first 5 min',
    hint: 'loot gathered right after the drop',
    pick: (r) => r.earlyPickupsN,
    fmt: (v) => num(v, 1),
  },
  {
    key: 'ride',
    label: 'Distance driven',
    hint: 'vehicle use across the whole match',
    pick: (r) => r.rideDistance,
    fmt: distance,
  },
]

export function Strategy() {
  // Defaults to the combined view: "how do we play as a team" is the question
  // this page exists to answer; individual players are one click away.
  const [selected, setSelected] = useState<string>(COMBINED)

  useEffect(() => {
    document.title = 'Strategy · PUBG dashboard'
  }, [])

  const players = useQuery({
    queryKey: ['players', 'tracked'],
    queryFn: () => get<PlayerCard[]>('/players', { tracked: true }),
    staleTime: 5 * 60_000,
  })

  useEffect(() => {
    if (players.data) registerPlayers(players.data.map((p) => p.accountId))
  }, [players.data])

  const tracked = players.data?.map((p) => p.accountId) ?? []
  const ids = selected === COMBINED ? tracked : [selected]

  const rowQueries = useQueries({
    queries: ids.map((id) => ({
      queryKey: ['strategy', id],
      queryFn: async (): Promise<Row[]> =>
        (await get<StrategyMatchRow[]>(`/players/${id}/strategy`)).map((r) => ({
          ...r,
          accountId: id,
        })),
    })),
  })
  const weaponQueries = useQueries({
    queries: ids.map((id) => ({
      queryKey: ['weapons', id],
      queryFn: () => get<WeaponStat[]>(`/players/${id}/weapons`),
    })),
  })
  const squad = useQuery({
    queryKey: ['strategy', 'squad'],
    queryFn: () => get<SquadMatchRow[]>('/strategy/squad'),
  })

  const combined = selected === COMBINED
  const loading =
    players.isPending || ids.length === 0 || rowQueries.some((q) => q.isPending)
  const data: Row[] = rowQueries.flatMap((q) => q.data ?? [])
  const measurable = data.filter((r) => r.blueS !== null || r.firstEngageS !== null)

  // Bars stay in one colour per view; the scatter dots carry per-player
  // attribution, which only matters when the pool mixes players.
  const barColour = combined ? 'var(--accent)' : playerColourHex(selected)
  const colourFor = (accountId: string) =>
    combined ? playerColourHex(accountId) : barColour

  const weapons = weaponQueries.some((q) => q.isPending)
    ? undefined
    : mergeWeapons(weaponQueries.map((q) => q.data ?? []))

  return (
    <div className="strategy grid" style={{ gap: 16 }}>
      <div className="row">
        <h1>Strategy</h1>
        <span className="spacer" />
        <button
          className={combined ? 'on' : ''}
          onClick={() => setSelected(COMBINED)}
          title="every tracked player's matches, pooled"
        >
          {tracked.map((id) => (
            <span key={id} className="dot" style={{ background: playerColourHex(id) }} />
          ))}
          combined
        </button>
        {players.data?.map((p) => (
          <button
            key={p.accountId}
            className={selected === p.accountId ? 'on' : ''}
            onClick={() => setSelected(p.accountId)}
          >
            <span className="dot" style={{ background: playerColourHex(p.accountId) }} />
            {p.name}
          </button>
        ))}
      </div>

      <p className="note">
        Each card contrasts the <strong>best-placed</strong> matches against the{' '}
        <strong>worst-placed</strong> ones (official matches only)
        {combined
          ? `, pooled across the squad — ${data.length || '…'} player-matches, where a match two of you played counts once per player. A suggestive read, not proof`
          : `. With ${data.length || '…'} matches this is a suggestive read, not proof`}{' '}
        — a dash means the metric was not measurable on that side (no landing, no
        teammates, no fights).
      </p>

      {loading ? (
        <Skeleton h={300} />
      ) : data.length < 4 ? (
        <div className="empty">not enough official matches to contrast</div>
      ) : measurable.length === 0 ? (
        <div className="empty">
          no strategy metrics yet — they appear once matches are parsed by parser v7
          (reparse from settings)
        </div>
      ) : (
        <div className="metric-grid">
          {METRICS.map((m) => (
            <MetricCard
              key={m.key}
              label={m.label}
              hint={m.hint}
              fmt={m.fmt}
              barColour={barColour}
              colourFor={colourFor}
              rows={data}
              contrast={contrastByPlacement(data, m.pick)}
              pick={m.pick}
            />
          ))}
        </div>
      )}

      <div className="split">
        <section className="card">
          <h3 style={{ marginBottom: 10 }}>Squad cohesion by match</h3>
          <SquadTable rows={squad.data} />
        </section>
        <section className="card">
          <h3 style={{ marginBottom: 10 }}>
            {combined ? 'Weapons that get the squad its kills' : 'Weapons that get your kills'}
          </h3>
          <WeaponsTable rows={weapons} />
        </section>
      </div>
    </div>
  )
}

function MetricCard({
  label,
  hint,
  fmt,
  barColour,
  colourFor,
  rows,
  contrast,
  pick,
}: {
  label: string
  hint: string
  fmt: (v: number) => string
  barColour: string
  colourFor: (accountId: string) => string
  rows: Row[]
  contrast: Contrast | null
  pick: (r: StrategyMatchRow) => number | null
}) {
  if (!contrast) return null
  const { best, worst } = contrast
  const max = Math.max(best.mean ?? 0, worst.mean ?? 0)
  return (
    <section className="card metric" title={hint}>
      <h3>{label}</h3>
      <div className="bars">
        <BarRow
          label={`best ${best.n || contrast.groupSize}`}
          value={best.mean}
          max={max}
          fmt={fmt}
          colour={barColour}
        />
        <BarRow
          label={`worst ${worst.n || contrast.groupSize}`}
          value={worst.mean}
          max={max}
          fmt={fmt}
          colour="var(--text-faint)"
        />
      </div>
      <ScatterStrip rows={rows} pick={pick} colourFor={colourFor} />
    </section>
  )
}

function BarRow({
  label,
  value,
  max,
  fmt,
  colour,
}: {
  label: string
  value: number | null
  max: number
  fmt: (v: number) => string
  colour: string
}) {
  const width = value === null || max <= 0 ? 0 : Math.max(2, (value / max) * 100)
  return (
    <div className="bar-row">
      <span className="bar-label faint">{label}</span>
      <div className="bar-track">
        {value !== null && <div className="bar-fill" style={{ width: `${width}%`, background: colour }} />}
      </div>
      <span className="bar-value num">{value === null ? '—' : fmt(value)}</span>
    </div>
  )
}

/**
 * Placement (x, #1 on the left) against the metric (y). Hand-rolled SVG for
 * the same reason the Overview sparklines are: this page should not pull in a
 * charting library to draw forty dots. In the combined view each dot wears
 * its player's colour, so "who drives this pattern" is visible at a glance.
 */
function ScatterStrip({
  rows,
  pick,
  colourFor,
}: {
  rows: Row[]
  pick: (r: StrategyMatchRow) => number | null
  colourFor: (accountId: string) => string
}) {
  const W = 260
  const H = 44
  const points = useMemo(() => {
    const usable = rows
      .map((r) => ({ place: r.winPlace, v: pick(r), accountId: r.accountId }))
      .filter((p): p is { place: number; v: number; accountId: string } => p.v !== null)
    if (usable.length === 0) return []
    const maxPlace = Math.max(...usable.map((p) => p.place), 2)
    const maxV = Math.max(...usable.map((p) => p.v))
    return usable.map((p) => ({
      x: 4 + ((p.place - 1) / (maxPlace - 1)) * (W - 8),
      y: maxV === 0 ? H - 4 : H - 4 - (p.v / maxV) * (H - 10),
      place: p.place,
      accountId: p.accountId,
    }))
  }, [rows, pick])

  if (points.length === 0) return null
  return (
    <svg
      className="scatter"
      width="100%"
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      role="img"
      aria-label="metric by placement"
    >
      {points.map((p, i) => (
        <circle key={i} cx={p.x} cy={p.y} r={2.4} fill={colourFor(p.accountId)} opacity={0.55}>
          <title>{`#${p.place}`}</title>
        </circle>
      ))}
    </svg>
  )
}

function SquadTable({ rows }: { rows: SquadMatchRow[] | undefined }) {
  if (!rows) return <Skeleton h={120} />
  if (rows.length === 0) {
    return <div className="empty">no matches with two tracked players on one team yet</div>
  }
  const contrast = contrastByPlacement(rows, (r) => {
    const vals = r.players
      .map((p) => p.teammateNearPct)
      .filter((v): v is number => v !== null)
    return vals.length ? (vals.reduce((a, b) => a + b, 0) / vals.length) * 100 : null
  })
  return (
    <>
      {contrast && contrast.best.mean !== null && contrast.worst.mean !== null && (
        <p className="note" style={{ marginTop: 0 }}>
          In your {contrast.groupSize} best-placed squad matches you were within 100 m of
          each other <strong>{num(contrast.best.mean)}%</strong> of the time, against{' '}
          <strong>{num(contrast.worst.mean)}%</strong> in the worst.
        </p>
      )}
      <table>
        <thead>
          <tr>
            <th>Match</th>
            <th>Place</th>
            <th className="num">Spread</th>
            <th className="num">Together</th>
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, 20).map((r) => {
            const dists = r.players
              .map((p) => p.teammateDistAvgCm)
              .filter((v): v is number => v !== null)
            const nears = r.players
              .map((p) => p.teammateNearPct)
              .filter((v): v is number => v !== null)
            return (
              <tr key={r.matchId}>
                <td>
                  <Link to={`/matches/${r.matchId}`}>
                    {dateTime(r.playedAt)} <span className="faint">{gameMode(r.gameMode)}</span>
                  </Link>
                </td>
                <td>
                  <Place place={r.winPlace} />
                </td>
                <td className="num">
                  {dists.length
                    ? distance(dists.reduce((a, b) => a + b, 0) / dists.length / 100)
                    : '—'}
                </td>
                <td className="num">
                  {nears.length
                    ? `${num((nears.reduce((a, b) => a + b, 0) / nears.length) * 100)}%`
                    : '—'}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </>
  )
}

function WeaponsTable({ rows }: { rows: WeaponStat[] | undefined }) {
  if (!rows) return <Skeleton h={120} />
  if (rows.length === 0) return <div className="empty">no weapon kills recorded</div>
  return (
    <table>
      <thead>
        <tr>
          <th>Weapon</th>
          <th className="num">Kills</th>
          <th className="num">Avg range</th>
          <th className="num">Longest</th>
        </tr>
      </thead>
      <tbody>
        {rows.slice(0, 8).map((w) => (
          <tr key={w.weapon}>
            <td>{weaponName(w.weapon)}</td>
            <td className="num">{w.kills}</td>
            <td className="num">{distance(w.avgDistanceM)}</td>
            <td className="num">{distance(w.longestM)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
