import type { TileInfo } from '../api/types'
import { apiBase } from '../api/client'

/**
 * The tile pyramid as a plain CSS grid of <img>.
 *
 * Deliberately not Pixi: outside the replay there is no animation, the tiles
 * are immutable and the browser's own cache handles them better than anything
 * we would write.
 */
export function MapTiles({ info, size, zoom }: { info: TileInfo; size: number; zoom: number }) {
  const z = Math.max(0, Math.min(zoom, info.maxZoom))
  const n = 2 ** z
  const tiles = []
  for (let y = 0; y < n; y++) {
    for (let x = 0; x < n; x++) {
      tiles.push(
        <img
          key={`${x}_${y}`}
          src={`${apiBase}/tiles/${info.mapName}/${z}/${x}_${y}.webp`}
          width={size / n}
          height={size / n}
          loading="lazy"
          alt=""
          style={{ display: 'block' }}
        />,
      )
    }
  }
  return (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        width: size,
        height: size,
        display: 'grid',
        gridTemplateColumns: `repeat(${n}, 1fr)`,
      }}
    >
      {tiles}
    </div>
  )
}
