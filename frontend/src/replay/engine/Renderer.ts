import { Application, Assets, Container, Graphics, Sprite, Text, Texture } from 'pixi.js'
import type { ReplayBundle } from '../../lib/replayBundle'
import { FLAG_ALIVE, FLAG_DBNO, FLAG_IN_VEHICLE, NULL_PLAYER } from '../../lib/replayBundle'
import { BOT_COLOUR, teamColour } from '../../lib/palette'
import { playerColourInt } from '../../lib/players'
import { Viewport } from './Viewport'
import { publish } from '../store'

/**
 * The replay renderer.
 *
 * **React never renders at 60 Hz.** Everything here is imperative Pixi; the
 * playhead lives on this object, and DOM panels subscribe to an external store
 * that ticks at 10 Hz. That boundary is the whole performance design.
 *
 * PixiJS v8 API only — `beginFill`/`drawRect`/`lineStyle`/`app.view`/
 * `cacheAsBitmap` and the ticker's delta argument are all gone.
 */

const DOT_R = 5

/** Below this viewport scale every name at once is unreadable clutter, so only
 *  the tracked players and whoever is being followed keep a label. */
const LABEL_SCALE = 0.55

interface Options {
  bundle: ReplayBundle
  tileBase: string
  mapName: string
  sourcePx: number
  /** Edge length of one tile in the pyramid. Needed to choose a level whose
   *  resolution matches the display; without it the map renders blurred. */
  tilePx: number
  imageScale: number
  maxZoom: number
  tracked: Set<string>
  /** Surfaced in the UI. A renderer that fails silently is a black rectangle
   *  nobody can debug — which is exactly how this page shipped. */
  onError?: (message: string) => void
}

export class Renderer {
  private readonly world = new Container()
  private readonly mapLayer = new Container()
  private readonly gridLayer = new Container()
  private readonly zoneLayer = new Graphics()
  private readonly trailLayer = new Graphics()
  private readonly worldLayer = new Container()
  private readonly dotLayer = new Container()
  private readonly labelLayer = new Container()
  private readonly fxLayer = new Container()

  private readonly dots: Sprite[] = []
  private readonly rings: Graphics[] = []
  /** Built lazily — a hundred `Text` objects up front is a hundred canvas
   *  rasterisations, and most are never shown. */
  private readonly labels: (Text | null)[] = []
  /** Monotonic per-player cursor into the CSR arrays — the hot loop's state. */
  private readonly cursor: Int32Array
  private readonly worldPx: number
  private viewport!: Viewport
  private tileLevel = -1
  private destroyed = false

  /** Playhead, in milliseconds since t0. A ref, never React state. */
  nowMs = 0
  speed = 1
  playing = true

  private readonly app: Application
  private readonly opts: Options

  constructor(app: Application, opts: Options) {
    this.app = app
    this.opts = opts
    const b = opts.bundle
    this.cursor = new Int32Array(b.players.length)
    // World units are source-image pixels, so the cm->px transform is the same
    // one the tiles were cut with (including the 8160/8192 correction).
    this.worldPx = opts.sourcePx

    this.world.addChild(
      this.mapLayer,
      this.gridLayer,
      this.trailLayer,
      this.zoneLayer,
      this.worldLayer,
      this.dotLayer,
      this.labelLayer,
      this.fxLayer,
    )
    app.stage.addChild(this.world)

    this.buildGrid()
    this.buildDots()
    this.viewport = new Viewport(
      app.canvas as HTMLCanvasElement,
      this.world,
      this.worldPx,
      (s) => this.onZoom(s),
    )
    this.onZoom(this.viewport.scale)
  }

  // -- geometry ------------------------------------------------------------
  /** Quantised bundle coordinate -> world pixels. */
  private toWorld(q: number): number {
    const cm = (q / 65535) * this.opts.bundle.worldSize
    return (cm / this.opts.bundle.worldSize) * this.worldPx * this.opts.imageScale
  }

  // -- layers --------------------------------------------------------------
  private buildGrid(): void {
    const g = new Graphics()
    const step = this.worldPx / 8
    for (let i = 1; i < 8; i++) {
      g.moveTo(i * step, 0).lineTo(i * step, this.worldPx)
      g.moveTo(0, i * step).lineTo(this.worldPx, i * step)
    }
    g.stroke({ width: 1, color: 0xffffff, alpha: 0.07 })
    this.gridLayer.addChild(g)

    // **Deliberately NOT cached to a texture.** `cacheAsTexture(true)` used to
    // be here, and it rasterises the container at its own bounds — which are
    // the whole world, 8192x8192. That is a 268 MB RGBA render texture at
    // devicePixelRatio 1 and 16384x16384 (1.07 GB, past the maximum texture
    // dimension on most GPUs) at dpr 2, to cache **fourteen straight lines**.
    // When the allocation fails Pixi throws inside its own render pass, which
    // runs as a separate lower-priority ticker listener — so our `drawFrame`
    // kept publishing to the store and the DOM panels kept updating while the
    // canvas stayed completely black. Fourteen lines cost nothing to redraw.
  }

  private buildDots(): void {
    const b = this.opts.bundle
    for (const p of b.players) {
      const s = new Sprite(Texture.WHITE)
      s.anchor.set(0.5)
      s.width = DOT_R * 2
      s.height = DOT_R * 2
      // Tracked players wear their **identity colour** — the same hue as their
      // nav entry, their match-feed chip and their trend line. They were all
      // rendered the same flat white, so on a hundred-dot map you could tell
      // that one of your squad was there but never which one.
      s.tint = p.b
        ? BOT_COLOUR
        : this.opts.tracked.has(p.a)
          ? playerColourInt(p.a)
          : teamColour(p.t)
      s.alpha = p.b ? 0.45 : 1
      s.visible = false
      this.dots.push(s)
      this.dotLayer.addChild(s)

      // A ring around the tracked players, so they are findable by shape as
      // well as by hue — three colours in a crowd is still a hunt.
      const ring = new Graphics()
      if (!p.b && this.opts.tracked.has(p.a)) {
        ring.circle(0, 0, DOT_R + 3).stroke({ width: 2, color: 0xffffff, alpha: 0.9 })
      }
      ring.visible = false
      this.rings.push(ring)
      this.dotLayer.addChild(ring)
    }
  }

  /** The name tag for one player, created on first use. */
  private label(p: number): Text {
    const existing = this.labels[p]
    if (existing) return existing
    const player = this.opts.bundle.players[p]!
    const t = new Text({
      text: player.n,
      style: {
        fontFamily: 'system-ui, sans-serif',
        fontSize: 12,
        fill: this.opts.tracked.has(player.a) ? playerColourInt(player.a) : 0xffffff,
        // An outline rather than a background: names sit over satellite
        // imagery that is light in the towns and dark in the water.
        stroke: { color: 0x000000, width: 3 },
      },
    })
    t.anchor.set(0.5, 1)
    t.visible = false
    this.labels[p] = t
    this.labelLayer.addChild(t)
    return t
  }

  /** Swap the tile pyramid level to match the current zoom. */
  private async onZoom(scale: number): Promise<void> {
    // A non-finite scale or maxZoom used to poison this silently: `wanted`
    // became NaN, the tile loops never ran, and the `tileLevel !== wanted`
    // check below is always true for NaN, so it returned having drawn
    // nothing and left `tileLevel` as NaN forever after.
    if (!Number.isFinite(scale) || !Number.isFinite(this.opts.maxZoom)) {
      this.opts.onError?.(
        `replay geometry is not a number (scale=${scale}, maxZoom=${this.opts.maxZoom})`,
      )
      return
    }

    // Pick the level whose pyramid has at least as many pixels as the map
    // occupies on the physical display.
    //
    // Level z is a 2^z grid of `tilePx` tiles, so the whole map is
    // `tilePx * 2^z` pixels; on screen it covers `worldPx * scale * dpr`
    // device pixels. Solving for z gives the log below.
    //
    // This used to be `ceil(log2(scale * 2))`, which accounts for neither the
    // tile size nor the device pixel ratio and lands **three levels low**: at
    // fit on a 900px canvas it chose level 0, stretching a single 512px tile
    // over 900 CSS pixels (1800 on a retina display). That is the blur — the
    // tiles were always fine, the wrong one was being asked for.
    const dpr = Math.max(1, globalThis.devicePixelRatio || 1)
    const needed = (this.worldPx * scale * dpr) / this.opts.tilePx
    const wanted = Math.max(
      0,
      Math.min(this.opts.maxZoom, Math.ceil(Math.log2(Math.max(needed, 1)))),
    )
    if (wanted === this.tileLevel) return
    this.tileLevel = wanted

    const n = 2 ** wanted
    const size = this.worldPx / n
    const urls: string[] = []
    for (let y = 0; y < n; y++)
      for (let x = 0; x < n; x++)
        urls.push(`${this.opts.tileBase}/${this.opts.mapName}/${wanted}/${x}_${y}.webp`)

    // `allSettled`, and failures are reported. This was
    // `.catch(() => Texture.EMPTY)`, which turned any loading problem into a
    // blank map with no error anywhere — indistinguishable from a map that
    // rendered correctly onto a dark background.
    const results = await Promise.allSettled(urls.map((u) => Assets.load<Texture>(u)))
    if (this.destroyed || this.tileLevel !== wanted) return

    const failed = results.filter((r) => r.status === 'rejected').length
    if (failed > 0) {
      this.opts.onError?.(
        `${failed} of ${urls.length} map tiles failed to load for ${this.opts.mapName} ` +
          `at zoom ${wanted} — run scripts/fetch_map_assets.py`,
      )
    }

    this.mapLayer.removeChildren().forEach((c) => c.destroy())
    let i = 0
    for (let y = 0; y < n; y++) {
      for (let x = 0; x < n; x++) {
        const result = results[i++]!
        const s = new Sprite(result.status === 'fulfilled' ? result.value : Texture.EMPTY)
        s.position.set(x * size, y * size)
        s.width = size
        s.height = size
        this.mapLayer.addChild(s)
      }
    }
  }

  // -- clock ---------------------------------------------------------------
  start(): void {
    this.app.ticker.add(this.tick)
  }

  private tick = (): void => {
    if (this.playing) {
      this.nowMs += this.app.ticker.deltaMS * this.speed
      if (this.nowMs > this.opts.bundle.durationMs) {
        this.nowMs = this.opts.bundle.durationMs
        this.playing = false
      }
    }
    this.drawFrame()
  }

  seek(ms: number): void {
    const clamped = Math.max(0, Math.min(ms, this.opts.bundle.durationMs))
    // Backwards seek invalidates every monotonic cursor, so they are rebuilt
    // by binary search — 100 searches, microseconds — and the trail is wiped
    // because it is append-only.
    if (clamped < this.nowMs) {
      this.resetCursors(clamped)
      this.trailLayer.clear()
    }
    this.nowMs = clamped
    this.drawFrame()
  }

  private resetCursors(ms: number): void {
    const b = this.opts.bundle
    const tick = ms / b.tickMs
    for (let p = 0; p < b.players.length; p++) {
      const lo0 = b.pos.off[p]!
      const hi0 = b.pos.off[p + 1]!
      let lo = lo0
      let hi = hi0
      while (lo < hi) {
        const mid = (lo + hi) >> 1
        if (b.pos.t[mid]! <= tick) lo = mid + 1
        else hi = mid
      }
      this.cursor[p] = Math.max(lo0, lo - 1)
    }
  }

  // -- frame ---------------------------------------------------------------
  private drawFrame(): void {
    const b = this.opts.bundle
    const tick = this.nowMs / b.tickMs

    let alive = 0
    let followX = 0
    let followY = 0

    for (let p = 0; p < b.players.length; p++) {
      const start = b.pos.off[p]!
      const end = b.pos.off[p + 1]!
      const dot = this.dots[p]!
      const ring = this.rings[p]!
      const existingLabel = this.labels[p]
      if (start === end) {
        dot.visible = false
        ring.visible = false
        if (existingLabel) existingLabel.visible = false
        continue
      }

      // O(1) amortised: the cursor only ever moves forward during playback.
      let c = this.cursor[p]!
      while (c + 1 < end && b.pos.t[c + 1]! <= tick) c++
      this.cursor[p] = c

      const t0 = b.pos.t[c]!
      if (t0 > tick) {
        // Player has not appeared yet.
        dot.visible = false
        ring.visible = false
        if (existingLabel) existingLabel.visible = false
        continue
      }

      let x = this.toWorld(b.pos.x[c]!)
      let y = this.toWorld(b.pos.y[c]!)
      if (c + 1 < end) {
        // Positions are ~10s apart at worst, so interpolation is mandatory —
        // without it everyone teleports between samples.
        const t1 = b.pos.t[c + 1]!
        const span = t1 - t0
        if (span > 0) {
          const f = Math.max(0, Math.min(1, (tick - t0) / span))
          x += (this.toWorld(b.pos.x[c + 1]!) - x) * f
          y += (this.toWorld(b.pos.y[c + 1]!) - y) * f
        }
      }

      const flags = b.pos.flags[c]!
      const isAlive = (flags & FLAG_ALIVE) !== 0
      dot.visible = isAlive
      if (!isAlive) {
        ring.visible = false
        if (existingLabel) existingLabel.visible = false
        continue
      }
      alive++

      dot.position.set(x, y)
      const dbno = (flags & FLAG_DBNO) !== 0
      dot.alpha = b.players[p]!.b ? 0.45 : dbno ? 0.5 : 1
      const scale = (flags & FLAG_IN_VEHICLE) !== 0 ? 1.4 : 1
      dot.width = DOT_R * 2 * scale
      dot.height = DOT_R * 2 * scale

      const followed = this.viewport.isFollowing === p
      const tracked = this.opts.tracked.has(b.players[p]!.a)

      // Counter-scaled so markers stay a constant size on screen: they live in
      // the world container, which is what zooming scales.
      const inv = 1 / this.viewport.scale
      ring.visible = tracked
      if (tracked) {
        ring.position.set(x, y)
        ring.scale.set(inv)
      }

      // Everyone gets a name once you are zoomed in; before that only the
      // people you came to watch, or a hundred labels overlap into noise.
      const wantLabel =
        !b.players[p]!.b && (tracked || followed || this.viewport.scale >= LABEL_SCALE)
      if (wantLabel) {
        const t = this.label(p)
        t.visible = true
        t.position.set(x, y - (DOT_R + 5) * inv)
        t.scale.set(inv)
      } else if (existingLabel) {
        existingLabel.visible = false
      }

      if (followed) {
        followX = x
        followY = y
      }
    }

    if (this.viewport.isFollowing !== null) this.viewport.centreOn(followX, followY)

    this.drawZones(tick)
    publish({ nowMs: this.nowMs, alive, playing: this.playing, speed: this.speed })
  }

  private drawZones(tick: number): void {
    const z = this.opts.bundle.zones
    if (z.n === 0) return
    const g = this.zoneLayer
    g.clear()

    // Find the sample bracketing `tick`.
    let i = 0
    while (i + 1 < z.n && z.t[i + 1]! <= tick) i++

    // BLUE = safetyZone* — the current damaging circle. Continuous, so it is
    // interpolated between samples.
    let bx = this.toWorld(z.bx[i]!)
    let by = this.toWorld(z.by[i]!)
    let br = this.toWorld(z.br[i]!)
    if (i + 1 < z.n) {
      const span = z.t[i + 1]! - z.t[i]!
      if (span > 0) {
        const f = Math.max(0, Math.min(1, (tick - z.t[i]!) / span))
        bx += (this.toWorld(z.bx[i + 1]!) - bx) * f
        by += (this.toWorld(z.by[i + 1]!) - by) * f
        br += (this.toWorld(z.br[i + 1]!) - br) * f
      }
    }
    if (br > 0) g.circle(bx, by, br).stroke({ width: 2.5, color: 0x3fa7ff, alpha: 0.95 })

    // WHITE = poisonGasWarning* — the next circle. A step function, so it is
    // SNAPPED. Interpolating makes it slide across the map instead of jumping,
    // which looks smooth and is wrong.
    const wr = this.toWorld(z.wr[i]!)
    if (wr > 0) {
      g.circle(this.toWorld(z.wx[i]!), this.toWorld(z.wy[i]!), wr).stroke({
        width: 2,
        color: 0xffffff,
        alpha: 0.85,
      })
    }

    // Red zone is 0 across every archived match, so it is guarded rather than
    // assumed — the track exists, the circles do not.
    const rr = this.toWorld(z.rr[i]!)
    if (rr > 0) {
      g.circle(this.toWorld(z.rx[i]!), this.toWorld(z.ry[i]!), rr).fill({
        color: 0xff4444,
        alpha: 0.18,
      })
    }
  }

  /** Draw kill markers for everything that has happened up to now. */
  drawEvents(): void {
    const b = this.opts.bundle
    this.worldLayer.removeChildren().forEach((c) => c.destroy())
    const g = new Graphics()
    const tick = this.nowMs / b.tickMs
    for (const e of b.events) {
      if (e.t > tick) break
      if (e.k === 'kill') {
        const vx = this.toWorld(e.vx as number)
        const vy = this.toWorld(e.vy as number)
        g.moveTo(vx - 4, vy - 4).lineTo(vx + 4, vy + 4)
        g.moveTo(vx + 4, vy - 4).lineTo(vx - 4, vy + 4)
      } else if (e.k === 'cp') {
        const x = this.toWorld(e.x as number)
        const y = this.toWorld(e.y as number)
        g.rect(x - 4, y - 4, 8, 8)
      }
    }
    g.stroke({ width: 1.5, color: 0xff6b6b, alpha: 0.75 })
    this.worldLayer.addChild(g)
  }

  followPlayer(index: number | null): void {
    this.viewport.follow(index)
  }

  fit(): void {
    this.viewport.fit()
  }

  destroy(): void {
    this.destroyed = true
    this.app.ticker.remove(this.tick)
    this.viewport.destroy()
  }
}

export { NULL_PLAYER }
