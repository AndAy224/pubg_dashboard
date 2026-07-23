import { useEffect, useRef } from 'react'
import type { Heatmap } from '../api/types'

/**
 * Renders a heatmap grid over the map tiles.
 *
 * **`ctx.filter = 'blur()'` is deliberately not used.** It is disabled by
 * default in Safari desktop and iOS 18.0–26.5, so the heatmap would silently
 * render unblurred for a chunk of users — no error, just a worse picture that
 * nobody reports. Blurring 65k cells by hand is a few milliseconds and runs
 * once per filter change.
 */

/** Three box blurs approximate a gaussian closely enough at this scale. */
type F32 = Float32Array<ArrayBuffer>

function boxBlur(src: F32, w: number, h: number, radius: number): F32 {
  let a: F32 = src
  let b: F32 = new Float32Array(src.length)
  for (let pass = 0; pass < 3; pass++) {
    // horizontal
    for (let y = 0; y < h; y++) {
      const row = y * w
      for (let x = 0; x < w; x++) {
        let sum = 0
        let n = 0
        for (let d = -radius; d <= radius; d++) {
          const xx = x + d
          if (xx < 0 || xx >= w) continue
          sum += a[row + xx]!
          n++
        }
        b[row + x] = sum / n
      }
    }
    ;[a, b] = [b, a]
    // vertical
    for (let x = 0; x < w; x++) {
      for (let y = 0; y < h; y++) {
        let sum = 0
        let n = 0
        for (let d = -radius; d <= radius; d++) {
          const yy = y + d
          if (yy < 0 || yy >= h) continue
          sum += a[yy * w + x]!
          n++
        }
        b[y * w + x] = sum / n
      }
    }
    ;[a, b] = [b, a]
  }
  return a
}

/** 256-entry ramp: transparent -> cyan -> amber -> red. */
function ramp(t: number): [number, number, number, number] {
  const c = Math.max(0, Math.min(1, t))
  if (c < 0.001) return [0, 0, 0, 0]
  if (c < 0.4) {
    const k = c / 0.4
    return [Math.round(40 * k), Math.round(150 * k + 40), Math.round(200 * k + 55), Math.round(190 * k)]
  }
  if (c < 0.75) {
    const k = (c - 0.4) / 0.35
    return [Math.round(40 + 200 * k), Math.round(190 - 10 * k), Math.round(255 - 200 * k), 200 + Math.round(40 * k)]
  }
  const k = (c - 0.75) / 0.25
  return [Math.round(240 + 15 * k), Math.round(180 - 140 * k), Math.round(55 - 40 * k), 245]
}

export function decodeCells(b64: string): Uint32Array {
  const bin = atob(b64)
  const bytes = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
  // Little-endian, matching what the server wrote.
  return new Uint32Array(bytes.buffer, bytes.byteOffset, bytes.byteLength / 4)
}

/**
 * The heat layer, filling whatever box `.mapwrap` gives it.
 *
 * There is deliberately no `size`: the backing store is the heatmap's own
 * grid resolution and CSS scales it to the wrapper, so the canvas stays
 * correct at any rendered width instead of being pinned to a pixel count.
 */
export function HeatmapCanvas({
  heatmap,
  blurRadius = 2,
  opacity = 0.82,
}: {
  heatmap: Heatmap
  blurRadius?: number
  opacity?: number
}) {
  const ref = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = ref.current
    if (!canvas) return
    const g = heatmap.grid
    canvas.width = g
    canvas.height = g
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const cells = decodeCells(heatmap.cells)
    const field: F32 = new Float32Array(g * g)
    for (let i = 0; i < field.length; i++) field[i] = cells[i] ?? 0

    const blurred = boxBlur(field, g, g, blurRadius)

    // Normalise on the blurred peak, not the raw one: blurring lowers the
    // maximum, and using the raw peak makes every heatmap look washed out.
    let peak = 0
    for (let i = 0; i < blurred.length; i++) if (blurred[i]! > peak) peak = blurred[i]!
    if (peak <= 0) return

    const img = ctx.createImageData(g, g)
    for (let i = 0; i < blurred.length; i++) {
      // sqrt keeps a handful of hot cells from flattening everything else.
      const [r, gg, b, a] = ramp(Math.sqrt(blurred[i]! / peak))
      const o = i * 4
      img.data[o] = r
      img.data[o + 1] = gg
      img.data[o + 2] = b
      img.data[o + 3] = a
    }
    ctx.putImageData(img, 0, 0)
  }, [heatmap, blurRadius])

  return (
    <canvas
      ref={ref}
      style={{
        position: 'absolute',
        inset: 0,
        width: '100%',
        height: '100%',
        opacity,
        // The grid is row-major with y growing downward, exactly like the
        // canvas — so it is drawn as-is. No flip.
        imageRendering: 'auto',
        pointerEvents: 'none',
      }}
    />
  )
}
