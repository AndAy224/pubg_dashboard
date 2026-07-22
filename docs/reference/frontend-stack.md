# Frontend Stack Reference — React + Vite + TypeScript + PixiJS

**Dimension:** frontend-stack
**Researched:** 2026-07-22
**Scope:** Everything the implementer needs to build the SPA described in `pubg-dashboard-plan(1).md` §7–8 (map replay renderer, heatmaps, dense stat tables, charts) against a FastAPI backend.

> **Read this first:** PixiJS v8 broke almost every drawing call that existed in v7. Most tutorials, StackOverflow answers, and LLM training data are v7-era and **will not run**. §3.2 is the authoritative rename table. If you find yourself typing `beginFill`, `drawRect`, `lineStyle`, or `app.view`, stop.

---

## 1. Sources

Every URL below was actually fetched during research on 2026-07-22.

### Registry / version truth
- `https://registry.npmjs.org/-/package/pixi.js/dist-tags`
- `https://registry.npmjs.org/-/package/react/dist-tags`
- `https://registry.npmjs.org/-/package/typescript/dist-tags`
- `https://registry.npmjs.org/pixi.js/latest`
- `https://registry.npmjs.org/@pixi/react/latest`
- `https://registry.npmjs.org/pixi-viewport/latest`
- `https://registry.npmjs.org/@tanstack/react-query/latest`
- `https://registry.npmjs.org/@tanstack/react-query` (dist-tags)
- `https://registry.npmjs.org/@tanstack/react-table/latest`
- `https://registry.npmjs.org/@tanstack/react-table` (dist-tags)
- `https://registry.npmjs.org/@tanstack/react-virtual/latest`
- `https://registry.npmjs.org/recharts` (dist-tags)
- `https://registry.npmjs.org/recharts/latest`
- `https://registry.npmjs.org/vite/latest`
- `https://registry.npmjs.org/@vitejs/plugin-react/latest`

### Vite / React / TypeScript
- `https://vite.dev/blog/announcing-vite8`
- `https://vite.dev/config/server-options`
- `https://github.com/vitejs/vite/tree/main/packages/create-vite/template-react-ts`
- `https://raw.githubusercontent.com/vitejs/vite/main/packages/create-vite/template-react-ts/package.json`
- `https://raw.githubusercontent.com/vitejs/vite/main/packages/create-vite/template-react-ts/tsconfig.app.json`
- `https://raw.githubusercontent.com/vitejs/vite/main/packages/create-vite/template-react-ts/vite.config.ts`
- `https://raw.githubusercontent.com/vitejs/vite-plugin-react/main/packages/plugin-react/README.md`
- `https://raw.githubusercontent.com/vitejs/vite-plugin-react/main/packages/plugin-react/CHANGELOG.md` (Babel removal, 6.0.0-beta.0)
- `https://raw.githubusercontent.com/vitejs/vite/main/packages/create-vite/template-react-ts/package.json`
- `https://documentation.pubg.com/en/telemetry-objects.html` (Location, Character)
- `https://raw.githubusercontent.com/mourner/simpleheat/master/simpleheat.js`
- `https://devblogs.microsoft.com/typescript/announcing-typescript-7-0/`
- `https://typescript-eslint.io/users/dependency-versions/`
- `https://react.dev/learn/react-compiler/installation`

### PixiJS
- `https://pixijs.com/8.x/guides/migrations/v8`
- `https://pixijs.com/8.x/guides/components/application`
- `https://pixijs.com/8.x/guides/components/scene-objects/graphics`
- `https://pixijs.com/8.x/guides/components/scene-objects/container`
- `https://pixijs.com/8.x/guides/components/scene-objects/particle-container`
- `https://pixijs.com/8.x/guides/components/scene-objects/text`
- `https://pixijs.com/8.x/guides/components/textures`
- `https://pixijs.com/8.x/guides/components/assets`
- `https://pixijs.com/8.x/guides/components/filters`
- `https://pixijs.com/8.x/guides/components/events`
- `https://pixijs.com/8.x/guides/concepts/render-loop`
- `https://pixijs.com/8.x/guides/concepts/performance-tips`
- `https://pixijs.com/blog/june-2026`
- `https://pixijs.download/release/docs/scene.Graphics.html`
- `https://pixijs.download/release/docs/ticker.Ticker.html`
- `https://pixijs.download/release/docs/text.BitmapFont.html`
- `https://raw.githubusercontent.com/pixijs/pixijs/dev/src/scene/graphics/shared/GraphicsContext.ts`
- `https://raw.githubusercontent.com/pixijs/pixijs/dev/src/scene/graphics/shared/FillTypes.ts`
- `https://raw.githubusercontent.com/pixijs/pixijs/dev/src/scene/particle-container/shared/Particle.ts`
- `https://raw.githubusercontent.com/pixijs/pixijs/dev/src/ticker/const.ts`
- `https://api.github.com/repos/pixijs/pixijs/issues/10456`

### Pixi ecosystem
- `https://raw.githubusercontent.com/pixijs/pixi-react/main/README.md`
- `https://react.pixijs.io/components/application/`
- `https://api.github.com/repos/pixijs/pixi-react`
- `https://raw.githubusercontent.com/davidfig/pixi-viewport/master/README.md`
- `https://api.github.com/repos/pixijs-userland/pixi-viewport`
- `https://api.github.com/repos/pixijs-userland/pixi-viewport/releases?per_page=5`

### Data layer / viz
- `https://tanstack.com/query/latest/docs/framework/react/guides/migrating-to-v5`
- `https://tanstack.com/table/latest/docs/framework/react/guide/table-state`
- `https://github.com/recharts/recharts/wiki/3.0-migration-guide` (via search summary)
- `https://developer.mozilla.org/en-US/docs/Web/API/CanvasRenderingContext2D/filter`
- `https://caniuse.com/mdn-api_canvasrenderingcontext2d_filter`

---

## 2. Version matrix (verified 2026-07-22)

| Package | Latest stable | Notes |
|---|---|---|
| `pixi.js` | **8.19.0** | v8 line since Mar 2024. No v9. `prerelease-v8` tag exists but `latest` is 8.19.0. |
| `@pixi/react` | **8.0.5** | peerDeps: `react >=19.0.0`, `pixi.js ^8.2.6` |
| `pixi-viewport` | **6.0.3** | peerDep `pixi.js >=8`. Published 2024-11-27; repo `pushed_at` 2025-02-03. See §6 for the maintenance caveat. |
| `react` / `react-dom` | **19.2.8** | `create-vite` template currently pins `19.2.7`. Either is fine; use `^19.2.7`. |
| `vite` | **8.1.5** | Vite 8 GA 2026-03-12. Rolldown is now the single bundler. `engines: {"node": "^20.19.0 \|\| >=22.12.0"}` |
| `@vitejs/plugin-react` | **6.0.4** | peerDep `vite: ^8.0.0`. **Babel removed** — uses Oxc. See §2.3. |
| `typescript` | `latest` = **7.0.2** | ⚠️ **Do not use 7.x yet for this project.** See §2.2. Use `~6.0.2` (what `create-vite` pins). |
| `oxlint` | 1.74.0 (per template) | `create-vite`'s react-ts template now ships oxlint, **not** ESLint. |
| `@tanstack/react-query` | **5.101.4** | No v6. peerDep `react: ^18 \|\| ^19` |
| `@tanstack/react-table` | **8.21.3** | v9 exists only as `beta: 9.0.0-beta.55`. Ship on v8. |
| `@tanstack/react-virtual` | **3.14.8** | peerDep `react: ^16.8 … ^19` |
| `recharts` | **3.10.0** | v2 is EOL / no longer receiving updates. peerDeps include `react-is` — see §11. |

### 2.1 What `create-vite`'s `react-ts` template actually contains (main branch, 2026-07-22)

Files: `public/`, `src/`, `README.md`, `_gitignore`, **`_oxlintrc.json`**, `index.html`, `package.json`, `tsconfig.app.json`, `tsconfig.json`, `tsconfig.node.json`, `vite.config.ts`.

Pinned versions in that template: `react`/`react-dom` `19.2.7`, `typescript` `~6.0.2`, `vite` `8.1.5`, `@vitejs/plugin-react` `6.0.3`, `oxlint` `1.74.0`. Scripts: `dev`, `build` (`tsc -b && vite build`), `lint` (oxlint), `preview`.

`vite.config.ts` verbatim from the template:

```ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
})
```

`tsconfig.app.json` key settings (verbatim values): `"target": "es2023"`, `"lib": ["ES2023", "DOM"]`, `"module": "esnext"`, `"moduleResolution": "bundler"`, `"jsx": "react-jsx"`, `"noUnusedLocals": true`, `"noUnusedParameters": true`, `"noFallthroughCasesInSwitch": true`, `"include": ["src"]`, plus a `tsBuildInfoFile` for incremental builds.

### 2.2 ⚠️ TypeScript 7 trap — pin to 6.x

TypeScript 7.0 (stable 2026-07-08) is the Go-native compiler rewrite. It is 8–12× faster, **but**:

> "TypeScript 7.0 does not ship with an API." — official announcement.

Consequences that will bite you:

- **typescript-eslint (v8.65.0) declares support for `>=4.8.4 <6.1.0`.** TS 7 is entirely outside that range. `npm ci` fails on the peer range; `npm install` succeeds but ESLint crashes inside `@typescript-eslint/typescript-estree`. A programmatic API is expected in **TS 7.1 (~Oct 2026)**.
- TS 7 turns former deprecations into hard errors: `target: es5`, `downlevelIteration`, `baseUrl`, `module: amd|umd|systemjs|none`, `moduleResolution: node|node10|classic` are removed; `esModuleInterop` and `allowSyntheticDefaultImports` can no longer be `false`; `assert` on imports is gone (use `with`).
- `stableTypeOrdering` is on and cannot be disabled; `rootDir` now defaults to `./`, so projects need an explicit `"rootDir": "./src"`.

**Recommendation:** `"typescript": "~6.0.2"` in `devDependencies`. Revisit after TS 7.1 ships.
If you *want* TS 7's speed now, Microsoft published `@typescript/typescript6` so both can coexist. The announcement's own recipe is an npm alias (`@typescript/typescript6@6.0.2` declares `"bin": {"tsc6": "bin/tsc6"}`, so the 6.x compiler is invoked as `tsc6`):

```sh
npm install -D typescript@npm:@typescript/typescript6
```

…and point ESLint at the 6.x install. For this project that complexity is not worth it. Note that `create-vite` itself still pins `~6.0.2`, which is the strongest signal available.

Corollary: since the template ships **oxlint** (a Rust linter with no TypeScript-API dependency), adopting oxlint sidesteps the whole problem. That is the recommended lint path.

### 2.3 ⚠️ `@vitejs/plugin-react` v6 dropped Babel

v6 moved React Refresh + JSX transform to **Oxc** (Rust). The inline `babel` option was **removed** — sourced to the plugin's CHANGELOG, 6.0.0-beta.0 (not the README, which does not mention the removal): *"Vite 8+ can handle React Refresh Transform by Oxc and doesn't need Babel for it. With that, there are no transform applied that requires Babel. To reduce the installation size of this plugin, babel is no longer a dependency of this plugin and the related features are removed."* If you want React Compiler you must add Babel back explicitly:

```sh
npm install -D @rolldown/plugin-babel @babel/core babel-plugin-react-compiler
```

```ts
// vite.config.ts
import { defineConfig } from 'vite'
import react, { reactCompilerPreset } from '@vitejs/plugin-react'
import babel from '@rolldown/plugin-babel'

export default defineConfig({
  plugins: [
    react(),
    babel({ presets: [reactCompilerPreset()] }),
  ],
})
```

`reactCompilerPreset()` accepts `compilationMode` and `target`.

**Recommendation for this project: skip React Compiler initially.** It is stable (v1.0, Oct 2025) and production-proven, but it auto-memoizes React components — and the hot path in this app (the replay renderer) lives *outside* React entirely (§5). Adding a Babel pass back into a Rolldown pipeline costs build speed for near-zero benefit here. Add it later if the dashboard shell (tables/charts) shows re-render pressure.

---

## 3. Project setup

### 3.1 Scaffold

```sh
npm create vite@latest pubg-dashboard-web -- --template react-ts
cd pubg-dashboard-web
npm install
npm install pixi.js @tanstack/react-query recharts @tanstack/react-table
npm install -D @types/node
```

Target `package.json` (dependency section):

```json
{
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "lint": "oxlint",
    "preview": "vite preview"
  },
  "dependencies": {
    "@tanstack/react-query": "^5.101.4",
    "@tanstack/react-table": "^8.21.3",
    "@tanstack/react-virtual": "^3.14.8",
    "pixi.js": "^8.19.0",
    "react": "^19.2.7",
    "react-dom": "^19.2.7",
    "recharts": "^3.10.0"
  },
  "devDependencies": {
    "@types/node": "^24.13.3",
    "@types/react": "^19.2.17",
    "@types/react-dom": "^19.2.3",
    "@vitejs/plugin-react": "^6.0.4",
    "oxlint": "^1.74.0",
    "typescript": "~6.0.2",
    "vite": "^8.1.5"
  }
}
```

> The `@types/*` versions above are taken from `create-vite`'s `template-react-ts/package.json` on `main` (`@types/node ^24.13.3`, `@types/react ^19.2.17`, `@types/react-dom ^19.2.3`). Still worth re-resolving at install time, but they are not placeholders.

### 3.2 `vite.config.ts` with the FastAPI proxy

FastAPI's conventional dev port is `8000` (`uvicorn app:app --reload --port 8000`). Vite dev server defaults to `5173`.

```ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [react()],

  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },

  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      // http://localhost:5173/api/players -> http://127.0.0.1:8000/api/players
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      // Replay progress / live ingest status over WebSocket (plan §2: "REST + WS")
      '/ws': {
        target: 'ws://127.0.0.1:8000',
        ws: true,
        changeOrigin: true,
      },
      // Raw telemetry / map tiles served straight off the backend's object store
      '/static': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },

  build: {
    // pixi.js + `await app.init()` needs top-level-await-capable output. See §12.
    target: 'esnext',
  },
})
```

`server.proxy` semantics, from the Vite docs:

| Form | Behaviour |
|---|---|
| `'/foo': 'http://localhost:4567'` | String shorthand. `/foo` → `http://localhost:4567/foo`. Path prefix is **kept**. |
| `'/api': { target, changeOrigin, rewrite }` | Options object. `rewrite: p => p.replace(/^\/api/, '')` strips the prefix. |
| Key starting with `^` | Treated as a **RegExp**, e.g. `'^/fallback/.*'`. |
| `ws: true` | Proxies WebSocket upgrade. |
| `configure(proxy, options)` | Gives you the raw `http-proxy-3` instance. |

Notes:
- Requests matching a proxy rule **bypass Vite's transform pipeline** entirely.
- Prefer **not** rewriting: mount your FastAPI routes under `/api` (`APIRouter(prefix="/api")`) so dev and prod paths are identical and you never need `rewrite`.
- `rewriteWsOrigin` exists but the docs explicitly warn it can open the proxy to CSRF. Don't use it.
- Use `127.0.0.1`, not `localhost`, as the proxy target — on Windows, `localhost` can resolve to `::1` first while uvicorn binds `0.0.0.0` (IPv4 only), producing `ECONNREFUSED`.
- `server.allowedHosts: true` is a DNS-rebinding hole per the docs; leave it at the default.

### 3.3 `.env` handling

Vite only exposes vars prefixed `VITE_`. Never put the PUBG API key in the frontend — the plan already puts all PUBG calls behind the ingestion worker/backend, which is correct.

```
# .env.development
VITE_API_BASE=/api
```

```ts
const API_BASE = import.meta.env.VITE_API_BASE ?? '/api'
```

---

## 4. PixiJS v8 — the current API

**Current major: 8. Current version: 8.19.0.** There is no v9.

### 4.1 Application bootstrap (async)

```ts
import { Application } from 'pixi.js'

const app = new Application()

await app.init({
  // canvas: existingCanvasEl,          // optional: bring your own <canvas>
  width: 1280,
  height: 720,
  background: 0x11150f,                 // map-toned neutral, plan §8
  backgroundAlpha: 1,
  antialias: true,
  resolution: window.devicePixelRatio,
  autoDensity: true,                    // scales canvas CSS size to match resolution
  preference: 'webgl',                  // 'webgl' | 'webgpu'
  powerPreference: 'high-performance',
  resizeTo: containerEl,                // element or window; auto-resizes renderer
  autoStart: true,
  sharedTicker: false,
})

document.getElementById('stage')!.appendChild(app.canvas)
```

Init option groups, reproducing the Application guide's own grouping: dimensions (`width`, `height`), visual (`backgroundColor`/`background`, `backgroundAlpha`), rendering (`preference`, `antialias`), texture GC (`textureGCActive`, `textureGCCheckCountMax` — default `600`, `textureGCMaxIdle` — default `3600`), behaviour (`autoStart` — default `true`, `sharedTicker` — default `false`, `clearBeforeRender`, `resizeTo`), advanced (`resolution`, `premultipliedAlpha`, `preserveDrawingBuffer`, `powerPreference`, `preferWebGLVersion`, `skipExtensionImports`). Note the guide lists `resolution` under *Advanced*, and does **not** enumerate `autoDensity` or `depth` in these groups — both are nevertheless real renderer options.

Renderer-specific overrides:

```ts
await app.init({
  width: 800,
  height: 600,
  webgl: { antialias: true },
  webgpu: { antialias: false },
})
```

Key properties: `app.canvas` (the `HTMLCanvasElement`), `app.stage` (root `Container`), `app.ticker`, `app.screen` (a `Rectangle` of the current view), `app.renderer`.

Teardown:

```ts
app.destroy(
  { removeView: true },                        // renderer destroy options
  { children: true, texture: true, textureSource: true }, // scene destroy options
)
```

### 4.2 ⚠️ v7 → v8 rename table (the single most important thing in this document)

| v7 | v8 | Note |
|---|---|---|
| `new Application({...})` | `const app = new Application(); await app.init({...})` | **Async.** Constructor takes no options. |
| `import { Sprite } from '@pixi/sprite'` | `import { Sprite } from 'pixi.js'` | Single package again; sub-packages gone. |
| `app.view` | `app.canvas` | |
| `container.name` | `container.label` | `getChildByLabel()` / `getChildrenByLabel()` |
| `container.cacheAsBitmap` | `container.cacheAsTexture()` | Renamed **and** refactored. |
| `graphics.drawRect(x,y,w,h)` | `graphics.rect(x,y,w,h)` | |
| `graphics.drawCircle(x,y,r)` | `graphics.circle(x,y,r)` | |
| `graphics.drawPolygon(pts)` | `graphics.poly(pts, close?)` | |
| `graphics.beginFill(c, a)` | `graphics.fill(style)` — **after** the shape | Workflow reversed. |
| `graphics.endFill()` | *(gone)* | `fill()` closes it. |
| `graphics.lineStyle(w, c)` | `graphics.stroke(style)` / `graphics.setStrokeStyle(style)` | **`lineStyle` does not exist in v8.** |
| `graphics.beginHole()` / `endHole()` | `graphics.cut()` | |
| `Texture.from('image.png')` (loads) | `await Assets.load('image.png')` **then** `Texture.from('image.png')` | Textures no longer load resources. |
| `ticker.add(dt => ...)` | `ticker.add(ticker => ... ticker.deltaTime ...)` | Callback arg is the **Ticker**, not a number. |
| `new ParticleContainer(); c.addChild(sprite)` | `new ParticleContainer(); c.addParticle(new Particle({texture}))` | Sprites are no longer valid children. |
| `container.getBounds() // Rectangle` | `container.getBounds().rectangle` | Returns a `Bounds`. |
| `new NineSlicePlane(...)` | `new NineSliceSprite(...)` | |
| `PIXI.settings.X = ...` | `AbstractRenderer.defaultOptions.X = ...` | `settings` removed. |
| `PIXI.utils.foo()` | `import { foo } from 'pixi.js'` | `utils` namespace removed. |
| `renderer.render(container, { renderTexture })` | `renderer.render({ container, target })` | Options object. |
| `new Filter(vert, frag, uniforms)` | `new Filter({ glProgram: GlProgram.from({vertex, fragment}), resources: {...} })` | |

### 4.3 Graphics

Full `GraphicsContext` method list, taken verbatim from `src/scene/graphics/shared/GraphicsContext.ts` on `dev`:

```ts
clone(): GraphicsContext
setFillStyle(style: FillInput): this
setStrokeStyle(style: StrokeInput): this
texture(texture: Texture): this
texture(texture: Texture, tint?: ColorSource, dx?: number, dy?: number, dw?: number, dh?: number): this
beginPath(): this
fill(style?: FillInput): this
fill(color: ColorSource, alpha: number): this
stroke(style?: StrokeInput): this
cut(): this
arc(x: number, y: number, radius: number, startAngle: number, endAngle: number, counterclockwise?: boolean): this
arcTo(x1: number, y1: number, x2: number, y2: number, radius: number): this
arcToSvg(rx: number, ry: number, xAxisRotation: number, largeArcFlag: number, sweepFlag: number, x: number, y: number): this
bezierCurveTo(cp1x: number, cp1y: number, cp2x: number, cp2y: number, x: number, y: number, smoothness?: number): this
closePath(): this
ellipse(x: number, y: number, radiusX: number, radiusY: number): this
circle(x: number, y: number, radius: number): this
path(path: GraphicsPath): this
lineTo(x: number, y: number): this
moveTo(x: number, y: number): this
quadraticCurveTo(cpx: number, cpy: number, x: number, y: number, smoothness?: number): this
rect(x: number, y: number, w: number, h: number): this
roundRect(x: number, y: number, w: number, h: number, radius?: number): this
poly(points: number[] | PointData[], close?: boolean): this
regularPoly(x: number, y: number, radius: number, sides: number, rotation?: number, transform?: Matrix): this
roundPoly(x: number, y: number, radius: number, sides: number, corner: number, rotation?: number): this
roundShape(points: RoundedPoint[], radius: number, useQuadratic?: boolean, smoothness?: number): this
filletRect(x: number, y: number, width: number, height: number, fillet: number): this
chamferRect(x: number, y: number, width: number, height: number, chamfer: number, transform?: Matrix): this
star(x: number, y: number, points: number, radius: number, innerRadius?: number, rotation?: number): this
svg(svg: string): this
restore(): this
save(): this
getTransform(): Matrix
resetTransform(): this
rotate(angle: number): this
scale(x: number, y?: number): this
setTransform(transform: Matrix): this
setTransform(a: number, b: number, c: number, d: number, dx: number, dy: number): this
transform(transform: Matrix): this
transform(a: number, b: number, c: number, d: number, dx: number, dy: number): this
translate(x: number, y?: number): this
clear(): this
containsPoint(point: PointData): boolean
unload(): void
destroy(options?: TypeOrBool<TextureDestroyOptions>): void
```

`Graphics` proxies all of these. Fill/stroke style shapes (from `FillTypes.ts`):

| Type | Members |
|---|---|
| `FillStyle` | `color`, `alpha`, `texture`, `matrix`, `fill` (`FillPattern \| FillGradient`), `textureSpace` (`'local' \| 'global'`) |
| `StrokeAttributes` | `width`, `alignment`, `cap` (`LineCap`), `join` (`LineJoin`), `miterLimit`, `pixelLine` |
| `StrokeStyle` | `FillStyle & StrokeAttributes` |
| `FillInput` | `ColorSource \| FillGradient \| FillPattern \| FillStyle \| Texture` |
| `StrokeInput` | `ColorSource \| FillGradient \| FillPattern \| StrokeStyle` |

`LineCap`: `'butt' | 'round' | 'square'`. `LineJoin`: `'miter' | 'round' | 'bevel'`.

Real code — zone circles for the replay (plan §7):

```ts
import { Graphics } from 'pixi.js'

const zones = new Graphics()

function drawZones(safe: Circle, blue: Circle, red: Circle | null) {
  zones.clear()

  // Blue zone: outer boundary, thick stroke, no fill
  zones
    .circle(blue.x, blue.y, blue.r)
    .stroke({ width: 3, color: 0x4aa3ff, alpha: 0.9, alignment: 0.5 })

  // Safe zone: white ring
  zones
    .circle(safe.x, safe.y, safe.r)
    .stroke({ width: 2, color: 0xffffff, alpha: 0.85 })

  // Red zone: translucent fill + stroke
  if (red) {
    zones
      .circle(red.x, red.y, red.r)
      .fill({ color: 0xff3b30, alpha: 0.12 })
      .stroke({ width: 1, color: 0xff3b30, alpha: 0.5 })
  }
}
```

**`pixelLine`** is genuinely useful here: a stroke with `{ pixelLine: true }` stays exactly 1 screen pixel wide regardless of viewport zoom — ideal for the map grid overlay and damage lines that must not fatten when you zoom in.

```ts
grid.moveTo(x, 0).lineTo(x, worldH).stroke({ color: 0x2a3128, pixelLine: true })
```

> ⚠️ The official Graphics guide page contains an example that chains `.lineStyle(5)` after `.stroke()`. **That example is stale/wrong** — `lineStyle` is not on `GraphicsContext` in v8 (confirmed against source). Use `setStrokeStyle()` if you want to set a style before building the path.

### 4.4 Container

| API | Purpose |
|---|---|
| `addChild(...children)`, `addChildAt(child, i)` | Insert |
| `removeChild(...)`, `removeChildAt(i)`, `removeChildren(start?, end?)` | Remove |
| `swapChildren(a, b)` | Reorder |
| `reparentChild(child)`, `reparentChildAt(child, i)` | Move between containers **preserving world transform** |
| `label`, `getChildByLabel(label, deep?)`, `getChildrenByLabel(label, deep?)` | Lookup (regex accepted). Replaces v7 `name`. |
| `zIndex` + parent `sortableChildren = true`, `sortChildren()` | Draw order |
| `position`/`x`/`y`, `scale`, `pivot`, `rotation`, `angle`, `skew` | Transform |
| `visible` | Excluded from render **and** bounds |
| `renderable` | Excluded from render, **still contributes to bounds** |
| `alpha`, `tint`, `blendMode` | Appearance |
| `cacheAsTexture(true \| options)` | v8 replacement for `cacheAsBitmap` |
| `isRenderGroup = true` / `enableRenderGroup()` | Promote to its own render group — the v8 perf primitive |
| `getBounds()` → `Bounds` | `.rectangle` for the old `Rectangle` |
| `onRender` | Per-frame callback invoked during the scene-graph phase |
| `eventMode`, `hitArea`, `interactiveChildren` | Interaction (§4.9) |
| `cullable`, `cullableChildren`, `cullArea` | Culling (§4.10) |
| `destroy(options)` | `{ children, texture, textureSource }` |

**Render groups** are the headline v8 optimization. A container marked `isRenderGroup = true` gets its own transform/render pass on the GPU, so moving the *group* is nearly free even with thousands of descendants. Perfect for the replay's world container: pan/zoom mutates one transform, not 100 sprites' world matrices.

### 4.5 Textures, Sprites, Assets

```ts
import { Assets, Sprite, Texture, Container } from 'pixi.js'

await Assets.init({ basePath: '/static/' })

// alias form
await Assets.load({ alias: 'erangel', src: 'maps/Erangel_Main_High_Res.png' })
const mapTex = Assets.get('erangel')

// plain form
const dotTex = await Assets.load('sprites/player-dot.png')

const mapSprite = new Sprite(mapTex)
mapSprite.width = WORLD_PX
mapSprite.height = WORLD_PX
```

`TextureSource` subclasses in v8: `ImageSource` (HTMLImageElement / ImageBitmap / SVG / VideoFrame), `CanvasSource` (HTMLCanvasElement / OffscreenCanvas), `VideoSource`, `BufferImageSource` (TypedArray + explicit width/height/format), `CompressedSource`.

Configuration lives on the source: `scaleMode`, `wrapMode` (`addressMode`), `format` (e.g. `'rgba8unorm'`), `resolution`.

Freeing memory: `texture.destroy()`, `Assets.unload('alias')`, or `texture.source.unload()` (drops the GPU copy, keeps CPU source).

If you will mutate a texture's `frame`/`trim`/`source` at runtime, construct it with `dynamic: true`.

**Spritesheet atlas** — standard TexturePacker JSON hash format, loaded through `Assets.load`:

```json
{
  "frames": {
    "care-package.png":  { "frame": {"x":0,"y":0,"w":32,"h":32},   "sourceSize": {"w":32,"h":32}, "spriteSourceSize": {"x":0,"y":0,"w":32,"h":32} },
    "vehicle-dacia.png": { "frame": {"x":32,"y":0,"w":24,"h":40},  "sourceSize": {"w":24,"h":40}, "spriteSourceSize": {"x":0,"y":0,"w":24,"h":40} },
    "kill-marker.png":   { "frame": {"x":56,"y":0,"w":16,"h":16},  "sourceSize": {"w":16,"h":16}, "spriteSourceSize": {"x":0,"y":0,"w":16,"h":16} }
  },
  "meta": {
    "image": "replay-atlas.png",
    "format": "RGBA8888",
    "size": { "w": 256, "h": 256 },
    "scale": "1"
  }
}
```

```ts
const sheet = await Assets.load('atlases/replay-atlas.json')
const pkg = new Sprite(sheet.textures['care-package.png'])
```

> ⚠️ The exact `sheet.textures[...]` / `sheet.animations[...]` accessor shape was **not** re-confirmed against a fetched v8 doc page in this pass (the spritesheet guide URL 404'd). It is the long-standing Pixi API and is almost certainly unchanged, but verify once at implementation time.

### 4.6 Text vs BitmapText

| Class | Render path | Use when | Avoid when |
|---|---|---|---|
| `Text` | Browser text engine → texture | Rich styling, text changes rarely | Changing every frame; hundreds of instances |
| `BitmapText` | Pre-baked glyph atlas | **Thousands of changing labels**, low memory | You need per-instance font changes |
| `HTMLText` | DOM/SVG → texture | Complex markup, semi-dynamic | Pixel-perfect perf; hundreds of blocks |

For the replay's 100 player-name labels and the ticking match clock, use **`BitmapText`**. Generate the font once at startup:

```ts
import { BitmapFont, BitmapText } from 'pixi.js'

BitmapFont.install({
  name: 'ReplayLabel',
  style: {
    fontFamily: 'Roboto Condensed',
    fontSize: 16,
    fill: 0xe8e6df,
    stroke: { color: 0x000000, width: 3 },
  },
  chars: [['a', 'z'], ['A', 'Z'], ['0', '9'], ' _-[]().'],
  resolution: 2,
})

const label = new BitmapText({ text: 'PlayerName', style: { fontFamily: 'ReplayLabel', fontSize: 16 } })
label.anchor.set(0.5, 1)
```

`BitmapFont.install(options)` fields: `name`, `style` (a `TextStyle`-shaped object), `chars`, `resolution`, `padding`, `textureStyle`. `BitmapFont.uninstall(name)` frees it.

The match clock and any per-frame numeric readouts should be **DOM elements overlaid on the canvas**, not Pixi text at all — cheaper and gets you the plan's required tabular figures and WCAG contrast for free.

### 4.7 Ticker

```ts
import { Ticker, UPDATE_PRIORITY } from 'pixi.js'

app.ticker.add((ticker: Ticker) => {
  // ticker.deltaTime  – dimensionless frame fraction at target fps (1.0 @ 60fps)
  // ticker.deltaMS    – capped/scaled ms since last frame
  // ticker.elapsedMS  – raw, uncapped, unscaled ms since last frame
  advanceReplay(ticker.deltaMS * playbackSpeed)
}, undefined, UPDATE_PRIORITY.NORMAL)
```

Signatures:

```ts
add<T = any>(fn: TickerCallback<T>, context?: T, priority?: number): this
addOnce<T = any>(fn: TickerCallback<T>, context?: T, priority?: number): this
```

| Property | Meaning |
|---|---|
| `deltaTime` | Scalar frame-time factor, default `1`. Fraction of a frame at target framerate. |
| `deltaMS` | Ms from last frame to this frame (capped by `minFPS`, scaled by `speed`). |
| `elapsedMS` | Raw elapsed ms — **not** capped or scaled. |
| `lastTime` | Ms since epoch of last update, default `-1`. |
| `speed` | Multiplier on `deltaTime`. Use for slow-mo / fast-forward. |
| `FPS` | Accessor, current fps. |
| `minFPS` | Caps the *maximum* ms allowed between updates (i.e. clamps huge deltas after tab-switch). |
| `maxFPS` | Sets the *minimum* ms required between updates (throttles). |
| `autoStart` | `false` by default on new tickers. |
| `started` | Whether it's running. |

`UPDATE_PRIORITY`, verbatim from `src/ticker/const.ts`:

```ts
export enum UPDATE_PRIORITY
{
    INTERACTION = 50,
    HIGH = 25,
    NORMAL = 0,
    LOW = -25,
    UTILITY = -50,
}
```

Higher runs first. For the replay: run interpolation at `HIGH`, trail/RenderTexture bookkeeping at `LOW`.

> For the replay use `deltaMS`, **not** `deltaTime`. You are advancing a wall-clock timeline in telemetry milliseconds; `deltaTime` is a frame-count fraction and will drift on non-60Hz displays.

Also note `maxFPS`: for a 20× fast-forward playback you still only need 60 renders/sec; do **not** raise it.

### 4.8 ParticleContainer + Particle

```ts
import { ParticleContainer, Particle, Texture } from 'pixi.js'

const container = new ParticleContainer({
  dynamicProperties: {
    position: true,   // default true
    vertex: false,    // scale / anchor / rotation baked
    rotation: false,
    uvs: false,      // set true only if you swap frames per-particle
    color: false,
  },
})

const p = new Particle({
  texture: Texture.from('spark.png'),
  x: 200,
  y: 100,
  scaleX: 0.8,
  scaleY: 0.8,
  rotation: Math.PI / 4,
  tint: 0xff0000,
  alpha: 0.5,
})

container.addParticle(p)
// after mutating a *static* property:
container.update()
```

The five `ParticleProperties` keys are exactly `vertex`, `position`, `rotation`, `uvs`, `color` — an omitted key is silently defaulted, not an error.

`IParticle` members — **exactly these nine** (from `src/scene/particle-container/shared/Particle.ts`):

| Field | Type | Default |
|---|---|---|
| `x` | `number` | `0` |
| `y` | `number` | `0` |
| `scaleX` | `number` | `1` |
| `scaleY` | `number` | `1` |
| `anchorX` | `number` | `0` |
| `anchorY` | `number` | `0` |
| `rotation` | `number` | `0` |
| `color` | `number` | `0xffffffff` (packed ABGR incl. alpha) |
| `texture` | `Texture` | — |

`alpha` and `tint` are **not** on `IParticle` — writing `const p: IParticle = { …, alpha: 1 }` is a compile error. They exist only as accessors on the concrete `Particle` class (`get/set alpha: number`, `get tint(): number` / `set tint(value: ColorSource)`) and as extra keys on `ParticleOptions`:

```ts
export type ParticleOptions = Omit<Partial<IParticle>, 'color'> & {
    texture: Texture;
    tint?: ColorSource;
    alpha?: number;
};
```

**Not available on `ParticleContainer`:** `addChild()`, `removeChild()`, `getChildAt()`, `setChildIndex()`, `swapChildren()`, `reparentChild()`. As of v8.18/8.19, `ParticleContainer` does now respect blend modes inherited from parent containers.

**For this project: do NOT use `ParticleContainer` for the 100 players.** See §8.

### 4.9 Events

| `eventMode` | Behaviour |
|---|---|
| `'none'` | Ignores all interaction, including children |
| `'passive'` | **Default.** No self hit-test; interactive children still receive events |
| `'auto'` | Hit-tested only if a parent is interactive |
| `'static'` | Emits events, hit-tested. For non-moving interactive elements |
| `'dynamic'` | Like static, plus synthetic events while the pointer is idle |

Supported event names:

- **Pointer (preferred):** `pointerdown`, `pointerup`, `pointerupoutside`, `pointermove`, `pointerover`, `pointerout`, `pointerenter`, `pointerleave`, `pointercancel`, `pointertap`, `globalpointermove`
- **Mouse:** `mousedown`, `mouseup`, `mouseupoutside`, `mousemove`, `mouseover`, `mouseout`, `mouseenter`, `mouseleave`, `click`, `rightdown`, `rightup`, `rightupoutside`, `rightclick`, `globalmousemove`, **`wheel`**
- **Touch:** `touchstart`, `touchend`, `touchendoutside`, `touchmove`, `touchcancel`, `tap`, `globaltouchmove`

```ts
const dot = new Sprite(dotTex)
dot.eventMode = 'static'
dot.cursor = 'pointer'
dot.on('pointerdown', () => selectPlayer(dot.label))
```

Perf: set `interactiveChildren = false` on containers that never need hit-testing (zone graphics, trail layer, map background) and set an explicit `hitArea` on the ones that do.

### 4.10 Culling

```ts
import { extensions, CullerPlugin, Rectangle } from 'pixi.js'

extensions.add(CullerPlugin) // must run BEFORE `await app.init()`
```

`CullerPlugin` overrides `Application.render()` to call `Culler.shared.cull()` first.

| Property | Default | Meaning |
|---|---|---|
| `container.cullable` | `false` | Cull this object when offscreen |
| `container.cullableChildren` | `true` | Recurse into children when culling |
| `container.cullArea` | `undefined` | `Rectangle` used instead of computed bounds — avoids an expensive bounds calc |

```ts
world.cullable = false          // the world container itself must stay
world.cullableChildren = true
for (const dot of playerDots) {
  dot.cullable = true
  dot.cullArea = new Rectangle(-8, -8, 16, 16)  // cheap, fixed local bounds
}
```

Culling is **off by default** and helps when GPU-bound. For 100 dots it is marginal; it becomes worthwhile once you add trails and per-player labels, and it matters a lot when the user zooms in and 90% of the world is offscreen.

### 4.11 Filters

```ts
import { BlurFilter, NoiseFilter } from 'pixi.js'

sprite.filters = [new BlurFilter({ strength: 4 }), new NoiseFilter({ noise: 0.2 })]
```

Order matters — filters apply in sequence. Core built-ins shipped in `pixi.js`: `AlphaFilter`, `BlurFilter`, `ColorMatrixFilter`, `DisplacementFilter`, `NoiseFilter`. Advanced blend modes (`ColorBurnBlend`, `ColorDodgeBlend`, `DarkenBlend`, `DivideBlend`, `HardMixBlend`, `LinearBurnBlend`, `LinearDodgeBlend`, `LinearLightBlend`, `PinLightBlend`, `SubtractBlend`) require `import 'pixi.js/advanced-blend-modes'`.

Custom filter (v8 shape):

```ts
import { Filter, GlProgram } from 'pixi.js'

const customFilter = new Filter({
  glProgram: new GlProgram({ fragment, vertex }),
  resources: {
    timeUniforms: {
      uTime: { value: 0.0, type: 'f32' },
    },
  },
})
```

⚠️ To support **both** renderers you must also supply a `gpuProgram` (WGSL). If you only ship `glProgram`, the filter breaks under `preference: 'webgpu'`. This is the main argument against a shader-based heatmap (§10).

Perf: release filter memory with `container.filters = null`; set `filterArea` when you know it; group same-blend-mode objects together to avoid breaking batches.

### 4.12 RenderTexture

```ts
import { RenderTexture, Sprite } from 'pixi.js'

const trailRT = RenderTexture.create({ width: 2048, height: 2048, antialias: false })
const trailSprite = new Sprite(trailRT)

// per frame:
app.renderer.render({ container: newTrailSegments, target: trailRT, clear: false })
```

Note the v8 signature: **`renderer.render({ container, target })`** — an options object, not `render(container, opts)`.

Do not create/destroy render textures per frame. Do not enable mipmaps on them; if you must, call `updateMipmaps()` after each update.

v8.18/8.19 added `RenderTexture.create()` `textureOptions` and a `defaultAnchor` option on `renderer.generateTexture()`.

---

## 5. Integrating Pixi with React — **recommendation: manual mount, not `@pixi/react`**

### The options

**A. `@pixi/react` v8.0.5** — declarative JSX over Pixi.

```tsx
import { Application, extend } from '@pixi/react'
import { Container, Graphics } from 'pixi.js'
import { useCallback } from 'react'

extend({ Container, Graphics })

const MyComponent = () => {
  const drawCallback = useCallback(graphics => {
    graphics.clear()
    graphics.setFillStyle({ color: 'red' })
    graphics.rect(0, 0, 100, 100)
    graphics.fill()
  }, [])

  return (
    <Application>
      <pixiContainer x={100} y={100}>
        <pixiGraphics draw={drawCallback} />
      </pixiContainer>
    </Application>
  )
}
```

Key facts: JSX intrinsics are lowercase `pixi`-prefixed (`<pixiSprite>`, `<pixiContainer>`, `<pixiGraphics>`); you must call `extend({ ... })` (or `useExtend`) to register each Pixi class you want as an element — this is what keeps the bundle tree-shakeable. `<Application>` accepts all `PIXI.ApplicationOptions` plus `defaultTextStyle`, `extensions`, and a `resizeTo` that takes an element **or a React ref**. Hooks: `useApplication()` → `{ app }`, `useTick(cbOrOptions)` where options are `{ callback, context, isEnabled, priority }`, and `useExtend()` (memoized; `extend()` is not).

**B. Manual mount** — a plain Pixi app created in `useEffect` on a `ref`'d div, with an imperative renderer class.

### Recommendation: **B, manual mount.** Use `@pixi/react` nowhere in this project.

Reasons, specific to this app:

1. **The replay is a 60fps imperative simulation, not a component tree.** Every frame you interpolate 100 positions, update 100 transforms, append trail segments, and redraw zone rings. In `@pixi/react` that is either (a) React state → reconciliation 60×/sec for ~300 nodes, or (b) `useTick` mutating refs — which means you've written imperative Pixi code anyway, just wrapped in JSX you now have to fight. You pay the abstraction and get none of it.
2. **`useTick`'s callback is not memoized.** The docs warn explicitly that a non-`useCallback`'d callback is removed and re-added to the ticker every frame. That is a footgun on the exact path that must never allocate.
3. **Maintenance velocity.** `pixi-react` `pushed_at` was 2026-01-16 (~6 months stale at time of writing), npm `8.0.5`, 43 open issues. `pixi.js` itself shipped 8.16 → 8.19 in that same window. You do not want your renderer gated on a wrapper's release cadence.
4. **Hard React 19 coupling.** peerDep `react >=19.0.0`. Fine today, but it's an extra constraint for zero gain.
5. **You still need imperative Pixi for the interesting parts** — `RenderTexture` trails, `cacheAsTexture`, render groups, culling, viewport math. None of those have a declarative expression.

`@pixi/react` is a good library for *scene-graph-as-UI* work (menus, HUDs, card games). This is a data-driven animation engine. Keep React for the shell (nav, tables, charts, timeline UI, inventory panel) and hand the canvas to an imperative class.

### The pattern to actually use

```tsx
// src/replay/ReplayCanvas.tsx
import { useEffect, useRef } from 'react'
import { ReplayRenderer } from './ReplayRenderer'
import type { ReplayData } from './types'

export function ReplayCanvas({
  data,
  timeMs,
  followAccountId,
}: {
  data: ReplayData
  timeMs: number
  followAccountId: string | null
}) {
  const hostRef = useRef<HTMLDivElement>(null)
  const rendererRef = useRef<ReplayRenderer | null>(null)

  // Mount / unmount. StrictMode-safe via the cancelled flag.
  useEffect(() => {
    const host = hostRef.current
    if (!host) return

    let cancelled = false
    const renderer = new ReplayRenderer()
    rendererRef.current = renderer

    void renderer.init(host).then(() => {
      if (cancelled) renderer.destroy()
    })

    return () => {
      cancelled = true
      rendererRef.current = null
      renderer.destroy()
    }
  }, [])

  // Push data in imperatively. No React state on the hot path.
  useEffect(() => {
    rendererRef.current?.setMatch(data)
  }, [data])

  useEffect(() => {
    rendererRef.current?.seek(timeMs)
  }, [timeMs])

  useEffect(() => {
    rendererRef.current?.setFollow(followAccountId)
  }, [followAccountId])

  return <div ref={hostRef} className="replay-canvas" />
}
```

```ts
// src/replay/ReplayRenderer.ts
import {
  Application, Container, Sprite, Texture, Graphics, BitmapText,
  Assets, extensions, CullerPlugin, Rectangle, Ticker, UPDATE_PRIORITY,
} from 'pixi.js'

extensions.add(CullerPlugin)

export class ReplayRenderer {
  private app: Application | null = null
  private world = new Container()          // pan/zoom target
  private mapLayer = new Container()
  private trailLayer = new Container()
  private zoneLayer = new Graphics()
  private dotLayer = new Container()
  private labelLayer = new Container()
  private destroyed = false

  // Preallocated scratch — never allocate inside tick().
  private readonly tmp = { x: 0, y: 0 }

  async init(host: HTMLElement) {
    const app = new Application()
    await app.init({
      resizeTo: host,
      background: 0x11150f,
      antialias: true,
      resolution: window.devicePixelRatio,
      autoDensity: true,
      preference: 'webgl',
      powerPreference: 'high-performance',
    })
    if (this.destroyed) { app.destroy(true); return }

    this.app = app
    host.appendChild(app.canvas)

    this.world.isRenderGroup = true          // v8: own GPU transform pass
    this.world.addChild(this.mapLayer, this.trailLayer, this.zoneLayer, this.dotLayer, this.labelLayer)
    app.stage.addChild(this.world)

    this.mapLayer.interactiveChildren = false
    this.trailLayer.interactiveChildren = false
    this.zoneLayer.interactiveChildren = false

    app.ticker.add(this.tick, this, UPDATE_PRIORITY.HIGH)
    this.attachViewportControls(app)
  }

  private tick = (ticker: Ticker) => { /* interpolate + write transforms */ }

  destroy() {
    this.destroyed = true
    this.app?.ticker.remove(this.tick, this)
    this.app?.destroy(
      { removeView: true },
      { children: true, texture: false, textureSource: false }, // keep shared atlases
    )
    this.app = null
  }

  setMatch(_d: unknown) {}
  seek(_ms: number) {}
  setFollow(_id: string | null) {}
  private attachViewportControls(_app: Application) {}
}
```

> **React 19 StrictMode double-invokes effects in dev.** Because `app.init()` is async, a naive mount leaks a whole WebGL context per remount and you will exhaust the browser's context limit (~16) after a few HMR cycles. The `cancelled` flag above is mandatory, not stylistic.

> **Texture ownership:** pass `texture: false, textureSource: false` to `app.destroy()` if your atlases are shared/cached through `Assets`; otherwise the next mount loads black sprites.

---

## 6. Pan/zoom viewport

### `pixi-viewport` status

`pixi-viewport@6.0.3`, peerDep `pixi.js >=8`. Release 6.0.0 (2024-11-17) is the pixi.js v8 port — the GitHub release body itself only reads "V6 by @danielbarion" plus fix bullets, so treat the "moves pixi-viewport to pixi.js v8+" phrasing as a paraphrase, not a quotation; the substantive point is supported by 6.0.1's "fix: update types to match pixi v8" and the `pixi.js: >=8` peerDep. 6.0.1 fixed wheel handling and PixiJS v8 type definitions; 6.0.3 fixed shipping global type declarations.

**Maintenance reality:** last npm publish **2024-11-27**; repo `pushed_at` **2025-02-03**; 144 open issues; not archived; 1,218 stars. That is ~17.5 months (since Feb 2025) without a commit while Pixi itself moved 8.6 → 8.19. It is not abandoned-and-broken, but it is unattended.

Usage (adapted — **the upstream README example is v7-era and does not run as written**):

```ts
// README as published (BROKEN under v8):
//   const app = new PIXI.Application();
//   document.body.appendChild(app.view);      // ❌ app.view -> app.canvas, and init() is missing

// Correct for pixi.js 8.x:
import { Application } from 'pixi.js'
import { Viewport } from 'pixi-viewport'

const app = new Application()
await app.init({ resizeTo: host, background: 0x11150f })
host.appendChild(app.canvas)

const viewport = new Viewport({
  screenWidth: app.screen.width,
  screenHeight: app.screen.height,
  worldWidth: WORLD_PX,
  worldHeight: WORLD_PX,
  events: app.renderer.events,   // v5+ breaking change: `interaction` was replaced by `events`
})

app.stage.addChild(viewport)
viewport
  .drag()
  .pinch()
  .wheel({ smooth: 3 })
  .decelerate()
  .clampZoom({ minScale: 0.3, maxScale: 12 })
  .clamp({ direction: 'all' })
```

### Recommendation: **hand-roll it.**

The plan needs: drag-pan, wheel-zoom-at-cursor, clamp, and a **follow-player camera** that smoothly re-centres. `pixi-viewport` gives you all of that plus 30 features you'll never use, at the cost of an unmaintained dependency sitting directly under your flagship feature. The hand-rolled version is ~80 lines and you own it.

Take `pixi-viewport` only if you later need pinch-to-zoom on tablets *and* the hand-rolled pointer handling proves fiddly — its touch handling is genuinely well-tested.

```ts
// src/replay/viewport.ts
import type { Application, Container, FederatedPointerEvent } from 'pixi.js'
import { Point } from 'pixi.js'

const MIN_SCALE = 0.25
const MAX_SCALE = 16

export function attachViewport(app: Application, world: Container, worldSize: number) {
  // Scratch objects — reused, never reallocated.
  const before = new Point()
  const after = new Point()
  const cursor = new Point()

  const clampScale = (s: number) => Math.min(MAX_SCALE, Math.max(MIN_SCALE, s))

  function clampPan() {
    const scaled = worldSize * world.scale.x
    const { width: sw, height: sh } = app.screen
    if (scaled <= sw) world.x = (sw - scaled) / 2
    else world.x = Math.min(0, Math.max(sw - scaled, world.x))
    if (scaled <= sh) world.y = (sh - scaled) / 2
    else world.y = Math.min(0, Math.max(sh - scaled, world.y))
  }

  /** Zoom by `factor`, keeping the world point under (sx, sy) fixed. */
  function zoomAt(sx: number, sy: number, factor: number) {
    cursor.set(sx, sy)
    world.toLocal(cursor, undefined, before)

    const next = clampScale(world.scale.x * factor)
    if (next === world.scale.x) return
    world.scale.set(next)

    world.toLocal(cursor, undefined, after)
    world.x += (after.x - before.x) * world.scale.x
    world.y += (after.y - before.y) * world.scale.y
    clampPan()
  }

  // --- wheel: native listener on the canvas, NOT a federated event ---
  const onWheel = (e: WheelEvent) => {
    e.preventDefault()
    const r = app.canvas.getBoundingClientRect()
    // deltaMode 1 = lines, 2 = pages; normalise to pixels-ish
    const unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 100 : 1
    zoomAt(e.clientX - r.left, e.clientY - r.top, Math.exp(-e.deltaY * unit * 0.0015))
  }
  app.canvas.addEventListener('wheel', onWheel, { passive: false })

  // --- drag: federated pointer events on the stage ---
  app.stage.eventMode = 'static'
  app.stage.hitArea = app.screen

  let dragging = false
  let lastX = 0
  let lastY = 0

  const onDown = (e: FederatedPointerEvent) => {
    dragging = true
    lastX = e.global.x
    lastY = e.global.y
  }
  const onMove = (e: FederatedPointerEvent) => {
    if (!dragging) return
    world.x += e.global.x - lastX
    world.y += e.global.y - lastY
    lastX = e.global.x
    lastY = e.global.y
    clampPan()
  }
  const onUp = () => { dragging = false }

  app.stage.on('pointerdown', onDown)
  app.stage.on('globalpointermove', onMove)
  app.stage.on('pointerup', onUp)
  app.stage.on('pointerupoutside', onUp)

  /** Smooth follow-cam: call from the ticker. */
  function centerOn(wx: number, wy: number, lerp = 0.15) {
    const tx = app.screen.width / 2 - wx * world.scale.x
    const ty = app.screen.height / 2 - wy * world.scale.y
    world.x += (tx - world.x) * lerp
    world.y += (ty - world.y) * lerp
    clampPan()
  }

  function destroy() {
    app.canvas.removeEventListener('wheel', onWheel)
    app.stage.off('pointerdown', onDown)
    app.stage.off('globalpointermove', onMove)
    app.stage.off('pointerup', onUp)
    app.stage.off('pointerupoutside', onUp)
  }

  return { zoomAt, centerOn, clampPan, destroy }
}
```

Why a **native** `wheel` listener rather than the federated `'wheel'` event: `wheel` *is* a supported federated event in v8, but you need `preventDefault()` with `{ passive: false }` to stop the page scrolling, and controlling passivity is far more direct on the DOM node. Use `globalpointermove` (not `pointermove`) for dragging so the drag survives the pointer leaving a child's hit area.

**`app.screen`** is a `Rectangle` reflecting the *current* renderer size — with `resizeTo` it updates automatically, which is why `hitArea = app.screen` keeps working after resize.

---

## 7. Data fetching — TanStack Query v5

**Current: `@tanstack/react-query@5.101.4`.** There is no v6; the `beta`/`rc`/`alpha` dist-tags are stale 5.0.0 pre-releases. peerDep `react: ^18 || ^19`.

### v4 → v5 changes you must not write the old way

| v4 | v5 |
|---|---|
| `useQuery(key, fn, options)` | `useQuery({ queryKey, queryFn, ...options })` — **object only** |
| `useMutation(fn, options)` | `useMutation({ mutationFn, ...options })` |
| `cacheTime` | `gcTime` |
| `status: 'loading'` | `status: 'pending'` |
| `isLoading` | `isPending` (`isLoading` now means `isPending && isFetching`) |
| `isInitialLoading` | `isLoading` |
| `useErrorBoundary` | `throwOnError` |
| `keepPreviousData: true` | `placeholderData: keepPreviousData` (import the sentinel) |
| `onSuccess`/`onError`/`onSettled` on `useQuery` | **Removed from queries.** Still available on mutations. |

Minimum: TypeScript 4.7+, React 18+.

### Setup

```tsx
// src/main.tsx
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Match history is append-only and the poller runs every 5-10 min.
      staleTime: 60_000,
      gcTime: 10 * 60_000,
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
)
```

```ts
// src/api/queries.ts
import { useQuery, keepPreviousData } from '@tanstack/react-query'

const API = import.meta.env.VITE_API_BASE ?? '/api'

async function json<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`${API}${path}`, { signal })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} on ${path}`)
  return res.json() as Promise<T>
}

export function useMatchHistory(accountId: string, page: number) {
  return useQuery({
    queryKey: ['matches', accountId, page] as const,
    queryFn: ({ signal }) => json<MatchRow[]>(`/players/${accountId}/matches?page=${page}`, signal),
    placeholderData: keepPreviousData,   // no flash between pages
  })
}

export function useReplay(matchId: string) {
  return useQuery({
    queryKey: ['replay', matchId] as const,
    queryFn: ({ signal }) => json<ReplayData>(`/matches/${matchId}/replay`, signal),
    staleTime: Infinity,   // processed replays are immutable once generated
    gcTime: 30 * 60_000,   // a few hundred KB; keep it around while the user scrubs
  })
}
```

Notes for this app:
- Processed replay payloads are immutable → `staleTime: Infinity`. Never refetch mid-scrub.
- If the backend serves MessagePack (plan §7), do `await res.arrayBuffer()` in `queryFn` and decode there; keep the decoded object in the cache, not the bytes.
- Use `queryClient.prefetchQuery(['replay', id])` when the user hovers a "Watch Replay" button — the download is the long pole.

---

## 8. Performance playbook — 100 moving sprites + labels + trails at 60fps

### The verdict up front

100 sprites is **nothing** for Pixi v8. The reference `bunnymark` runs tens of thousands. Your risk is not sprite count — it is (a) per-frame allocations, (b) 100 `Text` objects re-rasterizing, (c) trails implemented as growing `Graphics`, and (d) React re-rendering the tree at 60Hz. Address those four and you're done.

### `ParticleContainer` vs `Container` → **use `Container`**

`ParticleContainer` is for "hundreds of thousands or even millions of particles". It costs you `addChild`, `removeChild`, `getChildAt`, `setChildIndex`, `swapChildren`, `reparentChild`, children of children, per-object interactivity, and per-object filters. Your 100 dots need: click-to-select (interaction), a child health ring, a child label, and z-ordering (tracked player on top). `ParticleContainer` forbids all of that.

Use a plain `Container` with `isRenderGroup = true`. If you later add a genuine particle effect (muzzle flashes, blood splatter on kills, 1000s of instances), that is what `ParticleContainer` is for.

### The eight rules

**1. One texture atlas, zero texture swaps.**
Pixi batches sprites; the batch breaks on texture change and on blend-mode change. Sprites can batch across ~16 textures depending on hardware. Put every dot, marker, vehicle icon, care-package icon and arrow into a **single** atlas so all 100+ dots are one draw call. Tint per team rather than shipping 25 coloured dot PNGs:

```ts
dot.texture = atlas.textures['player-dot.png']
// character.teamId is an integer on the telemetry Character object.
// Solo modes can have up to 100 teams, so size/modulo explicitly.
dot.tint = TEAM_PALETTE[character.teamId % TEAM_PALETTE.length]
```

Group same-blend-mode objects adjacently — mixing `'add'` (kill flashes) into the dot layer will shred your batching. Keep additive effects in their own layer above the dots.

**2. Preallocate everything. Zero allocations in `tick()`.**
The garbage from 100 objects × 60fps is what produces stutter, not the draw calls.

```ts
// ❌ allocates 6000 objects/sec
world.toLocal({ x, y })
const pos = { x: lerp(a.x, b.x, t), y: lerp(a.y, b.y, t) }
positions.map(p => ...)

// ✅
world.toLocal(scratchIn, undefined, scratchOut)
dot.position.set(ax + (bx - ax) * t, ay + (by - ay) * t)
for (let i = 0; i < n; i++) { ... }   // indexed loop, no closures
```

Store the frame index as **flat `Float32Array`s** (`tArr`, `xArr`, `yArr`, `healthArr`) with a per-player offset table, not arrays of objects. Cache the last sample index per player and advance it forward — for monotonic playback that's O(1) per player per frame instead of a binary search.

**3. Sprite pool sized to 100. Never create/destroy per frame.**
Reuse the same 100 `Sprite`s for the whole match; toggle `.visible` for dead players. Do the same for labels and health rings.

**4. Labels: `BitmapText`, and only render what's readable.**
100 `Text` objects means 100 canvas rasterizations; changing any text re-rasterizes. `BitmapText` is explicitly documented for "thousands of changing labels". Better still: **only show labels above a zoom threshold or on hover**, which the plan already specifies ("name labels on hover/zoom"). Below that threshold set `labelLayer.visible = false` — one flag, 100 objects skipped.

**5. Trails: one `RenderTexture`, not growing `Graphics`.**
Rebuilding a `Graphics` with 100 players × 30 seconds of history every frame is the single most likely way to blow your frame budget. Instead:

```ts
const trailRT = RenderTexture.create({ width: 2048, height: 2048, antialias: false })
const trailSprite = new Sprite(trailRT)
trailSprite.alpha = 0.7
trailLayer.addChild(trailSprite)

// Each frame: draw only the NEW segment, never clear.
segments.clear()
for (let i = 0; i < n; i++) {
  segments.moveTo(prevX[i], prevY[i]).lineTo(curX[i], curY[i])
       .stroke({ width: 2, color: teamColor[i], alpha: 0.6 })
}
app.renderer.render({ container: segments, target: trailRT, clear: false })
```

To make trails fade, render a full-screen translucent black quad into the same RT every N frames (`clear: false`, blend `'normal'`, alpha ~0.04). On **seek**, clear the RT and replay the last 30s of segments in one pass.

⚠️ Trails must live in **world space** inside the RT, which means the RT resolution fixes your maximum trail sharpness at high zoom. 2048² over an 8km map = ~4m/texel; acceptable for trails, not for anything crisp. If that bothers you, keep the trail as a `Graphics` rebuilt only on seek and per-second (not per-frame) instead.

**6. Static layers: `cacheAsTexture()` and render groups.**
The map background, the grid, and the death-marker layer never change between seeks:

```ts
gridLayer.cacheAsTexture(true)   // v8 replacement for cacheAsBitmap
// invalidate on rebuild:
gridLayer.cacheAsTexture(false)
```

Mark `world.isRenderGroup = true` so pan/zoom is a single GPU transform update rather than 300 world-matrix recomputations.

**7. Culling once you're zoomed in.**
Register `CullerPlugin` (§4.10) and give every dot a fixed `cullArea` so Pixi doesn't compute bounds. At 8× zoom this drops ~90% of the scene.

**8. Keep React out of the loop entirely.**
Zero `setState` at 60Hz. The playhead lives in a `ref` inside `ReplayRenderer`. React learns about it only when something *user-visible in DOM* must change — kill-feed entries, inventory panel, the clock — and even then throttle to ~10Hz via a `useSyncExternalStore` subscription or a plain interval, not per frame.

Additional documented tips: `interactiveChildren = false` on non-interactive containers; explicit `hitArea`; masks cost ordering is rectangle (scissor) < graphics (stencil) < sprite (filter); `container.filters = null` frees filter memory; set `filterArea` where known; on low-end devices `antialias: false` and half-resolution `@0.5x` textures.

### Frame budget sanity check (16.6ms @ 60fps)

| Work | Realistic cost |
|---|---|
| Interpolate 100 players from Float32Arrays | < 0.1 ms |
| Write 100 sprite transforms | < 0.2 ms |
| Rebuild 3 zone circles in one `Graphics` | ~0.1 ms |
| Trail segment pass into RenderTexture | ~0.3 ms |
| Draw: ~4 batches (map, trails, dots, labels) | ~1–2 ms GPU |

You have an order of magnitude of headroom. Spend it on visual quality, not on defending against sprite count.

---

## 9. Rendering the heatmap

### Recommendation: **offscreen Canvas 2D + manual separable blur + LUT colorization → `Sprite` in Pixi.** Not a Pixi filter.

### Why not a Pixi filter/shader

1. **Dual-shader tax.** A custom v8 `Filter` needs `glProgram` (GLSL) *and* `gpuProgram` (WGSL) to work under both renderers. That's two shaders to write, debug and keep in sync for a static overlay image.
2. **It's a static image.** The heatmap doesn't animate. The plan's server already precomputes `heatmap_bins(map_name, kind, account_id, grid_x, grid_y, count)` — a 256×256 grid. Colorizing 65,536 cells on the CPU is a sub-5ms one-off. GPU acceleration buys nothing when you rebuild once per filter change.
3. **Filters composite through the whole render pipeline** and need `filterArea` management; a plain `Sprite` with a `CanvasSource` texture is just another batched quad.

### Why not `ctx.filter = 'blur(Npx)'`

⚠️ **`CanvasRenderingContext2D.filter` is not Baseline.** MDN: *"This feature is not Baseline because it does not work in some of the most widely-used browsers."* Per caniuse (~80.5% global): Chrome 52+ ✅, Firefox 49+ ✅, Edge 79+ ✅ — but **Safari desktop 18.0–26.5: "Disabled by default"**, Safari desktop 3.1–17.6: **"Not supported"**; Safari on iOS mirrors it — **3.2–17.7: "Not supported"**, **18.0–26.5: "Disabled by default"**. Do not build the heatmap on it. Roll the blur yourself — on a 256×256 grid it's trivially fast.

### Implementation

```ts
// src/heatmap/renderHeatmap.ts

/** Perceptually-ordered ramp. Build once into a 256-entry LUT. */
const RAMP: Array<[number, [number, number, number]]> = [
  [0.00, [  0,   0,   0]],
  [0.25, [ 20,  60, 140]],
  [0.50, [ 30, 160, 120]],
  [0.75, [230, 190,  60]],
  [1.00, [220,  60,  40]],
]

function buildLut(): Uint8ClampedArray {
  const lut = new Uint8ClampedArray(256 * 4)
  for (let i = 0; i < 256; i++) {
    const t = i / 255
    let k = 0
    while (k < RAMP.length - 2 && t > RAMP[k + 1][0]) k++
    const [t0, c0] = RAMP[k]
    const [t1, c1] = RAMP[k + 1]
    const f = (t - t0) / (t1 - t0 || 1)
    lut[i * 4 + 0] = c0[0] + (c1[0] - c0[0]) * f
    lut[i * 4 + 1] = c0[1] + (c1[1] - c0[1]) * f
    lut[i * 4 + 2] = c0[2] + (c1[2] - c0[2]) * f
    // Alpha ramps in fast then plateaus so sparse cells stay legible over the map.
    lut[i * 4 + 3] = Math.min(255, Math.round(255 * Math.pow(t, 0.6)))
  }
  return lut
}
const LUT = buildLut()

/** Three box-blur passes ≈ a true gaussian (central limit theorem). Separable, O(n). */
function boxBlurPass(src: Float32Array, dst: Float32Array, w: number, h: number, r: number, horizontal: boolean) {
  const inv = 1 / (r + r + 1)
  const outer = horizontal ? h : w
  const inner = horizontal ? w : h
  const stepIn = horizontal ? 1 : w
  const stepOut = horizontal ? w : 1

  for (let o = 0; o < outer; o++) {
    const base = o * stepOut
    let acc = 0
    for (let i = -r; i <= r; i++) {
      acc += src[base + Math.min(inner - 1, Math.max(0, i)) * stepIn]
    }
    for (let i = 0; i < inner; i++) {
      dst[base + i * stepIn] = acc * inv
      const add = Math.min(inner - 1, i + r + 1)
      const sub = Math.max(0, i - r)
      acc += src[base + add * stepIn] - src[base + sub * stepIn]
    }
  }
}

export function renderHeatmapCanvas(
  bins: Float32Array,   // length N*N, raw counts straight from the API
  n: number,            // grid size, e.g. 256
  blurRadius = 3,
): HTMLCanvasElement {
  const a = Float32Array.from(bins)
  const b = new Float32Array(n * n)

  for (let pass = 0; pass < 3; pass++) {
    boxBlurPass(a, b, n, n, blurRadius, true)
    boxBlurPass(b, a, n, n, blurRadius, false)
  }

  // Normalize. sqrt compresses the long tail so hot-drop zones don't flatten everything else.
  let max = 0
  for (let i = 0; i < a.length; i++) if (a[i] > max) max = a[i]
  const norm = max > 0 ? 1 / Math.sqrt(max) : 0

  const canvas = document.createElement('canvas')
  canvas.width = n
  canvas.height = n
  const ctx = canvas.getContext('2d')!
  const img = ctx.createImageData(n, n)

  for (let i = 0; i < a.length; i++) {
    const v = Math.min(255, Math.round(Math.sqrt(a[i]) * norm * 255))
    const o = v * 4
    const p = i * 4
    img.data[p + 0] = LUT[o + 0]
    img.data[p + 1] = LUT[o + 1]
    img.data[p + 2] = LUT[o + 2]
    img.data[p + 3] = LUT[o + 3]
  }
  ctx.putImageData(img, 0, 0)
  return canvas
}
```

Mount it in Pixi as a normal sprite over the map:

```ts
import { Sprite, Texture } from 'pixi.js'

const canvas = renderHeatmapCanvas(bins, 256, 3)
const heatSprite = new Sprite(Texture.from(canvas))
heatSprite.width = WORLD_PX
heatSprite.height = WORLD_PX
heatSprite.blendMode = 'add'     // ⚠️ 'screen' or 'normal' may read better; test on the dark map
world.addChild(heatSprite)

// When filters change, re-render the canvas and refresh the GPU copy:
function updateHeatmap(newBins: Float32Array) {
  const c = renderHeatmapCanvas(newBins, 256, 3)
  const ctx = (heatSprite.texture.source as any).resource as HTMLCanvasElement
  ctx.getContext('2d')!.drawImage(c, 0, 0)
  heatSprite.texture.source.update()
}
```

Simpler and safer than mutating in place: build a fresh `Texture.from(canvas)`, assign `heatSprite.texture = newTex`, and `destroy()` the old one. Do that unless profiling says otherwise.

**If you instead render raw client-side points** (e.g. the user filters to "kills with an AWM in the last 7 days" and the server returns raw coordinates rather than bins): use the `simpleheat`/`heatmap.js` technique — draw a radial-gradient stamp per point with `globalAlpha` proportional to weight, accumulating into the alpha channel, then colorize through the same LUT. No blur pass needed; the gradient stamp *is* the kernel. Defaults from `simpleheat` (verbatim from `simpleheat.js`): `defaultRadius: 25`, blur `15`, and `defaultGradient = {0.4: 'blue', 0.6: 'cyan', 0.7: 'lime', 0.8: 'yellow', 1.0: 'red'}` — five stops, not three.

**Coordinate mapping (from plan §6):** telemetry positions are centimetres. `px = x / world_size_cm * image_px`. Do **not** derive the world size from the map's advertised km size — use the official per-map ranges from the telemetry docs (Location object): X/Y run `0 – 816,000` for Erangel, Miramar, Taego, **Vikendi** and Deston; `0 – 408,000` Sanhok; `0 – 306,000` Paramo; `0 – 204,000` Karakin and Range; `0 – 102,000` Haven. (Vikendi is not an 8×8 km map yet still uses 816,000, which is why the km-based rule of thumb is wrong.) Get the per-map world size from the backend rather than hardcoding — this is exactly the kind of thing that silently produces a heatmap squashed into one corner.

---

## 10. Charts — Recharts

**Current: `recharts@3.10.0`.** v2 and older are explicitly no longer receiving updates.

**Verdict: yes, Recharts is still the right pick** for what the plan describes (damage/kills over time, placement distribution, survival-time histogram, recent-form sparkline). Reasons: React-native component model (composition, not config objects), SVG output so it inherits your CSS/theme tokens and stays crisp, ~150 kB, and the largest React-chart community by a wide margin.

Where it would be wrong — and none of these apply here:

| Alternative | When it beats Recharts |
|---|---|
| Chart.js / `react-chartjs-2` | Canvas rendering, 10k–100k points. Your charts are ≤ 200 points. |
| ECharts | Very large datasets, exotic chart types. Client-only, heavy. |
| Nivo | Best-in-class defaults + WCAG 2.1 AA out of the box, but 500 kB+ full install and its look fights the plan's "no generic dashboard template" rule. |
| visx | ~15 kB of low-level D3 primitives for fully bespoke marks. Steeper curve. **Worth considering for the §8 "match strip" timeline** — that is a bespoke mark, not a chart. |

Practical note: the plan's **signature "match strip"** (zone-phase shading + kill tick marks + alive/dead span) should be **hand-written SVG or a small Pixi/canvas strip**, not Recharts. It is a custom mark with click-to-seek interaction; forcing it into a composed chart will cost more than writing 60 lines of SVG.

### peerDependencies gotcha

```json
{
  "react": "^16.8.0 || ^17.0.0 || ^18.0.0 || ^19.0.0",
  "react-dom": "^16.0.0 || ^17.0.0 || ^18.0.0 || ^19.0.0",
  "react-is": "^16.8.0 || ^17.0.0 || ^18.0.0 || ^19.0.0"
}
```

⚠️ **`react-is` is a peer dependency.** With strict peer resolution (pnpm, or npm with `--strict-peer-deps`) you must install it explicitly or the build fails with a confusing missing-module error.

### v2 → v3 breaking changes (in case you copy old code)

- Whole state management rewritten; the `CategoricalChartState` previously threaded through several APIs no longer exists.
- `recharts-scale` removed — `getNiceTickValues` is now exported from `recharts` itself.
- `react-smooth` removed — animations are in-tree.
- **SVG has no z-index**: element stacking is purely render order. If your Tooltip renders under a Line, move it later in the JSX.
- `XAxis`/`YAxis` axis lines now render even with no ticks.

### Sketch

```tsx
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis,
  CartesianGrid, Tooltip, ReferenceLine,
} from 'recharts'

export function DamageOverTime({ data }: { data: { playedAt: string; damage: number }[] }) {
  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
        <CartesianGrid stroke="var(--surface-3)" strokeDasharray="2 4" vertical={false} />
        <XAxis dataKey="playedAt" tick={{ fill: 'var(--text-2)', fontSize: 11 }} tickLine={false} />
        <YAxis tick={{ fill: 'var(--text-2)', fontSize: 11 }} tickLine={false} width={44} />
        <ReferenceLine y={0} stroke="var(--surface-3)" />
        <Tooltip
          contentStyle={{ background: 'var(--surface-1)', border: '1px solid var(--surface-3)', borderRadius: 4 }}
          cursor={{ stroke: 'var(--accent)', strokeWidth: 1 }}
        />
        {/* isAnimationActive={false} respects the plan's motion budget */}
        <Line type="monotone" dataKey="damage" stroke="var(--accent)" strokeWidth={2} dot={false} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  )
}
```

Set `isAnimationActive={false}` globally — the plan's motion budget bans scattered micro-animations, and it also removes a class of `ResponsiveContainer` resize jank.

---

## 11. Dense tables — TanStack Table v8

**Current: `@tanstack/react-table@8.21.3`.** v9 exists only as `9.0.0-beta.55`; ship on v8. peerDeps `react >= 16.8`.

TanStack Table is headless — it computes sorting/filtering/pagination state and gives you row/cell models; **you render the `<table>` yourself**. That is exactly right for the plan's "real tables with tight row heights, right-aligned numerals, and column sorting — not grids of padded stat cards."

```tsx
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getFilteredRowModel,
  flexRender,
  createColumnHelper,
  type SortingState,
  type ColumnFiltersState,
} from '@tanstack/react-table'
import { useMemo, useState } from 'react'

type MatchRow = {
  matchId: string
  playedAt: string
  mapName: string
  gameMode: string
  winPlace: number
  kills: number
  damageDealt: number
  timeSurvived: number
}

const col = createColumnHelper<MatchRow>()

export function MatchHistoryTable({ rows }: { rows: MatchRow[] }) {
  const [sorting, setSorting] = useState<SortingState>([{ id: 'playedAt', desc: true }])
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([])

  // MUST be stable: a new array identity every render resets internal table state.
  const columns = useMemo(() => [
    col.accessor('playedAt', {
      header: 'When',
      cell: c => new Date(c.getValue()).toLocaleString(),
    }),
    col.accessor('mapName',  { header: 'Map',  filterFn: 'equalsString' }),
    col.accessor('gameMode', { header: 'Mode', filterFn: 'equalsString' }),
    col.accessor('winPlace', {
      header: '#',
      meta: { align: 'right' },
      cell: c => `#${c.getValue()}`,
    }),
    col.accessor('kills',       { header: 'K',   meta: { align: 'right' } }),
    col.accessor('damageDealt', { header: 'DMG', meta: { align: 'right' }, cell: c => Math.round(c.getValue()) }),
    col.accessor('timeSurvived', {
      header: 'Survived',
      meta: { align: 'right' },
      cell: c => {
        const s = Math.round(c.getValue())
        return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
      },
    }),
  ], [])

  const table = useReactTable({
    data: rows,
    columns,
    state: { sorting, columnFilters },
    onSortingChange: setSorting,
    onColumnFiltersChange: setColumnFilters,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
  })

  return (
    <table className="stat-table">
      <thead>
        {table.getHeaderGroups().map(hg => (
          <tr key={hg.id}>
            {hg.headers.map(h => (
              <th
                key={h.id}
                onClick={h.column.getToggleSortingHandler()}
                aria-sort={
                  h.column.getIsSorted() === 'asc' ? 'ascending'
                  : h.column.getIsSorted() === 'desc' ? 'descending'
                  : 'none'
                }
                data-align={(h.column.columnDef.meta as any)?.align}
              >
                {h.isPlaceholder ? null : flexRender(h.column.columnDef.header, h.getContext())}
                {{ asc: ' ▲', desc: ' ▼' }[h.column.getIsSorted() as string] ?? null}
              </th>
            ))}
          </tr>
        ))}
      </thead>
      <tbody>
        {table.getRowModel().rows.map(row => (
          <tr key={row.id}>
            {row.getVisibleCells().map(cell => (
              <td key={cell.id} data-align={(cell.column.columnDef.meta as any)?.align}>
                {flexRender(cell.column.columnDef.cell, cell.getContext())}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  )
}
```

```css
.stat-table { font-variant-numeric: tabular-nums; border-collapse: collapse; width: 100%; }
.stat-table td, .stat-table th { padding: 4px 8px; border-bottom: 1px solid var(--surface-3); }
.stat-table [data-align='right'] { text-align: right; }
.stat-table th { cursor: pointer; user-select: none; text-transform: uppercase; letter-spacing: .06em; font-size: 11px; }
```

`font-variant-numeric: tabular-nums` is what the plan means by "tabular figures"; it is one CSS line and it is non-negotiable for stat columns.

Typing `columnDef.meta` properly (instead of the `as any` above):

```ts
declare module '@tanstack/react-table' {
  interface ColumnMeta<TData extends RowData, TValue> {
    align?: 'left' | 'right'
  }
}
```

**Virtualization:** a match page has ~100 rows — no virtualization needed. A player's full history (thousands of rows over months) does. Use `@tanstack/react-virtual@3.14.8` (`useVirtualizer`) over `table.getRowModel().rows`. Do **not** reach for an all-in-one data grid; the plan's density requirements are easier to hit with your own `<table>` markup.

---

## 12. Implementation notes — gotchas that will silently break things

### PixiJS

1. **`await app.init()` is mandatory.** `new Application({...})` compiles (options are ignored) and then everything is `undefined`. There is no runtime error telling you what you did wrong.
2. **`build.target: 'esnext'`.** pixijs#10456 ("Can't `await` `Application.init` from top level if bundled using vite", closed 2024-05-11) was the RC-era version of this. The general rule stands: top-level `await` needs ES2022+ output. Vite's dev server uses `esnext` regardless, so **this bug only appears in `vite build` / `vite preview`, never in `vite dev`.** Set `build.target: 'esnext'` on day one or you will ship a white screen. Better: don't use top-level await at all — do the init inside your renderer class (as in §5), which sidesteps it entirely.
3. **StrictMode + async init leaks WebGL contexts.** React 19 dev double-invokes effects. Without the `cancelled` guard you create two `Application`s per mount; after ~8 HMR cycles the browser refuses new contexts and the canvas goes black with no error. Symptom: "works, then stops working after editing a file."
4. **`Texture.from()` no longer loads.** It resolves from the cache. If you call it before `Assets.load()`, you get a white/empty texture, silently. Always `await Assets.load(...)` first.
5. **`getBounds()` returns `Bounds`, not `Rectangle`.** `.x/.y/.width/.height` reads may appear to work while producing wrong numbers. Use `.rectangle`.
6. **`container.name` is gone → `label`.** Assigning `.name` on a v8 Container is not a TS error in loose configs — it just creates an unused property, and `getChildByLabel` finds nothing.
7. **`lineStyle()` does not exist.** Confirmed against `GraphicsContext.ts` source. An official docs example still shows it — the docs are wrong there.
8. **Fill/stroke come *after* the shape.** `g.fill(0xff0000).rect(...)` produces nothing and throws no error.
9. **Ticker callback receives a `Ticker`, not a number.** `ticker.add(dt => x += dt)` silently makes `x` `[object Object]…` / `NaN`.
10. **`ParticleContainer.addChild()` throws / no-ops** — use `addParticle(new Particle({...}))`.
11. **Static particle properties need `container.update()`.** Mutating `rotation` on a container configured with `dynamicProperties.rotation === false` does nothing until you call it.
12. **`resolution` + `autoDensity`.** Without `autoDensity: true`, a `resolution: 2` canvas renders at double CSS size. With `resizeTo`, the renderer resizes but `app.screen` is in *logical* pixels — always do viewport math in `app.screen` units, never `canvas.width`.
13. **Blend-mode and texture changes break sprite batching.** Keep additive effects in a dedicated layer.
14. **`visible` vs `renderable`:** `visible = false` removes the object from bounds calculations too, which will move your `getBounds()`-derived camera. Use `renderable = false` if you need the bounds preserved.
15. **`app.destroy()` texture flags.** `{ texture: true }` destroys textures your *next* mount still expects from the `Assets` cache. For HMR-heavy dev, keep them.

### Vite / TS / build

16. **`typescript@7` breaks `typescript-eslint`.** Pin `~6.0.2`. Prefer **oxlint** (what `create-vite` now ships) which has no TS-API dependency.
17. **`@vitejs/plugin-react@6` removed the inline `babel` option.** Any tutorial doing `react({ babel: { plugins: [...] } })` is pre-v6 and will silently drop your Babel plugins.
18. **Proxy target must be `127.0.0.1`, not `localhost`.** On Windows, `localhost` may resolve to `::1` while uvicorn binds IPv4 only → `ECONNREFUSED` that looks like a backend crash.
19. **Proxied requests bypass Vite's transform pipeline** — don't expect `import.meta.env` substitution or anything else on those responses.
20. **`import.meta.env` only exposes `VITE_`-prefixed vars.** No PUBG API key in the frontend, ever.
21. **Vite needs Node `^20.19.0 || >=22.12.0`.** Node 21 is excluded.
22. **Static assets:** files under `public/` are served at `/` verbatim and are **not** hashed or processed. Map images (large PNGs from `pubg/api-assets`) should be served by the backend (`/static/...`), not bundled — a full-res Erangel PNG in `public/` bloats your deploy and can't be cached independently.

### Casing / naming traps specific to this project

23. **PUBG telemetry field casing is inconsistent** (documented risk in plan §10). Normalize at the **backend** boundary and let the frontend see one consistent camelCase shape. Do not spread raw telemetry objects into TS interfaces — the compiler cannot protect you from `winPlace` vs `WinPlace`.
24. **Team colours: index by `character.teamId`, never by array position.** `teamId` is an integer on the telemetry `Character` object (alongside `name`, `health`, `location`, `ranking`, `accountId`, `isInBlueZone`, `isInRedZone`, `zone`). There is no `rosterId` field in telemetry; the Match API's Roster `id` is a **UUID string** and cannot index a palette. Roster order in a payload is not stable across requests. Size the palette for the mode — 25 covers squads, but solo has up to 100 teams — and modulo explicitly.
25. **Telemetry coordinates are centimetres and Y grows *downward***. PUBG documents this verbatim: *"(0,0) is at the top-left of each map."* That is uniform across all maps and matches canvas/Pixi convention. (Source: documentation.pubg.com/en/telemetry-objects.html, Location object.)

### React

26. **Never put the replay playhead in React state.** 60 `setState`/sec re-renders the whole page tree.
27. **`useTick` (if you ever use `@pixi/react`) is not memoized** — pass a `useCallback`'d function or it detaches/reattaches every frame.
28. **TanStack Table `columns` must be `useMemo`'d.** A fresh array identity each render resets sorting/filter state on every keystroke — the classic "my sort keeps clearing itself" bug.
29. **`react-is` must be installed** alongside Recharts under strict peer resolution.

---

## 13. ⚠️ Unverified / needs live confirmation

Everything below was asserted in this document but could **not** be confirmed against an authoritative fetched source in this pass. Verify before relying on it.

1. **`app.destroy()` second-argument option key names** (`children` / `texture` / `textureSource`). Consistent with v8 docs prose but not read from a signature.
2. **Whether `pixi-viewport@6.0.3` has any behavioural break against `pixi.js@8.19.0` specifically.** It declares `pixi.js >=8` and was published against ~8.6. ~17.5 months of Pixi releases have not been regression-tested against it by its maintainer. §6 recommends hand-rolling partly for this reason.
3. **Recharts `contentStyle` / `cursor` prop shapes in v3.10** — carried over from v2 knowledge; the v3 migration guide was read via search summary, not fetched directly.
4. **The claim that `Cell` should migrate to a `shape` prop in Recharts v3** (previously listed in §10). The 3.0 migration guide does not mention `Cell` at all, so the bullet was removed from §10. Confirmation would mean finding it in a Recharts release note or the v3 `Cell` API docs; until then, assume `Cell` is unchanged.
5. **TanStack Table v8 exact example code** — the `table-state` docs page did not contain a single unified example; the §11 snippet is assembled from the documented v8 API surface (`useReactTable`, `getCoreRowModel`, `getSortedRowModel`, `getFilteredRowModel`, `flexRender`, `createColumnHelper`) rather than reproduced verbatim.
6. **`UPDATE_PRIORITY` numeric values** are confirmed from `src/ticker/const.ts` on the `dev` branch, which may be ahead of the 8.19.0 tag. Values have been stable since v5.
7. **Safari's `ctx.filter` status** is from caniuse. Not cross-checked against a WebKit release note. The §9 recommendation avoids the feature entirely, so this does not affect the design.
8. **Per-map world sizes and coordinate origin at runtime.** The ranges and "(0,0) is top-left" in §9/§12 come from the official telemetry docs; still worth spot-checking against a real telemetry file once the API key is wired up, since a wrong world size or flipped Y produces a *plausible looking* and completely wrong heatmap.

**Confirmed since the first pass (previously listed here, now verified — do not write defensive workarounds for these):** `Spritesheet.textures: Record<keyof S['frames'], Texture>` and `animations: Record<…, Texture[]>` (src/spritesheet/Spritesheet.ts); `CanvasSource extends TextureSource<ICanvas>` so `.resource` is real and typed `ICanvas`; `RenderTextureOptions extends TextureSourceOptions` which declares `antialias?: boolean` and `create()` spreads `...rest` into `new TextureSource(rest)`, so top-level `antialias` works; `BitmapFont.install`'s `chars` is documented as an "array of character ranges"; the Container guide shows `container.cacheAsTexture(false)` verbatim; `toLocal<P extends PointData = Point>(position: PointData, from?: Container, point?: P, skipUpdate?: boolean): P` (toLocalGlobalMixin.ts); and the June 2026 blog confirms `app.domContainerRoot`, the `pixi.js/html-source` subpath, `graphicsContextToSvg`, `setMask` channel ('red' default / 'alpha'), `RenderTexture.create` `textureOptions`, `generateTexture` `defaultAnchor`, and `ParticleContainer` inheriting ancestor blend modes. The `@types/*` versions in §3.1 are now taken from create-vite's template.
