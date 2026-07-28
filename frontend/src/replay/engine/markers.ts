/**
 * Pure geometry for everything the replay draws that is not a player dot.
 *
 * This lives apart from `Renderer` for one reason: **every bug this frontend
 * has actually shipped lived in a pure function**, and `Renderer` cannot be
 * tested without a GPU. The renderer keeps the Pixi calls; the arithmetic that
 * decides *what* and *where* is here, in node-testable form.
 *
 * Coordinates in and out are the bundle's **quantised u16** space, never world
 * pixels — `Renderer.toWorld` owns that conversion and it depends on the map,
 * which this module deliberately knows nothing about.
 */

import type { BundleEvent, ReplayBundle } from '../../lib/replayBundle'
import { FLAG_ALIVE } from '../../lib/replayBundle'

/** The CSR position block. Narrowed so tests can build one by hand. */
export type PosArrays = ReplayBundle['pos']

export interface Sample {
  /** Interpolated position, quantised. */
  x: number
  y: number
  /** Resolved cursor — the index of the sample at or before `tick`. */
  c: number
  /** Flags of the sample at or before `tick`. Not interpolated; they are bits. */
  flags: number
}

/**
 * Where player `p` is at `tick`, interpolated between position samples.
 *
 * **This is the single definition.** `Renderer.drawFrame` and `trailPoints`
 * both call it, so a trail can never disagree with the dot it trails from —
 * which is the failure mode worth designing against here, because a hundred
 * trails drawn from the wrong CSR row look like one thick line rather than
 * like a bug (HANDOFF §21: a hundred *dots* drawn from row 0 read as a quiet
 * map for exactly the same reason).
 *
 * `cursorHint` is an optimisation, not a contract: it must be a lower bound
 * for `tick`, and the result is identical without it.
 */
export function interpolateAt(
  pos: PosArrays,
  p: number,
  tick: number,
  cursorHint?: number,
): Sample | null {
  const start = pos.off[p]!
  const end = pos.off[p + 1]!
  if (start === end) return null

  let c = cursorHint !== undefined && cursorHint >= start && cursorHint < end ? cursorHint : start
  while (c + 1 < end && pos.t[c + 1]! <= tick) c++
  const t0 = pos.t[c]!
  if (t0 > tick) return null

  let x = pos.x[c]!
  let y = pos.y[c]!
  if (c + 1 < end) {
    const t1 = pos.t[c + 1]!
    const span = t1 - t0
    if (span > 0) {
      const f = Math.max(0, Math.min(1, (tick - t0) / span))
      x += (pos.x[c + 1]! - x) * f
      y += (pos.y[c + 1]! - y) * f
    }
  }
  return { x, y, c, flags: pos.flags[c]! }
}

/**
 * The last `windowTicks` of player `p`'s movement, oldest point first.
 *
 * Returned flat as `[x0, y0, x1, y1, …]`, quantised. The final pair is always
 * the *interpolated* current position, so the ribbon meets the dot instead of
 * ending at the last raw sample up to ten seconds behind it.
 *
 * A trail is **not** a fixed-length ribbon and callers must not assume one.
 * Measured on a live bundle, inter-sample gaps are median 1.0 s, p90 10.0 s
 * and max 197.8 s — so 30 s of trail is ~30 points while someone sprints and
 * 3 points while they hold a building. That is the correct behaviour: the
 * point density *is* the information.
 *
 * Returns an empty array for a player who is not in the match at `tick`, so a
 * corpse never keeps a trail.
 */
export function trailPoints(
  pos: PosArrays,
  p: number,
  tick: number,
  windowTicks: number,
  cursorHint?: number,
): number[] {
  const here = interpolateAt(pos, p, tick, cursorHint)
  if (here === null) return []
  if ((here.flags & FLAG_ALIVE) === 0) return []

  const start = pos.off[p]!
  const from = tick - windowTicks
  const out: number[] = []
  // Walk back to the first sample outside the window, then emit forwards.
  let first = here.c
  while (first > start && pos.t[first]! > from) first--
  for (let i = first; i <= here.c; i++) {
    if (pos.t[i]! < from) continue
    out.push(pos.x[i]!, pos.y[i]!)
  }
  out.push(here.x, here.y)
  return out
}

export interface CrateMarker {
  x: number
  y: number
  /** True between the spawn tick and the landing tick — it is still in the air. */
  falling: boolean
  /** Dictionary index of the package id, or -1 on a pre-v12 bundle. */
  pkg: number
}

export interface KillMarker {
  x: number
  y: number
  /** Victim player index, so the renderer can colour a tracked player's death. */
  v: number
}

export interface VehicleMarker {
  x: number
  y: number
  /** 1 at the moment of abandonment, decaying to 0 across the window. */
  age: number
}

export interface Markers {
  kills: KillMarker[]
  crates: CrateMarker[]
  vehicles: VehicleMarker[]
}

/**
 * Everything on the world layer at `tick`.
 *
 * **`drawEvents` used to be called exactly once, at `nowMs === 0`**, where its
 * `if (e.t > tick) break` fired on the first event and it drew nothing. Kill
 * markers and care packages were therefore never visible in the replay's
 * entire life, and because they were also drawn at ±4 *world* units — under
 * half a pixel at Erangel fit zoom — fixing only the call site would have
 * looked identical to not fixing it at all.
 *
 * Abandoned vehicles decay rather than persisting: there are ~245 `leave`
 * events in a match and a map carrying all of them at once is noise. A car
 * dumped thirty seconds ago is tactical information; one dumped fifteen
 * minutes ago is litter.
 */
export function markersAt(
  events: BundleEvent[],
  tick: number,
  vehicleWindowTicks: number,
): Markers {
  const kills: KillMarker[] = []
  const crates: CrateMarker[] = []
  const vehicles: VehicleMarker[] = []

  for (const e of events) {
    if (e.t > tick) break
    if (e.k === 'kill') {
      kills.push({ x: e.vx as number, y: e.vy as number, v: e.v as number })
    } else if (e.k === 'cp') {
      // `t` is the *spawn* tick and `land` the landing tick — roughly 30 s
      // apart. Drawn as one square from `t`, a crate appeared on the map half
      // a minute before it existed.
      const land = typeof e.land === 'number' ? e.land : e.t
      crates.push({
        x: e.x as number,
        y: e.y as number,
        falling: tick < land,
        pkg: typeof e.pkg === 'number' ? e.pkg : -1,
      })
    } else if (e.k === 'leave') {
      const age = 1 - (tick - e.t) / vehicleWindowTicks
      if (age > 0) vehicles.push({ x: e.x as number, y: e.y as number, age })
    }
  }
  return { kills, crates, vehicles }
}

/**
 * Radius in world units that renders as `screenR` device-independent pixels.
 *
 * Trivial, and it is the whole bug. Every marker in this renderer lives inside
 * the scaled world container, so a constant world radius shrinks with the map:
 * at Erangel fit the scale is ~0.11, which turned a 4-unit kill cross into
 * 0.44 px. `markerRadius(r, s) * s === r` at every scale, and there is a test
 * that says so, because "drawn sub-pixel" and "not drawn" are the same picture.
 */
export function markerRadius(screenR: number, viewportScale: number): number {
  return screenR / viewportScale
}
