# HANDOFF — start here

Written 2026-07-22 at the point where development moves from a Windows
workstation to the Ubuntu deploy server. If you are the next agent picking this
up: **read this file, then `docs/BUILD-SPEC.md`, then start at "What to do
next".**

> **Updated 2026-07-22, later the same day, on the Ubuntu server.**
> Phase 1 is integrated and runs end to end, **and the telemetry parser is
> built and wired**. Nine Phase-1 defects were found by executing it — every
> one at a module boundary, invisible to imports and to the tests. Sections 3,
> 5, 7 and 8 are rewritten; the rest still stands. The corpus was re-archived
> here and is now **65 matches**, not 61, so the oracle numbers changed. See
> §10 for what is verified and §11 for what is still missing.
>
> Two documents were found to be **wrong and have been corrected in place**:
> BUILD-SPEC gotcha #25 (parachute distance) was never true — it came from a
> rendering bug in `extract_schema.py` that hid every float value — and rule
> #10's backpack casing is out of date. Both are detailed in §12.

---

## 1. What this project is

A self-hosted PUBG dashboard for three tracked players — match archive, stats,
heatmaps, and a top-down telemetry-driven match replay. Full goals and design
direction in [`docs/PLAN.md`](docs/PLAN.md); the consolidated implementation
spec is [`docs/BUILD-SPEC.md`](docs/BUILD-SPEC.md).

Tracked players (Steam/PC): **AndAy**, **DaddyGainz**, **SIERIUS_**

| Layer | Choice | Status |
|---|---|---|
| Backend | Python 3.12+, FastAPI, asyncio, uv | ingest + parser + API done |
| DB | Postgres 16 (Docker) | migrated (0001, 0002), 65 matches loaded |
| Storage | MinIO (Docker) | running; 65 telemetry + 65 replay + 65 ledger objects |
| Frontend | React + Vite + TS + PixiJS | built; served from the API at `/` |

---

## 2. The most important thing to understand

**This project's dominant failure mode is silently wrong data, not crashes.**

PUBG's API is inconsistently cased, partially undocumented, and its public docs
are stale. Nearly every trap found so far produces *plausible* output rather
than an error — a K/D that's simply double, a heatmap that's mirrored, a replay
where everyone stands still. None of them throw.

So the working method here has been: **do not trust documentation, measure the
real data.** There are 61 real matches and 2.26M real telemetry events archived
locally. Every schema claim in this repo was checked against them, and doing so
overturned four things that web research had confidently asserted.

Keep doing that. When you need a fact about the API, query the corpus first.

---

## 3. Current state

### Done and verified
- `.gitignore`, `.env.example`, `.env` (has a working API key), `README.md`
- `docker/docker-compose.yml` — Postgres 16 + MinIO + bucket init
- `scripts/panic_archive.py` — archived **61 matches + 103 MB telemetry**
- `scripts/extract_schema.py` — derives real schema from the corpus
- `docs/reference/` — 9 documents. **`telemetry-observed-schema.md` is
  machine-generated from the corpus and outranks every other doc including
  PUBG's own.** The other 8 are web-researched and adversarially fact-checked.
- `docs/BUILD-SPEC.md` — final DDL, module design, replay bundle format,
  frontend tree, 34 gotchas, 9 open questions
- `backend/pyproject.toml`, `config.py`, `db/models.py` — the contract

### Phase 1 and the telemetry parser — built, run, verified

The integration pass has happened. `uv run pytest -q` is **636 passed, 1
skipped**, every module imports, and the whole pipeline has been exercised
against real Postgres and the live API. See §10.

`ingest/queue.py` and `queue/jobs.py` do both still exist, and the duplication
is real, but it was **measured, not assumed**: both build the same
`{kind}:{ident}` dedupe key and both dedupe correctly against the partial
unique index, so they interoperate. `queue/jobs.py` owns the full lifecycle
(claim/complete/fail/reap); `ingest/queue.py` owns bulk enqueue, which is
genuinely better for the poller (one statement for N matches instead of N).
Consolidating them is tidy-up, **not** a correctness fix — `tests/test_queue.py`
pins the behaviour of both first.

**The `telemetry/` package is complete** (BUILD-SPEC §3.6–3.12): `reader`,
`events`, `maps`, `frames`, `combat`, `world`, `inventory`, `heatmap`,
`bundle`, `parse`, plus `ingest/persist.py`. All 65 archived matches parse
and persist, and reparsing is idempotent. `parse_telemetry` is a real handler,
no longer a stub.

Still missing: `logging.py`, `backend/README.md`, `tests/test_client.py`,
`test_storage.py`, and the API + frontend (Phase 2/3).

### The Alembic migration — regenerated and applied
`backend/alembic/versions/0001_initial.py` now exists, generated against the
corrected `models.py` and applied to a real Postgres 16.

**Autogenerate omitted all 8 partial and functional indexes** — `env.py` puts
them in `HAND_MANAGED_INDEXES` on purpose, because Alembic does not compare a
partial index's WHERE predicate. They are hand-written at the bottom of
`upgrade()`. If you add another partial index, add it there too; autogenerate
will not.

The most important is `uq_jobs_dedupe_live`, the partial UNIQUE that is the
queue's whole idempotency story. Without it `ON CONFLICT DO NOTHING` has no
arbiter to infer and the poller re-enqueues every match on every cycle,
forever. All 8 were verified present in `pg_indexes` after `upgrade head`, and
`ck_players_human_only` with them.

---

## 4. Two schema defects that were found and fixed — do not reintroduce

Both were in `db/models.py`, both would have corrupted data permanently, and
both were caught only by measuring the corpus.

**1. Bot account IDs are match-scoped and recycled.**
`ai.<n>` ids are NOT stable identities. Measured: 98 of 106 distinct `ai.*` ids
(92%) recur across matches, and `ai.322` alone is **14 unrelated bots with 14
different names**. The original schema gave them `players` rows keyed by
`account_id`, which would merge dozens of bots into one fictional player and
FK real rows to it.
→ Fixed: `players` is human-only, enforced by
`CHECK (account_id LIKE 'account.%')`. `participants.account_id` has **no FK**.
Bots exist only as participant rows flagged `is_bot`.

**2. `NULL != NULL` breaks the heatmap upsert.**
`heatmap_bins` had a UNIQUE constraint over nullable `account_id`/`game_mode`,
where NULL meant "global aggregate". In Postgres that constraint never
conflicts, so `ON CONFLICT DO UPDATE` silently no-ops and every reparse appends
a fresh duplicate set of global bins — inflating heatmaps without ever erroring.
→ Fixed: `''` sentinels, NOT NULL, and the tuple promoted to the primary key.

---

## 5. Hard-won facts — verified live or against the corpus

Do not "fix" these back to something that looks more sensible.

1. Headers: `Authorization: Bearer <key>`, `Accept: application/vnd.api+json`.
2. Rate-limit headers are lowercase `x-ratelimit-{limit,remaining,reset}`.
   Confirmed limit **10/min**. `reset` is a **UNIX epoch**, not a delta — but
   sources disagree on units, so the limiter sniffs magnitude defensively.
3. `GET /matches/{id}` returns **no** rate-limit headers and is **not** limited.
   Never spend budget on it.
4. Telemetry CDN is **unauthenticated and unlimited**. Do not send the API key
   to it — needless leak into a third party's logs.
5. Telemetry URL is at `included[type=asset].attributes.`**`URL`** — uppercase.
   This single field gates the entire replay feature.
6. `roster.attributes.won` is the **string** `"true"`/`"false"`.
   `bool("false")` is `True` in Python and truthy in JS. Compare `== "true"`.
7. Participant stats have **exactly 23 fields**. `killPoints`, `winPoints`,
   `rankPoints`, `rankPointsTitle`, `killPlacePoints`, `winPlacePoints`,
   `mostDamage` **no longer exist**. Most online references still list them.
8. `killPlace` observed up to **107**. Do not constrain it to ≤ 100.
9. `teamId` is unique per match (verified, 61/61). Participants link to rosters
   via `roster.relationships.participants.data[]`, and `participants` has a
   composite FK to `rosters(match_id, team_id)` — **insert order must be
   players → match → rosters → participants** or it fails at runtime.
10. Bots: `accountId` starts with `ai.`, telemetry `character.type == "user_ai"`.
    ~20% of participants overall; **92.6% in TPP squad, 89% in TPP solo**; and
    **47% of the tracked players' kills**.
11. `common.isGame == 0.1` is **never true** — the wire value is
    `0.10000000149011612` (a 32-bit float widened). Compare with tolerance.
    This gates plane-phase detection and the movement-heatmap filter.
12. Erangel (`Baltic_Main`) world size is **816,000 units**, confirmed against
    320k in-play samples (median x≈400k, y≈394k). Positions during the plane
    phase legitimately fall outside `0..816000` and go negative.
13. **y is NOT inverted** — origin top-left, y grows downward, same as canvas.
    Flipping it yields a mirrored heatmap that still looks plausible.
14. Zone fields are semantically **inverted** from their names: `safetyZone*`
    is the **blue/current damaging** circle; `poisonGasWarning*` is the
    **white/next** circle. Interpolate blue; **snap** white (it's a step
    function). Getting this backwards looks almost right and is entirely wrong.
15. `redZone*` and `blackZone*` are **always 0** across all 9,150 game-state
    events — red zones are gone from current Erangel. Don't build that renderer.
16. `LogItemDrop` does **not** fire on death. The victim emits a
    `LogItemDetach` burst at +0–1 s and a `LogItemUnequip` burst at **exactly
    +60 s** (n=563). Applied naively, every dead player's gear evaporates a
    minute after death. Suppress item events for an account after its **final**
    death — and a player can die twice in comeback modes, so key on the *last*
    `LogPlayerKillV2`, not the first.
17. `LogPlayerMakeGroggy`/`LogPlayerRevive` are absent from solo matches
    entirely (55/61 and 53/61). Any parser assuming presence breaks.

Full list of 34 gotchas: `docs/BUILD-SPEC.md` §6.

---

## 6. Decisions already made by the user — do not relitigate

- **Stack**: FastAPI + Postgres/MinIO in Docker + React/Vite/TS/PixiJS.
- **Bots**: persist with `is_bot`; **stats default to human-only** with an
  "include bots" toggle; bots render dimmed in replay.
- **Career stats**: **`official` match type only.** `airoyale` and
  `tutorialatoz` are stored and replayable but excluded from aggregates.
  (Note: `BUILD-SPEC.md` §7 Q3 was written before this was decided and says
  airoyale is included — **this file is correct, the spec is stale there**.)

Still open — see `docs/BUILD-SPEC.md` §7 for the rest: raw telemetry retention,
ranked stats, map-tile strategy, auth model, double-death rendering.

---

## 7. The Ubuntu server — as actually set up

The move happened. The corpus was **re-archived on the server** rather than
rsynced, which cost nothing because it ran the same day: 65 matches / 111 MB,
0 failures, ~22 s. That is 4 *more* than the Windows box had, because the
tracked players kept playing. No rsync is needed unless matches archived
before 2026-07-08 matter, in which case they are already gone.

```bash
cd backend && uv sync --all-groups
uv run alembic upgrade head
uv run pubgd import-archive     # loads the archive, no API calls
uv run pubgd seed               # tracks the three players (1 token)
```

### What is installed, and what is not

`uv` is installed at `~/.local/bin/uv` (not on the default PATH for
non-login shells — `export PATH="$HOME/.local/bin:$PATH"`).

**Docker is not installed, and neither is node/npm.** Installing them needs
root, and this account's `sudo` requires a password nobody has typed. So:

* **Postgres 16.2 runs unprivileged** out of `~/pgdata_dev`, via the `pgserver`
  pip package, over a unix socket. `DATABASE_URL` in `.env` points at it:
  `postgresql+asyncpg://postgres@/pubg?host=/home/pubg/pgdata_dev`.
  It is a real Postgres 16 — partial indexes, `SKIP LOCKED`, `ON CONFLICT`
  inference all verified against it. Start it with:
  ```bash
  <scratch>/pg/bin/python -c "import pgserver; \
      pgserver.get_server('/home/pubg/pgdata_dev', cleanup_mode=None)"
  ```
  `cleanup_mode=None` is load-bearing — the default stops the server when the
  launching process exits.
* **Storage is the filesystem backend**, not MinIO, for the same reason.
  `STORAGE_BACKEND=filesystem`, telemetry under `data/telemetry/`.

Neither is the intended production shape. `docker/docker-compose.yml` still
describes it, and switching over is a `.env` change plus `alembic upgrade
head` against the new DSN — no code change, which is why the abstraction was
worth having. **Getting Docker installed is the main open infrastructure
task.** RAM is also tight for the intended stack: 1.6 GB total, 2 GB swap.

---

## 8. What to do next

Steps 1–4 of the original list are **done** (see §10). What remains, in order:

1. **Decide how the dashboard is reached.** The API binds to 127.0.0.1
   because **there is no authentication anywhere** and `/players` and
   `/ingest` mutate state and spend rate-limit budget. An SSH tunnel
   (`ssh -L 8000:localhost:8000 pubg@<host>`) works today with no change.
   Binding to the LAN means accepting unauthenticated access from it.
2. ~~Give `heatmap_bins` a `match_type` dimension.~~ **Done** — migration
   0003, parser v3. It carries the real match type with **no `''` "all"
   sentinel**, unlike `account_id` and `game_mode`: there are only three
   values, so "all types" is a query that omits the predicate and lets the
   existing SUM/GROUP BY aggregate. An `''` aggregate row would have doubled
   the table to save summing three rows. The API's `matchType` defaults to
   `official` so heatmaps and career stats now agree by default; pass the
   literal `all` for every type (a sentinel, not an empty string, because
   clients drop empty query parameters and a silently dropped filter would
   fall back to `official` while the UI claimed otherwise).

   Verified after reparse: for each tracked player, official-only binned
   kills == official `kill_events` rows == raw `kills`, exactly. The
   remaining gap to `kills_human` is the bot axis, which is a separate and
   deliberate distinction — heatmap bins count bots, career K/D does not.

   The migration **truncates the bins and clears the parse markers** rather
   than backfilling. Backfilling to one literal would mislabel the 12
   non-`official` matches, and the stored ledgers record contributions under
   the *old* key, so replaying one against the new key would subtract from
   rows that do not exist and drive bins negative.
3. ~~Frontend polish.~~ **Done** — see §13.
4. `logging.py` (structlog config) and `backend/README.md`.

### Settled — do not re-research
`X-RateLimit-Reset` is **UNIX epoch seconds**. Measured live on this key:
header `1784752312` against a request at `1784752251.9`, i.e. 60.1 s ahead.
Read as ms or µs it lands ~56 years in the past. Issue #61's "microseconds"
claim is wrong. Limit is **10/min**, headers lowercase. `ratelimit.py` already
treats it as seconds and clamps the hold, so it needs no change.
This closes BUILD-SPEC §7 Q1.

---

## 9. Repo map

```
docs/PLAN.md                 original project plan — goals, design direction
docs/BUILD-SPEC.md           implementation spec: DDL, modules, replay format
docs/reference/              9 verified API/telemetry references
  telemetry-observed-schema.md   <-- AUTHORITATIVE, generated from real data
scripts/panic_archive.py     archive matches before 14-day expiry (idempotent)
scripts/extract_schema.py    regenerate the observed schema from the corpus
backend/                     Python package (see §3 for what's real)
docker/docker-compose.yml    Postgres + MinIO (not running — see §7)
data/                        GITIGNORED — corpus, fixtures, telemetry
```

---

## 10. Verified on the server, 2026-07-22

Numbers below are **measured**, not asserted. Re-derive rather than trust if
anything looks off.

### The oracle changed: 65 matches, not 61
Counted straight from `data/matches/*.json` and compared against Postgres
after `import-archive`. Every figure matched:

| | oracle (files) | Postgres |
|---|---:|---:|
| matches | 65 | 65 |
| rosters | 2 800 | 2 800 |
| participants | 5 978 | 5 978 |
| bots | 1 129 (18.9 %) | 1 129 |
| humans | 4 849 | 4 849 |
| distinct human players | 4 341 | 4 341 |
| **`ai.` rows in `players`** | **0** | **0** |

Match types: 53 `official`, 8 `airoyale`, 4 `tutorialatoz`.
That last row is the §4.1 invariant, and it now has a test behind it.

### Commands that have actually run
`import-archive` (65/65, 0 failed, 6.3 s) · `seed` (3 tracked) ·
`poll --once` (3 polled, 1 request, 0 failed) · `worker` (68 jobs drained,
0 failures) · `jobs` · `stats`.

### The nine defects found by running it
All at module boundaries; imports and the pre-existing tests saw none of them.

1. `.env` could not be parsed at all — pydantic-settings JSON-decodes
   `list[str]` before validators run, so the documented `PUBG_SEED_PLAYERS`
   CSV raised `SettingsError` at import. Fixed with `NoDecode`.
2. `TELEMETRY_DIR=./data/telemetry` resolved against the **CWD**, so the
   importer silently reported all telemetry "missing" instead of failing.
3. `poller.select_due_players` filtered on `Player.is_bot`, a column that no
   longer exists → `AttributeError` on the poller's first cycle.
4. `_upsert_players` raised `CompileError: Unconsumed column names: is_bot`
   on **every** match — ingest failed 100 % of the time.
5. …and had a second branch inserting **bots into `players`**, the exact
   defect §4.1 says was removed, justified by an FK that no longer exists.
6. `import-archive` called `import_archive()` with no session.
7. `poll` called `run_poller(once=...)`; it takes the context positionally.
8. `worker` imported `pubg_dashboard.jobs.worker` (it is `queue.worker`) and
   never built a handler registry — it would have dead-lettered every job.
9. Nothing ever constructed an `IngestContext`, and neither the client nor the
   storage class satisfied its port. Fixed by `ingest/wiring.py`.

Plus one test bug: 131 failures the fresh corpus exposed were all
`roster.stats`, where `Roster` flattens to `.team_id` / `.rank`.

---

## 11. Still missing

* **No authentication anywhere.** The API binds to 127.0.0.1 for that reason.
  `/players` and `/ingest` mutate state and spend rate-limit budget, so put
  something in front of them before exposing the box (BUILD-SPEC §7 Q7).
* **Replay panels**: inventory (§4.5) and the match strip (§5.2) are not
  built. The bundle already carries the inventory delta track and keyframes,
  so it is frontend work only — no reparse needed.
* **Only Erangel and Camp Jackal are tiled**, because they are the only maps
  in the archive. `uv run scripts/fetch_map_assets.py` picks up any new map
  automatically; `--all` tiles everything (~600 MB of source).
* **No safe way to delete a match.** Deleting the row orphans its heatmap
  contribution, and a later re-ingest then double-counts those bins. The
  ledger in object storage makes a correct `pubgd match rm` straightforward;
  it just does not exist yet.
* `logging.py` (structlog config), `backend/README.md`,
  `tests/test_client.py`, `test_storage.py`.
* `data/fixtures/telemetry_event_samples.json` — `panic_archive.py` does not
  generate it, so one test still skips.
* Map tiles (`scripts/fetch_map_assets.py`) — needed before the replay can
  render anything but dots on a blank background.
* BUILD-SPEC §7 Q2–Q9 remain open. Q1 (rate limit) is settled in §8.

---

## 12. Documents that turned out to be wrong

Both were *corpus-verified claims* that did not survive re-measurement. Worth
reading before trusting any other single-sourced number in the spec.

**1. `extract_schema.py` was hiding its own evidence.** `FieldStat.observe`
collected enum candidates from `str`/`bool`/`int` only. Floats were counted in
`types` but never in `values`, and nothing recorded that they had been
dropped — so a field that is 99.7% float and 0.3% integer zero rendered as
`| distance | 1.00 | float/int | 0 |`, which reads as "the only value ever
observed is 0".

That manufactured **BUILD-SPEC gotcha #25**, "LogParachuteLanding.distance is
0 in all 61 archived matches", recorded as fact. It is false: 1,429 of 1,430
sampled events carry a real float distance (4.7–2,391.7 cm). **219 fields were
misrepresented this way**, the largest being `common.isGame`, which hid
213,056 float observations behind an integer-looking enum — those floats being
exactly the `0.10000000149011612` plane-phase marker that gotcha #21 is about.
The authoritative document was concealing the evidence for its own subtlest
trap. Fixed: fields now render "plus N non-enumerated (float) value(s)".

**2. Backpack casing (BUILD-SPEC §3.11 rule 10).** The spec says `"BackPack"`
(capital P) on the current patch; PUBG's enum file says `"Backpack"`. The
corpus emits **`"backpack"`, entirely lowercase**, 12,521 times, and no other
spelling appears. Three spellings from three sources — which is the argument
for normalising rather than tracking whichever is current.

**3. `allWeaponStats` was read with field names PUBG does not send.**
Found 2026-07-22 while building the accuracy stat. `combat.py` read
`shotsFired` and `hitCount`/`shotsHit`; the wire format is **`shots`** and
**`hits`** (plus `dBNOHits`, `damage`, `dBNODamage`, `holdingTime`,
`hitDetails`). Every lookup missed, so `shots_fired` and `shots_hit` were
`0` for all 5,978 archived participants.

It hid the way everything here hides. The columns are NOT NULL, so
`count(shots_fired)` returned 5,978 and read as "fully populated" — the
number was checked, and the check confirmed the wrong thing. Ask for
`count(*) FILTER (WHERE shots_fired > 0)` instead; it returned 0.

`tests/test_telemetry_combat.py` had a unit test for this, and it passed,
because it was written from the same assumption as the code — a
hand-written fixture using the same two invented names. **A unit test whose
fixture you wrote is not evidence about a wire format.** There is now a
corpus-backed regression test beside it that fails on a corpus-wide zero,
and a second one asserting the old names produce nothing, so no one
"restores" them as a fallback.

Two things were measured while diagnosing it, both worth keeping:

* **`LogWeaponFireCount.fireCount` cannot substitute.** It is a periodic
  ping quantised to multiples of 10 — checked against `allWeaponStats` on
  the same matches, 99 real shots report as 120, 63 as 60, 276 as 270, and
  a weapon fired fewer than 10 times is never reported at all. It looks
  like an exact counter and is not.
* **Coverage is severe and is the real limit.** PUBG populates
  `allWeaponStats` for a median of **2 accounts per match** (max 4 across
  the archive), and for a *tracked* player in only **3 of 65 matches**.
  Fixing the names made the data correct without making it available. So
  `shots_fired == 0` means **"not reported"**, never "fired nothing", and
  every surface treats it that way: the player page prints "—  not
  reported by PUBG" rather than a headline 0%.

Parser bumped to v2 for the fix (v3 for the heatmap change below).

---

## 13. UI overhaul, 2026-07-22

Plan and audit: [`docs/UI-OVERHAUL.md`](docs/UI-OVERHAUL.md). The prompt was
that the dashboard under-delivered — most sharply that the recent-matches feed
did not say **which tracked player played or where they finished**, which are
the two facts the page exists to convey.

### The feed fix
`GET /api/matches` never touched `participants`. It now returns `MatchFeedRow`
with the tracked roster's placement, per-player kills (human-only, with the raw
figure alongside), knocks, damage, and who killed them with what — the last
resolved through a `participants` self-join, because ~19% of killers are bots
and bots have **no `players` row at all**, so joining there would blank them.

Two facts shaped it, both measured rather than assumed:

* The three tracked players are **always on the same roster** when they play
  together — 0 counterexamples across the archive, 48 of 65 matches have ≥2 of
  them. So a row carries **one** placement and per-player kill counts, not
  three competing placements.
* The feed is **two statements, not one join**. Joining tracked participants
  before `LIMIT` multiplies each match by the number of tracked players in it,
  so a page of 20 silently returns 8 matches on a night all three squadded.
  There is a test for this.

### New API surface
`/api/overview` (the whole home page in one request — was five),
`/players/{id}/placements`, `/players/{id}/nemeses` (humans only, and not a
toggle: `ai.<n>` ids are recycled, so grouping kills by one invents a single
arch-enemy out of dozens), `/players/{id}/sessions`, `kd` and `accuracy`
metrics on `/timeseries`, kill/killer **positions** on `/matches/{id}/kills`
(stored since the parser was written, never previously served), and
`matchType` on `/heatmap`.

### Efficiency, measured
* **GZip middleware.** The heatmap was 349,638 B and ignored `Accept-Encoding`
  entirely; it is now **31,381 B**. Starlette skips responses that already
  carry `Content-Encoding`, which is what keeps it from re-compressing the
  replay bundle — there is a test that unpacks the bundle to prove it.
* Overview: 5 requests → 1.
* Recharts (415 KB) is behind a lazy route. The home page's sparklines are a
  hand-rolled 12-line SVG precisely so the first paint does not wait on a
  charting library.
* Match detail prefetches on row hover with `staleTime: Infinity` — a parsed
  match is immutable by construction.

### Frontend
Nav now carries the three players (they *are* the app). New `/matches`
archive browser with keyset pagination, and `/compare`. Identity colours
assigned by **sorted account id**, not array position, so a fourth tracked
player cannot recolour the other three. Placement is graded identically
everywhere via `lib/players.ts`; form strips, map-tile thumbnails and heroes.
Match page gained a kill map drawn from the stored positions — **no y flip**,
`imageScale` applied. Replay gained the match strip (alive-count curve, kill
ticks, phase boundaries), an inventory panel, knocks/revives in the feed, and
`?t=`/`?follow=` deep links.

**The inventory panel folds deltas from zero**, which BUILD-SPEC §5.3 warns
against. The warning is about resolving *every* player *every frame*; this
resolves one player at 10 Hz, memoised per whole second, over a few thousand
deltas. The bundle ships the delta track but **not** the parser's keyframes,
so there is nothing to rewind to — adding them is the alternative if this ever
gets hot.

### State
`uv run pytest -q` — **783 passed, 1 skipped**. `ruff`, `tsc`, `oxlint` clean.
`mypy` still not a gate (see CLAUDE.md). Parser is **v3**; all 65 matches
reparsed. Migration head is **0003**.

---

## 14. The replay never worked in a browser — fixed 2026-07-23

Reported as "there is no replay bundle for any match". The bundles were
fine: 65/65 present in object storage, correct size, valid gzip, valid
MessagePack, every section intact. **Nothing could read them.**

`lib/replayBundle.ts` wrapped each `bin` section in place —
`new Uint16Array(buf.buffer, buf.byteOffset, n)` — for zero-copy decoding.
But a typed-array view **must begin on a multiple of its element size**, and
msgpack packs sections back to back with no padding, so where a section lands
depends on the byte length of everything before it, which is match data.

Measured across the whole archive: **every one of the 65 bundles has at least
one misaligned section**, and which ones differ per match (`pos.t` here,
`pos.off` and `zones.t` there). The pre-fix decoder throws on **65 of 65**;
the fixed one decodes **65 of 65**, verified by running the real
`decodeBundle` source over every bundle and cross-checking values against a
`DataView` oracle, which has no alignment constraint.

Fix keeps the zero-copy path and falls back to a copy when the offset is
odd — once per bundle load, largest section ~28 KB, not worth padding the
format for. Note `ArrayBuffer.prototype.slice`, not `TypedArray.slice`: under
Node msgpack yields a `Buffer`, whose `.slice()` returns a *view*, and that
detail silently defeated the first attempt at the fix.

### Why it survived this long

* **`tsc`, `oxlint` and `npm run build` all pass.** There is no frontend test
  runner at all, so nothing executes the decoder. This is the largest gap in
  the project's testing story: the backend has 783 tests and the flagship
  feature had none.
* **The error message named a cause it had not checked.** Any failure —
  including this exception, thrown inside the react-query `queryFn` —
  rendered "no replay bundle for this match, it has not been parsed yet".
  Every match *was* parsed, so the message was false, and it read as a known
  limitation. It now distinguishes a 404/409 from the server (genuinely
  missing) from a client-side throw (prints the real error), and separately
  reports missing map tiles instead of rendering dots on a void.

### Closed: the frontend now has tests

**vitest, node environment, no jsdom** — deliberately. Every bug this
frontend has actually shipped lived in a pure function, so jsdom would buy
brittle render tests and a large dependency for a class of bug this codebase
does not have. `npm test`, or `npm run check` for typecheck + lint + test.

32 tests over the decoder, the identity-colour/placement logic and the
formatters. Two layers, matching the backend's split:

* `replayBundle.test.ts` — hermetic. Encodes bundles with a padding string
  whose length walks every section through both byte parities, which is
  exactly how real alignment ends up being a function of match data. Also
  pins the big-endian refusal, the dictionary fallback, and that a realigning
  copy does not alias two sections onto each other.
* `replayBundle.corpus.test.ts` — decodes **real** bundles from the running
  API and **skips cleanly when it is absent** (`PUBGD_API_BASE` to redirect),
  the same convention `tests/conftest.py` uses for Postgres. Checks the CSR
  offset array covers the position arrays exactly, that per-player tick
  cursors never go backwards, that health never exceeds 100, and that the
  bundle's kill count equals `kill_events` — the two being separate outputs
  of one parse, so disagreement means one is being read wrong.

**Verified to catch the bug**: reverting the alignment fix fails 9 tests,
including all 3 corpus tests. A regression test that does not fail on the
regression is worth nothing, so this was checked rather than assumed.

One unrelated inconsistency surfaced while writing them: `duration()`
zero-padded seconds but not minutes, so "1h 0m" misaligned against "1h 30m"
in the `tabular-nums` columns. Fixed.

---

## 15. Lazy-route CSS leaked globally — fixed 2026-07-23

Reported as: the recent-matches list is fine on first load, but after
navigating away and back the formatting collides and is unreadable.

`.feed-row` was declared in **two** stylesheets — `components/MatchFeed.css`
(the home page's match rows, `display: flex`) and `pages/Replay.css` (the
replay kill feed, `display: grid; grid-template-columns: 42px 1fr auto 1fr`).

Vite injects a lazily-loaded chunk's stylesheet when the chunk first loads and
**never removes it**. `Replay.css` ships in the lazy Replay chunk, so it does
not exist on a fresh load — the home page is correct. Open a replay and the
sheet is injected permanently; navigate back and the match feed's five-column
rows are now being laid out by a four-column grid meant for something else.

That load-order dependence is why it looked intermittent and why a fresh
reload always "fixed" it.

**Fix:** every selector in `pages/Replay.css` is scoped under `.replay`, the
page root. `.replay-error` is the one exception — it renders *instead of*
`.replay`, never inside it — and is declared as such in the test.

`src/styles/css-scope.test.ts` enforces two rules and both were verified to
fail when the offending declaration is restored:

1. every selector in a `pages/*.css` sheet sits under that page's root class,
   and a new page stylesheet must opt into a declared scope rather than
   silently becoming global;
2. no class is declared globally by two stylesheets at all.

### TypeScript projects split three ways

The scope test reads stylesheets off disk, which needs `node` types — and
`tsconfig.app.json` deliberately has none, so that app code cannot reference
`process` or `node:fs` and crash in a browser. Rather than weaken that,
tests got their own project (`tsconfig.test.json`) with the Node types, and
`tsconfig.app.json` now excludes `src/**/*.test.ts`. Verified both ways: a
`process.env` added to `src/lib/format.ts` still fails the build.

Worth noting the first attempt at this **silently produced a stale `dist/`**:
`npm run build` is `tsc -b && vite build`, so the type error aborted the
build and left the previously-built assets in place, which still contained
the unscoped CSS. Check that `build` actually reached the vite step before
believing a fix shipped.
