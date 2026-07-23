/**
 * Exercise a pan/zoom map in a real browser and report whether it behaved.
 *
 * Sibling of `probe-replay.mjs`, and it exists for the same reason: `tsc`,
 * `oxlint` and `vitest` all passed on a heatmap that panned exactly one pointer
 * event and then died. The tiles are `<img>`, an `<img>` is natively draggable,
 * and pressing one starts an HTML5 image drag that fires `pointercancel` and
 * stops the pointer stream — so the user gets a ghost thumbnail on the cursor
 * instead of a map. Nothing but a browser can see that.
 *
 * The kill map hid the same bug by accident: its SVG overlay covers the tiles,
 * so the press never lands on an image. Check both.
 *
 *   CHROME=/path/to/chrome-headless-shell \
 *   LD_LIBRARY_PATH=... \
 *   node scripts/probe-map.mjs <url> <selector> [--shot=out.png]
 *
 * HANDOFF §17 has the no-root setup for a headless Chrome.
 */
import puppeteer from 'puppeteer'

const args = process.argv.slice(2)
const positional = args.filter((a) => !a.startsWith('--'))
const url = positional[0]
const selector = positional[1] ?? '.mapview'
const shot = args.find((a) => a.startsWith('--shot='))?.split('=')[1]

if (!url) {
  console.error('usage: node scripts/probe-map.mjs <url> [selector] [--shot=out.png]')
  process.exit(2)
}

const browser = await puppeteer.launch({
  executablePath: process.env.CHROME,
  headless: true,
  args: [
    '--no-sandbox',
    '--enable-unsafe-swiftshader',
    '--use-gl=angle',
    '--use-angle=swiftshader',
  ],
})
const page = await browser.newPage()
const errors = []
page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`))
page.on('console', (m) => m.type() === 'error' && errors.push(`console: ${m.text()}`))
page.on('requestfailed', (r) => errors.push(`requestfailed: ${r.url()}`))

await page.setViewport({ width: 1500, height: 1000, deviceScaleFactor: 1 })
await page.goto(url, { waitUntil: 'networkidle2' })
await new Promise((r) => setTimeout(r, 2000))

const found = await page.$(selector)
if (!found) {
  console.error(`selector not found: ${selector}`)
  await browser.close()
  process.exit(1)
}
await page.evaluate((s) => document.querySelector(s).scrollIntoView({ block: 'center' }), selector)
await new Promise((r) => setTimeout(r, 400))

const transform = () =>
  page.evaluate((s) => {
    const world = document.querySelector(s).querySelector('.mapview-world')
    const m = new DOMMatrix(getComputedStyle(world).transform)
    return { scale: m.a, tx: m.e, ty: m.f }
  }, selector)

// --- wheel zoom, anchored under the cursor -------------------------------
const wheel = await page.evaluate(async (s) => {
  const root = document.querySelector(s)
  const stage = root.querySelector('.mapview-stage')
  const r = stage.getBoundingClientRect()
  const at = (k) => new DOMMatrix(getComputedStyle(root.querySelector('.mapview-world')).transform)[k]
  const fx = 0.25
  const before = { a: at('a'), e: at('e') }
  let prevented = null
  for (let i = 0; i < 4; i++) {
    const ev = new WheelEvent('wheel', {
      deltaY: -120,
      clientX: r.left + r.width * fx,
      clientY: r.top + r.height * 0.25,
      bubbles: true,
      cancelable: true,
    })
    stage.dispatchEvent(ev)
    prevented = ev.defaultPrevented
    await new Promise((res) => setTimeout(res, 120))
  }
  await new Promise((res) => setTimeout(res, 400))
  const after = { a: at('a'), e: at('e') }
  return {
    scale: `${before.a} -> ${+after.a.toFixed(3)}`,
    // The point under the cursor must not move; scaling about the origin is
    // the classic bug and slides the map out from under the pointer.
    anchorDrift: +((fx - after.e / r.width) / after.a - (fx - before.e / r.width) / before.a).toFixed(5),
    preventsPageScroll: prevented,
    pageScrollY: window.scrollY,
  }
}, selector)

// --- drag pans 1:1 -------------------------------------------------------
const before = await transform()
const box = await (await page.$(`${selector} .mapview-stage`)).boundingBox()
const dx = -Math.round(box.width * 0.25)
const dy = -Math.round(box.height * 0.1)
await page.mouse.move(box.x + box.width * 0.6, box.y + box.height * 0.6)
await page.mouse.down()
await page.mouse.move(box.x + box.width * 0.6 + dx, box.y + box.height * 0.6 + dy, { steps: 10 })
await page.mouse.up()
await new Promise((r) => setTimeout(r, 500))
const after = await transform()

const tiles = await page.evaluate(
  (s) => {
    const imgs = [...document.querySelector(s).querySelectorAll('.mapview-world img')]
    return {
      count: imgs.length,
      level: imgs[0]?.getAttribute('src')?.split('/').at(-2) ?? null,
      // A draggable tile is the bug this script exists for.
      anyDraggable: imgs.some((i) => i.draggable),
    }
  },
  selector,
)

const overflow = await page.evaluate(() => ({
  scrollWidth: document.documentElement.scrollWidth,
  innerWidth: window.innerWidth,
}))

console.log(
  JSON.stringify(
    {
      url,
      selector,
      wheel,
      drag: {
        requested: { dx, dy },
        actual: { dx: +(after.tx - before.tx).toFixed(1), dy: +(after.ty - before.ty).toFixed(1) },
        movedFully: Math.abs(after.tx - before.tx - dx) < 2 && Math.abs(after.ty - before.ty - dy) < 2,
      },
      tiles,
      pageOverflowsHorizontally: overflow.scrollWidth > overflow.innerWidth,
      errors: errors.length ? errors : 'none',
    },
    null,
    1,
  ),
)

if (shot) {
  await (await page.$(selector)).screenshot({ path: shot })
  console.log('screenshot ->', shot)
}
await browser.close()
