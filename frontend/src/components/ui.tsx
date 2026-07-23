import { Link } from 'react-router'
import { apiBase } from '../api/client'
import type { FormEntry } from '../api/types'
import { num } from '../lib/format'
import { placeGrade, playerColour } from '../lib/players'
import './ui.css'

/**
 * A placement, graded and rendered identically everywhere.
 *
 * Always shows the denominator when it is known: "#8" alone is unreadable
 * without knowing whether the lobby held 25 teams or 100.
 */
export function Place({
  place,
  of,
  size = 'md',
}: {
  place: number | null | undefined
  of?: number | null
  size?: 'sm' | 'md'
}) {
  if (place == null) return <span className="faint">—</span>
  return (
    <span className={`place place-${placeGrade(place)} place-${size}`}>
      <span className="place-n num">#{place}</span>
      {of ? <span className="place-of num">/{of}</span> : null}
    </span>
  )
}

/**
 * The last N results as graded squares, oldest first.
 *
 * Answers "how are we doing lately" without reading a single number, which is
 * the question a career average cannot answer.
 */
export function FormStrip({ form }: { form: FormEntry[] }) {
  if (form.length === 0) return <div className="faint small">no career matches yet</div>
  return (
    <div className="form-strip">
      {form.map((f) => (
        <Link
          key={f.matchId}
          to={`/matches/${f.matchId}`}
          className={`form-cell form-${placeGrade(f.winPlace)}`}
          title={`#${f.winPlace}${f.numStartTeams ? ` of ${f.numStartTeams}` : ''} · ${f.kills} kills · ${f.mapDisplay}`}
        >
          {f.winPlace === 1 ? '★' : f.kills > 0 ? f.kills : ''}
        </Link>
      ))}
    </div>
  )
}

/**
 * Zoom-0 map tile as a thumbnail.
 *
 * The whole pyramid is served locally and immutable, so this costs one cached
 * request per map for the entire session.
 */
export function MapThumb({ mapName, size = 40 }: { mapName: string; size?: number }) {
  return (
    <img
      className="map-thumb"
      src={`${apiBase}/tiles/${mapName}/0/0_0.webp`}
      width={size}
      height={size}
      loading="lazy"
      alt=""
      /* A map with no tiles built yet must not leave a broken-image glyph in
         the middle of the feed. */
      onError={(e) => {
        e.currentTarget.style.visibility = 'hidden'
      }}
    />
  )
}

/** A tracked player's contribution to a match, in their own colour. */
export function KillChip({
  accountId,
  name,
  kills,
  title,
}: {
  accountId: string
  name: string
  kills: number
  title?: string
}) {
  return (
    <span className="kill-chip" title={title}>
      <span className="dot-sm" style={{ background: playerColour(accountId) }} />
      <span className="kc-name">{name}</span>
      <span className="kc-kills num">{kills}</span>
    </span>
  )
}

export function Tile({
  label,
  value,
  sub,
  delta,
  tone,
}: {
  label: string
  value: string
  sub?: string
  /** Signed change vs the previous window; sign alone drives the colour. */
  delta?: number | null
  /** `lower` inverts the colour — for placement, smaller is better. */
  tone?: 'higher' | 'lower'
}) {
  const good = delta == null ? null : tone === 'lower' ? delta < 0 : delta > 0
  return (
    <div className="tile">
      <div className="tile-label">{label}</div>
      <div className="tile-value num">
        {value}
        {delta != null && Math.abs(delta) > 0.0001 && (
          <span className={`tile-delta ${good ? 'good' : 'bad'}`}>
            {delta > 0 ? '▲' : '▼'}
            {num(Math.abs(delta), Math.abs(delta) < 10 ? 2 : 0)}
          </span>
        )}
      </div>
      {sub && <div className="tile-sub faint">{sub}</div>}
    </div>
  )
}

/**
 * An inline sparkline over evenly spaced values.
 *
 * Deliberately not Recharts: this renders at 60x18 inside a stat tile, where a
 * charting library's axes, tooltips and responsive container are all cost and
 * no benefit. Recharts is used on the player page, where they earn their keep.
 */
export function Sparkline({
  values,
  width = 64,
  height = 20,
  colour = 'var(--accent)',
}: {
  values: number[]
  width?: number
  height?: number
  colour?: string
}) {
  if (values.length < 2) return null
  const lo = Math.min(...values)
  const hi = Math.max(...values)
  // A flat series has zero range; without this guard every point divides by
  // zero and the path collapses to NaN, which renders as nothing at all.
  const span = hi - lo || 1
  const step = width / (values.length - 1)
  const d = values
    .map((v, i) => `${i === 0 ? 'M' : 'L'}${(i * step).toFixed(1)},${(height - ((v - lo) / span) * height).toFixed(1)}`)
    .join(' ')
  return (
    <svg className="spark" width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden>
      <path d={d} fill="none" stroke={colour} strokeWidth="1.5" strokeLinejoin="round" />
    </svg>
  )
}

/** Placeholder block with the shimmer, so a loading page has the shape of the
 *  page that is coming rather than the word "loading". */
export function Skeleton({ h = 80, w }: { h?: number; w?: number | string }) {
  return <div className="skeleton" style={{ height: h, width: w ?? '100%' }} />
}
