# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Self-hosted PUBG dashboard: match archive, career stats, heatmaps, and a
telemetry-driven top-down replay, for three tracked Steam players.

**Read [HANDOFF.md](HANDOFF.md) before starting.** It records current state,
what is verified, and what is left. `docs/BUILD-SPEC.md` is the implementation
spec.

## The one thing to internalise

**This project's dominant failure mode is silently wrong data, not crashes.**

PUBG's API is inconsistently cased and partially undocumented, and its public
docs are stale. Nearly every trap found here produces *plausible* output rather
than an error — a K/D that is simply double, a heatmap that is mirrored, a
replay where everyone stands still. None of them throw.

So: **do not trust documentation, measure the real data.** There are 65 real
matches and 2.4M real telemetry events under `data/`. Every schema claim in the
repo was checked against them, and doing so has already overturned several
things that documentation — including this repo's own — asserted confidently.

Two corrections that happened exactly that way are written up in HANDOFF §12,
including one where `scripts/extract_schema.py` was hiding the evidence for its
own most subtle trap. When you need a fact about the API, query the corpus.

### Authority order when documents disagree

1. `docs/reference/telemetry-observed-schema.md` — machine-generated from the
   corpus. Outranks everything, including PUBG.
2. The other hand-written docs in `docs/reference/`.
3. PUBG's official documentation. Wrong in several load-bearing places.

## Commands

All backend commands run from `backend/`. `uv` lives at `~/.local/bin`, which is
not on the default non-login PATH.

```bash
export PATH="$HOME/.local/bin:$PATH"
uv sync --all-groups

uv run pytest -q                          # full suite
uv run pytest tests/test_telemetry_combat.py::test_zone_death_has_a_null_killer
uv run pytest -q -rs                      # show why anything skipped
uv run ruff check . --fix                 # clean; keep it that way (backend/ only)
uv run mypy pubg_dashboard                # NOT clean, and never has been — see below

uv run alembic upgrade head
uv run alembic revision --autogenerate --rev-id 0003 -m "..."
```

Live services are systemd **user** units — restart them after a backend change:

```bash
systemctl --user restart pubgd-api.service     # also: pubgd-worker, pubgd-poller
```

Frontend, from `frontend/` (Node via nvm: `. "$HOME/.nvm/nvm.sh"`):

```bash
npm run dev          # :5173, proxies /api to :8000
npm run build        # tsc -b && vite build  -> dist/, which the API serves
npm run typecheck
npm run lint         # oxlint
npm test             # vitest run
npm run check        # typecheck + lint + test, the whole gate
```

Frontend tests are **vitest in a node environment, no jsdom**: every bug this
frontend has actually shipped lived in a pure function, not in markup.
`src/lib/*.test.ts` are hermetic; `replayBundle.corpus.test.ts` decodes real
bundles from a running API and **skips cleanly when it is absent**, mirroring
the backend's convention — so a source-only checkout stays green. Point it
elsewhere with `PUBGD_API_BASE`.

Three TypeScript projects, and the split is load-bearing: `tsconfig.app.json`
is what ships and deliberately has **no `node` types**, so app code cannot
reference `process` or `node:fs` and crash in a browser;
`tsconfig.test.json` adds them for tests; `tsconfig.node.json` covers the
config files. Put a `process.env` in `src/` and the build fails, by design.

### CSS from a lazy route is global once that route loads

Vite injects a lazy chunk's stylesheet on first load and **never removes it**,
so `pages/*.css` is global from the moment someone visits that page — on every
other page, for the rest of the session. `pages/Replay.css` is therefore
scoped entirely under `.replay`, and `src/styles/css-scope.test.ts` enforces
that plus "no class is declared globally by two stylesheets".

This is not hypothetical: `.feed-row` was declared in both `Replay.css` and
`MatchFeed.css`, and the replay's four-column grid landed on the home page's
five-column match rows. A fresh load looked perfect — the collision only
appeared after opening a replay and navigating back.

`ruff` and the frontend checks pass. **`mypy` does not** — it is configured
`strict = true` but the codebase has never satisfied it, mostly `type-arg`,
`import-untyped` from boto3, and SQLAlchemy statement reassignment. Treat it as
a source of hints, not a gate, and do not assume a red run means you broke
something. No count is given here on purpose: it drifts, and a stale number
reads as a regression budget it was never meant to be.

**The ruff gate covers `backend/` only.** `scripts/` sits outside it and has
long-standing failures of its own (RUF100, E501), so a red run there is
probably not yours — check whether the file you touched is the one complaining
before fixing anything.

Operator CLI (`pubgd`): `seed`, `poll`, `worker`, `import-archive`, `stats`,
`player`, `jobs`. Scripts: `scripts/panic_archive.py` (archive before the 14-day
window closes, idempotent), `scripts/extract_schema.py` (regenerate the observed
schema, ~3 min), `scripts/fetch_map_assets.py` (download + tile maps),
`scripts/build_gazetteer.py` (rebuild the committed place-name artifacts from
the corpus; run it after a new map enters `data/telemetry`).

`fetch_map_assets.py` asks the **running API** which maps have been played, not
`data/matches/`, which is a raw-payload archive that lags the database. It
lagged by 24 matches and two whole maps, so the default run reported success and
built nothing for a Miramar match played that afternoon — no error, just a
confident list of the wrong maps. When the API is unreachable it falls back to
the archive scan and **says so**; a silent fallback would be the same bug again.

### Tests

`tests/conftest.py` is deliberately Postgres-free and network-free. Tests
needing either bring their own fixture and **skip cleanly when it is absent**, so
a source-only checkout stays green — which means a skip can hide a real failure.
When touching test infrastructure, run `-rs` and read the reasons.

- `PUBGD_TEST_DATABASE_URL` — overrides the scratch DB (default: the configured
  DSN with the database swapped to `pubg_test`). These tests TRUNCATE.
- `PUBGD_TEST_DATA_DIR` — overrides the corpus location (default `data/`).

`db/session.py` caches the engine process-wide while `asyncio_mode = auto` gives
each test its own loop, so any DB test module needs a per-test `dispose_engine`
or the second test onward fails with "attached to a different loop".

**A corpus test can go red with no code change.**
`frontend/src/lib/format.corpus.test.ts` checks every damage causer in the live
API against the kill feed's display tables, so the poller ingesting a match with
an unseen vehicle or grenade fails it on a checkout nobody has touched. That is
the test working: a BRDM roadkill arrived and reached the feed as the raw id
`BP BRDM`, and the fix was one prefix in `VEHICLES` in `src/lib/format.ts`.
Before assuming you caused a corpus-test failure, stash and re-run it.

## Architecture

Four processes over Postgres + MinIO. Three run as systemd **user** units
(`deploy/systemd/`, installed with `loginctl enable-linger` — no root).

```
poller ──enqueue──> jobs table <──claim── worker ──> Postgres + MinIO
  (rate-limited)     (SKIP LOCKED)          │
                                            └─ fetch_match -> fetch_telemetry
                                               -> parse_telemetry
api (FastAPI) ── reads Postgres + MinIO, and serves frontend/dist at /
```

**Rate limit is the organising constraint.** `GET /players` costs one token of
10/min. `GET /matches/{id}` and the telemetry CDN are **free and unmetered** — so
three tracked players cost one request per poll cycle and fanning out to 150
matches costs nothing. Never spend a token on `/matches` or the CDN, and never
send the API key to the CDN.

### Ingest

`ingest/` talks to the PUBG API and object storage through Protocols in
`ports.py`; `ingest/wiring.py` is the composition root that adapts the concrete
`PubgClient` and `Storage` onto them. The adapter exists because the two sides
disagree on purpose — the client returns parsed pydantic models and streams
telemetry to disk, while ingest wants raw JSON:API dicts, since `upsert` and
`parse_players_payload` are verified field-by-field against the corpus in that
form.

Job queue is Postgres `FOR UPDATE SKIP LOCKED`. `attempts` increments **at
claim**, so a job that SIGKILLs the worker still dead-letters. `uq_jobs_dedupe_live`
is a partial UNIQUE over live rows only — that index is the entire idempotency
story, and dedupe keys must be namespaced `{kind}:{ident}` because it covers
`dedupe_key` alone.

Note `ingest/queue.py` and `queue/jobs.py` both exist. The duplication is real
but was **measured**: both build the same key and both dedupe correctly.
Consolidating is tidy-up, not a correctness fix.

### Telemetry parser

`telemetry/` is two passes over ~37k events, never more. The prescan collects
t0, the roster, a pickup index, and each account's **final** death; the main pass
fans out to `frames`, `world`, `combat`, `inventory` and `heatmap`. Two passes
are the minimum — the inventory state machine needs lookahead that no forward
pass can provide.

Output is a MessagePack+gzip replay bundle (`bundle.py`), `kill_events` rows,
`heatmap_bins` upserts, and telemetry-derived `participants` columns.
`ingest/persist.py` writes them, and everything it does is idempotent.

`PARSER_VERSION` is in `bundle.py`. Bumping it and requeueing `parse_telemetry`
re-derives every output from stored raw telemetry with **no re-download** —
which is the entire reason raw telemetry is archived. It is also part of the
replay object key, so a bump invalidates caches cleanly.

**Reparse is only idempotent because of the heat ledger.** Each parse records
exactly what it contributed to `heatmap_bins`; the next subtracts that before
adding. If a parsed match has no ledger, persist *refuses* rather than
proceeding — a heatmap that is quietly 2x is indistinguishable from a popular
drop spot.

**`telemetry/engagements.py` is the parser's only model.** Everything else it
writes is a reading of something PUBG states — a kill, a knock, a circle
roster, a position. PUBG does **not** record fights, so an "engagement" is a
grouping this codebase invents by cutting the stream of cross-team blows at
`ENGAGEMENT_GAP_S` (20 s) of silence between the same two teams. The sweep
behind that constant found **no knee** anywhere from 5 s to 120 s — 20 s gives
2,992 engagements over 25 matches and 30 s gives 2,589, a 13% swing from a
ten-second choice. So the row *count* is a judgement call, every rate over it
inherits that, and the constant is returned by `/api/review/engagements` so the
page can name it rather than presenting it as discovered.

For the same reason there is deliberately **no `outcome` column**: the per-side
kill, knock and damage counters are facts given the grouping, a verdict is not.
The API derives a label at query time and names it after what it counts
(`ours_only`, `theirs_only`, `both`, `neither`), never "won" or "lost". Both
`test_no_outcome_verdict_is_stored` and a frontend test pin that, because it is
the kind of decision that gets quietly reversed by whoever writes the next card.

### Frontend

Vite/React/Pixi. `npm run build` emits `dist/`, which the API mounts at `/`
after every router, so the deployed app is one origin with no CORS. In
development Vite proxies instead, so a missing `dist/` is normal.

**React never renders at 60 Hz.** The replay playhead lives on the `Renderer`
object, Pixi is mounted imperatively, and DOM panels subscribe to an external
store that ticks at 10 Hz. `ReplayCanvas` is the only React↔Pixi boundary.

That boundary also shapes debugging: Pixi's render is a *separate, lower
priority* ticker listener, so it can throw on every frame while `drawFrame`
keeps publishing. **Live rail panels with a black canvas means Pixi is
failing, not the replay logic.** Two traps found that way — never
`cacheAsTexture` a container whose bounds are the whole world (8192², a 268 MB
texture, 1.07 GB at dpr 2), and never let `Viewport.fit` scale by 0 when the
canvas has not been laid out yet, because rendering nothing looks exactly like
a broken renderer.

Version pins in BUILD-SPEC §5.5 are deliberate — TypeScript ~6.0.2 (not 7.x),
react-table 8 (not the v9 beta), no `@pixi/react`, no `pixi-viewport`.
TypeScript 6's `erasableSyntaxOnly` rejects constructor parameter properties.

## Traps that produce plausible-looking wrong output

Full list: BUILD-SPEC §6 (34 of them) and HANDOFF §5. The ones that bite most:

- **Bot ids (`ai.<n>`) are match-scoped and recycled.** `ai.322` is 14
  unrelated bots. `players` is human-only, enforced by
  `CHECK (account_id LIKE 'account.%')`; `participants.account_id` has no FK.
  Bots exist only as participant rows flagged `is_bot`.
- **The bot share moves between measurements — re-measure before quoting it.**
  This line used to read "~19% of all kills and just over half of the tracked
  players'". At 97 matches both halves are wrong: bots are **14.0% of all
  participants** (1,265/9,041) but only **6.7%** of official-match ones
  (545/8,116), **6.6% of official kill victims** (545/8,289), and **11% of the
  tracked players' kills** (27/238 — SIERIUS_ 10%, DaddyGainz 5%, AndAy 26%).
  The 19% came from the 65-match corpus and did not survive the archive
  growing. `kills_human` stays the default everywhere — that decision is right
  independently of the ratio, and the ratio is exactly the kind of number that
  goes stale in a document while looking authoritative.
- **`NULL != NULL` in Postgres**, so `heatmap_bins` uses `''` sentinels in its
  primary key for `account_id` and `game_mode`. Nullable "all" columns would
  make `ON CONFLICT DO UPDATE` never fire and every reparse would append
  duplicates. Note `match_type` deliberately does **not** follow this pattern —
  it stores the real value, and "all types" is a query omitting the predicate,
  because three values are cheaper to sum than to precompute.
- **`roster.attributes.won` is the string `"true"`/`"false"`.** `bool("false")`
  is `True`.
- **A `Character` block's `health` is sometimes the value *before* the event.**
  `LogPlayerTakeDamage.victim.health` is pre-damage (1,900 corpus pairs agree
  with `health - damage`, 134 with `health`) and `LogHeal.character.health` is
  pre-heal (295 to 2). Stored raw, a player shows full health at the exact
  instant you watch them get shot. `frames._HEALTH_DELTA` lists the corrections.
- **A knocked player reports `health: 0`** — 31,153 of 31,156 DBNO snapshots
  sit at exactly 0 — so "alive" cannot be read off health, and doing so hid
  every knock. Worse, **51% of kill victims are still flagged `isDBNO` at the
  moment of death**, so "alive or knocked" as a visibility test strands half of
  every lobby's corpses on the map. Only the final death time tells them apart:
  `FLAG_ALIVE` means *still in the match* and is resolved in `FrameIndex`.
- **`LogHeal` is the third most common event in a match** (~4,000 of 37,000)
  and is the only signal for health going *up*. It fires per heal tick, mostly
  +1, so it is thinned on health delta — see `HEAL_MIN_DELTA`.
- **`character.isInVehicle` includes the match-start aircraft**, so it is true
  for the *entire lobby* for the first ~90 s, and 43% of in-vehicle samples are
  aircraft, pickup balloons or a mounted mortar. Draw vehicle markers from
  `FLAG_DRIVING`, which cross-references `LogVehicleRide.vehicle.vehicleType`
  (`frames.DRIVEN_VEHICLES`). **Match phase is not a proxy** — it fails both
  ways: 28 aircraft rides happen mid-match (flare-gun redeploys, with
  `LogParachuteLanding` as late as `isGame` 5) and 17 real car rides happen
  before `isGame` reaches 1.
- **Zone field names are inverted.** `safetyZone*` is the **blue** damaging
  circle (interpolate); `poisonGasWarning*` is the **white** next circle
  (**snap** — it is a step function).
- **Red zones exist; `redZone*` is the wrong field.** `LogGameStatePeriodic`'s
  `redZone*`/`blackZone*` are 0 in every archived match, and this repo
  concluded from that in four separate documents that red zones had been
  removed and the renderer should not be built. They had not been:
  `LogSpecialZoneInCharacters` carries `zoneType: "RedZone"` with a full
  lifecycle (Warning → Activating at +45 s → ActivationDone at ~1 Hz →
  Deactivating ~30 s later), a fixed position, a 395–500 m radius and the
  roster of everyone inside — **seven per match, in 19 of 20 measured**. Parsed
  since v12; `zones.rx/ry/rr` were deleted rather than backfilled, because one
  per-sample radius cannot say "warned" versus "being bombed".
  `character.isInRedZone` is set from the **warning**, not from the first bomb.
  Red-zone *damage* is negligible (3 events, 1 kill across 15 matches) — this
  is map fidelity, not a statistic.
- **A care-package id can be a vehicle.** The flare-gun delivery guard was the
  single literal `"uaz_armored_c"`, which occurs **nowhere** in the corpus, so
  19 vehicle drops rendered as loot crates. What arrives is
  `Carapackage_FlareGun_C` and `BP_BRDM_C` — and PUBG spells it `Carapackage`
  in three package ids and `Carepackage` in a fourth, so match a lowercased
  **substring**, never equality.
- **`common.isGame == 0.1` is never true**; the wire value is
  `0.10000000149011612`. Compare with tolerance. Gates plane-phase detection,
  the movement heatmap, and the phase-pair split below.
- **`LogPhaseChange` fires twice per phase, and `common.isGame` says which is
  which.** `isGame == phase - 0.5` is the white-circle **announcement**;
  `isGame == phase` is the moment the blue **starts** closing on it — measured
  from the radii, 1921 m -> 1835 m one sample later, not "finished closing".
  362 events over 23 matches, three values, no exceptions; the earlier event is
  the announcement in 178 of 178 pairs. Phase 1's announcement is the special
  case at `isGame == 0.1`, during the plane phase. 6 of 184 phases have no
  close — a match can end on an announcement, so never assume pairs.
  `playersInWhiteCircle` is trustworthy: 155 of 156 named players are genuinely
  inside the radius.
- **A death can land a minute after the last hit that caused it, and it leaves
  no trail.** `Damage_DBNO` bleed-out ticks are **self-attributed** — attacker
  == victim, `attackId: -1` — so `CombatTracker._damage` drops them under the
  self-damage guard and they produce no `Hit` at all. Measured: on **16% of
  cross-team kills** the credited killer's last attributed hit on that victim
  is 20 s or more earlier, up to 122 s. Anything grouping combat by hit
  timestamps therefore loses those deaths, or opens a fresh one-event fight for
  each one — reading as "team A killed team B with no exchange" a minute after
  the fight that actually did it. `engagements.py` attaches kills afterwards
  instead, and its middle rule is `dbno_maker`'s knock: PUBG's own link, no
  threshold. 1.3% attach to nothing at all, and those are **counted**
  (`ParseResult.unattached_kills`), because a kill that silently vanished would
  make a fight review kinder than the match.
- **`LogItemDrop` never fires on death.** The victim emits a `LogItemDetach`
  burst at +0s and a `LogItemUnequip` burst at **exactly +60s**. Suppress item
  events after an account's **final** death — a player can die twice, and seven
  in the corpus died three times.
- **`Sample.t_ms` is absolute epoch milliseconds; most other parser times are
  seconds relative to t0.** `PhaseChange.t_s`, `KillEvent.t_s` and the zone
  samples are all relative. Comparing the two directly matches nothing and
  **fails silently** — `zoneplay.py` shipped rows with every geometry column
  quietly NULL on its first run, and the roster-derived columns beside them
  were correct, so the output looked fine.
- **`world.white_circle_at` snaps to the last sample at or before the time
  asked for**, and a phase announcement fires in the same second the white
  circle updates — so asking at the announce returns the *previous* circle
  about half the time. Ask at the close, where the circle is constant until
  the next announcement.
- **`y` is not inverted** (origin top-left, like canvas), and the
  `8160/8192` correction applies **only** to 816000-cm maps. Both verified
  against the map's own printed town names.
- **PUBG ships its own place names, in `Character.zone`.** This file used to
  say no place-name data existed. It does: `["pochinki"]`,
  `["sosnovkamilitarybase"]`, on 32% of position events and 62% of pickups, 26
  names on Erangel. But **`LogParachuteLanding` carries a zone only 1.2% of the
  time** — the one event that says where someone dropped is the one that will
  not name the place. Hence `scripts/build_gazetteer.py`: harvest names from
  the events that do carry them, bin onto the 256² heatmap grid, look up
  afterwards. Measured purity 0.9847 over 1.3M samples; **8.8% of the grid is
  named**, so "no name near here" is the common and correct answer. Exclude
  `8thEventSpot` — an event marker, never appears alone.
- **`distance = -1` is a "not applicable" sentinel**, 8.6% of kills. Filter
  `> 0` in any "longest kill" query.
- **`asset.attributes.URL` is uppercase.** It gates the entire replay feature.
- **`LogArmorDestroy` carries `victim`, never `character`.** Reading
  `character.accountId` silently drops every destroy (73 events, 0 deltas in a
  measured match — hidden for the feature's whole life by a unit test whose
  fixture invented a `character` field). The engine also emits a
  `LogItemUnequip` for the destroyed piece 0–1 ms around the destroy, in
  either same-millisecond order; unsuppressed it leaks the piece into the
  loose inventory. And telemetry carries **no armor durability anywhere** —
  the replay's armor bar is a corpus-fitted estimate (HANDOFF §12.4), never
  read it as exact.
- **`allWeaponStats` fields are `shots` and `hits`** (plus `dBNOHits`), not
  `shotsFired`/`hitCount`. Reading the wrong names produced `0` for all 5,978
  participants, and because the columns are NOT NULL, `count(shots_fired)`
  reported them fully populated. **`count()` of a non-nullable column proves
  nothing** — use `count(*) FILTER (WHERE col > 0)`. Coverage is also tiny:
  PUBG reports it for ~2 accounts per match and a *tracked* player in 3 of 65.
  **Since parser v10 it is no longer the source of accuracy** — see below.
- **`dBNOHits` is a *subset* of `hits`, not an addend.** The parser summed them
  for its whole life, on the reading that `hits` meant standing targets and
  `dBNOHits` knocked ones. Measured: `dBNOHits <= hits` on **547 of 547**
  weapon rows, and per-weapon derived hits match `hits` alone at median 1.00
  against 0.78 for the sum. It inflated **every accuracy figure the dashboard
  showed by 31%** — corpus `shots 32,821 / hits 5,592 / dBNOHits 1,757`, so
  17.0% displayed as 22.4%. Nothing caught it: `shots_hit` never exceeded
  `shots_fired` (0 rows of 9,041), so it stayed a plausible percentage, and the
  unit test guarding it was written from the same assumption as the code.
  Fixed in parser v9.
- **Accuracy is derived, not copied (parser v10).** `LogPlayerAttack` joined to
  `LogPlayerTakeDamage` on **`attackId`** reproduces PUBG's own per-weapon
  numbers at a median ratio of 1.000 (402 of 531 rows exact for shots, 444 of
  453 for hits) while covering **91.8% of human participants instead of 3.2%**.
  Three things make it correct, and each is a corpus test:
  - exclude attackIds that also appear in `LogPlayerUseThrowable` — a throw
    emits both events under one id, worth 4.7%. Resolve **after** the pass;
    they arrive in the same millisecond in either order.
  - join on `(attackId, attacker)`, and count only the linked subset. ~120
    attributed damage events per match have no attack, and `Damage_DBNO`
    bleed-out ticks are self-attributed with `attackId: -1`.
  - `shots_fired`/`shots_hit` are **trigger pulls, not pellets**. PUBG counts
    90 shots for 10 Berreta686 attacks, so a pellet ratio reads as several
    hundred percent accuracy on a shotgun. `PELLET_WEAPONS` exists only so a
    test can assert nothing *outside* it behaves that way.

  PUBG's own figures live on in `aws_shots`/`aws_hits` as a permanent oracle.
  A zero in `shots_fired` now genuinely means "fired nothing".
- **`LogWeaponFireCount.fireCount` is quantised to multiples of 10** and omits
  any weapon fired fewer than 10 times. It looks like an exact shot counter
  and is not — 99 real shots report as 120.
- **Every PUBG enum is open**, and casing changes between patches. Dispatch on
  lowercased names; never write an exhaustive switch without a default.
- **A typed-array view must start on a multiple of its element size.**
  `new Uint16Array(buf.buffer, buf.byteOffset, n)` throws a `RangeError` when
  `byteOffset` is odd, and msgpack packs the replay bundle's sections back to
  back with no padding, so the offset is effectively match data. Every one of
  the 65 bundles has at least one misaligned section, and which ones differ
  per match — this broke the replay for the entire archive. `replayBundle.ts`
  keeps the zero-copy path and falls back to a copy. Under Node, msgpack
  yields a `Buffer`, whose `.slice()` returns a **view**, not a copy; use
  `ArrayBuffer.prototype.slice`.

## Testing wire formats

A unit test whose fixture you wrote is not evidence about a wire format. The
`allWeaponStats` bug had a passing unit test the whole time — written from the
same invented field names as the code. **Assert against the corpus**, as
`tests/test_telemetry_combat.py` does: those tests skip cleanly when `data/`
is absent, so they cost a source-only checkout nothing.

The same rule holds on the frontend. `tsc`, `oxlint` and `npm run build` all
passed on a decoder that could not read a single bundle in the archive,
because none of them execute it — that is what `npm test` is now for, and why
the decoder has a corpus test as well as a synthetic one.

**`players` is not a list of tracked players.** It holds a row per human
opponent too (4,338 of 4,341 rows are untracked and never were tracked), which
is what makes opponent lookup and aggregate heatmaps free. "Players I stopped
tracking" is `untracked_at IS NOT NULL`, exposed as
`GET /players?formerlyTracked=true` — never `tracked = false`.

**An unknown player name 404s**, and the client's generic 404 text says
"unknown resource, or outside the 14-day retention window" — a true sentence
about matches and a misleading one about a name. `ingest/tracking.py` converts
any 404 into `PlayerNameNotResolved` so the answer names the real causes: PUBG's
name lookup is **case-sensitive**, or the account is on another shard. Two
different exception classes carry that same 404, so test the status code, not
the type.

**An `<img>` is natively draggable, which silently kills a pan gesture.**
Pressing a map tile starts an HTML5 image drag: the browser fires
`pointercancel`, the pointer stream stops, and the user drags a ghost thumbnail
instead of the map. `MapTiles` sets `draggable={false}` for this reason. The
kill map hid the bug by accident — its SVG overlay covers the tiles, so the
press never reaches an image — while the heatmaps, which have no overlay,
panned exactly one pointer event and stopped. `scripts/probe-map.mjs` checks it.

**Point a real browser at it before theorising.** Five frontend bugs in a
row were invisible to `tsc`, `oxlint`, `vitest` and the server logs — one
was a plain `TypeError` during render that React Router's error boundary
swallowed, taking the whole page with it, and it took ten seconds to find once
a browser was actually loading the page. The latest: every player dot drew
*player 0*, because the CSR cursors are zero-filled and index 0 is inside
player 0's row. A hundred dots stacked on one player looks like a quiet map
rather than a broken one — the tell was the alive counter reading 97 against a
bundle that says 51. `frontend/scripts/probe-replay.mjs` prints page errors,
failed requests and a DOM summary, and writes a screenshot. It takes a **match
id, not a URL**: `node scripts/probe-replay.mjs <matchId> --t=600 --shot=x.png`,
run from `frontend/` so node resolves `puppeteer`. HANDOFF §17 has the no-root
setup for a headless Chrome — note `/tmp` here is an **821 MB tmpfs**, so stage
the browser on `/`, or the download wedges every shell on the box.

It probes the deployed `dist/`, so **rebuild before probing** or you are testing
the previous build and concluding things about code that is not running.

## Error messages must not name a cause they have not checked

The replay page reported "no replay bundle for this match — it has not been
parsed yet" for *any* failure, including a decoder exception. All 65 matches
were parsed, so the message was provably false, and it read as a known
limitation rather than a defect. An error that guesses its own cause is worse
than one that says "failed" — it sends the reader somewhere else entirely.
Distinguish the cases you can actually tell apart (a 404/409 from the server
versus a client-side throw) and print the real error for the rest.

## .gitignore patterns must be anchored

An unanchored directory pattern matches at **any** depth. `telemetry/` in
`.gitignore` silently excluded `backend/pubg_dashboard/telemetry/` — the whole
parser package — from git for several sessions: working tree fine, tests
green, the pushed repository unrunnable. It is now `/data/telemetry/`.

`git status` staying quiet is not evidence a file is committed. `git ls-files
<path>` answers that, and `git check-ignore -v <path>` names the line to blame.

## Migrations

`alembic/env.py` lists partial and functional indexes in `HAND_MANAGED_INDEXES`
and excludes them from autogenerate, because Alembic does not compare a partial
index's WHERE predicate and would emit a plain full index that silently replaces
it. **Autogenerate will not create them — hand-write them at the bottom of
`upgrade()`,** as 0001 and 0002 do, and always inspect the generated file.

ON CONFLICT predicates must match the index predicate character for character or
Postgres will not infer the partial index.

## Deployment notes

Docker publishes ports by inserting iptables rules **ahead of ufw**, so a
`0.0.0.0` port mapping is reachable regardless of firewall rules. Postgres and
MinIO are bound to `127.0.0.1` in `docker/docker-compose.yml` for that reason.

Compose commands need `--env-file .env` — the compose file is in `docker/` while
`.env` is at the repo root, and it fails on the password guards without it.

There is **no authentication anywhere**; the API is on the LAN by explicit
decision. `/api/players` and `/api/ingest` mutate state and spend rate-limit
budget.

`data/` (raw corpus) and `assets/` (map tiles + cached sources) are gitignored
and regenerable — `data/` only within PUBG's 14-day window.
