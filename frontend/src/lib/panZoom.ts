/**
 * Pan and zoom for the DOM maps — the kill map and the heatmaps.
 *
 * **Everything here is in viewport *fractions*, not pixels.** `x: -0.25` means
 * "shifted left by a quarter of the box", whatever the box currently measures.
 * That matters because these maps are fluid: `.mapwrap` is `width: 100%` with a
 * square aspect ratio, so the same panel is 660 px on a desktop and 324 px in a
 * narrow pane, and it changes width while the user is looking at it. A pixel
 * offset captured at one width is silently wrong at the next, and the failure
 * looks like a map that drifts when you resize the window rather than like a
 * unit bug.
 *
 * Fractions also let one transform drive two coordinate systems that never
 * learn each other's units: a CSS `translate(%) scale()` on the tile layer, and
 * SVG user units on the marker overlay.
 *
 * The replay has its own pan/zoom in `replay/engine/Viewport.ts` and keeps it.
 * It is parameterised in pixels against a fixed `worldPx`, carries follow-cam
 * and drives Pixi containers rather than DOM nodes; merging the two would
 * complicate the most fragile part of the renderer to save a dozen lines of
 * arithmetic. Only the *ideas* are shared, and both are tested separately.
 */

export interface Transform {
  /** 1 is fit-to-box. Never below — see `MIN_SCALE`. */
  scale: number
  /** Pan, as a fraction of the viewport's own width and height. */
  x: number
  y: number
}

export const FIT: Transform = { scale: 1, x: 0, y: 0 }

/**
 * Fit is the floor, deliberately.
 *
 * The map already fills the box at 1, so zooming out only pads it with
 * background — an easy state to reach by over-scrolling and a confusing one to
 * be in, since nothing outside the map exists to look at.
 */
export const MIN_SCALE = 1

/**
 * Erangel is 8x8 km across ~660 px, so 8x puts roughly 1 km across the panel.
 * Past that the tile pyramid runs out of levels and further zoom only
 * magnifies blur.
 */
export const MAX_SCALE = 8

/** One wheel notch. */
export const ZOOM_STEP = 1.25

/**
 * Keep the map covering the box on one axis.
 *
 * Below fit there is no edge to pin to, so it centres instead. Without this,
 * panning at high zoom walks the map off screen and leaves an empty panel that
 * looks broken rather than scrolled.
 */
export function clampAxis(pos: number, scale: number): number {
  if (scale <= 1) return (1 - scale) / 2
  return Math.max(1 - scale, Math.min(0, pos))
}

export function clamp(t: Transform): Transform {
  return { scale: t.scale, x: clampAxis(t.x, t.scale), y: clampAxis(t.y, t.scale) }
}

export function limitScale(scale: number): number {
  return Math.max(MIN_SCALE, Math.min(MAX_SCALE, scale))
}

/**
 * Zoom, keeping whatever sits under (`fx`, `fy`) exactly where it is.
 *
 * `fx`/`fy` are the pointer as a fraction of the box. Scaling about the origin
 * instead is the classic version of this bug: the map slides out from under the
 * cursor, so aiming at a compound and zooming lands you somewhere else.
 */
export function zoomAbout(t: Transform, fx: number, fy: number, nextScale: number): Transform {
  const scale = limitScale(nextScale)
  if (scale === t.scale) return t
  // Where the cursor is in map space, then put that back under the cursor.
  const mapX = (fx - t.x) / t.scale
  const mapY = (fy - t.y) / t.scale
  return clamp({ scale, x: fx - mapX * scale, y: fy - mapY * scale })
}

/** Drag, in fractions of the box. */
export function panBy(t: Transform, dx: number, dy: number): Transform {
  return clamp({ scale: t.scale, x: t.x + dx, y: t.y + dy })
}

/** Zoom a step about the centre, for the +/- buttons. */
export function zoomStep(t: Transform, factor: number): Transform {
  return zoomAbout(t, 0.5, 0.5, t.scale * factor)
}

/**
 * Tile pyramid level for the current zoom.
 *
 * Level `z` is a 2^z grid of `tilePx` tiles, so the whole map carries
 * `tilePx * 2^z` pixels; on screen it covers `widthPx * scale * dpr` device
 * pixels. Solving for z gives the log.
 *
 * The replay shipped with this hardcoded three levels too low and the map was
 * simply blurry — the tiles were always fine, the wrong one was being asked
 * for. A zoomable map that does not climb the pyramid magnifies a stretched
 * low-resolution tile, which reads as a bad screenshot rather than a bug.
 */
export function tileLevel(
  widthPx: number,
  scale: number,
  tilePx: number,
  maxZoom: number,
  dpr = 1,
): number {
  if (!(widthPx > 0) || !(tilePx > 0) || !Number.isFinite(scale)) return 0
  const needed = (widthPx * scale * Math.max(1, dpr)) / tilePx
  return Math.max(0, Math.min(maxZoom, Math.ceil(Math.log2(Math.max(needed, 1)))))
}
