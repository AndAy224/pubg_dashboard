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
  tilePx,
  imageScale,
  maxZoom,
  tracked,
  onReady,
  onError,
}: {
  bundle: ReplayBundle
  sourcePx: number
  tilePx: number
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
    /** True only once `app.init()` has resolved. See the cleanup below. */
    let initialised = false

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
      initialised = true
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
        tilePx,
        imageScale,
        maxZoom,
        tracked,
        onError,
      })
      renderer.start()
      // Deliberately global. Three replay bugs in a row were only findable by
      // driving the live renderer from a headless browser
      // (`scripts/probe-replay.mjs`), and a handle turns that from guesswork
      // into two lines. This is a LAN dashboard for three people; the leak is
      // a debugging affordance, not an attack surface.
      ;(window as unknown as Record<string, unknown>).__replay = renderer
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
      // **Only an Application that finished `init()` may be destroyed.** Pixi's
      // ResizePlugin assigns `_cancelResize` during `init`, and `destroy()`
      // calls it unconditionally — so tearing down while `init()` is still in
      // flight throws `this._cancelResize is not a function`, synchronously,
      // inside a React cleanup. React Router's error boundary then takes the
      // whole page, the canvas reads as MISSING, and the only message anyone
      // gets names a Pixi internal that has nothing to do with the problem.
      //
      // Observed once in a headless probe and not reproduced in five further
      // runs, which is exactly how a mount/unmount race behaves. Nothing is
      // actually wrong in that case: the `if (cancelled)` branch above already
      // destroys the app properly once init resolves.
      if (initialised) app?.destroy(true, { children: true, texture: true })
    }
  }, [bundle, sourcePx, tilePx, imageScale, maxZoom, tracked, onReady, onError])

  return <div ref={holder} className="canvas-holder" />
}
