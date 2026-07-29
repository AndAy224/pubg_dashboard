/**
 * Load an ordinary page in a real browser and report whether it rendered.
 *
 * Third sibling of `probe-replay.mjs` and `probe-map.mjs`, and it exists for
 * the same reason they do: `tsc`, `oxlint`, `vitest` and `npm run build` have
 * all passed on pages that threw during render. React Router's error boundary
 * swallows that throw and takes the whole page with it, so the server log is
 * clean, the build is clean, and the page is blank.
 *
 * Those two probes are specific — one drives the Pixi replay, one drags a map.
 * This one just asks "did the page come up, and what is on it", which is the
 * check every other route needs and none of them had.
 *
 * **Probes the deployed `dist/`**, so `npm run build` first or you are testing
 * the previous build and drawing conclusions about code that is not running.
 *
 *   CHROME=/path/to/chrome-headless-shell \
 *   LD_LIBRARY_PATH=... \
 *   node scripts/probe-page.mjs <url> [--shot=out.png] [--wait=2500]
 *
 * Run it from `frontend/` — node resolves `puppeteer` from the script's own
 * location, not the working directory. HANDOFF §17 has the no-root setup.
 */
import puppeteer from 'puppeteer'

const args = process.argv.slice(2)
const url = args.find((a) => !a.startsWith('--'))
const shot = args.find((a) => a.startsWith('--shot='))?.split('=')[1]
const wait = Number(args.find((a) => a.startsWith('--wait='))?.split('=')[1] ?? 2500)

if (!url) {
  console.error('usage: node scripts/probe-page.mjs <url> [--shot=out.png] [--wait=ms]')
  process.exit(2)
}

const browser = await puppeteer.launch({
  executablePath: process.env.CHROME,
  args: [
    '--no-sandbox',
    // Real WebGL with no GPU. Harmless here, but shared with the other probes
    // so one page that happens to mount a canvas does not need a second recipe.
    '--enable-unsafe-swiftshader',
    '--use-gl=angle',
    '--use-angle=swiftshader',
  ],
})

const page = await browser.newPage()
await page.setViewport({ width: 1440, height: 1200 })

const pageErrors = []
const failedRequests = []
const consoleMessages = []
page.on('pageerror', (e) => pageErrors.push(String(e)))
page.on('requestfailed', (r) => failedRequests.push(`${r.failure()?.errorText} ${r.url()}`))
page.on('console', (m) => {
  if (m.type() === 'error' || m.type() === 'warning') consoleMessages.push(`${m.type()}: ${m.text()}`)
})

await page.goto(url, { waitUntil: 'networkidle0', timeout: 45_000 })

// Recharts animates its marks in over ~1.5 s of requestAnimationFrame time,
// so an early screenshot shows axes with no bars and looks like a broken
// chart. Wait real time before summarising. (HANDOFF §24.)
await new Promise((r) => setTimeout(r, wait))

const summary = await page.evaluate(() => ({
  h1: document.querySelector('h1')?.textContent ?? null,
  sections: [...document.querySelectorAll('h2')].map((h) => h.textContent),
  tables: [...document.querySelectorAll('table')].map((t) => ({
    rows: t.querySelectorAll('tbody tr').length,
    columns: [...t.querySelectorAll('thead th')].map((h) => h.textContent),
  })),
  tiles: [...document.querySelectorAll('.tile')].map((t) => t.textContent.trim()),
  // Empty states and error notices are the two things most likely to be
  // rendering *instead of* the content, so they are called out rather than
  // left for someone to spot in a screenshot.
  emptyOrError: [...document.querySelectorAll('.empty, .notice')].map((e) => e.textContent.trim()),
  // A page body that scrolls sideways is a layout bug on every screen size.
  bodyScrollsSideways: document.body.scrollWidth > document.body.clientWidth,
  textLength: document.body.innerText.length,
}))

console.log('page errors:      ', pageErrors.length ? pageErrors : 'none')
console.log('failed requests:  ', failedRequests.length ? failedRequests : 'none')
console.log('console warnings: ', consoleMessages.length ? consoleMessages.slice(0, 10) : 'none')
console.log(JSON.stringify(summary, null, 1))

if (shot) {
  await page.screenshot({ path: shot, fullPage: true })
  console.log('screenshot ->', shot)
}

await browser.close()

// A page that threw is a failure, not a report. Exit non-zero so this can sit
// in a shell chain without the caller having to grep the output.
process.exit(pageErrors.length > 0 ? 1 : 0)
