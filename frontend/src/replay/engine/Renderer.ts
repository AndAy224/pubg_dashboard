import { Application, Assets, Container, Graphics, Sprite, Text, Texture } from 'pixi.js'
import type { ReplayBundle } from '../../lib/replayBundle'
import { FLAG_ALIVE, FLAG_DBNO, FLAG_DRIVING, FLAG_IN_VEHICLE, NULL_PLAYER } from '../../lib/replayBundle'
import { BOT_COLOUR, teamColour } from '../../lib/palette'
import { playerColourInt } from '../../lib/players'
import { Viewport } from './Viewport'
import { interpolateAt, markerRadius, markersAt, trailPoints } from './markers'
import { ALIVE, KNOCKED, OUT, publish, publishHealth } from '../store'

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

/**
 * How long a combat tracer stays on screen, in **match** milliseconds.
 *
 * Deliberately match time, not wall-clock: at 20x the replay covers 20 s per
 * real second, and a wall-clock fade would leave every tracer of the last
 * several seconds of fighting on screen at once. Scaling with playback keeps
 * the same *amount of combat* visible at every speed.
 */
const TRACER_MS = 1200

/**
 * How much of a player's recent movement the trail shows, in **match** ms —
 * match time for the same reason `TRACER_MS` is (a wall-clock window would
 * show 20x as much ground at 20x speed).
 *
 * Trails are drawn only for tracked players and whoever is being followed.
 * A hundred of them at fit zoom is a grey wash over the island, and it is the
 * same argument the health rings settled: a mark that every player carries all
 * the time carries no information.
 */
const TRAIL_MS = 30_000

/**
 * How long an abandoned vehicle stays on the map, in match ms.
 *
 * There are ~245 `leave` events in a match. Persisting them all litters the
 * island with cars that were dumped fifteen minutes ago; a fading window keeps
 * the signal that actually matters — someone just got out, near here, now.
 */
const VEHICLE_MS = 30_000

/** Screen-pixel radii for the world markers. Constant at every zoom. */
const KILL_R = 5
const CRATE_R = 4
const VEHICLE_R = 4

/**
 * Health ring geometry, in world units before the counter-scale.
 *
 * The ring sits outside the dot rather than filling it, so the dot body keeps
 * carrying the identity/team colour — that hue is how you find your squad in a
 * hundred-dot lobby, and a health-coloured dot would destroy it.
 *
 * The radius has to clear two things, and the dot's own size is the smaller of
 * them: the marker is a **square** sprite, so its corners reach `DOT_R * √2`
 * (7.07), not `DOT_R`. The tracked player's white ring is the real constraint
 * — it ends at `DOT_R + 3 + 1` = 9 — so the health ring goes outside that and
 * stays concentric with both.
 */
const HP_RING_R = DOT_R + 5
const HP_RING_W = 1.8

/**
 * Health is quantised to this many steps before deciding to redraw.
 *
 * A `Graphics` arc cannot be transformed into a different arc — changing the
 * sweep means re-tessellating it — so redrawing 100 of them every frame is
 * real work. Health only has to *look* continuous, and 5% steps are well under
 * one pixel of arc at any zoom the map is legible at.
 */
const HP_STEPS = 20

/**
 * Severity ramp. Deliberately only three stops: the ring answers "should I be
 * worried", and a continuous gradient reads as noise at 10 px.
 */
function healthColour(hp: number): number {
  if (hp > 60) return 0x4ade80
  if (hp > 25) return 0xfbbf24
  return 0xf87171
}

/** Texture-space radius of the steering wheel. Drawn large, scaled down. */
const WHEEL_R = 30

/**
 * The steering-wheel marker, rasterised once and shared by every dot.
 *
 * It **replaces** the square rather than sitting on top of it, so the marker
 * still carries exactly one colour — the player's — and the map does not gain
 * a second overlapping thing per dot. It occupies the same footprint the
 * enlarged in-vehicle square already did, so no other ring has to move.
 *
 * Drawn white over a fat black pass. `tint` multiplies, so the black survives
 * as an outline while the white takes the player's identity colour — which is
 * what keeps the glyph legible on all 24 team hues *and* on satellite imagery
 * that is bright in the towns and near-black in the water.
 *
 * Returns null rather than throwing: a marker that cannot be built is worth a
 * plain square, not a dead replay.
 */
function buildWheelTexture(app: Application): Texture | null {
  try {
    const g = new Graphics()
    // Three spokes from 12 o'clock, the shape everyone reads as a wheel.
    const spokes = [-Math.PI / 2, Math.PI / 6, (5 * Math.PI) / 6]
    for (const [width, colour] of [
      [14, 0x000000],
      [7, 0xffffff],
    ] as const) {
      g.circle(0, 0, WHEEL_R - width / 2).stroke({ width, color: colour })
      for (const a of spokes) {
        g.moveTo(0, 0).lineTo(Math.cos(a) * WHEEL_R, Math.sin(a) * WHEEL_R)
      }
      g.stroke({ width, color: colour })
      g.circle(0, 0, width).fill({ color: colour })
    }
    return app.renderer.generateTexture({ target: g, resolution: 2, antialias: true })
  } catch {
    return null
  }
}

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
  private readonly tracerLayer = new Graphics()
  private readonly worldLayer = new Graphics()
  private readonly dotLayer = new Container()
  private readonly labelLayer = new Container()

  private readonly dots: Sprite[] = []
  private readonly rings: Graphics[] = []
  /** Health ring per player, redrawn only when the drawn state changes. */
  private readonly hpRings: Graphics[] = []
  /** Last state each health ring was drawn for; -1 means "never drawn". */
  private readonly hpDrawn: Int16Array
  /** Live health for the DOM panels. Written in place, never reallocated. */
  private readonly hpOut: Uint8Array
  private readonly statusOut: Uint8Array
  /** Bumped when `hpOut`/`statusOut` changed, so the store can skip the rest. */
  private hpVersion = 0
  /** Built lazily — a hundred `Text` objects up front is a hundred canvas
   *  rasterisations, and most are never shown. */
  private readonly labels: (Text | null)[] = []
  /** Monotonic per-player cursor into the CSR arrays — the hot loop's state. */
  private readonly cursor: Int32Array
  private readonly worldPx: number
  private viewport!: Viewport
  private tileLevel = -1
  private destroyed = false
  /** Lower bound into `hits`, advanced monotonically like the position cursors. */
  private hitCursor = 0
  private _headShotIndex: number | undefined
  /** Shared steering-wheel marker; null if it could not be rasterised. */
  private readonly wheelTexture: Texture | null

  /**
   * What the last frame actually put on the canvas.
   *
   * Read through `window.__replay` by `scripts/probe-replay.mjs`. HANDOFF §19:
   * four probe attempts in a row showed no combat tracers and all four were
   * the probe's fault — wrong camera, wrong moment. **A blank screenshot
   * proves nothing about the code**, so the drawing is confirmed from live
   * state first and the picture second.
   */
  readonly drawn = { kills: 0, crates: 0, vehicles: 0, trails: 0, tracers: 0, plane: false }

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
    // **Seed each cursor at its own CSR row.** Zero-filled is not a neutral
    // starting point: index 0 is inside *player 0's* row, so until something
    // triggered `resetCursors` every player read player 0's position, health
    // and flags. A hundred dots stacked on one player looks like a quiet map
    // rather than a broken one, and the alive counter read 97 where the bundle
    // says 51. `resetCursors` only runs on a *backwards* seek, so a fresh load
    // — the common case — never corrected it.
    this.cursor = new Int32Array(b.players.length)
    for (let p = 0; p < b.players.length; p++) this.cursor[p] = b.pos.off[p]!
    this.hpDrawn = new Int16Array(b.players.length).fill(-1)
    this.hpOut = new Uint8Array(b.players.length)
    this.statusOut = new Uint8Array(b.players.length)
    this.wheelTexture = buildWheelTexture(app)
    if (this.wheelTexture === null) {
      opts.onError?.('the in-vehicle marker could not be built; dots stay square')
    }
    // World units are source-image pixels, so the cm->px transform is the same
    // one the tiles were cut with (including the 8160/8192 correction).
    this.worldPx = opts.sourcePx

    this.world.addChild(
      this.mapLayer,
      this.gridLayer,
      this.trailLayer,
      this.zoneLayer,
      this.worldLayer,
      // Above the world markers so a tracer is never hidden by a care package,
      // below the dots so it never covers the people involved.
      this.tracerLayer,
      this.dotLayer,
      this.labelLayer,
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

      // Health ring. Added before the tracked ring in z-order would put it
      // over the white outline, so it goes last and sits outside everything.
      const hp = new Graphics()
      hp.visible = false
      this.hpRings.push(hp)
      this.dotLayer.addChild(hp)
    }
  }

  /** Record a player's health for the DOM panels, noting whether it moved. */
  private setHealth(p: number, hp: number, status: number): void {
    if (this.hpOut[p] === hp && this.statusOut[p] === status) return
    this.hpOut[p] = hp
    this.statusOut[p] = status
    this.hpVersion++
  }

  /**
   * Redraw one player's health ring, if the state it shows has changed.
   *
   * `state` is the quantised health, or -1 for knocked. Returns nothing; the
   * caller positions and scales the ring, which are transforms and therefore
   * free.
   */
  private drawHealthRing(p: number, state: number): void {
    if (this.hpDrawn[p] === state) return
    this.hpDrawn[p] = state
    const g = this.hpRings[p]!
    g.clear()

    if (state < 0) {
      // Knocked. A full red ring rather than an empty one: health is genuinely
      // 0 here, so a proportional arc would draw nothing at all and a knocked
      // player would look identical to a healthy one.
      g.circle(0, 0, HP_RING_R).stroke({ width: HP_RING_W, color: 0xf87171, alpha: 0.95 })
      return
    }

    const hp = (state / HP_STEPS) * 100
    // The unfilled remainder, so the ring reads as a gauge rather than as a
    // stray arc whose length you have to guess against nothing.
    g.circle(0, 0, HP_RING_R).stroke({ width: HP_RING_W, color: 0x000000, alpha: 0.5 })
    if (state > 0) {
      // Clockwise from 12 o'clock, like every health dial in the game.
      const start = -Math.PI / 2
      g.arc(0, 0, HP_RING_R, start, start + (hp / 100) * Math.PI * 2).stroke({
        width: HP_RING_W,
        color: healthColour(hp),
        alpha: 0.95,
      })
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
    // by binary search — 100 searches, microseconds.
    //
    // The trail layer is *not* cleared here any more: it is rebuilt from the
    // position arrays every frame, so it has no accumulated state to
    // invalidate. Leaving the clear in place would have been a second
    // invalidation path that no longer says anything true.
    if (clamped < this.nowMs) {
      this.resetCursors(clamped)
      // Monotonic like the position cursors, so a backwards seek invalidates it.
      this.hitCursor = 0
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
      const hpRing = this.hpRings[p]!
      const existingLabel = this.labels[p]
      if (start === end) {
        dot.visible = false
        ring.visible = false
        hpRing.visible = false
        if (existingLabel) existingLabel.visible = false
        this.setHealth(p, 0, OUT)
        continue
      }

      // O(1) amortised: the cursor only ever moves forward during playback.
      // Positions are ~10 s apart at worst, so interpolation is mandatory —
      // without it everyone teleports between samples. **`interpolateAt` is
      // the one definition of where a player is**, shared with `trailPoints`,
      // so a trail can never disagree with the dot it trails from.
      const sample = interpolateAt(b.pos, p, tick, this.cursor[p]!)
      if (sample === null) {
        // Player has not appeared yet.
        dot.visible = false
        ring.visible = false
        hpRing.visible = false
        if (existingLabel) existingLabel.visible = false
        this.setHealth(p, 0, OUT)
        continue
      }
      const c = sample.c
      this.cursor[p] = c

      const x = this.toWorld(sample.x)
      const y = this.toWorld(sample.y)
      const flags = sample.flags
      // "Still in the match", knocked included — parser version 5 resolves
      // this against the final death, so a knocked player is drawn and a dead
      // one is not. Before that this bit meant `health > 0` and every knock
      // was invisible.
      const isAlive = (flags & FLAG_ALIVE) !== 0
      dot.visible = isAlive
      if (!isAlive) {
        ring.visible = false
        hpRing.visible = false
        if (existingLabel) existingLabel.visible = false
        this.setHealth(p, 0, OUT)
        continue
      }
      alive++

      dot.position.set(x, y)
      const dbno = (flags & FLAG_DBNO) !== 0
      dot.alpha = b.players[p]!.b ? 0.45 : dbno ? 0.5 : 1

      // Health is **stepped, not interpolated**: it jumps on a hit, and a ramp
      // between samples would show a player at 60 when they are at 10. Only
      // position is continuous enough to interpolate.
      const hp = b.pos.hp[c]!
      this.setHealth(p, hp, dbno ? KNOCKED : ALIVE)

      const followed = this.viewport.isFollowing === p
      const tracked = this.opts.tracked.has(b.players[p]!.a)

      // Counter-scaled so markers stay a constant size on screen: they live in
      // the world container, which is what zooming scales.
      //
      // **The dots themselves were not**, and that is why nobody could tell
      // them apart: `DOT_R * 2` is 10 *world* units, and at fit on Erangel the
      // world is scaled to about 0.11, so a player rendered **1.1 pixels
      // across**. They were not ambiguous, they were nearly invisible.
      const inv = 1 / this.viewport.scale

      // A steering wheel while they are in something they drive around the
      // map. **`FLAG_DRIVING`, not `FLAG_IN_VEHICLE`** — the match-start
      // aircraft is a vehicle, so the latter would put a wheel on all hundred
      // players before anyone has landed.
      const wheel = (flags & FLAG_DRIVING) !== 0 && this.wheelTexture !== null
      const texture = wheel ? this.wheelTexture! : Texture.WHITE
      // Assigned before the size, because `width` is derived from the
      // texture's own dimensions — swapping after would rescale the marker.
      if (dot.texture !== texture) dot.texture = texture

      const size = DOT_R * 2 * ((flags & FLAG_IN_VEHICLE) !== 0 ? 1.4 : 1) * inv
      dot.width = size
      dot.height = size
      ring.visible = tracked
      if (tracked) {
        ring.position.set(x, y)
        ring.scale.set(inv)
      }

      // **Only when it says something.** A ring on every player at 100 health
      // is a hundred rings carrying no information, and at fit zoom that is
      // solid clutter over the map. It appears when someone is hurt, which is
      // exactly when the eye should be pulled to them.
      const showHp = dbno || hp < 100
      hpRing.visible = showHp
      if (showHp) {
        this.drawHealthRing(p, dbno ? -1 : Math.round((hp / 100) * HP_STEPS))
        hpRing.position.set(x, y)
        hpRing.scale.set(inv)
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
    this.drawTrails(tick)
    this.drawMarkers(tick)
    this.drawTracers(tick)
    publish({ nowMs: this.nowMs, alive, playing: this.playing, speed: this.speed })
    publishHealth(this.hpOut, this.statusOut, this.hpVersion)
  }

  /**
   * Shots that landed, as fading lines from shooter to victim.
   *
   * This is what makes a fight legible: two dots near each other say nothing
   * about who is shooting whom, and the kill feed only reports the last shot
   * of an exchange.
   *
   * The window is scanned with a lower-bound cursor rather than filtering the
   * whole array — a match has ~550 hits, which is cheap, but this runs every
   * frame and the cursor makes it O(hits in window).
   */
  private drawTracers(tick: number): void {
    const h = this.opts.bundle.hits
    const g = this.tracerLayer
    g.clear()
    if (h.n === 0) return

    const tickMs = this.opts.bundle.tickMs
    const windowTicks = TRACER_MS / tickMs
    const from = tick - windowTicks

    // Advance the cursor to the first hit still inside the window. Reset on a
    // backwards seek, exactly like the position cursors.
    if (this.hitCursor > 0 && h.t[this.hitCursor - 1]! > from) this.hitCursor = 0
    while (this.hitCursor < h.n && h.t[this.hitCursor]! < from) this.hitCursor++

    const headShot = this.dmgReasonIndex('HeadShot')
    this.drawn.tracers = 0

    for (let i = this.hitCursor; i < h.n; i++) {
      const t = h.t[i]!
      if (t > tick) break

      // 1 at the moment of impact, 0 as it leaves the window.
      const age = 1 - (tick - t) / windowTicks
      if (age <= 0) continue
      this.drawn.tracers++

      const ax = this.toWorld(h.ax[i]!)
      const ay = this.toWorld(h.ay[i]!)
      const vx = this.toWorld(h.vx[i]!)
      const vy = this.toWorld(h.vy[i]!)

      const attacker = this.opts.bundle.players[h.a[i]!]
      const victim = this.opts.bundle.players[h.v[i]!]
      const involvesTracked =
        (attacker !== undefined && this.opts.tracked.has(attacker.a)) ||
        (victim !== undefined && this.opts.tracked.has(victim.a))

      const isHead = h.dr[i]! === headShot
      const colour = isHead ? 0xff3b30 : involvesTracked ? 0xffd400 : 0xffffff
      // Everything is divided by the viewport scale so it keeps a constant
      // size on screen — these live in the world container, which zoom scales.
      const inv = 1 / this.viewport.scale

      // Damage drives thickness, so a body-shot burst reads differently from
      // a grazing hit.
      g.moveTo(ax, ay).lineTo(vx, vy).stroke({
        width: (0.8 + (h.dmg[i]! / 100) * 2.2) * inv,
        color: colour,
        alpha: (involvesTracked ? 0.95 : 0.55) * age,
      })

      // **Both ends are marked, and that is not decoration.** Measured over
      // the archive, 31% of hits land inside 15 m and 8% inside 5 m — a
      // point-blank exchange draws a line a few pixels long, so the line alone
      // cannot show that a fight is happening. The muzzle flash and the impact
      // are a fixed size on screen, so a close-quarters burst still reads as
      // two bright pulsing marks.
      g.circle(ax, ay, 2.6 * inv).fill({ color: colour, alpha: 0.75 * age })

      g.circle(vx, vy, (isHead ? 4.2 : 3.2) * inv).fill({
        color: isHead ? 0xff3b30 : 0xffe066,
        alpha: 0.95 * age,
      })
      // An expanding ring on the freshest hits, so a burst pulses rather than
      // just brightening.
      if (age > 0.55) {
        g.circle(vx, vy, (5 + (1 - age) * 16) * inv).stroke({
          width: 1.2 * inv,
          color: isHead ? 0xff3b30 : 0xffe066,
          alpha: (age - 0.55) * 1.6,
        })
      }
    }
  }

  /** Index of a damage reason in the bundle's dictionary, resolved once. */
  private dmgReasonIndex(name: string): number {
    if (this._headShotIndex === undefined) {
      this._headShotIndex = this.opts.bundle.dicts['dmgReason']?.indexOf(name) ?? -1
    }
    return this._headShotIndex
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

  /**
   * Death markers, care packages, abandoned vehicles and the flight path.
   *
   * **This used to be a public `drawEvents()` called exactly once**, from
   * `ReplayCanvas` right after `start()` while `nowMs === 0`. Its loop breaks
   * on the first event with `t > tick`, so at tick 0 it drew nothing, and
   * nothing ever called it again — not from `drawFrame`, not from `seek`. Kill
   * crosses and crates were invisible for the whole life of the replay.
   *
   * Fixing the call site alone would not have shown anything: the markers were
   * sized in **world** units (±4), which is 0.44 px at Erangel fit zoom. They
   * are counter-scaled now, like every other marker here.
   */
  private drawMarkers(tick: number): void {
    const b = this.opts.bundle
    const g = this.worldLayer
    g.clear()

    const inv = 1 / this.viewport.scale
    const m = markersAt(b.events, tick, VEHICLE_MS / b.tickMs)
    this.drawn.kills = m.kills.length
    this.drawn.crates = m.crates.length
    this.drawn.vehicles = m.vehicles.length
    this.drawn.plane = b.plane !== null

    // Flight path first, underneath everything: it is context, not an event.
    if (b.plane !== null) {
      g.moveTo(this.toWorld(b.plane.x0), this.toWorld(b.plane.y0))
        .lineTo(this.toWorld(b.plane.x1), this.toWorld(b.plane.y1))
        .stroke({ width: markerRadius(1, this.viewport.scale), color: 0x8fa0c0, alpha: 0.35 })
    }

    // Abandoned vehicles: a hollow ring, fading out over VEHICLE_MS.
    for (const v of m.vehicles) {
      g.circle(this.toWorld(v.x), this.toWorld(v.y), markerRadius(VEHICLE_R, this.viewport.scale))
      g.stroke({ width: 1.2 * inv, color: 0x9ab0c8, alpha: 0.5 * v.age })
    }

    // Care packages. Hollow while falling, solid once landed — the spawn and
    // landing ticks are ~30 s apart, and one square from `t` put a crate on
    // the map half a minute before it existed.
    for (const c of m.crates) {
      const x = this.toWorld(c.x)
      const y = this.toWorld(c.y)
      const r = markerRadius(CRATE_R, this.viewport.scale)
      g.rect(x - r, y - r, r * 2, r * 2)
      if (c.falling) {
        g.stroke({ width: 1.2 * inv, color: 0xf0b429, alpha: 0.55 })
      } else {
        g.fill({ color: 0xf0b429, alpha: 0.8 })
      }
    }

    // Deaths. A tracked player's death is gold, like everywhere else.
    for (const k of m.kills) {
      const x = this.toWorld(k.x)
      const y = this.toWorld(k.y)
      const r = markerRadius(KILL_R, this.viewport.scale)
      const victim = b.players[k.v]
      const tracked = victim !== undefined && this.opts.tracked.has(victim.a)
      g.moveTo(x - r, y - r).lineTo(x + r, y + r)
      g.moveTo(x + r, y - r).lineTo(x - r, y + r)
      g.stroke({
        width: (tracked ? 2 : 1.5) * inv,
        color: tracked ? 0xffd400 : 0xff6b6b,
        alpha: tracked ? 0.95 : 0.7,
      })
    }
  }

  /**
   * The last `TRAIL_MS` of movement, for the people you came to watch.
   *
   * Tracked players and whoever is followed only. A hundred trails at fit zoom
   * is a grey wash across the island, and "everyone has been somewhere" is not
   * worth a hundred marks — the same argument that keeps the health ring off
   * players at full health.
   */
  private drawTrails(tick: number): void {
    const b = this.opts.bundle
    const g = this.trailLayer
    g.clear()

    const windowTicks = TRAIL_MS / b.tickMs
    const width = markerRadius(1.4, this.viewport.scale)
    this.drawn.trails = 0

    for (let p = 0; p < b.players.length; p++) {
      const player = b.players[p]!
      if (!this.opts.tracked.has(player.a) && this.viewport.isFollowing !== p) continue

      const pts = trailPoints(b.pos, p, tick, windowTicks, this.cursor[p]!)
      if (pts.length < 4) continue

      g.moveTo(this.toWorld(pts[0]!), this.toWorld(pts[1]!))
      for (let i = 2; i < pts.length; i += 2) {
        g.lineTo(this.toWorld(pts[i]!), this.toWorld(pts[i + 1]!))
      }
      g.stroke({ width, color: playerColourInt(player.a) ?? teamColour(player.c), alpha: 0.5 })
      this.drawn.trails++
    }
  }

  /** Current zoom, for the probe. Markers are counter-scaled by 1/this. */
  get viewportScale(): number {
    return this.viewport.scale
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
