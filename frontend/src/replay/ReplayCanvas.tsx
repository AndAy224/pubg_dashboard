import { useEffect, useRef } from 'react'
import { Application } from 'pixi.js'
import type { ReplayBundle } from '../lib/replayBundle'
import { Renderer } from './engine/Renderer'
import { reset } from './store'
import { apiBase } from '../api/client'

/**
 * The only React <-> Pixi boundary in the app.
 *
 * Everything below this component is imperative and pooled; everything above
 * is React. The effect remounts only when the match changes.
 */
export function ReplayCanvas({
  bundle,
  sourcePx,
  imageScale,
  maxZoom,
  tracked,
  onReady,
  onError,
}: {
  bundle: ReplayBundle
  sourcePx: number
  imageScale: number
  maxZoom: number
  tracked: Set<string>
  onReady: (r: Renderer) => void
  onError?: (message: string) => void
}) {
  const holder = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let app: Application | null = null
    let renderer: Renderer | null = null
    let cancelled = false

    ;(async () => {
      const el = holder.current
      if (!el) return
      app = new Application()
      await app.init({
        background: 0x0a0d11,
        antialias: true,
        resolution: window.devicePixelRatio,
        autoDensity: true,
        resizeTo: el,
        preference: 'webgpu',
      })
      if (cancelled) {
        app.destroy(true, { children: true, texture: true })
        return
      }
      // `app.canvas` — `app.view` was removed in Pixi v8.
      el.appendChild(app.canvas as HTMLCanvasElement)
      ;(app.canvas as HTMLCanvasElement).style.cursor = 'grab'

      reset()
      renderer = new Renderer(app, {
        bundle,
        tileBase: `${apiBase}/tiles`,
        mapName: bundle.mapName,
        sourcePx,
        imageScale,
        maxZoom,
        tracked,
        onError,
      })
      renderer.start()
      renderer.drawEvents()
      onReady(renderer)
    })().catch((e: unknown) => {
      // Without this the whole init is a floating promise: any failure — WebGPU
      // refusing to initialise, a bad bundle — rejected into nothing, `onReady`
      // never fired, and the page sat on a black rectangle with no explanation.
      if (!cancelled) onError?.(e instanceof Error ? e.message : String(e))
    })

    return () => {
      cancelled = true
      renderer?.destroy()
      app?.destroy(true, { children: true, texture: true })
    }
  }, [bundle, sourcePx, imageScale, maxZoom, tracked, onReady, onError])

  return <div ref={holder} className="canvas-holder" />
}
