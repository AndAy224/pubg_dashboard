import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { Viewport } from './Viewport'

/**
 * The viewport's job is to never render nothing "successfully".
 *
 * `fit()` scales the world by `min(width, height) / worldPx`. Pixi defers its
 * first `resizeTo` resize to an animation frame, so the canvas can still be
 * zero-sized when the renderer is constructed — and a scale of 0 collapses
 * every layer to a single point. The clock still ticks, the store still
 * publishes, the DOM panels still update, and the canvas is perfectly black.
 * That is indistinguishable from a rendering bug and took a round trip to
 * diagnose.
 */

const WORLD_PX = 8192

interface FakeWorld {
  scale: { value: number; set(v: number): void }
  position: { x: number; y: number; set(x: number, y: number): void }
}

function fakeWorld(): FakeWorld {
  return {
    scale: { value: -1, set(v: number) { this.value = v } },
    position: { x: 0, y: 0, set(x: number, y: number) { this.x = x; this.y = y } },
  }
}

function fakeCanvas(clientWidth: number, clientHeight: number, width = 0, height = 0) {
  return {
    clientWidth,
    clientHeight,
    width,
    height,
    style: {} as CSSStyleDeclaration,
    addEventListener: () => {},
    removeEventListener: () => {},
  } as unknown as HTMLCanvasElement
}

/** `Viewport` attaches a pointerup listener to `window` and may defer a refit. */
let frames: (() => void)[] = []

beforeEach(() => {
  frames = []
  vi.stubGlobal('window', { addEventListener: () => {}, removeEventListener: () => {} })
  vi.stubGlobal('requestAnimationFrame', (cb: () => void) => {
    frames.push(cb)
    return frames.length
  })
  vi.stubGlobal('cancelAnimationFrame', () => {})
})

afterEach(() => vi.unstubAllGlobals())

/** Run whatever the viewport queued, as a browser would on the next frame. */
function nextFrame(): void {
  const queued = frames
  frames = []
  for (const cb of queued) cb()
}

describe('fit', () => {
  it('scales the world to the shorter axis', () => {
    const world = fakeWorld()
    // eslint-disable-next-line no-new
    new Viewport(fakeCanvas(1200, 800), world as never, WORLD_PX)
    expect(world.scale.value).toBeCloseTo(800 / WORLD_PX, 10)
  })

  it('never scales the world to zero', () => {
    // The whole bug: a zero-sized canvas produced scale 0 and a black canvas
    // that looked like a broken renderer rather than a missing layout.
    const world = fakeWorld()
    new Viewport(fakeCanvas(0, 0), world as never, WORLD_PX)
    expect(world.scale.value).not.toBe(0)
  })

  it('defers the fit until the canvas has been laid out', () => {
    const world = fakeWorld()
    const canvas = fakeCanvas(0, 0)
    new Viewport(canvas, world as never, WORLD_PX)

    // Nothing sensible can be computed yet, so nothing was applied.
    expect(world.scale.value).toBe(-1)
    expect(frames).toHaveLength(1)

    // The layout lands; the retry now succeeds.
    Object.assign(canvas, { clientWidth: 1000, clientHeight: 900 })
    nextFrame()
    expect(world.scale.value).toBeCloseTo(900 / WORLD_PX, 10)
  })

  it('only queues one retry while it waits', () => {
    const world = fakeWorld()
    const canvas = fakeCanvas(0, 0)
    const vp = new Viewport(canvas, world as never, WORLD_PX)
    vp.fit()
    vp.fit()
    // Otherwise every caller piles on another frame callback and they all fire.
    expect(frames).toHaveLength(1)
  })

  it('falls back to the backing-store size when there is no CSS size', () => {
    // A canvas that has width/height attributes but no layout yet is still
    // measurable, and is better than refusing to draw.
    const world = fakeWorld()
    new Viewport(fakeCanvas(0, 0, 640, 480), world as never, WORLD_PX)
    expect(world.scale.value).toBeCloseTo(480 / WORLD_PX, 10)
  })

  it('reports the scale it settled on', () => {
    const seen: number[] = []
    new Viewport(fakeCanvas(1200, 800), fakeWorld() as never, WORLD_PX, (s) => seen.push(s))
    // The renderer picks its tile pyramid level from this, so a fit that does
    // not report leaves the map at whatever level it happened to start on.
    expect(seen).toEqual([800 / WORLD_PX])
  })

  it('does not report a scale it refused to apply', () => {
    const seen: number[] = []
    new Viewport(fakeCanvas(0, 0), fakeWorld() as never, WORLD_PX, (s) => seen.push(s))
    expect(seen).toEqual([])
  })
})
