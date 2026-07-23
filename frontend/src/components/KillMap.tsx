import { useMemo, useState } from 'react'
import type { KillRow, MatchDetail, TileInfo } from '../api/types'
import { MapView } from './MapView'
import { weaponName } from '../lib/format'
import './KillMap.css'

/**
 * Where every kill happened, drawn from `kill_events`.
 *
 * The positions have been stored since the parser was written and were never
 * rendered. Nothing new is fetched or computed on the server.
 *
 * **The transform has no y flip.** Telemetry's origin is top-left with y
 * growing downward, exactly like canvas, and the `8160/8192` correction
 * (`imageScale`) applies only to the 816000-cm maps. Flipping y yields a
 * mirrored map that still looks entirely plausible.
 */
export function KillMap({
  kills,
  match,
  info,
  size,
}: {
  kills: KillRow[]
  match: MatchDetail
  info: TileInfo
  size: number
}) {
  const [focus, setFocus] = useState<number | null>(null)
  const [trackedOnly, setTrackedOnly] = useState(false)

  const trackedIds = useMemo(
    () =>
      new Set(
        match.rosters.flatMap((r) => r.participants.filter((p) => p.tracked).map((p) => p.accountId)),
      ),
    [match.rosters],
  )

  const toPx = useMemo(() => {
    const k = info.imageScale
    return (cm: number) => (cm / match.worldSize) * size * k
  }, [info.imageScale, match.worldSize, size])

  const shown = useMemo(
    () =>
      kills.filter(
        (k) =>
          !trackedOnly ||
          trackedIds.has(k.victimAccountId) ||
          (k.killerAccountId !== null && trackedIds.has(k.killerAccountId)),
      ),
    [kills, trackedOnly, trackedIds],
  )

  const landings = useMemo(
    () =>
      match.rosters
        .flatMap((r) => r.participants)
        .filter((p) => p.tracked && p.landingX !== null && p.landingY !== null),
    [match.rosters],
  )

  return (
    <div className="killmap">
      <div className="row" style={{ marginBottom: 8 }}>
        <h3>Kill map</h3>
        <div className="spacer" />
        <button className={trackedOnly ? 'on' : ''} onClick={() => setTrackedOnly((v) => !v)}>
          {trackedOnly ? 'tracked only' : 'everyone'}
        </button>
        <span className="faint small">{shown.length} kills</span>
      </div>

      <MapView
        info={info}
        size={size}
        overlay={(t) => {
          // Map centimetres straight to overlay units. The markers live
          // *outside* the transformed layer so they keep a constant size —
          // you zoom into a crowded fight to separate the dots, and markers
          // that grow with the map arrive at the same pile, just larger.
          const at = (cm: number) => size * t.x + toPx(cm) * t.scale
          const atY = (cm: number) => size * t.y + toPx(cm) * t.scale
          return (
            <svg
              className="killmap-svg"
              width={size}
              height={size}
              viewBox={`0 0 ${size} ${size}`}
            >
              {/* Tracer from killer to victim, drawn only for the hovered kill
                  so the map is not a bowl of spaghetti at 100 kills. */}
              {focus !== null &&
                shown[focus]?.killerX != null &&
                shown[focus]?.killerY != null && (
                  <line
                    className="tracer"
                    x1={at(shown[focus]!.killerX!)}
                    y1={atY(shown[focus]!.killerY!)}
                    x2={at(shown[focus]!.victimX)}
                    y2={atY(shown[focus]!.victimY)}
                  />
                )}

              {landings.map((p) => (
                <g key={`land-${p.accountId}`} className="landing">
                  <circle cx={at(p.landingX!)} cy={atY(p.landingY!)} r={5} />
                  <text x={at(p.landingX!) + 8} y={atY(p.landingY!) + 4}>
                    {p.name}
                  </text>
                </g>
              ))}

              {shown.map((k, i) => {
                const tracked =
                  trackedIds.has(k.victimAccountId) ||
                  (k.killerAccountId !== null && trackedIds.has(k.killerAccountId))
                const victimTracked = trackedIds.has(k.victimAccountId)
                return (
                  <circle
                    key={k.seq}
                    className={`kill-dot ${tracked ? 'tracked' : ''} ${
                      victimTracked ? 'victim' : ''
                    } ${k.victimIsBot ? 'bot' : ''}`}
                    cx={at(k.victimX)}
                    cy={atY(k.victimY)}
                    r={tracked ? 4.5 : 3}
                    onMouseEnter={() => setFocus(i)}
                    onMouseLeave={() => setFocus(null)}
                  >
                    <title>
                      {`${k.killerName ?? 'zone/fall'} → ${k.victimName ?? '?'}` +
                        (k.weapon ? ` · ${weaponName(k.weapon)}` : '') +
                        (k.distanceM !== null ? ` · ${Math.round(k.distanceM)} m` : '')}
                    </title>
                  </circle>
                )
              })}
            </svg>
          )
        }}
      />

      <div className="killmap-legend faint small">
        <span><i className="sw tracked" /> tracked player involved</span>
        <span><i className="sw victim" /> tracked player died</span>
        <span><i className="sw bot" /> bot victim</span>
        <span><i className="sw landing" /> drop point</span>
        <span>hover a dot for the shot line · scroll to zoom</span>
      </div>
    </div>
  )
}
