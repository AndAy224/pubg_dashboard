/**
 * Load a page in a real browser, report what it did, and screenshot it.
 *
 * This exists because three separate frontend bugs in a row were invisible to
 * `tsc`, `oxlint`, `vitest` and the API logs, and cost multiple round trips to
 * diagnose by reasoning alone:
 *
 *   * a typed-array alignment throw that broke every replay bundle;
 *   * `cacheAsTexture` on a world-sized container;
 *   * `gameMode('')` throwing during render, which sent the **entire** replay
 *     page into React Router's error boundary — canvas included.
 *
 * The last one took ten seconds to find once a browser was actually pointed at
 * the page. It prints `pageerror`, console errors, failed requests, tile
 * responses and a DOM summary, then writes a PNG.
 *
 * Not part of `npm test`: it needs a browser binary and a running API, and the
 * deploy box has neither by default. See HANDOFF §17 for getting a headless
 * Chrome onto a box with no root.
 *
 *   CHROME=/path/to/chrome-headless-shell \
 *   LD_LIBRARY_PATH=... \
 *   node scripts/probe-replay.mjs <matchId> [--t=600] [--shot=out.png]
 */
import puppeteer from 'puppeteer'

const args = process.argv.slice(2)
const matchId = args.find((a) => !a.startsWith('--'))
const opt = (name, fallback) =>
  args.find((a) => a.startsWith(`--${name}=`))?.split('=')[1] ?? fallback

if (!matchId) {
  console.error('usage: node scripts/probe-replay.mjs <matchId> [--t=600] [--shot=out.png]')
  process.exit(2)
}

const base = opt('base', 'http://127.0.0.1:8000')
const at = opt('t', null)
const shot = opt('shot', 'replay-probe.png')

const browser = await puppeteer.launch({
  executablePath: process.env.CHROME,
  headless: true,
  args: [
    '--no-sandbox',
    '--disable-dev-shm-usage',
    // The deploy box has no GPU; ANGLE over SwiftShader gives real WebGL.
    '--enable-unsafe-swiftshader',
    '--use-gl=angle',
    '--use-angle=swiftshader',
  ],
})

try {
  const page = await browser.newPage()
  await page.setViewport({ width: 1500, height: 950 })

  const problems = []
  page.on('pageerror', (e) => problems.push(`[pageerror] ${e.message}`))
  page.on('console', (m) => {
    if (m.type() === 'error') problems.push(`[console] ${m.text()}`)
  })
  page.on('requestfailed', (r) =>
    problems.push(`[reqfail] ${r.url()} :: ${r.failure()?.errorText}`),
  )

  const tiles = []
  page.on('response', (r) => {
    if (r.url().includes('/tiles/') && r.url().endsWith('.webp')) tiles.push(r.status())
  })

  const url = `${base}/matches/${matchId}/replay${at ? `?t=${at}` : ''}`
  await page.goto(url, { waitUntil: 'networkidle2', timeout: 45_000 })
  await new Promise((r) => setTimeout(r, 5000))

  const dom = await page.evaluate(() => {
    const canvas = document.querySelector('canvas')
    return {
      canvas: canvas ? `${canvas.clientWidth}x${canvas.clientHeight}` : 'MISSING',
      renderError: document.querySelector('.render-error')?.textContent ?? null,
      railPanels: document.querySelectorAll('.panel').length,
      feedRows: document.querySelectorAll('.feed-row').length,
      teamButtons: document.querySelectorAll('.member').length,
      clock: document.querySelector('.topbar')?.textContent ?? null,
    }
  })

  console.log(JSON.stringify({ url, ...dom, tiles: tiles.length }, null, 2))
  console.log(problems.length ? problems.slice(0, 20).join('\n') : 'no errors')

  await page.screenshot({ path: shot })
  console.log(`screenshot -> ${shot}`)

  // A canvas that never appeared, or a page that threw, is a failure.
  process.exitCode = dom.canvas === 'MISSING' || problems.length > 0 ? 1 : 0
} finally {
  await browser.close()
}
