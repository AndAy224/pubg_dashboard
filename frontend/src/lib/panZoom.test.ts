import { describe, expect, it } from 'vitest'
import {
  clamp,
  clampAxis,
  FIT,
  MAX_SCALE,
  panBy,
  tileLevel,
  zoomAbout,
  zoomStep,
} from './panZoom'

/**
 * These are the whole feature. There is no DOM here by design — every bug this
 * frontend has actually shipped lived in a pure function, and pan/zoom is
 * exactly the shape that looks right until you check a number.
 */

describe('clampAxis', () => {
  it('centres when the map is not larger than the box', () => {
    expect(clampAxis(-0.3, 1)).toBe(0)
    expect(clampAxis(0.4, 1)).toBe(0)
  })

  it('pins to the edges once zoomed in', () => {
    // At 2x the map is twice the box, so pan runs over [-1, 0].
    expect(clampAxis(0.2, 2)).toBe(0)
    expect(clampAxis(-5, 2)).toBe(-1)
    expect(clampAxis(-0.5, 2)).toBe(-0.5)
  })
})

describe('zoomAbout', () => {
  it('keeps the point under the cursor fixed', () => {
    // The classic failure is scaling about the origin, which slides the map out
    // from under the pointer — you aim at a town, zoom, and land elsewhere.
    const t = zoomAbout(FIT, 0.25, 0.75, 4)
    const mapX = (0.25 - t.x) / t.scale
    const mapY = (0.75 - t.y) / t.scale
    expect(mapX).toBeCloseTo(0.25, 10)
    expect(mapY).toBeCloseTo(0.75, 10)
  })

  it('still holds when zooming about a corner, where clamping bites', () => {
    const t = zoomAbout(FIT, 0, 0, 4)
    expect((0 - t.x) / t.scale).toBeCloseTo(0, 10)
    expect(t.x).toBe(0)
  })

  it('never zooms out past fit, and never past the pyramid', () => {
    expect(zoomAbout(FIT, 0.5, 0.5, 0.2).scale).toBe(1)
    expect(zoomAbout(FIT, 0.5, 0.5, 500).scale).toBe(MAX_SCALE)
  })

  it('returns the same object when the scale is already at the limit', () => {
    expect(zoomAbout(FIT, 0.5, 0.5, 0.5)).toBe(FIT)
  })

  it('leaves the map covering the box at every step of a zoom-then-out', () => {
    let t = FIT
    for (const s of [1.5, 3, 6, 8, 4, 2, 1]) {
      t = zoomAbout(t, 0.8, 0.2, s)
      expect(t.x, `x at ${s}x`).toBeLessThanOrEqual(0.0000001)
      expect(t.x, `x at ${s}x`).toBeGreaterThanOrEqual(1 - t.scale - 0.0000001)
    }
    // Back at fit the map is centred again, not stranded off to one side.
    expect(t).toEqual(FIT)
  })
})

describe('panBy', () => {
  it('does nothing at fit, because there is nowhere to go', () => {
    expect(panBy(FIT, -0.4, 0.4)).toEqual(FIT)
  })

  it('moves and then stops at the edge', () => {
    const zoomed = zoomStep(FIT, 2)
    expect(zoomed.scale).toBe(2)
    expect(panBy(zoomed, -0.2, 0).x).toBeCloseTo(-0.7, 10)
    expect(panBy(zoomed, -99, 0).x).toBe(-1)
    expect(panBy(zoomed, 99, 0).x).toBe(0)
  })
})

describe('clamp', () => {
  it('is idempotent', () => {
    const once = clamp({ scale: 3, x: -9, y: 4 })
    expect(clamp(once)).toEqual(once)
  })
})

describe('tileLevel', () => {
  it('matches the pyramid to the pixels actually on screen', () => {
    // 660 css px of a 512 px tile needs one level up; doubling the zoom needs
    // one more each time.
    expect(tileLevel(660, 1, 512, 5)).toBe(1)
    expect(tileLevel(660, 2, 512, 5)).toBe(2)
    expect(tileLevel(660, 4, 512, 5)).toBe(3)
  })

  it('counts device pixels, which is what made the replay blurry', () => {
    expect(tileLevel(660, 1, 512, 5, 2)).toBe(2)
  })

  it('never exceeds the levels that exist, or goes below zero', () => {
    expect(tileLevel(660, 8, 512, 2)).toBe(2)
    expect(tileLevel(10, 1, 512, 5)).toBe(0)
  })

  it('survives a box that has not been laid out yet', () => {
    // A zero width used to produce log2(0) = -Infinity. Rendering nothing looks
    // exactly like a broken renderer.
    expect(tileLevel(0, 1, 512, 5)).toBe(0)
    expect(tileLevel(660, Number.NaN, 512, 5)).toBe(0)
  })
})
