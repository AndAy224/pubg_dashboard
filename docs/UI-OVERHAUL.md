# UI Overhaul Plan

Written 2026-07-22 against the live deployment (65 matches, all parsed, API on
:8000). Everything below labelled *measured* was checked against the running
Postgres or the live API, not asserted from the code.

> **Status: implemented 2026-07-22.** Outcomes and deviations in
> [HANDOFF §13](../HANDOFF.md). One claim in this document was **wrong**, in
> the exact way the project is about — see the correction immediately below.

## Correction: this plan's own accuracy claim was false

§2 below asserted `shots_fired` / `shots_hit` were "populated" on all 5,978
participants and proposed **accuracy** as a headline stat on the player page,
the scoreboard and a trend chart.

The evidence was `count(shots_fired) = 5978`. That counts non-NULL, and the
column is NOT NULL — so it was 5,978 zeros. **`count()` of a non-nullable
column proves nothing.** `count(*) FILTER (WHERE shots_fired > 0)` returned 0.

Two separate problems sat underneath, both found only by reading raw telemetry:

1. `combat.py` read `shotsFired` / `hitCount`, which PUBG does not send. The
   real names are `shots` and `hits`. Fixed, parser v2, reparsed — the totals
   now reconcile exactly with the raw corpus (32,821 shots / 7,349 hits).
2. **Fixing it did not make accuracy available.** PUBG populates
   `allWeaponStats` for a median of 2 accounts per match, and for a *tracked*
   player in 3 of 65. `LogWeaponFireCount` cannot substitute: it is quantised
   to multiples of 10 and drops weapons fired fewer than 10 times.

So accuracy was **cut as a headline stat**. It renders only where PUBG
actually reported it, and reads "not reported by PUBG" otherwise. Its place on
the player page went to **headshot rate**, which comes from the API's own
`headshot_kills` and is exact. Everywhere else in this plan that says
"accuracy", read it as "shown only when `shotsFired > 0`".

The prompt for this document: the dashboard works but under-delivers. The
recent-matches feed does not even say **which tracked player played or where
they finished** — the two facts anyone opens the page for. This plan covers
four goals: fix that class of problem everywhere (show the interesting data),
restructure navigation, redesign the look, and make the app measurably more
efficient.

---

## 1. Audit — what is on screen today

| Page | What it shows | What is wrong |
|---|---|---|
| Overview (`Home.tsx`) | 3 player cards (K/D, wins, top10, avg dmg), 15 recent matches | Match rows carry **no player, no placement, no kills** — just map/mode/duration. Cards have no trend, no form, no last-session context. 5 HTTP requests for one screen. |
| Player (`Player.tsx`) | 8 stat tiles, weapons table, distance panel, 50-match history | No charts (`recharts` is installed and tree-shaken out — the `/timeseries` endpoint already works, nothing calls it). No filters (mode/map/date params exist server-side, unused). No accuracy, no "who kills you", no placement distribution. |
| Match (`Match.tsx`) | Scoreboard grouped by roster, kill feed | No kill map, although `kill_events` stores killer *and* victim positions for all 6,164 kills. No link back to the player you came from. Scoreboard hides accuracy, knocks, headshots — all stored. |
| Heatmaps | 7 kinds, map + player pickers | Server supports `gameMode`, `since`, `until` filters — UI exposes none of them. Known career-vs-heatmap discrepancy (no `match_type` dimension) is displayed as a tooltip instead of fixed. |
| Replay | Canvas, kill feed, team list, controls | Bundle already carries the full inventory delta track, knock/revive/care-package/ride/phase events, and a per-tick alive count — none rendered. No timeline strip with kill ticks (BUILD-SPEC §5.2 planned it). |
| Settings | Read-only health, queue, tracked players | `POST /ingest/backfill` and `POST /ingest/reparse` exist and are unreachable from the UI. |
| Navigation | Overview · Heatmaps · Settings | The three tracked players — the entire point of the app — are not in the nav. There is no matches browser at all (the archive is only reachable 15-at-a-time via Overview or 50 via a player page). No `/compare` (planned in BUILD-SPEC §5.1). |

**Efficiency, measured:**

- `GET /api/heatmap` returns **349,638 bytes** and ignores `Accept-Encoding:
  gzip` — there is no compression middleware. Gzipped this payload is ~10–15 KB
  (the base64 cells are mostly zeros). Every heatmap toggle costs a third of a
  megabyte on the LAN.
- Overview fires **5 requests** (players, 3× per-player stats, recent matches)
  where one composed payload would do.
- react-query runs with default `staleTime: 0`, so every navigation refetches
  everything, including immutable data (a parsed match's scoreboard never
  changes).
- `@tanstack/react-table` and `@tanstack/react-virtual` are installed and
  unused; every table is hand-rolled.

---

## 2. The data goldmine — stored but never shown

All measured against the live DB. This is the "show all interesting data" list;
the API/UI changes in §3–§6 exist to surface it.

**`participants` (5,978 rows, telemetry-derived columns populated on all):**

| Column(s) | Populated | What it unlocks |
|---|---:|---|
| ~~`shots_fired`, `shots_hit`~~ | ~~5,978~~ **164** | ~~Accuracy~~ — **see the correction at the top; this row was wrong** |
| `killer_account_id`, `death_weapon` | 5,610 | "Killed by Xx_Slayer (M416, 210 m)" on every match row; career **nemesis** list |
| `landing_x/y`, `landed_at_s` | 5,978 | Landing marker on the match kill map; drop-spot consistency |
| `death_x/y`, `died_at_s` | 5,866 | Death marker; "died at 3:12, #47" timeline context |
| `dbnos`, `knocks_human` | all | Knocks column (currently only in career totals) |
| `kill_streaks`, `road_kills`, `vehicle_destroys`, `team_kills`, `weapons_acquired`, `heals`, `boosts`, `swim_distance`, `kill_place` | all | Fun-fact tiles and scoreboard columns |

**`matches`:** `weather_id` (Clear 44 / Sunset 11 / Overcast 10), `bot_count`,
`num_start_players`, `team_size`, `telemetry_t0` — all populated on 65/65,
none shown outside the match header.

**`kill_events` (6,164 rows):** killer *and* victim positions (a per-match
kill map costs zero new storage), `damage_reason` (headshot markers),
`assists[]` (1,547 kills have assists), `is_team_kill`, `dbno_maker` vs
`finisher`. Non-fact: `through_wall` is never true in the corpus — do not
build a wallbang stat.

**Replay bundle (already decoded in `replayBundle.ts`):** full inventory
track (`inv`), events `knock`/`revive`/`cp`/`ride`/`leave`/`phase`, per-tick
`zones.alive` + `zones.teams` (an alive-count curve), plane path, per-player
final rank.

**Unused API surface:** `/players/{id}/timeseries` (works today — measured),
`gameMode`/`since`/`until` on stats, matches and heatmap, `q=` player search,
keyset pagination (`before`), both `POST /ingest/*` operations.

**Ground truth for the feed design (measured):** the three tracked players
appear together — 48 of 65 matches have ≥2 of them — and when they do they are
**always on the same roster** (0 counterexamples). So a match row gets **one
placement** and per-player kill counts, not three competing placements.

---

## 3. Phase A — API changes (enables everything else)

New code lives in the existing routers; reuse `career_filter()` /
`kills_column()` from `api/deps.py`. All aggregates default human-only
(`kills_human`) with raw available — repo rule, do not deviate.

### A1. Enriched recent-matches feed — *the headline fix*

`GET /api/matches` (rewrite; give it a real response model instead of
`list[dict]`):

```jsonc
{
  "matchId": "...", "playedAt": "...", "mapName": "Baltic_Main",
  "mapDisplay": "Erangel", "gameMode": "duo-fpp", "matchType": "official",
  "durationS": 1873, "hasReplay": true,
  "weatherId": "Sunset", "botCount": 61, "numStartPlayers": 96, // was hidden
  "winPlace": 8, "won": false, "teamRank": 8,     // the tracked roster's result
  "results": [                                    // one per tracked participant
    { "accountId": "...", "name": "SIERIUS_", "killsHuman": 6, "kills": 7,
      "damage": 812, "survivedS": 1490, "deathType": "byplayer",
      "killedBy": "SomeGuy", "deathWeapon": "WeapHK416_C" }
  ]
}
```

One query: matches ⨝ participants ⨝ players(tracked) ⨝ roster, plus a
self-join on participants for the killer name (killers can be bots — join
participants, **never** players; repo rule). Replaces today's correlated
`COUNT(*) > 0` subquery. Add `map`, `mode`, `type`, `before` params so the
same endpoint powers the new `/matches` browser page (§4).

### A2. `GET /api/overview` — one call for the home page

`{ players: [PlayerStats + form], matches: [A1 rows], health: Health }` where
`form` is the last 10 official placements + human-kill counts (for the form
strip, §5). Collapses 5 requests into 1.

### A3. Kill positions on the kill feed

Add `victimX/Y`, `killerX/Y` (cm) to `KillRow` — the columns are already in
the table. Powers the match-page kill map with zero storage work.

### A4. Player-page aggregates (one cheap query each)

- Extend `PlayerStats`: `accuracy` (Σhit/Σfired), `headshotRate`
  (hs/killsHuman), `knocksHuman`, `roadKills`, `vehicleDestroys`,
  `teamKills`, `avgSurvivedS`.
- `GET /players/{id}/placements` — win_place histogram buckets
  (1, 2–5, 6–10, 11–25, 26+).
- `GET /players/{id}/nemeses` — from `kill_events` both directions, humans
  only: who kills them, who they farm. `killed_by` names join participants.
- Extend `/timeseries`: metrics `kd`, `damage`, `accuracy`, `placement`;
  `gameMode` param.
- `MatchSummary` gains `killedBy` + `deathWeapon` + `knocks`.

### A5. Heatmap `match_type` dimension — the one schema change

Already prescribed by HANDOFF §8.2. Migration `0003`: add `match_type` to
`heatmap_bins` PK with `''` sentinel (same NULL≠NULL reasoning as the existing
sentinels — see the model docstring), extend the parser's cross-product, bump
`PARSER_VERSION`, `POST /ingest/reparse`. Free (no re-download), idempotent
(heat ledger). **Hand-write the index in `upgrade()`** — autogenerate omits
partial/functional indexes (`HAND_MANAGED_INDEXES`), and any ON CONFLICT
predicate must match the index predicate character-for-character.

### A6. Compression

`GZipMiddleware(minimum_size=1024)` in `app.py`. The replay route already
sets `Content-Encoding: gzip` itself, so the middleware skips it — verify
with a curl of both. Heatmap goes ~350 KB → ~15 KB.

---

## 4. Phase B — navigation & information architecture

```
┌────────────────┐
│ PUBG dash      │   Nav gains the three players — they ARE the app.
│                │   Each row: identity-coloured dot, name, mini K/D,
│ ⌂ Overview     │   "2h ago" last-seen.
│ ≣ Matches      │   NEW: full archive browser.
│ ▦ Heatmaps     │
│ ⇄ Compare      │   NEW: side-by-side.
│ ────────────   │
│ ● AndAy        │
│ ● DaddyGainz   │
│ ● SIERIUS_     │
│ ────────────   │
│ ⚙ Settings     │
│ ● 65/65 ok     │   Ingest badge stays.
└────────────────┘
```

- **`/matches` browser** (new page): the whole archive, A1 rows, filter bar
  (map, mode, type, player, has-replay), keyset "load more". Use
  `@tanstack/react-table` + `react-virtual` — already installed, this is the
  page they were installed for.
- **Player page**: sticky section nav (Overview · Trends · Weapons · Matches ·
  Maps), and a filter bar (mode, date range) threaded into stats, weapons,
  matches and heatmap queries — all params already exist server-side.
- **Match page**: breadcrumb back to the player you navigated from
  (`location.state`), prev/next-match arrows within that player's history,
  and "same session" chips (other matches within ±4 h).
- **`/compare`**: 2–3 tracked players, stat columns + recharts `RadarChart`
  (K/D, win %, top-10 %, accuracy, avg damage, avg placement normalised).
  Cheap: three `PlayerStats` calls and one table.
- **Settings**: wire the two POST endpoints (backfill per player, reparse
  stale) with confirm dialogs; show `oldestUnparsed` and parser version drift.
- **Replay**: Esc → match page; clicking a kill-feed row seeks to it.

---

## 5. Phase C — visual redesign

Keep the dark, dense, information-first character. The current UI's problem is
not that it is dark — it is that everything is the same shade of grey table.
Three moves change that:

### C1. Identity colours

The three tracked players get fixed hues used *everywhere* — nav dots, card
headers, chart lines, match-row kill chips, replay markers, heatmap picker:

```css
--p-anday:  #f0b429;  /* amber  — keeps the existing accent as AndAy */
--p-gainz:  #4cc9f0;  /* cyan   */
--p-sierius:#b388ff;  /* violet */
```

Once these exist, "which tracked player did what" reads at a glance without a
label — the fix for the user's complaint is half colour-coding.

### C2. Placement grading

Placement is the game's scoreline; render it like one, everywhere the same:

- `#1` gold chip (existing `.tag.win`), `#2–5` silver, `#6–10` steel-blue,
  rest dim mono. Always `#8 / 25 teams` with the denominator faint.
- **Form strip** on every player card: last 10 official matches as 10 small
  squares coloured by that grade (tooltip: map, placement, kills). Instantly
  answers "how are we doing lately".

### C3. Map imagery as texture

The tile pyramid is already served locally and looks great — use it:

- 48 px map thumbnail (zoom-0 tile, `border-radius`) as the left edge of every
  match row.
- Player-page hero: latest map's tile, darkened under a gradient, behind the
  name + form strip.
- Match-page header: same treatment.

### Page specs

**Overview** — answers "what happened recently" in one glance:

```
┌ TONIGHT ────────────────────────────────────────────────────────┐
│ 5 matches · best #8 · 15 human kills · 2,410 dmg · 1h 40m       │  ← from A2
├ AndAy ──────────┬ DaddyGainz ─────┬ SIERIUS_ ───────────────────┤
│ ■■□■□■□□■■ form │ …               │ …                            │
│ K/D 1.42  ▄▆▂▇ │                 │                              │  ← sparkline
├ RECENT MATCHES ─┴─────────────────┴──────────────────────────────┤
│ [thumb] 18:19 · Duo FPP · Sunset   #8/25   ●DaddyGainz 1  ●SIERIUS_ 6   ▶ │
│ [thumb] 17:59 · Duo FPP            #12/28  ●DaddyGainz 6  ●SIERIUS_ 6   ▶ │
│          ↑ placement chip, graded    ↑ identity-coloured kill chips        │
└──────────────────────────────────────────────────────────────────┘
```

**Player** — hero (map backdrop, name, form strip, session summary) → stat
tiles *with deltas vs the previous 14 days* → charts row (recharts:
K/D + damage trend from `/timeseries`, placement histogram from A4) → weapons
table with headshot % → nemeses panel ("killed by Xx_Slayer ×4") → full match
table (killedBy column, placement chips, replay ▶).

**Match** — header (map hero, weather, bots, real start from `telemetryT0`) →
**kill map**: `MapTiles` + kill markers from A3, killer→victim tracer on
hover, landing/death markers for tracked players, filter by roster/tracked →
scoreboard gains Acc%, HS, Knocks columns (data in `ParticipantRow` already
or A4) → kill feed gains headshot glyph (`damage_reason == "HeadShot"`),
assist names, team-kill flag, and links each row to the replay at that
timestamp (`/replay?t=`).

**Heatmaps** — expose the `gameMode` and date-range params that already work;
after A5, an "official only" default toggle replaces the apologetic tooltip.
Side-by-side compare mode (two panels, same filters, different player) is a
cheap win for "where do we each drop".

Polish sweep: skeleton loaders instead of "loading…", `document.title` per
page, empty states with the next action, favicon, error boundary.

Constraints that stand: TS ~6.0.2 (`erasableSyntaxOnly` — no constructor
parameter properties), react-table 8, no `@pixi/react`, no `pixi-viewport`,
dark-only. All new stat surfaces default human-only kills.

---

## 6. Phase D — replay upgrades (bundle already carries it all)

1. **Timeline strip** (BUILD-SPEC §5.2): scrubber with kill ticks (coloured by
   tracked involvement), phase boundaries from `phase` events, alive-count
   area curve behind it from `zones.alive`. This is the single biggest replay
   usability win — you can *see* where the fights are.
2. **Inventory panel**: resolve state via `nearestKeyframe(t) + deltas`
   (`inv.kfEveryMs` is in the bundle; never replay from zero — spec §5.3).
   Show for the followed/selected player: weapons + attachments, heals, ammo.
3. **Feed upgrades**: knocks (dim) and revives (green) interleaved with kills;
   care-package drops as map pings + feed rows (`cp` events).
4. **Deep links**: `?t=185s&follow=account.…` so match-page rows and kill feed
   can jump straight into the moment.

---

## 7. Phase E — efficiency

| Fix | Cost | Effect (measured baseline) |
|---|---|---|
| GZip middleware (A6) | 2 lines | heatmap 349,638 B → ~15 KB |
| `/api/overview` (A2) | S | Overview 5 requests → 1 |
| react-query `staleTime: 60s` default; `Infinity` + `X-Parser-Version` key for match detail/kills/replay of parsed matches (immutable by design) | S | eliminates every refetch-on-navigate |
| Prefetch match detail on row hover (`queryClient.prefetchQuery`) | S | match page feels instant |
| Virtualise the `/matches` browser table | S (lib installed) | archive scales past 65 |
| `Cache-Control: public, max-age=31536000, immutable` on `/api/tiles/*` (fingerprint-equivalent: tiles never change for a map version) | S | repeat map views hit disk cache |
| Heatmaps page: fetch zoom-1 tiles for the 720 px canvas (zoom 2 is 4× oversampled today) | S | 16 tile requests → 4 |

Not worth doing at this scale: server-side response caching, DB query tuning
beyond A1's join rewrite (65 matches; the enriched feed measured <10 ms).

---

## 8. Suggested order

| Step | Contents | Size |
|---|---|---|
| 1 | A1 + A2 + A6, Overview redesign (match rows with players/placement, form strips, tonight bar) | **M — do first, it is the stated complaint** |
| 2 | Nav restructure + `/matches` browser + C1/C2/C3 tokens & chips | M |
| 3 | Player page: filters, charts, placements, nemeses, deltas (A4) | M |
| 4 | Match page: kill map (A3), scoreboard columns, feed upgrades | M |
| 5 | A5 migration + reparse; Heatmaps filters + compare mode | S–M |
| 6 | Replay: timeline strip → inventory → feed → deep links | L |
| 7 | Compare page, Settings actions, polish sweep | S |

Each step ships independently; nothing blocks on the replay work.

---

## 9. Verification

- **Backend**: pytest per new endpoint against corpus oracles — e.g. the A1
  feed for the 18:19 duo match must return `winPlace 8` with DaddyGainz 1 /
  SIERIUS_ 6 human kills (verified by SQL above); overview player count 3;
  accuracy = Σ`shots_hit`/Σ`shots_fired` recomputed independently in the test.
  DB tests bring their own fixture and skip clean without Postgres
  (`conftest` rule); run `-rs` and read the skips.
- **A5**: after reparse, per-player official-only kill-bin totals must not
  exceed pre-migration totals, and ledger objects must exist for all 65;
  persist must still *refuse* a ledger-less match.
- **Frontend**: `npm run typecheck && npm run lint && npm run build`; devtools
  network tab: Overview = 1 API call, heatmap response gzipped ≤ 20 KB,
  second visit to a parsed match = 0 API calls.
- **Traps to re-check while implementing** (CLAUDE.md): human-only kill
  defaults on every new surface; killer name joins go to `participants`,
  never `players` (bots); `distance > 0` filter on anything "longest";
  placement chips must handle `winPlace` > 100 (`killPlace` observed at 107);
  no y-flip in the kill-map transform; enum dispatch lowercased with defaults.
