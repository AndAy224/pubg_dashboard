import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import type { TileInfo } from '../api/types'
import { MapTiles } from './MapTiles'
import {
  FIT,
  MIN_SCALE,
  ZOOM_STEP,
  panBy,
  zoomAbout,
  zoomStep,
  type Transform,
} from '../lib/panZoom'

/**
 * A pannable, zoomable map box, shared by the kill map and the heatmaps.
 *
 * Two layers, and which one a thing belongs in is the whole design:
 *
 * * **`world`** is transformed with the map — the heat field, which *is* the
 *   terrain and must stay glued to it.
 * * **`overlay`** is drawn in screen space and handed the transform to position
 *   itself — kill dots and drop labels, which must keep a constant size. You
 *   zoom into a crowded firefight to *separate* the dots; markers that grow
 *   with the map arrive at the same pile, just larger. The replay counter-scales
 *   its markers for exactly this reason.
 *
 * The tile pyramid climbs with the zoom, so magnifying does not just stretch
 * one low-resolution tile.
 */
export function MapView({
  info,
  size,
  world,
  overlay,
  children,
}: {
  info: TileInfo
  /** The overlay's coordinate space, and the panel's natural width. */
  size: number
  world?: ReactNode
  overlay?: (t: Transform) => ReactNode
  children?: ReactNode
}) {
  const boxRef = useRef<HTMLDivElement>(null)
  const [t, setT] = useState<Transform>(FIT)
  const [widthPx, setWidthPx] = useState(size)

  // The rendered width, not `size` — `.mapwrap` is `width: 100%`, so the panel
  // is 660 px on a desktop and 324 px in a narrow pane, and it changes while
  // the user is looking at it. The tile level is chosen from this.
  useLayoutEffect(() => {
    const box = boxRef.current
    if (!box) return
    const observer = new ResizeObserver(([entry]) => {
      const w = entry?.contentRect.width ?? 0
      if (w > 0) setWidthPx(w)
    })
    observer.observe(box)
    return () => observer.disconnect()
  }, [])

  /** Pointer position as a fraction of the box, which is what `panZoom` speaks. */
  const fractionOf = useCallback((clientX: number, clientY: number) => {
    const rect = boxRef.current?.getBoundingClientRect()
    if (!rect || rect.width <= 0 || rect.height <= 0) return null
    return { fx: (clientX - rect.left) / rect.width, fy: (clientY - rect.top) / rect.height }
  }, [])

  // Attached by hand rather than with `onWheel`, because React's wheel listener
  // is passive and cannot `preventDefault` — without which every zoom also
  // scrolls the page out from under the map.
  useEffect(() => {
    const box = boxRef.current
    if (!box) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const at = fractionOf(e.clientX, e.clientY)
      if (!at) return
      const factor = e.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP
      setT((prev) => zoomAbout(prev, at.fx, at.fy, prev.scale * factor))
    }
    box.addEventListener('wheel', onWheel, { passive: false })
    return () => box.removeEventListener('wheel', onWheel)
  }, [fractionOf])

  const drag = useRef<{ x: number; y: number } | null>(null)

  const onPointerDown = (e: React.PointerEvent) => {
    // Nothing to pan to at fit, and grabbing there would swallow the hover that
    // the kill map's tooltips and shot lines depend on.
    if (t.scale <= MIN_SCALE) return
    drag.current = { x: e.clientX, y: e.clientY }
    e.currentTarget.setPointerCapture(e.pointerId)
  }

  const onPointerMove = (e: React.PointerEvent) => {
    const from = drag.current
    const rect = boxRef.current?.getBoundingClientRect()
    if (!from || !rect || rect.width <= 0) return
    setT((prev) =>
      panBy(prev, (e.clientX - from.x) / rect.width, (e.clientY - from.y) / rect.height),
    )
    drag.current = { x: e.clientX, y: e.clientY }
  }

  const endDrag = (e: React.PointerEvent) => {
    if (drag.current === null) return
    drag.current = null
    if (e.currentTarget.hasPointerCapture(e.pointerId)) {
      e.currentTarget.releasePointerCapture(e.pointerId)
    }
  }

  const zoomed = t.scale > MIN_SCALE

  return (
    <div className="mapwrap mapview" style={{ maxWidth: size }}>
      <div
        ref={boxRef}
        className={`mapview-stage ${zoomed ? 'zoomed' : ''}`}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
      >
        <div
          className="mapview-world"
          style={{
            // Percentages of the layer's own box, which is the map box — so the
            // transform stays correct at any rendered width.
            transform: `translate(${t.x * 100}%, ${t.y * 100}%) scale(${t.scale})`,
          }}
        >
          <MapTiles info={info} widthPx={widthPx} scale={t.scale} />
          {world}
        </div>
        {overlay?.(t)}
      </div>

      <div className="mapview-controls">
        <button onClick={() => setT((p) => zoomStep(p, ZOOM_STEP))} title="zoom in">+</button>
        <button onClick={() => setT((p) => zoomStep(p, 1 / ZOOM_STEP))} title="zoom out">−</button>
        <button
          className="mapview-reset"
          onClick={() => setT(FIT)}
          disabled={!zoomed}
          title="reset the view"
        >
          {zoomed ? `${t.scale.toFixed(1)}×` : 'fit'}
        </button>
      </div>
      {children}
    </div>
  )
}
