import { useMemo, useState } from 'react'
import type { DropRow, Gazetteer, TileInfo } from '../api/types'
import { MapView } from './MapView'
import { clusterDrops, labelCluster, summariseCluster } from '../lib/drops'
import { placeName } from '../lib/format'
import type { ClusterLabel, DropCluster } from '../lib/drops'
import './DropMap.css'

/**
 * Where the squad drops, and whether it worked.
 *
 * The heatmaps have always shown *where* landings happen. None of them showed
 * whether landing there was a good idea. This is the same positions joined to
 * the placement on the same row.
 *
 * **The transform has no y flip** — telemetry's origin is top-left with y
 * growing downward, exactly like canvas, and `imageScale` corrects only the
 * 816000-cm maps. Flipping y yields a mirrored map that looks entirely
 * plausible.
 *
 * Markers live in the **overlay** layer, so they keep a constant screen size:
 * you zoom in to separate two nearby spots, and markers that grow with the map
 * arrive at the same pile, just larger.
 */
export function DropMap({
  drops,
  gazetteer,
  info,
  worldSize,
  size,
  selected,
  onSelect,
}: {
  drops: DropRow[]
  gazetteer: Gazetteer | null
  info: TileInfo
  worldSize: number
  size: number
  selected: string | null
  onSelect: (id: string | null) => void
}) {
  const clusters = useMemo(() => clusterDrops(drops), [drops])
  const [hover, setHover] = useState<string | null>(null)

  const toPx = useMemo(() => {
    const k = info.imageScale
    return (cm: number) => (cm / worldSize) * size * k
  }, [info.imageScale, worldSize, size])

  // Marker area scales with n, so a spot used twice as often reads as twice
  // the ink rather than twice the radius — area is what the eye compares.
  const maxN = Math.max(1, ...clusters.map((c) => c.drops.length))
  const radiusOf = (n: number) => 5 + 13 * Math.sqrt(n / maxN)

  return (
    <MapView
      info={info}
      size={size}
      overlay={(t) => {
        const at = (cm: number) => size * t.x + toPx(cm) * t.scale
        return (
          <svg className="dropmap-svg" width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
            {clusters.map((cluster) => {
              const s = summariseCluster(cluster)
              const label = labelCluster(cluster, gazetteer)
              const cx = at(cluster.x)
              const cy = at(cluster.y)
              const r = radiusOf(s.n)
              const active = selected === cluster.id || hover === cluster.id
              return (
                <g
                  key={cluster.id}
                  className={`drop-marker ${placeClass(s.medianPlace)} ${active ? 'active' : ''}`}
                  onMouseEnter={() => setHover(cluster.id)}
                  onMouseLeave={() => setHover(null)}
                  onClick={() => onSelect(selected === cluster.id ? null : cluster.id)}
                >
                  <circle cx={cx} cy={cy} r={r} />
                  <text className="drop-n" x={cx} y={cy + 4}>
                    {s.n}
                  </text>
                  {(active || s.n >= 5) && (
                    <text className="drop-label" x={cx} y={cy - r - 5}>
                      {shortLabel(label)}
                    </text>
                  )}
                </g>
              )
            })}
          </svg>
        )
      }}
    />
  )
}

/**
 * Placement banding for the marker colour.
 *
 * Three bands, not a gradient: with 1–25 drops per spot the median placement
 * is not precise enough to justify a continuous scale, and a gradient invites
 * reading a two-place difference as meaningful.
 */
export function placeClass(medianPlace: number): string {
  if (medianPlace <= 0) return 'unplaced'
  if (medianPlace <= 10) return 'good'
  if (medianPlace <= 25) return 'mid'
  return 'poor'
}

/** The marker caption. Open country gets a bearing, never a nearby town's name. */
export function shortLabel(label: ClusterLabel): string {
  if (label.kind === 'named' && label.name) return placeName(label.name)
  if (label.kind === 'unnamed' && label.nearest) {
    return `${label.bearing} of ${placeName(label.nearest)}`
  }
  return 'unnamed'
}

/** The full caption, used in the table where there is room for the distance. */
export function fullLabel(label: ClusterLabel): string {
  if (label.kind === 'named' && label.name) return placeName(label.name)
  if (label.kind === 'unnamed' && label.nearest && label.nearestDistanceM !== null) {
    const d =
      label.nearestDistanceM >= 1000
        ? `${(label.nearestDistanceM / 1000).toFixed(1)} km`
        : `${Math.round(label.nearestDistanceM)} m`
    return `unnamed — ${d} ${label.bearing} of ${placeName(label.nearest)}`
  }
  // `unknown` means no gazetteer was built for this map at all, which is a
  // missing artifact rather than a place with no name. Say so.
  return 'no place names for this map'
}

export type { DropCluster }
