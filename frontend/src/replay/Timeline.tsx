import { useMemo } from 'react'
import type { ReplayBundle } from '../lib/replayBundle'
import { NULL_PLAYER } from '../lib/replayBundle'
import { duration } from '../lib/format'

/**
 * The match strip: a scrubber with the shape of the match drawn behind it.
 *
 * Everything here comes out of the bundle, which has carried it since the
 * parser was written: `zones.alive` is a per-sample survivor count, `phase`
 * events mark the blue-zone steps, and every kill already has a tick. Nothing
 * new is fetched.
 *
 * The point is to make fights findable. A flat scrubber gives no clue where
 * anything happened in a 30-minute match; the alive curve's cliffs are the
 * fights, and the ticks say who was in them.
 */
export function Timeline({
  bundle,
  nowMs,
  tracked,
  onSeek,
}: {
  bundle: ReplayBundle
  nowMs: number
  tracked: Set<string>
  onSeek: (ms: number) => void
}) {
  const width = 1000
  const height = 34

  const { curve, kills, phases } = useMemo(() => {
    const total = bundle.durationMs || 1
    const z = bundle.zones

    // Alive count over time, as an SVG area. `zones.t` is in ticks.
    const points: string[] = []
    const maxAlive = Math.max(1, ...Array.from(z.alive))
    for (let i = 0; i < z.n; i++) {
      const x = ((z.t[i]! * bundle.tickMs) / total) * width
      const y = height - (z.alive[i]! / maxAlive) * height
      points.push(`${x.toFixed(1)},${y.toFixed(1)}`)
    }
    const area =
      points.length > 1 ? `M0,${height} L${points.join(' L')} L${width},${height} Z` : ''

    const trackedIdx = new Set(
      bundle.players.map((p, i) => (tracked.has(p.a) ? i : -1)).filter((i) => i >= 0),
    )

    const killTicks = bundle.events
      .filter((e) => e.k === 'kill')
      .map((e) => {
        const victim = e.v as number
        const killer = e.p as number
        const involvesTracked =
          trackedIdx.has(victim) || (killer !== NULL_PLAYER && trackedIdx.has(killer))
        return {
          x: ((e.t * bundle.tickMs) / total) * width,
          ms: e.t * bundle.tickMs,
          tracked: involvesTracked,
          victimTracked: trackedIdx.has(victim),
          label: `${bundle.players[killer]?.n ?? 'zone'} → ${bundle.players[victim]?.n ?? '?'}`,
        }
      })

    const phaseTicks = bundle.events
      .filter((e) => e.k === 'phase')
      .map((e) => ({ x: ((e.t * bundle.tickMs) / total) * width, ph: e.ph as number }))

    return { curve: area, kills: killTicks, phases: phaseTicks }
  }, [bundle, tracked])

  const playheadX = ((nowMs / (bundle.durationMs || 1)) * width).toFixed(1)

  const seekFromEvent = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect()
    const frac = (e.clientX - rect.left) / rect.width
    onSeek(Math.max(0, Math.min(1, frac)) * bundle.durationMs)
  }

  return (
    <div className="timeline">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        className="timeline-svg"
        onClick={seekFromEvent}
      >
        <path className="tl-alive" d={curve} />

        {phases.map((p, i) => (
          <line key={`ph-${i}`} className="tl-phase" x1={p.x} x2={p.x} y1={0} y2={height} />
        ))}

        {kills.map((k, i) => (
          <line
            key={`k-${i}`}
            className={`tl-kill ${k.tracked ? 'tracked' : ''} ${k.victimTracked ? 'victim' : ''}`}
            x1={k.x}
            x2={k.x}
            y1={k.tracked ? 0 : height * 0.55}
            y2={height}
          >
            <title>{`${duration(k.ms / 1000)} · ${k.label}`}</title>
          </line>
        ))}

        <line className="tl-playhead" x1={playheadX} x2={playheadX} y1={0} y2={height} />
      </svg>
    </div>
  )
}
