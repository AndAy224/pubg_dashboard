import type { Container } from 'pixi.js'

/**
 * Pan and zoom, applied to the world container.
 *
 * Hand-rolled on purpose. `pixi-viewport`'s last commit was Feb 2025 and its
 * README is still v7-era, and the whole feature is this file — taking the
 * dependency would mean pinning a stale package to the most load-bearing part
 * of the renderer.
 */
export class Viewport {
  private dragging = false
  private lastX = 0
  private lastY = 0
  private following: number | null = null

  scale = 1
  minScale = 0.4
  maxScale = 12

  private readonly canvas: HTMLCanvasElement
  private readonly world: Container
  private readonly worldPx: number
  private readonly onZoomChange?: (scale: number) => void

  constructor(
    canvas: HTMLCanvasElement,
    world: Container,
    worldPx: number,
    onZoomChange?: (scale: number) => void,
  ) {
    this.canvas = canvas
    this.world = world
    this.worldPx = worldPx
    this.onZoomChange = onZoomChange
    canvas.addEventListener('pointerdown', this.down)
    canvas.addEventListener('pointermove', this.move)
    window.addEventListener('pointerup', this.up)
    canvas.addEventListener('wheel', this.wheel, { passive: false })
    this.fit()
  }

  destroy(): void {
    this.canvas.removeEventListener('pointerdown', this.down)
    this.canvas.removeEventListener('pointermove', this.move)
    window.removeEventListener('pointerup', this.up)
    this.canvas.removeEventListener('wheel', this.wheel)
  }

  /** Scale the whole map to fit the shorter viewport axis. */
  fit(): void {
    const w = this.canvas.clientWidth || this.canvas.width
    const h = this.canvas.clientHeight || this.canvas.height
    this.scale = Math.min(w, h) / this.worldPx
    this.minScale = this.scale * 0.85
    this.world.scale.set(this.scale)
    this.world.position.set((w - this.worldPx * this.scale) / 2, (h - this.worldPx * this.scale) / 2)
    this.onZoomChange?.(this.scale)
  }

  /** Follow a player: keep world point (x, y) centred. */
  follow(index: number | null): void {
    this.following = index
  }

  get isFollowing(): number | null {
    return this.following
  }

  centreOn(x: number, y: number): void {
    const w = this.canvas.clientWidth || this.canvas.width
    const h = this.canvas.clientHeight || this.canvas.height
    this.world.position.set(w / 2 - x * this.scale, h / 2 - y * this.scale)
  }

  private down = (e: PointerEvent) => {
    this.dragging = true
    this.lastX = e.clientX
    this.lastY = e.clientY
    // A manual drag cancels follow-cam; otherwise the camera fights the user.
    this.following = null
    this.canvas.style.cursor = 'grabbing'
  }

  private move = (e: PointerEvent) => {
    if (!this.dragging) return
    this.world.position.x += e.clientX - this.lastX
    this.world.position.y += e.clientY - this.lastY
    this.lastX = e.clientX
    this.lastY = e.clientY
  }

  private up = () => {
    this.dragging = false
    this.canvas.style.cursor = 'grab'
  }

  private wheel = (e: WheelEvent) => {
    e.preventDefault()
    const rect = this.canvas.getBoundingClientRect()
    const px = e.clientX - rect.left
    const py = e.clientY - rect.top

    const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15
    const next = Math.max(this.minScale, Math.min(this.maxScale, this.scale * factor))
    if (next === this.scale) return

    // Keep the point under the cursor fixed: convert to world space, rescale,
    // then put it back. Scaling about the origin instead makes the map slide
    // out from under the pointer.
    const worldX = (px - this.world.position.x) / this.scale
    const worldY = (py - this.world.position.y) / this.scale
    this.scale = next
    this.world.scale.set(next)
    this.world.position.set(px - worldX * next, py - worldY * next)
    this.onZoomChange?.(next)
  }
}
