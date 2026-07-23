import type { TileInfo } from '../api/types'
import { apiBase } from '../api/client'
import { tileLevel } from '../lib/panZoom'

/**
 * The tile pyramid as a plain CSS grid of <img>.
 *
 * Deliberately not Pixi: outside the replay there is no animation, the tiles
 * are immutable and the browser's own cache handles them better than anything
 * we would write.
 *
 * The level is chosen from the pixels actually on screen — the rendered width,
 * the current zoom and the device pixel ratio — rather than fixed. It used to
 * be a hardcoded `zoom={1}`, which was right for a static 660 px panel at
 * dpr 1 and wrong for everything else: on a retina display it stretched a
 * 512 px tile over 1320 device pixels, and once these maps became zoomable it
 * would have magnified that same stretched tile instead of fetching detail
 * that already exists. That exact mistake shipped in the replay (HANDOFF §18)
 * and reads as a bad screenshot rather than as a bug.
 */
export function MapTiles({
  info,
  widthPx,
  scale = 1,
}: {
  info: TileInfo
  /** Rendered width of the map box in CSS pixels. */
  widthPx: number
  scale?: number
}) {
  const dpr = Math.max(1, globalThis.devicePixelRatio || 1)
  const z = tileLevel(widthPx, scale, info.tilePx, info.maxZoom, dpr)
  const n = 2 ** z
  const tiles = []
  for (let y = 0; y < n; y++) {
    for (let x = 0; x < n; x++) {
      tiles.push(
        <img
          key={`${x}_${y}`}
          src={`${apiBase}/tiles/${info.mapName}/${z}/${x}_${y}.webp`}
          loading="lazy"
          alt=""
          /* **Load-bearing.** An `<img>` is natively draggable, so pressing on
             one starts an HTML5 image drag: the browser fires `pointercancel`,
             the pointer stream stops dead, and the user gets a ghost thumbnail
             on the cursor instead of a panning map. The kill map hid this by
             accident — its SVG overlay covers the tiles, so the press never
             lands on an image. The heatmaps have no overlay and panned exactly
             one pointer event before dying. */
          draggable={false}
          /* Fills its 1fr grid cell so the pyramid scales with the wrapper
             rather than pinning it to a pixel count. */
          style={{ display: 'block', width: '100%', height: '100%' }}
        />,
      )
    }
  }
  return (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        display: 'grid',
        gridTemplateColumns: `repeat(${n}, 1fr)`,
      }}
    >
      {tiles}
    </div>
  )
}
