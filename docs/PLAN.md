# PUBG Dashboard — Project Plan

A self-hosted dashboard for tracking PUBG players: full match history and stats, kill/position heatmaps, and full top-down match replay driven by telemetry data.

---

## 1. Goals

- Add/remove tracked players by name (per shard/platform)
- Persist every match a tracked player appears in (the API only retains ~14 days, so we archive continuously)
- Full stats: per-match, per-season, ranked, lifetime, weapon mastery
- Heatmaps: kills, deaths, landings, movement density — per player and aggregate
- Match replay: top-down map view with scrubber/timeline, showing all 100 players, kills, zone circles, care packages, and vehicles

## 2. Architecture Overview

```
┌─────────────┐     ┌──────────────────┐     ┌──────────────┐
│ PUBG API     │────▶│ Ingestion Worker │────▶│ PostgreSQL   │
│ (REST + CDN  │     │ (poller + rate   │     │ + object     │
│  telemetry)  │     │  limiter)        │     │ storage      │
└─────────────┘     └──────────────────┘     └──────┬───────┘
                                                    │
                                             ┌──────▼───────┐
                                             │ API Backend  │
                                             │ (REST + WS)  │
                                             └──────┬───────┘
                                                    │
                                             ┌──────▼───────┐
                                             │ Web Frontend │
                                             │ (SPA, canvas │
                                             │  /WebGL map) │
                                             └──────────────┘
```

### Components

| Component | Purpose | Suggested tech |
|---|---|---|
| Ingestion worker | Polls PUBG API for tracked players, fetches new matches + telemetry | Rust (tokio + reqwest + serde) or Python (httpx + asyncio) |
| Database | Players, matches, participant stats, derived aggregates | PostgreSQL |
| Object storage | Raw telemetry JSON (gzipped, ~2–10 MB/match) | Filesystem or MinIO/S3 |
| Backend API | Serves the frontend: stats queries, heatmap data, replay frames | Same language as worker; Axum (Rust) or FastAPI (Python) |
| Frontend | Dashboard UI, charts, heatmap overlay, replay renderer | React/Svelte + Canvas or PixiJS (WebGL) |

Everything containerized; runs comfortably as a single VM/LXC on Proxmox.

## 3. PUBG API Integration

### Key facts
- Base: `https://api.pubg.com/shards/{shard}/...` with `Authorization: Bearer {key}`, `Accept: application/vnd.api+json`
- Sharded by platform: `steam`, `xbox`, `psn`, `kakao`, `stadia`
- Rate limit: 10 req/min default (can request more). **Telemetry CDN URLs are unauthenticated and do not count against the limit.**
- Match retention: ~14 days — the poller must run continuously to build history
- JSON:API format (`data` / `included` / `relationships`)

### Endpoints used
| Endpoint | Use |
|---|---|
| `GET /players?filter[playerNames]=` | Resolve names → account IDs; recent match IDs (batch up to 10 names/req) |
| `GET /matches/{id}` | Match metadata + all 100 participants' stats + telemetry asset URL (this endpoint is NOT rate limited) |
| `GET /seasons`, `/players/{id}/seasons/{seasonId}` | Season + ranked stats |
| `GET /players/{id}/seasons/lifetime` | Lifetime stats |
| Weapon mastery / survival mastery | Per-player mastery data |
| Telemetry asset URL (CDN) | Full event stream for replay + heatmaps |

### Rate-limit strategy
- Token-bucket limiter shared across all keyed calls; read `X-RateLimit-*` response headers
- Batch player lookups (10 names per request)
- `/matches/{id}` is unkeyed/unlimited — hammer it freely (be polite)
- Cache season list daily; player season stats hourly at most

## 4. Data Model (PostgreSQL)

```sql
players(id PK, account_id UNIQUE, name, shard, tracked BOOL, added_at, last_polled_at)

matches(id PK, match_id UNIQUE, shard, map_name, game_mode, custom BOOL,
        duration_s, played_at, telemetry_url, telemetry_path, ingested_at)

participants(id PK, match_id FK, account_id, name, roster_id,
             kills, assists, dbnos, damage, headshot_kills, longest_kill,
             ride_distance, walk_distance, swim_distance, revives, heals, boosts,
             weapons_acquired, time_survived, win_place, death_type)

rosters(id PK, match_id FK, roster_rank, won BOOL)

-- Derived / precomputed
player_daily_stats(account_id, date, matches, wins, kills, damage, ...)
heatmap_bins(map_name, kind, account_id NULLABLE, grid_x, grid_y, count)
```

- Store **all 100 participants** per match, not just tracked players — enables opponent lookups and aggregate heatmaps for free
- Raw telemetry stays out of Postgres (object storage); parse-on-demand with a processed-frame cache

## 5. Ingestion Pipeline

1. **Player poller** (every 5–10 min per tracked player, batched):
   fetch player objects → diff match ID list against DB → enqueue new matches
2. **Match fetcher**: pull `/matches/{id}`, upsert match + participants + rosters, record telemetry URL
3. **Telemetry fetcher**: download gzipped telemetry from CDN → store raw file
4. **Telemetry processor** (async job):
   - Parse events: `LogPlayerPosition`, `LogPlayerKillV2`, `LogPlayerTakeDamage`, `LogParachuteLanding`, `LogGameStatePeriodic` (zone), `LogCarePackageLand`, `LogVehicleRide`
   - Parse inventory events: `LogItemPickup` (+ `...FromCarepackage` / `...FromLootbox` / `...FromVehicleTrunk` / `...FromCustomPackage`), `LogItemDrop`, `LogItemUse`, `LogItemEquip` / `LogItemUnequip`, `LogItemAttach` / `LogItemDetach`, `LogItemPutToVehicleTrunk`
   - Emit: heatmap bin increments, replay frame index + inventory delta track (see §7), per-match derived stats (landing spot, kill positions)
5. **Backfill command**: on adding a new player, immediately ingest their available ~14 days of history

Job queue: Postgres-backed (SKIP LOCKED) is plenty; no need for Redis at this scale.

## 6. Heatmaps

- **Coordinate system**: telemetry positions are centimeters; maps are 8×8 km (816,000 units), 4×4 km, etc. Normalize: `px = x / world_size * image_size`
- **Map images**: official high-res map assets are in the `pubg/api-assets` GitHub repo (low/high res per map, incl. no-text variants)
- Bin positions into a grid (e.g. 256×256) per map, per kind (kill / death / landing / movement), per player and global
- Render client-side: canvas overlay with gaussian blur + color ramp over the map image
- Filters: date range, game mode, squad vs solo, specific weapon (from kill events)

## 7. Match Replay (top-down)

The flagship feature. Telemetry gives everything needed for a smooth 2D replay.

### Preprocessing (server-side, once per match)
- `LogPlayerPosition` fires ~every 10s per player (more often in combat) — too sparse to render directly
- Build a **frame index**: for each player, a time-sorted array of `(t, x, y, health, alive)` samples; interpolate client-side between samples
- Extract event track: kills (killer/victim/weapon/position), knocks, zone circle states (safe zone, blue zone, red zone from `LogGameStatePeriodic`), care packages, plane path (derivable from earliest positions/parachute events)
- **Inventory reconstruction**: run a per-player state machine over the item events in timestamp order — pickup adds, drop/use removes, equip moves to weapon/armor slots, attach/detach nests attachments under their parent weapon (`parentItem`/`childItem`). Emit an **inventory delta track**: `(t, playerId, op, item, slot)` tuples rather than full snapshots per frame. Notes:
  - Item objects carry ID, category, sub-category, and stack count
  - Ammo consumed by firing is NOT an `LogItemUse` event — infer from `LogPlayerAttack`/`LogWeaponFireCount` if ammo counts matter, or just display magazine-agnostic totals
  - Death loot transfers appear as other players' pickups, not an explicit drop-all — clear a player's inventory on death
  - Cross-check against `LogPlayerKillV2` weapon fields to catch state-machine drift
- Serialize compactly (MessagePack or flat JSON arrays, gzipped) → cache in object storage; typical processed replay: a few hundred KB

### Frontend renderer
- Canvas 2D or PixiJS over the map image
- Playback controls: play/pause, 1×–20× speed, timeline scrubber with kill markers
- Render per frame (interpolated): player dots (team-colored, tracked player highlighted), name labels on hover/zoom, health rings, death markers, zone circles animating between phases, care package icons
- Kill feed panel synced to timeline; click a kill → jump to that moment and center camera
- **Inventory panel**: click/select a player → side panel shows their loadout at the current timestamp (weapons with nested attachments, armor/helmet tier, heals, boosts, throwables, ammo). Client applies inventory deltas incrementally as the scrubber moves; on a backwards seek, rebuild from the nearest keyframe (store a full snapshot every ~60s to keep seeks cheap)
- Zoom/pan (viewport transform); "follow player" camera mode
- Nice-to-have: trace trails (last 30s of movement), damage lines between shooter and target

## 8. Dashboard UI

- **Home**: tracked player cards (K/D, win rate, recent form sparkline), recent matches feed
- **Player page**: lifetime/season/ranked stat panels, match history table (filterable), performance-over-time charts, personal heatmaps, weapon mastery
- **Match page**: full scoreboard (all rosters), tracked player highlights, per-match heatmap, **"Watch Replay"** button
- **Compare view**: two+ tracked players side by side
- Charts: Recharts/Chart.js (frontend) — damage/kills over time, placement distribution, survival time histogram

### Design direction

The look should come from PUBG's own world — military-sim, map-and-grid, utilitarian — not from a generic dashboard template. Treat it like a tactical ops console: the map and the numbers are the product; the chrome exists to frame them and then get out of the way.

**Layout principles**

- **Map-first hierarchy.** On match and replay pages the map viewport dominates (70%+ of width); stats, kill feed, and inventory live in a single collapsible rail, not scattered cards. On the replay page, chrome recedes entirely — dark edge-to-edge canvas, thin timeline docked at the bottom, overlays on hover.
- **Density is a feature.** The audience reads scoreboards and K/D tables for fun. Use real tables with tight row heights, right-aligned numerals, and column sorting — not grids of padded stat cards. One screen of a match page should answer "how did that game go" without scrolling.
- **Fixed, predictable structure.** Left nav (players / matches / compare), content area, optional right rail. Same skeleton on every page so navigation becomes muscle memory. No centered marketing-style layouts anywhere.
- **Alignment over decoration.** A strict 8px spacing grid and consistent column alignment do more for "pleasing to the eye" than any visual effect. When something looks off, fix spacing before adding borders or shadows.

**Color & surface**

- Dark UI, but built from a *map-toned* neutral ramp (warm gray-greens, like Erangel terrain at night) rather than flat #111 black — define ~5 surface steps and use elevation by lightness, not drop shadows.
- One accent drawn from the game's identity (PUBG gold/orange) used *only* for interactive/current things: the scrubber position, the tracked player, active filters. Semantic colors reserved for meaning: red = kills/deaths, blue = zone, white = neutral data.
- Team colors in replay come from a fixed 25-color categorical palette tested on the dark map background; tracked player always renders in the accent color with a halo.

**Typography**

- Two faces: a condensed, slightly military display face for page titles and big numbers (e.g., an industrial grotesque — think stencil-adjacent, not literal stencil), and a clean body face for everything else.
- **Tabular (monospaced) figures everywhere numbers appear** — tables, timers, the replay clock. Nothing reads more amateur than stat columns that wiggle.
- Uppercase micro-labels with letterspacing for section eyebrows (`MATCH HISTORY`, `SEASON 34`) — this is the one place the tactical vernacular is allowed to show; use it consistently and nowhere else.

**Signature element**

- The replay timeline: not a plain scrubber but a **match strip** — a horizontal band showing zone phase shading, kill tick marks (colored by team), and the tracked player's alive/dead span. It doubles as navigation on the match page (click a tick → open replay at that moment) and makes every match visually fingerprintable in lists.

**Anti-slop rules (hard bans)**

- No gradient hero cards, no glassmorphism/blur panels, no emoji as icons, no 24px-radius rounded everything (max 4–6px radii)
- No "big number + label + sparkline" KPI card grids as the default answer — cards only where a card is genuinely the right container
- No drop shadows for hierarchy; use surface lightness and 1px borders
- No skeleton-shimmer overload or scattered micro-animations. Motion budget: replay playback itself, one page-transition fade, and hover states. Respect `prefers-reduced-motion`.
- No filler copy. Empty states say what to do ("Add a player to start tracking"), errors say what happened and how to fix it. Buttons name the action ("Track player", not "Submit").

**Quality floor**

- Keyboard: full replay control without the mouse (space = play/pause, ←/→ = seek, ↑/↓ = speed)
- Responsive down to tablet; replay degrades gracefully on small screens (map + timeline only)
- Visible focus rings, WCAG AA contrast on all text over map imagery (text sits on a subtle scrim, never raw over the map)

## 9. Milestones

| Phase | Deliverable |
|---|---|
| **1. Ingestion core** | API client + rate limiter, player tracking CRUD, match + participant persistence, telemetry download. Runs headless. |
| **2. Basic dashboard** | Backend API + frontend: player pages, match history, stat panels, season/lifetime stats |
| **3. Telemetry processing** | Parser, heatmap bins, frame index generation; heatmap UI with filters |
| **4. Replay MVP** | Map render, interpolated player positions, zone circles, play/pause/scrub |
| **5. Replay polish** | Kill feed sync, follow-cam, trails, damage lines, speed controls |
| **6. Ops** | Docker compose, backups (PBS-friendly), metrics (ingest lag, rate-limit headroom), alerting on poller failures |

## 10. Risks & Notes

- **14-day retention**: history before the poller starts is gone forever — get Phase 1 running early, add players immediately
- **Rate limit (10/min)**: fine for a handful of players; request a higher limit from PUBG if tracking many. `/matches` being unlimited saves us — only player polling is constrained
- **Telemetry size**: ~2–10 MB gzipped per match; 5 players × 10 matches/day ≈ manageable, but plan retention policy (keep processed frames, optionally expire raw telemetry after N months)
- **Telemetry schema drift**: PUBG occasionally adds/renames event fields per patch — parse defensively, log unknown events
- **Map asset licensing**: PUBG's API assets repo is provided for API developers; fine for personal/self-hosted use
- **PUBG Mobile**: not available via this API — PC/console shards only

## 11. Reference Links

- Developer portal / API keys: https://developer.pubg.com
- Docs: https://documentation.pubg.com
- Telemetry event docs: https://documentation.pubg.com/en/telemetry-events.html
- Map images & data dictionaries: https://github.com/pubg/api-assets
