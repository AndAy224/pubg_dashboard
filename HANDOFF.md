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
    events. ~~Red zones are gone from current Erangel. Don't build that
    renderer.~~ **That conclusion was wrong** — see §26. The *fields* are dead;
    the feature moved to `LogSpecialZoneInCharacters`, where 19 of 20 matches
    carry seven complete lifecycles. The renderer shipped in parser v12.
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

**4. `LogArmorDestroy` was read from a field it does not have.**
Found 2026-07-23 while adding armor condition to the replay inventory. The
event carries `attacker` and `victim` — **never `character`** — but
`InventoryTracker.feed` derives its account from `character.accountId`, so
every destroy read an empty account and fell through: 73 destroy events in a
measured match, **0 `OP_ARMOR_DESTROY` deltas**, across the feature's whole
life. The unit test passed the entire time because its fixture invented a
`character` field — the same failure as #3, in the other direction: the
fixture was written from the code's assumption instead of the wire's shape.

Two adjacent facts, measured while fixing it:

* **The engine emits `LogItemUnequip` for the destroyed piece 0–1 ms around
  the destroy, in either sort order** (same-millisecond ordering is a
  lottery). Unsuppressed, the destroyed helmet either leaks into `loose` as a
  phantom item or wipes the slot the destroy is about to report on. The
  parser now drops unequips within 100 ms of a matching destroy
  (`suppressed_destroy_unequips` counts them).
* **Telemetry carries no armor durability anywhere**, and it cannot be
  reconstructed exactly: armor looted off a corpse keeps its unknown prior
  wear, and hits on knocked players report `damage: 0` (285 of 288 zero-damage
  protected gun hits in one match were DBNO victims). What *does* hold, fitted
  over every clean destroy in the corpus: per-hit durability loss equals raw
  damage — `damage / (1 − mitigation)` — median ~43 at every level, and the
  fitted max durabilities contradict the wiki (Lv2 helmet ≈ 150, not 100).
  So the replay ships an exact hit count plus a percent clearly labeled an
  estimate (`OP_ARMOR_HIT`, parser v8), never a precise-looking durability.

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

---

## 16. The replay canvas rendered nothing — fixed 2026-07-23

Reported as "the match replay has no map rendering". The canvas was
**completely black** — no map, no player dots, no zone circles — while the
kill feed and team list in the rail worked normally.

That combination is the diagnosis. The kill feed reads `nowMs` from the
external store, which is only written by `Renderer.drawFrame` → `publish()`.
A populated feed proves the clock was running, the frame loop was completing
and the renderer had constructed successfully. So the failure was not in the
replay logic at all; it was that Pixi drew nothing.

**Cause: `gridLayer.cacheAsTexture(true)`.** It rasterises a container at its
own bounds, and the grid spans the whole world — 8192x8192. That is a 268 MB
RGBA render texture at devicePixelRatio 1, and 16384x16384 (1.07 GB, past the
maximum texture dimension on most GPUs) at dpr 2 — to cache **fourteen
straight lines**. Pixi's own render runs as a separate, lower-priority ticker
listener, so when the allocation failed it threw inside Pixi's render pass
while our `drawFrame` listener carried on publishing to the store. Hence:
live panels, dead canvas. The cache is gone; fourteen lines cost nothing to
redraw each frame.

### Three silent-failure modes closed with it

* **`Assets.load(...).catch(() => Texture.EMPTY)`** turned any tile-loading
  problem into a blank map with no error anywhere — a missing map is not
  visually distinguishable from a dark one. Now `Promise.allSettled`, and
  failures are reported to the UI.
* **`Viewport.fit()` could scale the world by 0.** Pixi defers its first
  `resizeTo` resize to an animation frame, so the canvas can still be
  zero-sized when the renderer is built; `min(0,0)/8192` is 0, which collapses
  every layer to a point and renders a perfectly black canvas while everything
  else keeps working. It now defers and retries.
  `src/replay/engine/Viewport.test.ts` pins this — 4 of its 7 tests fail when
  the guard is removed.
* **A non-finite `scale` or `maxZoom` poisoned `onZoom` permanently.** `wanted`
  became NaN, the tile loops never ran, and `tileLevel !== wanted` is always
  true for NaN, so it returned having drawn nothing and left `tileLevel` NaN
  forever after.

The renderer now takes an `onError` callback and the page shows a real message
over the canvas instead of a black rectangle. The Pixi init promise is also no
longer floating — a WebGPU failure used to reject into nothing.

## The replay rail was rebuilt around the loadout

Selecting a player to see their loadout inserted a third panel between the
kill feed and the team list, pushing the list down — so the one action that
makes you want to switch players was also the one that made switching hard.

The loadout is now a card **on the canvas**, next to the player it describes,
with the followed player's name and a close button. The rail holds two panels:
the kill feed (capped at 44% of the height) and the team list (takes the
rest). Both scroll independently and neither can displace the other, so the
team list never moves.

---

## 17. The replay page threw on every cold load — fixed 2026-07-23

After §16 the canvas was still black. The actual cause was a **crash**, not a
rendering problem:

```
TypeError: Cannot read properties of undefined (reading 'toUpperCase')
```

`gameMode('')` — `''.split('-')` is `['']`, so `p[0]` is `undefined` and
`p[0]!.toUpperCase()` threw. The `!` silenced TypeScript at exactly the point
where the value really is undefined. The call site is the replay's TopBar:
`gameMode(match?.gameMode ?? '')`, which passes `''` for as long as the match
query is in flight. The throw happened during render, so React Router's error
boundary swallowed the **whole page** — canvas included.

That is why it presented differently at different times: arriving from the
match page, react-query already had the match cached and nothing threw;
hard-reloading the replay URL threw every time. Fixed, with tests for the
empty, null and malformed cases.

### Two more things fixed once the page could render

* **Camera clamping.** Following a player near the coast dragged the island
  into a corner and filled most of the canvas with background. `Viewport`
  now keeps the map covering the viewport, centring on an axis where the world
  is smaller than the canvas.
* **`itemName`.** The loadout showed `Item Attach Weapon Muzzle AR
  MuzzleBrake` and `Item Head F 01 Lv2`. `weaponName` only strips weapon
  decoration. `itemName` handles attachments, armour (reduced to its tier —
  the model letter and number mean nothing, and the slot label already names
  the piece), heals and ammo, and still falls back to the raw id.

## Getting a browser onto this box, with no root

Three frontend bugs in a row were invisible to `tsc`, `oxlint`, `vitest` and
the server logs, and each cost a round trip to diagnose by reasoning. The last
took ten seconds once a browser was actually pointed at the page. **Do this
first next time.** `frontend/scripts/probe-replay.mjs` is the harness; it is
not in `npm test` because it needs a browser and a running API.

The box has no browser and `sudo` needs a password nobody has. It is still
entirely doable:

```bash
S=$HOME/.cache/probe && mkdir -p $S && cd $S    # NOT /tmp: it is an 821 MB
                                                # tmpfs, and filling it wedges
                                                # every shell on the box
# 1. Chrome for Testing. `npm i puppeteer` fails here: its extractor needs
#    `unzip`, which is not installed. Fetch and unpack it directly instead.
curl -sSL -o chs.zip https://storage.googleapis.com/chrome-for-testing-public/150.0.7871.24/linux64/chrome-headless-shell-linux64.zip
python3 -c "import zipfile;zipfile.ZipFile('chs.zip').extractall('chrome')"
chmod -R +x chrome/            # zipfile drops the executable bit

# 2. Its shared libraries. `apt-get download` needs no root, and `dpkg-deb -x`
#    unpacks anywhere.
mkdir -p debs libs && cd debs
apt-get download libasound2t64 libatk1.0-0t64 libatk-bridge2.0-0t64 \
  libatspi2.0-0t64 libgbm1 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
  libxkbcommon0 libpango-1.0-0 libcairo2 libnss3 libnspr4 libcups2t64 libdrm2 \
  libxshmfence1 libxrender1 libxext6 libxi6 libxtst6 libexpat1 libfontconfig1 \
  libfreetype6 libpangocairo-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libfribidi0 \
  libthai0 libdatrie1 libgraphite2-3 libpixman-1-0 libxcb-render0 libxcb-shm0 \
  libxres1 fonts-dejavu-core
for d in *.deb; do dpkg-deb -x "$d" ../libs; done
cp -r ../libs/usr/share/fonts/truetype/dejavu/* ~/.local/share/fonts/   # or no text renders

# 3. Run it.
export LD_LIBRARY_PATH=$(find $S/libs -name '*.so*' -printf '%h\n' | sort -u | tr '\n' ':')
export CHROME=$S/chrome/chrome-headless-shell-linux64/chrome-headless-shell
cd <repo>/frontend && PUPPETEER_SKIP_DOWNLOAD=1 npm i puppeteer   # binary already present
node scripts/probe-replay.mjs <matchId> --t=600 --shot=$S/replay.png
```

Revert `package.json`/`package-lock.json` afterwards — puppeteer is an
ad-hoc tool here, not a dependency of the app, and `node_modules` keeps it
for the rest of the session either way. Mouse-wheel events time out under
swiftshader, so drive zoom through the app rather than `page.mouse.wheel`.

`--enable-unsafe-swiftshader --use-gl=angle --use-angle=swiftshader` gives
real WebGL with no GPU. WebGPU is unavailable and logs "No available
adapters"; Pixi falls back to WebGL on its own, so that warning is expected
and harmless.

---

## 18. Blurry map, anonymous dots — fixed 2026-07-23

**The tile level was three steps too low.** `onZoom` chose it with
`ceil(log2(scale * 2))`, which accounts for neither the tile size nor the
device pixel ratio. At fit on a 900px canvas that picks level 0 — a single
512px tile stretched over 900 CSS pixels, or 1800 on a retina display. The
tiles were always fine; the wrong one was being asked for.

Level z is a 2^z grid of `tilePx` tiles, so the map is `tilePx * 2^z` pixels
and covers `worldPx * scale * dpr` device pixels. The level is now
`ceil(log2(worldPx * scale * dpr / tilePx))`, and `tilePx` is threaded through
from the manifest. Verified with the headless probe: dpr 1 requests level 1
(4 tiles), dpr 2 requests level 2 (16 tiles), both ~1.14x the displayed
resolution.

**Dots had no identity.** Every tracked player rendered the same flat white,
so on a hundred-dot map you could see that one of your squad was there but
never which one. They now wear their **identity colour** — the same hue as
their nav entry, match-feed chip and trend line — plus a white ring, and a
name label. Untracked players get a label once you zoom past `LABEL_SCALE`;
below that a hundred names overlap into noise. Labels are counter-scaled by
`1/viewport.scale` so they stay a constant size, and built lazily, since a
hundred `Text` objects up front is a hundred canvas rasterisations that mostly
never show. The team list shows the same coloured dot beside each tracked
name.

Note `registerPlayers` is called **during render** in `Replay.tsx`, not in an
effect: the replay route mounts outside `AppShell` (which registers the
palette everywhere else), and child effects run before parent effects, so
`ReplayCanvas` would otherwise build its dots before the colours existed.

---

## 19. Combat tracers — added 2026-07-23

"Show gunshots that hit players so we can see combat." `LogPlayerTakeDamage`
is the only event carrying **both** the attacker's and the victim's position,
which is exactly what a tracer needs.

### Measured before building

| | |
|---|---:|
| damage events per match | ~5,000 |
| of which blue-zone (no attacker) | **63%** |
| attributed combat hits per match | ~550 |
| bundle cost | 126 KB -> **132 KB** gzipped |
| median engagement distance | **26 m** |
| hits under 15 m | **31%** |
| hits under 5 m | 8% |

Parser v4 emits a `hits` section as parallel typed arrays (`t, a, v, ax, ay,
vx, vy, dmg, dr, w`), not the map-per-entry shape `_event_track` uses — this
is an order of magnitude more entries. Blue-zone and self-damage are dropped
at collection, and `_TRACER_TYPES` filters the rest so a tracer always means
"someone shot someone".

### The 31% is why both ends are marked

A third of hits land inside 15 m, so at any sane zoom the *line* is a few
pixels and cannot show that a fight is happening. Every marker is therefore
divided by `viewport.scale` and keeps a **constant size on screen**: a muzzle
flash at the shooter, a larger impact at the victim, an expanding ring on the
freshest hits. A point-blank exchange still reads as two bright pulsing marks.
Headshots are red; anything involving a tracked player is amber and brighter.

`TRACER_MS` is **match** time, not wall-clock: at 20x the replay covers 20 s
per real second, and a wall-clock fade would leave every tracer of the last
several seconds on screen at once.

### Dots were 1.1 pixels

Found while checking this: `DOT_R * 2` is 10 **world** units, and the dot
layer sits inside the scaled world container. At fit on Erangel the scale is
~0.11, so a player rendered **1.1 pixels across**. "I don't know which dots
are which" was not ambiguity, it was near-invisibility. Dots are now
counter-scaled like every other marker.

### Verifying this needed the renderer handle

Four probe attempts showed no tracers and all four were the probe's fault —
the camera was pointed somewhere else, or the moment was between bursts.
`ReplayCanvas` now exposes `window.__replay`, and `drawTracers` was confirmed
by reading live state (`drawn: 7` at tick 2900) *before* any screenshot
matched. Then aiming the camera at the hit's own coordinates produced the
picture. **Instrument first, screenshot second** — a blank screenshot proves
nothing about the code.

### The parser package was never in git

Found while committing the above: `git status` showed no backend changes even
though `combat.py` and `parse.py` had clearly been edited.

`.gitignore` contained an **unanchored** `telemetry/`. That matches a
directory of that name at *any* depth, so it silently swallowed
`backend/pubg_dashboard/telemetry/` — the whole parser, eleven files, 2,954
lines. It had never been committed and never pushed. The working tree was
fine, `uv run pytest -q` was green against it, and the repository on GitHub
could not have run.

Fixed by anchoring the pattern to `/data/telemetry/`. A leading slash is the
whole difference. A sweep of every source file in the tree confirmed this
package was the only casualty.

Worth internalising: this project's rule is "measure, do not assume", and
`git status` being quiet was taken as "nothing to commit" for several
sessions. `git ls-files <path>` answers the actual question — whether a file
is tracked — and `git check-ignore -v <path>` names the offending line.

---

## 20. Full git audit, 2026-07-23

Prompted by §19's discovery that the parser package had never been committed.
Verified against a **fresh clone of the pushed repository**, not by reading
`.gitignore`:

| check | result |
|---|---|
| files in the working tree absent from the clone | **`.env` only** (correct — it holds the API key) |
| files in the repo but not locally | none |
| backend internal imports resolving to a file in the clone | 170/170 across 69 files |
| frontend relative imports resolving | 103/103 across 34 files |
| `npm run typecheck` / `oxlint` / `vitest` / `vite build` in the clone | clean, **55 tests pass** |
| `uv sync && pytest` in the clone | **160 passed, 48 skipped, 0 failed** |
| `pubgd --help`, `alembic heads` | work; all three migrations present |

The 48 skips are the intended contract — corpus and tile tests skip cleanly
when `data/` and `assets/` are absent, so a source-only checkout is green.
(The working tree reports 783 because the corpus parametrises many tests
across 65 matches.)

### Two more dead `.gitignore` rules

`!data/.gitkeep` and `!assets/.gitkeep` could never fire: **git does not
descend into an excluded directory**, so a negation beneath a bare `data/` or
`assets/` is unreachable. Both are now `data/*` / `assets/*`, which excludes
the *contents* while leaving the directory visible for the negation, and the
placeholders are committed so a clone gets the directories.

Nothing depended on this — `storage/filesystem.py` does
`mkdir(parents=True, exist_ok=True)` — but a `.gitignore` that states an
intent git cannot honour is exactly the kind of quiet wrongness that hid the
parser package for weeks.

**The lesson worth keeping:** a quiet `git status` is not evidence. Use
`git ls-files <path>` to ask whether a file is tracked and
`git check-ignore -v <path>` to find the rule to blame — and when it matters,
clone the remote and run it.

---

## 21. Health on the replay map — added 2026-07-23

Player dots now carry a **radial health ring**, like the in-game replay: a dark
track with an arc sweeping clockwise from 12 o'clock, green above 60, amber
above 25, red below. The rail's team list gained a matching bar and the exact
number, on its own store subscription. A knocked player is a **full red ring**.

The ring only appears when it says something — full health draws nothing. At
fit zoom a hundred rings is solid clutter over the map, and "everyone is fine"
is not worth a hundred marks; the ring appearing *is* the signal.

`pos.hp` was already in every bundle and had never been drawn. Wiring it up
took a parser version bump anyway, because all three of the things it needed
were wrong, and every one of them rendered plausibly.

### `LogPlayerTakeDamage.victim.health` is the health *before* the shot

Measured across the corpus by comparing consecutive damage events on the same
victim: **1,900 pairs agree with `health - damage`, 134 with `health`**. Stored
raw — which is what `frames` did — a player reads at their fullest for up to
the full 10 s position interval *starting from the instant they are hit*, which
is precisely the moment someone is watching them. `LogHeal` is the same shape:
`character.health` is pre-heal, 295 pairs to 2.

### `LogHeal` was not a health source at all

It is the **third most common event in a match** (~4,000 of 37,000) and fires
once per heal tick — which is to say, exactly and only when health is moving
upwards. Without it a player who bandages from 20 to 100 read as 20 until the
next position report.

Taking every tick cost **+40% samples and +21% bundle** to animate a bar a few
pixels tall, because most ticks are +1 of boost regeneration. They are now
thinned on *health delta* (`HEAL_MIN_DELTA`, 5 points), not on time — the
renderer steps health rather than interpolating it and each kept sample resets
the baseline, so the drawn value trails the true one by strictly less than the
threshold. That is a statable error rather than a hopeful one. Cost is now
**+1.7% bundle**. Damage is never thinned; a hit is when the number matters.

### `FLAG_ALIVE` meant `health > 0`, and knocked players report `health: 0`

31,153 of 31,156 DBNO snapshots sit at exactly 0. So every knocked player was
flagged dead and the renderer hid them — `LogPlayerPosition` keeps firing while
knocked, so those dots existed and were simply never drawn. In a squad mode the
knock is most of the story, and `Renderer`'s `dbno ? 0.5 : 1` alpha branch had
never been reachable.

**And it cannot be fixed in the renderer.** At `LogPlayerKillV2` the victim's
`isDBNO` is **true in 51% of deaths** (979 of 1,918), so "alive or knocked" as
a visibility test leaves half of every lobby's corpses on the map forever as
knocked players who never get up. Only the final death time separates the two,
and only the parser knows it. `FLAG_ALIVE` now means *still in the match*,
resolved in `FrameIndex.build`; `FLAG_DBNO` implies it.

Stated limit: between an earlier death and a respawn a player still reads as in
the match. Telemetry has no respawn event and no archived match is a comeback
mode, so there is nothing to measure the gap against.

### Every dot was drawing player 0 — a pre-existing renderer bug

Found only because the health ring made it visible. `Renderer`'s per-player CSR
cursors are a zero-filled `Int32Array`, and **index 0 is inside player 0's
row**, so until something triggered `resetCursors` every player read player 0's
position, health and flags. `resetCursors` runs only on a *backwards* seek, so
a fresh load — the common case — never corrected it.

A hundred dots stacked on one player looks like a quiet map, not a broken one.
The tell was the counter: the top bar said **97 alive** where the bundle says
**51**, with 50 kills already in the feed. Cursors are now seeded at `off[p]`.
After the fix the browser reports 51, matching the bundle exactly.

This is the fourth replay bug in a row that `tsc`, `oxlint` and `vitest` all
passed. **Point a browser at it.** §17 has the no-root setup — note `/tmp` on
this box is a **821 MB tmpfs**, so stage Chrome somewhere on `/` (there is 60 G
free) or the download will wedge every shell on the machine.

---

## 22. Steering wheel for players in a vehicle — added 2026-07-23

The dot's square swaps to a **steering wheel** glyph while the player is in a
vehicle: rim, three spokes, hub, drawn white over a fat black pass and tinted
with the player's identity colour. It replaces the square rather than sitting
on it, so the marker still carries exactly one colour and no other ring has to
move — it occupies the same footprint the existing 1.4x in-vehicle enlargement
already used. Rasterised once via `generateTexture` and shared by every dot; if
that fails the renderer reports it and keeps plain squares.

### `isInVehicle` is true for the whole lobby at match start

The transport aircraft is a vehicle. Keyed on `FLAG_IN_VEHICLE` the marker puts
a steering wheel on **all 99 players** before anyone has landed — verified by
screenshot, then verified absent after the fix.

Across the corpus, **3,261 of 7,635 in-vehicle position samples (43%) are not
something you drive**: the match-start aircraft, the flare-gun redeploy plane,
the emergency pickup balloon, and a mounted mortar.

**Match phase is not a usable proxy, and this is the part worth remembering.**
It looks like one — plane phase is when everybody is on the aircraft — but it
is wrong in both directions:

* **28 aircraft rides happen mid-match.** Flare-gun redeploys are real;
  `LogParachuteLanding` fires as late as `isGame` 5.
* **17 car rides happen during the plane phase.** `isGame` is still 0.1 for a
  while after the first players land, so suppressing by phase hides genuine
  early driving.

So `frames` tracks `LogVehicleRide`/`LogVehicleLeave` per account and sets the
new `FLAG_DRIVING` (bit 6) only for `WheeledVehicle`, `FloatingVehicle` and
`FlyingVehicle`. Measured coverage is **complete** — every one of the 7,635
in-vehicle samples had a preceding ride event, none unknown — which is what
makes the cross-reference trustworthy rather than best-effort.

Two deliberate constraints on that state machine:

* **`isInVehicle` still decides occupancy**; the ride index is only ever
  consulted to *name* the vehicle. A dropped `LogVehicleLeave` therefore cannot
  strand a player in a phantom car for the rest of the match.
* **Unknown types decline the flag.** Every PUBG enum is open and casing moves
  between patches, so a vehicle shipped next patch gets no marker rather than
  the whole lobby getting one.

Passengers count — the question is what the vehicle *is*, not who holds the
wheel, so `seatIndex` is deliberately not consulted.

`pos.flags` was already a byte with three spare bits, so this cost nothing:
bundle size is unchanged at ~113 KB.

---

## 23. The kill map and heatmaps are zoomable — added 2026-07-23

Both grew scroll-to-zoom, drag-to-pan and +/−/reset buttons. `MapView` is the
shared box; `lib/panZoom.ts` is the maths, and it is pure and tested because
that is where this frontend's bugs actually live.

**Everything is in viewport fractions, not pixels.** These panels are fluid —
`.mapwrap` is `width: 100%` with a square aspect ratio, so the same map is
660 px on a desktop and 324 px in a narrow pane, and it changes width while
someone is looking at it. A pixel offset captured at one width is wrong at the
next, and it reads as a map that drifts when you resize rather than as a unit
bug. Fractions also let one transform drive two coordinate systems that never
learn each other's units: a CSS `translate(%) scale()` on the tiles, and SVG
user units on the marker overlay.

### Two layers, and which one a thing goes in is the design

The heat field is *terrain* and rides inside the transformed layer. Kill dots
and drop labels are drawn **outside** it, in screen space, positioned from the
transform — so they keep a constant size. You zoom into a crowded fight to
separate the dots; markers that scale with the map arrive at the same pile,
just bigger. The replay counter-scales its markers for the same reason.

Verified numerically rather than by eye: after zooming, the overlay markers
agree with the transform the browser actually applied to the tile layer to
within 0.0014 of 660 SVG units, and a dot's radius is 3 at both fit and 2.4x.

### The tile pyramid now climbs with the zoom

`MapTiles` had a hardcoded `zoom={1}`, correct only for a static 660 px panel
at dpr 1. Left alone, zooming would have magnified one stretched
low-resolution tile — which is exactly the bug §18 documents in the replay, and
it reads as a bad screenshot rather than as a defect. The level now comes from
rendered width x zoom x device pixel ratio, measured with a `ResizeObserver`.

### `<img>` is draggable, and that silently killed the pan

Pressing a tile starts an HTML5 image drag: `pointercancel` fires, the pointer
stream stops dead, and the cursor picks up a ghost thumbnail. The heatmaps
panned **exactly one pointer event** and then froze.

The kill map worked the whole time and hid it — its SVG overlay covers the
tiles, so a press never lands on an image. Two surfaces sharing one component,
one of them accidentally immune, is precisely the shape that survives casual
testing. `tsc`, `oxlint` and `vitest` were all green throughout.

Diagnosis worth keeping: the tell was `pointerup: 0` alongside a partial drag.
Guessing produced four wrong theories (React remount, event coalescing, stale
refs, capture loss); a `MutationObserver` ruled out the remount in one run, and
counting the events the element actually received pointed straight at the
cancel. `draggable={false}` on the tiles, `user-select: none` on the stage.

`scripts/probe-map.mjs` is the harness — it asserts the wheel anchors under the
cursor, the drag moves 1:1, the pyramid level matches, no tile is draggable and
the page does not overflow horizontally. Run it against both surfaces.

---

## 24. Add and remove tracked players from Settings — added 2026-07-23

Tracking was CLI-only (`pubgd player add|remove`). Settings can now do both:
a name field under the tracked table, an `untrack` button per row, and a
**Not tracked** section offering a one-click re-track that spends no
rate-limit budget.

`ingest/tracking.py` is the state machine, and both the CLI and the API go
through it — the parts that must not differ are subtle. A re-track resets
`consecutive_poll_failures`, or `select_due_players`' exponential backoff (up to
six hours) keeps punishing an account for failures that predate it. A rename
refreshes `name` on the existing row, because the account id is the stable key.
Untracking never deletes: `tests/test_api.py` asserts the participant row count
is unchanged and that `/players/{id}/stats` still answers.

**Adding costs a token; re-tracking costs nothing.** Only `GET /players` can
turn a name into an account id, and that is the metered endpoint. Once the row
exists the id is already known, which is the whole reason the row survives an
untrack. Resolution is synchronous rather than queued because "that name does
not exist" is the common outcome and is useless to the operator minutes later
in a log nobody is reading. The backfill it queues spends a second token when
the worker picks it up.

### `tracked = false` is not "players I stopped tracking"

`players` holds a row per **human opponent** too — that is what makes opponent
lookup and aggregate heatmaps free — so 4,338 of the 4,341 rows are untracked
and were never tracked at all. A "not tracked" list built on the flag alone
renders every stranger who has ever been in a lobby.

Migration 0004 adds `players.untracked_at`, set by the shared `untrack` (and by
the CLI's `player remove`, or a CLI removal would not be re-trackable from the
UI). `GET /players?formerlyTracked=true` is the filter.

Rejected: inferring it from `last_polled_at IS NOT NULL`. That is exact today —
only the poller writes it and it only polls tracked players, verified 3 of 3
with zero false positives — but it is inference that stops holding the moment
the poller changes, and it misses anyone untracked inside the five-minute
window before their first poll.

### An unknown name 404s, and the generic message is about the wrong thing

`ports.PubgApi.get_players_by_names` documents it and the live API confirms it;
the first cut assumed a 200 with an empty `data` array, which *also* happens.
Left to propagate, a mistyped name reached the operator as the client's generic
404 text: **"unknown resource, or outside the 14-day retention window"** — true
of a match, nonsense about a player name, and it sends the reader to look at
retention instead of at their keyboard. Found by typing a bad name into a real
browser, not by reading the code.

`tracking` now converts any 404 into `PlayerNameNotResolved`, and the router
answers with the two causes that actually apply: case (PUBG's lookup is
case-sensitive, so `chocotaco` and `chocoTaco` are different lookups) and
shard. Asked by `status_code_of(exc) == 404` rather than `isinstance`, because
`ingest` reaches the API through a Protocol and there are **two** error classes
for the same 404 — `get_players_payload` raises a generic `PubgApiError` while
the name-probing path raises `PlayerNotFound`. Both are covered.

### `post()` was discarding every server error message

`api/client.ts::post` threw `r.statusText` while `get` parsed `detail` out of
the body. Unfixed, the entire explanation above would have reached the user as
the two words **"Not Found"**. Both now share one `errorFrom` helper.

## 23. Strategy insights — added 2026-07-23

**What**: a per-participant `strategy_metrics` table (parser v7), a `/strategy`
page contrasting each tracked player's best-placed vs worst-placed official
matches per metric, and a "Strategy" panel on the match page. Metrics: time in
blue (`FLAG_BLUE_ZONE` dwell, gaps clamped at 15 s), blue damage taken (new
per-victim accumulator in `combat.py` — attacker-less events matched on
lowercased `Damage_BlueZone`), rotation lag (white-circle announcement →
first sample inside, clock starting at `max(announcement, landing)`),
teammate distance/near-% (nearest-in-time pairing, ±15 s), hot-drop count,
first engagement, early damage dealt/taken, landing→first weapon, early
pickups. All 65 matches reparsed; all populated.

Facts that shaped it, verified against the archive:

- **`participants.landed_at_s` had existed since migration 0002 and was never
  written**, and `landing_x/y` came from the *first frame sample*, which can
  sit on the aircraft's path. Both now come from `LogParachuteLanding`
  (first landing wins — flare redeploys land twice; the death rule is the
  opposite, latest wins).
- **The smallest telemetry file in the corpus is a training-range match with a
  two-person roster.** Any corpus test that picks "the smallest file" and then
  asserts percentages must filter to `matchType == "official"` first —
  `tests/test_telemetry_strategy.py::_corpus` does.
- **Teammate pairing must select the nearest-in-time sample, not whichever
  bracketing sample is spatially closer** — the latter systematically
  understates squad spread (caught by a synthetic test before it shipped).
- **Raw blue-zone seconds are confounded by survival**: placing well means
  living longer, which means more chances to touch the blue. The page shows
  blue time as a share of time alive; the raw seconds stay in the table.
- Distributions after the full reparse (3,243 human rows): rotation lag p25
  5.4 s / median 54 s / p90 294 s; median blue time 0 s; median first weapon
  8.9 s; median teammate-near 97%.

Analysis is deliberately server-light: the API (`api/routers/strategy.py`)
returns joined rows; the best-vs-worst contrast (ties at the boundary
included, per-side n from non-null values only) is a pure function in
`frontend/src/lib/strategy.ts` with hermetic vitest coverage. Null means "not
measurable" (no landing, no teammates, no fights) and is never rendered as 0.

`strategy_metrics` is delete-then-insert like `kill_events` (absolute values,
no ledger needed). Migration 0005. The scatter strips are hand-rolled SVG, so
the page does not load Recharts.

The page defaults to a **combined** view: every tracked player's rows pooled
(a match two of them played counts once per player — stated in the note),
scatter dots coloured per player so "who drives this pattern" stays visible,
and the weapons table merged by `mergeWeapons` in `lib/strategy.ts` (kills
sum, longest is a max, average range weighted by kills). Purely client-side —
no new endpoint.

## 24. The "After Action" redesign shipped — 2026-07-23

The design proposal (artifact "After Action") is now the live UI. What changed
and where:

- **Tokens** (`styles/tokens.css`): olive-black ground biased toward the gold
  accent (`--bg #0d0f0a`, `--bg-raised #161911`, warm off-white ink), squared
  radii (2/3px), and a `--display` face. Gold (`#f0b429`) now means winning,
  placement and the brand — it is no longer any player's identity colour.
- **Identity trio re-hued**: cyan `#1e9fd2` / rose `#d84378` / violet
  `#8a72e8`, spare olive-chartreuse `#8f9a1f` — CVD-validated (all-pairs)
  against the new surface; green was rejected because green↔rose fails
  deuteranopia. Changed in exactly the two places that must stay parallel:
  `tokens.css` `--p-1..4` and `lib/players.ts` `SLOT_HEX` (canvas/Pixi cannot
  resolve `var()`); `players.test.ts` pins both.
- **Type**: Barlow Condensed 600/700, self-hosted in `public/fonts/` (~44 KB
  latin woff2, `@font-face` in `base.css`, no CDN). Headings, table headers,
  tile values, session numbers and buttons wear it; body stays system sans,
  data columns stay tabular mono. **Player names are never uppercased** — a
  `.name` escape class (base.css) protects them wherever a heading or `th`
  transform would blur "DaddyGainz" into "DADDYGAINZ" (Home card headers,
  Player hero, Compare column headers).
- **Shell** (`AppShell.tsx/.css`, rewritten): the 232px sidebar is gone.
  A 52px top command bar (brand, uppercase condensed nav with gold underline,
  ingest badge, settings gear) plus a persistent **squad strip** of the
  tracked players under it. Maps get the full viewport width. Narrow screens
  drop to horizontal scroll — the old icon-rail media query is gone with the
  sidebar.
- **Hardcoded blue-grey hexes swept** to olive equivalents: `tr.tracked`
  and the replay's `.feed-row.tracked` (#1b2015), form-strip cells, skeleton
  shimmer, notice, mapview buttons, replay timeline (`.tl-alive`/`.tl-phase`),
  Recharts chrome in Player/Compare (grid/axis/tooltip), placement-bucket
  neutrals, KillMap dot stroke. The heatmap ramp is untouched — cyan→amber→red
  reads correctly on the new ground.

Verified in a real browser (headless Chrome + probe-replay) on Overview,
Match, Strategy, Player, Compare, Heatmaps and the Replay. One false alarm
worth remembering: **Recharts entry animations mean an early headless
screenshot shows axes with no marks** — bars/lines animate in over ~1.5 s of
requestAnimationFrame time that `--virtual-time-budget` does not reliably
deliver. The DOM had correct geometry and computed styles all along; wait
~4 s of real time before screenshotting chart pages.

---

## 25. Accuracy was 31% too high, for the whole life of the feature — fixed 2026-07-28

Found while evaluating the app for what to build next, not by anyone noticing a
wrong number. `combat.py::_match_end` did:

```python
stats.shots_hit += int(weapon.get("hits") or 0) + int(weapon.get("dBNOHits") or 0)
```

on the reading that `hits` counts shots landing on a standing target and
`dBNOHits` those landing on a knocked one, so accuracy wants both. The corpus
disagrees, unambiguously:

* **`dBNOHits <= hits` on 547 of 547 weapon rows**, no exceptions.
* Per-weapon, derived hit events match `hits` alone at a median ratio of
  **1.00**, and `hits + dBNOHits` at **0.78**.
* Worked example, `WeapBerreta686_C` in `008a45cb…`: `shots 90, hits 44,
  dBNOHits 35` — against 44 attributed damage events, of which 35 had a DBNO
  victim. The 35 are inside the 44.

Corpus totals `shots 32,821 / hits 5,592 / dBNOHits 1,757`, so **17.0% accuracy
was displayed as 22.4%** — a 31% relative inflation on every accuracy figure the
dashboard has ever shown, everywhere it appears.

### Why nothing caught it

The two obvious guards both passed:

* `shots_hit` never exceeded `shots_fired` — **0 rows of 9,041** — so the figure
  stayed a plausible-looking percentage and no invariant fired. The existing
  corpus test asserted exactly `0 < total_hits < total_shots`, which the
  inflated value satisfies comfortably.
* The unit test asserted `shots_hit == 13` on a fixture with `hits 8+3` and
  `dBNOHits 0+2`. **It was written from the code's assumption**, so it pinned
  the bug rather than the wire — the third time that exact shape has appeared
  here, after `shotsFired`/`hitCount` (§12.3) and `LogArmorDestroy` (§12.4).

### What was added

Two corpus tests, and both were verified to **fail when the bug is restored**
(2 failed, 36 passed; the corpus one reports `parser 7349 != wire hits 5592`):

* `test_corpus_dbno_hits_are_a_subset_of_hits` — the wire fact itself, plus a
  guard against a vacuous pass if PUBG ever renames the key away.
* `test_corpus_hits_are_not_summed_with_dbno_hits` — asserts the parser
  reproduces `sum(hits)` **and** does *not* reproduce `sum(hits + dBNOHits)`.
  Two assertions on purpose: with only the first, someone "fixes" accuracy by
  restoring the sum and then relaxes the test to match.

### Reparse

Parser **v9**; `POST /api/ingest/reparse?staleOnly=true`, 97 matches, ~7 min,
0 failures. Verified after:

| | before | after |
|---|---:|---:|
| `sum(shots_fired)` | 47,111 | 47,111 |
| `sum(shots_hit)` | 10,497 | **7,996** |
| accuracy | 22.3% | **17.0%** |
| `heatmap_bins` total | 2,214,264 | **2,214,264** |
| `kill_events` | 9,275 | 9,275 |
| matches at head version | 97 @ v8 | 97 @ v9 |

The unchanged heatmap total is the ledger doing its job — that is the number to
check on every reparse, because a doubled heatmap is invisible by inspection.
Replay bundles re-uploaded under the v9 key and serve at 132,819 B;
`npm test`'s corpus decoder reads them (94 passed).

**Expect `shots_hit` to fall** on the 250 participants PUBG reports stats for.
That is the fix, not a regression.

---

## 26. Red zones were never gone — corrected 2026-07-28

§5.15 said: "`redZone*` and `blackZone*` are **always 0** across all 9,150
game-state events — red zones are gone from current Erangel. Don't build that
renderer." BUILD-SPEC §3.9, CLAUDE.md and a comment in `world.py` said the same
thing. **All four were wrong, and they were wrong in the same way**: a true
statement about `LogGameStatePeriodic.redZone*` was generalised into a false
statement about the game.

The feature lives in `LogSpecialZoneInCharacters`. Measured over 20 archived
matches:

* **19 of 20** carry red zones; 4,389 events
* `zoneInfo.zoneType == "RedZone"` is the only zone type that ever appears
* `zoneState` runs Warning (133) → Activating (133) → ActivationDone (3,990,
  at ~1 Hz) → Deactivating (133) — exactly **seven zones per match**
* each has a stable `uniqueId` 0–6, a position and radius that **do not move**
  for the zone's whole life (39,500–50,000 cm, i.e. 395–500 m), and
  `charactersInZone[]`, the roster of everyone inside
* timing, from one match: Warning, Activating at **+45 s**, Deactivating
  **~30 s** after that

Parser **v12** emits a discrete `redZones` bundle section — seven small maps,
~200 bytes gzipped. The renderer draws two states, because the data has two and
they mean different things: a dashed outline for the 45 s warning ("get
indoors") and a filled disc for the 30 s bombardment ("stay there").

### The zero arrays were deleted, not backfilled

`zones.rx/ry/rr` are gone from the bundle. Backfilling the discrete track into
them would resample a 45 s warning and a 30 s bombardment into a single
per-sample radius at the game-state cadence, losing the one distinction that
changes how anyone plays. Deleting them is also what makes that mistake
impossible to make later. The decoder no longer reads them, and the corpus test
asserts they are absent — a removal nobody asserts is a removal that comes back.

### The check that proves the circles are in the right place

`charactersInZone` and `character.isInRedZone` come from **two independent
event streams**, so their agreeing is real evidence. A red circle drawn at the
wrong coordinates still looks exactly like a red circle; nothing else that could
be written here would catch it.

Writing that test produced a fact worth keeping: **`isInRedZone` is set from the
warning, not from the first bomb.** A sample at t=633 s sat 29,157 cm inside a
zone of radius 43,550 that was warned at 631.3 s and did not start bombing until
676.3 s. A test window keyed on the bombardment start fails — correctly.

### Honest limit

Red-zone **damage is negligible**: `RedZoneBombingField_Def_C` appears in 3
damage events and 1 kill across 15 matches. This is map fidelity and a corrected
document. It is not a new statistic, and no stat page was built on it.

### Two more things fixed in the same pass

* **The flare-vehicle filter matched nothing.** `FLARE_VEHICLE_PACKAGE` was the
  literal `"uaz_armored_c"`, which does not occur anywhere in the corpus, so 19
  flare-gun vehicle deliveries were classified as loot crates for the whole life
  of the feature. What actually arrives is `Carapackage_FlareGun_C` (22) and
  `BP_BRDM_C` (16). Note PUBG spells it **`Carapackage`** in three package ids
  and **`Carepackage`** in a fourth — which is precisely why the replacement
  matches a lowercased substring rather than comparing ids.
* **Crate rarity reaches the bundle.** 500 of the corpus landings are
  `Carapackage_RedBox_C` and nothing downstream could tell one from a small
  drop. The replay now draws the red box larger and in red.

`LogPhaseChange.playersInWhiteCircle` is also carried now — exact ground truth
for the question `strategy_metrics.rotate_lag_s` answers with a heuristic. Two
properties, both measured: each phase **number appears twice** per match, and
the roster **does not shrink monotonically** — one match runs 17, 15, 8, 8, 9,
5, because the circle keeps getting smaller while players keep rotating into it.

> **Correction, 2026-07-29.** The parenthetical above used to say the pair must
> be resolved by taking the later event "or the first reports most of the
> lobby". Measured across 8 bundles / 65 phase pairs, **the first event is
> larger in only 18 of 65** — and its count on the match quoted here is 57,
> which is not a 101-player lobby.
>
> The real semantics fall out once `t` is decoded correctly: phase-event `t` is
> in **ticks of `tickMs` (100 ms)**, not milliseconds. Read that way the pair is
> the white-circle **announcement** and the moment the blue **starts closing**:
>
> ```
> phase 1:   90.8s n=57    330.3s n=34    240s apart
> phase 2:  600.5s n= 9    680.4s n=13     80s apart
> phase 3:  780.5s n=11    860.5s n=18     80s apart
> phase 4:  960.6s n=12   1040.5s n=15     80s apart
> phase 5: 1140.5s n= 7   1220.3s n= 7     80s apart
> phase 6: 1300.3s n= 2   1360.1s n= 2     60s apart
> phase 7: 1420.1s n= 1                    single
> ```
>
> Those gaps are PUBG's own zone timings. So **both events are worth keeping**:
> "were we already safe when the circle appeared" and "were we safe when the
> blue caught up" are two different pieces of coaching, and the roster moving
> up between them is players rotating in, not a bad reading being corrected.
> Phase 1's first event is the outlier — it fires at ~91 s while much of the
> lobby is still airborne over the circle.
>
> A match can also end on an announcement that never closes, so handle the
> missing side rather than assuming pairs.

Cost: average bundle 134,508 → **134,794 bytes**, +0.2%.

---

## 27. Ingest failure is loud now — added 2026-07-28

The highest-stakes gap in the project, and the only one where "we'll notice
eventually" is not true: **PUBG discards match history after ~14 days.** Every
other fault here is recoverable by re-running something. A poller that stops
and nobody notices is permanent loss, and until now the only signal was a
frontend badge whose threshold nobody was watching.

### The badge was measuring the wrong thing

`/health`'s `poller_lag_s` is `min(now() - last_polled_at)` filtered to
`last_polled_at IS NOT NULL`. `min` of an *age* is the **freshest** player, not
the stalest, and never-polled players are excluded entirely.

While everything works those are the same number — one batched `GET /players`
polls all three at once. They diverge exactly when one account enters
exponential backoff, which reaches **six hours**. Demonstrated live: with one
tracked player set nine hours stale, `pollerLagS` read **46 seconds** and the
badge stayed green.

### `pubgd doctor`, on a five-minute timer

A **separate process**, and that is the design: the poller cannot report its
own death and the API only works when asked. Five checks —

* `poller_stalled` — `max()` of the poll ages, not `min()`
* `player_never_polled` — the rows a lag calculation cannot see at all
* `queue_failed` — dead-lettered jobs, by kind
* `parse_failing` — fetched but unparsed for over an hour, or `parse_error` set
* `telemetry_at_risk` — **the one this exists for**: matches with no archived
  telemetry whose `played_at` is inside 4 days of the retention cliff

Each opens or closes a row in `ops_alerts`, upserted through a **partial unique
index over unresolved rows** (`uq_ops_alerts_open`, hand-written in migration
0008 and registered in `HAND_MANAGED_INDEXES` — autogenerate would have emitted
a plain `UNIQUE (kind)` that silently forbids ever recording a second
incident). Resolution closes rather than deletes, so two outages an hour apart
stay two facts.

The watchdog also stamps its own heartbeat, because something has to watch the
watcher, and `/api/health` reports how long ago it last ran. **`null` there is
not "fine"** — never run and stopped an hour ago are both reasons to look.

Verified end to end rather than by reading it: player set nine hours stale →
`pubgd doctor` exits 1 and logs → the alert appears in `/api/health` with its
detail → poll time restored → alert resolves → the row survives closed.

### Also in this pass

* **`matches.parse_error` was write-only-NULL.** Cleared on success by
  `persist_parse_result` and populated by nothing, so a parse failure existed
  only in `jobs.last_error`. `parse_telemetry` now records it and **re-raises**,
  with the recording in its own try/except — swallowing there would turn a
  parse failure into a silent success, which is strictly worse.
* **`pubgd match rm`**, and the order is the whole feature. `heatmap_bins` has
  no `match_id` and no foreign key, so the heat ledger in object storage is the
  only record of what a match contributed. It is read and reversed *before* the
  row is deleted; the other order orphans it permanently and leaves every
  affected bin quietly too high. Refuses outright when a parsed match has no
  ledger, exactly as `persist_parse_result` does.
* **`pubgd storage prune`** finally reads `raw_telemetry_retention_days`, which
  had been in the config since the beginning and had never been read by
  anything. Dry run by default, disabled by default, and it **never prunes a
  match below the head parser version** — that match is due for the next
  reparse, and pruning it means the reparse yields nothing while its ledger is
  still subtracted, so its heatmap contribution vanishes with no error. This
  session alone spent four parser bumps, so that is not hypothetical.
* **`queue/worker.py:HANDLER_MODULES`** named `pubg_dashboard.pipeline.handlers`,
  a module that has never existed. `load_handler_modules` swallows the
  ModuleNotFoundError and warns, so `pubgd worker` only ever worked because
  `cli.py` builds the registry explicitly — the console entry point would have
  dead-lettered every job it claimed. Now `()`, so the existing "no job handlers
  registered" guard fires and names the real problem.
* **`/api/heatmap?kind=`** was unvalidated. An unknown kind selected zero rows
  and returned a full 256×256 grid of zeroes with `max: 0` — byte-for-byte what
  a map nobody has died on looks like. `kind=kils` rendered as "no deaths here".
  Now a 422 that lists the valid kinds.
* **`logging.py`**, specced in BUILD-SPEC and never written. Console renderer on
  a terminal, JSON under systemd where the journal is the only record.

---

## 28. Crates: PUBG's own art, contents on click, and open when looted — 2026-07-29

Three changes to the same marker, in the order they were asked for.

### The square was the same shape as a player dot

Care packages were gold and red squares; player dots are team-coloured squares
at nearly the same size. The only difference was hue, over satellite imagery
that is yellow-brown through every town. Evidence it actually misleads:
reading a screenshot of this renderer, a cluster of player squares was taken
for care packages and only the instrumented `crates: 0` counter settled it.

PUBG publishes the art in `pubg/api-assets` under `Assets/Icons/CarePackage` —
the same repo the map tiles come from. Vendored into `frontend/public/crates/`
(29 KB) rather than fetched at build time, like the self-hosted fonts. They are
**not** Git-LFS pointers, unlike that repo's High_Res map PNGs.

Three details the real art forces, none of which applied to a square:

* **Never tint them.** They already carry PUBG's red/blue/white and `tint`
  multiplies. Rarity is size instead — which is honest anyway, since PUBG's own
  art does not separate a red box from a small drop. The hand-drawn fallback is
  kept monochrome precisely so it *can* be tinted.
* **Anchor on the box, not the centre.** The flying icon is 144x200 with the
  canopy above; centre-anchoring hangs the crate below where it lands.
* **Size it as a landmark**, 22 px (30 px red box) against a 10 px player dot.
  The first cut reused the square's size and drew a 14 px white blob: an
  illustration needs more pixels to read than a plain shape does.

Measured before wiring the parachute up, because two of the three package types
are literally named `NoParachute`:

| package | spawn → land | n |
|---|---:|---:|
| `Carapackage_RedBox_C` | **53.6 s** | 73 |
| `..._SmallPackage_NoParachute_C` | **0.0 s** | 40 |
| `..._NoParachute_Bluechip_C` | **0.0 s** | 99 |

The names are honest. Those land in the instant they spawn, so `falling` is
never true for them and a canopy cannot appear on something that does not fall.
Also measured: **0 of 216** spawn/land pairings matched a spawn with a
different `itemPackageId`, so the XY-nearest pairing that ignores package id has
never mis-paired.

### Contents on click, and the stack counts that were being dropped

`LogCarePackageLand` has carried the full item list since the parser was
written and nothing ever showed it. But `cp.items` kept only item **ids** — so
a red box holding three 30-round stacks of 7.62mm reached the client as three
entries, which renders as **"7.62mm x3"**: a completely believable quantity,
wrong by a factor of thirty. Parser **v13** carries quantities, aggregated per
item (three stacks of 30 arrive as one 90).

Clicking is Pixi hit-testing on the crate sprites, and two things had to be
true for it to work:

* **A pan must not count as a click.** The viewport pans on any pointer-move
  over the canvas, so `Viewport.dragged` now reports whether the pointer
  travelled more than 4 px since pointerdown. Without it, every pan that
  happened to finish over a crate would open the panel, and the map is covered
  in crates by the end of a match.
* **Only the crate layer is interactive.** Pixi hit-tests the whole scene graph
  on every pointer move, and this one holds ~100 dots, ~100 labels, the tile
  grid and several `Graphics` whose bounds are the entire world — the same
  "bounds are the whole map" property that made `cacheAsTexture` allocate
  268 MB in §16. Every other layer is now `eventMode: 'none'`.

`itemName` gained `withPiece`, because armour reduced to its tier is right in
the inventory panel (the slot label names the piece) and useless in a crate:
the three armour pieces rendered as **"Lv3", "Lv3", "Lv3"**. Calibres also got
their decimal point back — PUBG's ids spell it `556mm`, which reads as a number
rather than a cartridge.

### Open when looted

`LogItemPickupFromCarepackage` fires ~31 times a match, so "has anyone taken
anything out of this" is answerable — but **there is no id to join on**. The
pickup carries a `carePackageUniqueId`; `LogCarePackageLand` carries no id at
all (its `itemPackage` is exactly `itemPackageId`, `items`, `location`), and the
pickup's uniqueId is a per-match sequence 0–4 that means nothing alone.

Joined on position **and** package name, and both are needed:

* the looter is within **286 cm** of the crate in the worst of 269 measured
  pickups, median 132 — you stand on it to loot it;
* but two crates can land **0 cm apart** (21 pickups had more than one crate
  within 10 m), so proximity alone is ambiguous;
* the nearest crate's `itemPackageId` matched the pickup's `carePackageName` in
  **269 of 269**.

Stated limit: two crates of the same type stacked on one spot cannot be told
apart and the earlier wins — they are drawn on top of each other anyway.

Archive-wide, **166 of 632 crates (26%) are ever looted**. The corpus test
asserts *both* outcomes occur: if every crate read as looted the join would be
matching anything nearby, and if none did it would be matching nothing.

Parser **v14**. Bundle average 134,794 → **134,861 bytes**, +0.05%.

### Two probe lessons, both the probe's fault

* Setting `viewport.scale` does not apply the transform — the world container's
  scale has to be set and `onZoomChange` fired, or the canvas goes black. That
  looked exactly like a renderer bug.
* Zooming to level 4 under swiftshader saturates the main thread and **CDP
  calls time out** (`Runtime.callFunctionOn timed out`), which looks exactly
  like a wedged page. The fix was to stop zooming, not to raise the timeout:
  the crate is clickable where it already is.

---

## 29. The Review page — added 2026-07-29

**What**: a `/review` route answering "what happened in these games", a
`/api/review/*` router, and `frontend/src/lib/findings.ts` — the layer that
turns counts into sentences. **No migration, no `PARSER_VERSION` bump, no
reparse**: every figure comes from `kill_events`, `knock_events` and
`participants` as they already stand.

The split against `/strategy` is deliberate. Strategy aggregates the whole
archive to ask "what do we do differently when we place well". Review is about
specific evenings and specific deaths. Putting both on one page would have left
Strategy half-empty and duplicated its filters.

### The rule the findings layer exists to enforce

Every finding carries its `n`, and `n` is not optional. No p-values, no
significance stars, no confidence intervals — at ten matches a side an interval
is either ignored or misread as precision. No causal or prescriptive phrasing;
`findings.test.ts` fails on a regex of `because|therefore|you should|try to|…`,
because the ceiling this data supports is "in these matches, X looked like Y".

Findings below `MIN_N` are **dropped, not hedged** — a sentence with a caveat
still reads as a finding, an absent sentence does not.

### Four things measured before anything was built

* **Third-partying is real signal**: 44 of 195 tracked deaths (23%) had another
  team's kill within 200 m in the 30 s before. Both thresholds are a judgement
  call, so they are returned by the API and printed in the sentence.
* **"Died in the blue" cannot be a category**: 6 of 195. It ships as a bare
  count in a footnote. A tile that small on a page of percentages reads as a
  problem the squad has.
* **Kill distance is concentrated**: 162 of 238 tracked kills inside 50 m, and
  the bands above 150 m are single digits. Each band prints its own totals and
  the trade percentage is withheld below n=8.
* **The bot share had gone stale in CLAUDE.md** — see §29.2.

### 29.1 A tunable constant was about to become a wrong number

Knock-to-kill conversion was first written the obvious way: the victim's next
death within N seconds of the knock. The answer moves **50% → 68% as N sweeps
30–180 s**, with no knee anywhere in between, because a revived player who dies
again ten minutes later is indistinguishable in that join from a slow
bleed-out. Excluding re-knocks tightens the median from 19 s to 11.8 s and does
not fix the tail (p99 871 s).

`kill_events.dbno_maker_account_id` is the same question **already answered by
the parser**, with no threshold at all — it is NULL exactly when nobody had
knocked the victim first, and is populated on 4,716 of 8,289 career kills,
matching the ~51% of victims who die still flagged `isDBNO`.

Window-free result: we finish **122 of 200** knocks (61.0%); opponents finish
**112 of 182** against us (61.5%). The first framing of this, from the naive
join, read as an asymmetry — 72% against 73% — and it is not one. Two numbers
half a point apart are the same number, and `findings.ts` says "the same rate,
within noise" with a test pinning it.

The same column replaced the "knocked, then finished" vs "killed outright"
split, which had been about to acquire a window of its own.

**Where a column like that exists, use it.** A tunable constant inside a rate
is a place for a plausible wrong number to live.

### 29.2 CLAUDE.md's bot-kill claim did not survive the archive growing

It read "bots are ~19% of all kills and just over half of the tracked players'".
At 97 matches: bots are **14.0% of all participants** (1,265/9,041), **6.7%** of
official-match ones (545/8,116), **6.6% of official kill victims** (545/8,289),
and **11% of the tracked players' kills** (27/238). The 19% came from the
65-match corpus. `kills_human` stays the default — that decision is right
independently of the ratio — but the ratio itself is now marked as something to
re-measure rather than quote.

(545 appearing twice above is a real coincidence, checked with separate
queries, not a copy-paste.)

### 29.3 Tone is only claimed where the data says which way is better

The first build coloured a 38% revive rate red. Nothing in this app defines a
good revive rate, so that was inventing a standard and then failing the squad
against it. Tone is now neutral there and everywhere else without a reference
point; it survives on a losing trade ratio, which is self-evident from the
counts. Two tests pin it.

### 29.4 `scripts/probe-page.mjs`

Third sibling of `probe-replay.mjs` and `probe-map.mjs`. Those two are
specific — one drives Pixi, one drags a map — and there was no probe for "did
this ordinary page come up". It reports page errors, failed requests, the
section/table/tile structure, whether the body scrolls sideways, and exits
non-zero if anything threw.

It caught nothing this time, which is the point: the CSS-leak check
(load `/review`, then navigate in-session to Overview, Matches and Strategy and
confirm their rows keep their own layout) is the exact sequence that hid the
`.feed-row` collision in §15, and it is now a thing that can be run in seconds
rather than reasoned about.

### Verified

Backend `882 passed, 1 skipped` (the pre-existing missing-fixture skip in
`test_schemas.py`, §11). `ruff` clean. Frontend `npm run check` green —
158 tests across 12 files, 31 of them new in `findings.test.ts`. Built, then
probed in a real browser against the deployed `dist/`.

Numbers on the live page match the independent measurements exactly: 83
official matches, 195 deaths, 44 third-partied, 122/200 and 112/182 knocks,
first-down 32/71, 28/71, 11/38.

---

## 30. Where we drop — added 2026-07-29

**What**: a "Where we drop" section on `/strategy` — an Erangel map with one
marker per drop spot, sized by how often the squad lands there and coloured by
median placement, over a table with each spot's record. Clicking either the
marker or the row opens the individual drops, each linking into the replay at
the moment they landed.

**No migration, no `PARSER_VERSION` bump, no reparse.** `participants.landing_x/y`
and `landed_at_s` have been populated since parser v7 and nothing had ever
joined them to an outcome.

### 30.1 PUBG ships the place names, and this repo did not know

CLAUDE.md and the plan for this work both said there was no place-name data and
that drop spots would have to be anonymous pins. That was wrong. **Every
`Character` block carries a `zone` list** — `["pochinki"]`,
`["sosnovkamilitarybase"]` — on 32% of position events, 48% of damage events and
62% of item pickups. 26 distinct names on Erangel.

The catch, and the reason `scripts/build_gazetteer.py` exists rather than a
lookup at read time: **`LogParachuteLanding` carries a zone only 1.2% of the
time.** The one event that says where a player dropped is the one event that
almost never names the place. So the names are harvested from the events that
do carry them, binned onto the same 256² grid `heatmap_bins` uses, and looked up
afterwards.

Measured on 61 Erangel matches: 1,325,503 samples, **modal purity 0.9847**,
5,746 named cells — **8.8% of the grid**. Most of Erangel is fields, and a
gazetteer that named most of the map would confidently mislabel every drop.

Exactly two multi-zone combinations occur: `rozhok`+`school`, and
`8thEventSpot`+`ferrypier`. **`8thEventSpot` is excluded** — it is a
limited-time event marker, occurs 50 times, and never appears alone.

### 30.2 Why an artifact and not a table

`backend/pubg_dashboard/telemetry/places/baltic_main.json` is committed, with the
same standing as `docs/reference/telemetry-observed-schema.md`.

A `map_places` table filled at parse time would be a global aggregate over
matches **with no ledger** — precisely the failure mode `heatmap_bins` needed
the heat ledger to survive. A reparse would double every cell's support and the
modal name would still look right, so nothing would ever surface it. Building
it offline makes that error impossible.

### 30.3 The check that proves the names are on the right ground

Centroids were compared against **the map image's own printed labels** — the
same method that settled the y-inversion question. Cropping
`assets/.source/Erangel_Main_High_Res.png` at each centroid: Prison, Mansion,
Shelter, Rozhok, Boatyard, Ruins, School and Pochinki all sit exactly where the
gazetteer puts them.

Worth recording that **Prison came out at (6245, 3753), east-central, and that
looked wrong** — recollection said south-west. The map says east-central. The
crop settled it in ten seconds; the recollection would have "fixed" a correct
transform.

`tests/test_gazetteer.py` pins ten of those coordinates, plus a test asserting a
**transposed** lookup disagrees — otherwise the coordinate test would pass under
an x/y swap and guard nothing.

### 30.4 Clustering has to be order-independent

The obvious implementation — walk the drops, attach each to the first cluster
within a radius, else start a new one — gives a different partition depending on
arrival order. The API returns newest-first, so **one match played tonight could
re-partition every spot and silently change every number on the page.**

Ships as snap-to-400 m-grid, then union-find over occupied cells including
diagonals, then centroid. The grid does not move, so the partition is a function
of the points alone. `drops.test.ts` asserts forward, reversed and shuffled
inputs agree.

The diagonal merge is not decoration: the first measurement of this data
reported Sosnovka Military Base **twice** — n=19 averaging place 25.7 and n=6
averaging 11.8 — purely because a grid line ran through it. Two halves of one
spot, with wildly different apparent records.

### 30.5 What it says

83 Erangel squad drops over **13 spots**, top five covering 73 of them:

| spot | drops | median | contested | 1st weapon |
|---|---:|---:|---:|---:|
| Sosnovka Military Base | 25 | #15 | 72% | 7.2 s |
| Lipovka | 18 | #14 | 72% | 7.2 s |
| School | 15 | #24 | **93%** | 5.6 s |
| Georgopol | 8 | #15 | 50% | 6.6 s |
| Primorsk | 7 | **#36** | 100% | 7.8 s |

The table is sorted by **drops, not by placement**. Ranking by outcome on
single-digit samples reads as a recommendation the data cannot support, and
CLAUDE.md's dominant failure mode is plausible wrong output. Every rate carries
its denominator (`72% /25` versus `100% /1`).

### 30.6 Honest edges

* **Open country is a real answer.** A spot with no named cell within 150 m
  renders as "unnamed — 434 m NE of Sosnovka Military Base", never as the
  nearest town's name and never blank. Three of the 13 spots are unnamed.
* **Three states, not two.** `named`, `unnamed` (this map has names, none is
  near) and `unknown` (no gazetteer built for this map at all). The last is a
  missing artifact fixed by running a script; merging it with "open country"
  would hide that.
* `GET /api/maps/{map}/places` 404s with a message naming the real cause and
  listing what has been built, rather than "not found".
* `placeName()` in `lib/format.ts` maps PUBG's unspaced ids to printed names
  and **title-cases anything unknown** — every PUBG enum is open, so a new
  map's locations must still render as places.

### Verified

Backend `ruff` clean. Frontend `npm run check` green — 193 tests across 14
files, 30 new across `drops.test.ts`, `drops.corpus.test.ts` and
`test_gazetteer.py`'s 24. Built, then driven in a real browser: 13 rows render,
clicking a marker selects its row, and the row opens 25 replay links at the
landing timestamps.

---

## 31. Circle discipline — parser v15, added 2026-07-29

**What**: a `zone_play` table (migration 0009), a "Circle discipline" section on
`/strategy` showing the squad's in-circle rate per phase against the rest of the
lobby, and a row of per-phase pips on the match page. All 97 matches reparsed.

**This is the one metric in the app with no heuristic in it at all.**
`LogPhaseChange` carries `playersInWhiteCircle` — PUBG's own roster of who was
inside — so "were we in the circle" needs no geometry, no radius maths and no
threshold. `strategy_metrics.rotate_lag_s` infers a nearby answer from position
samples; this one is read off the wire.

### 31.1 The phase pair, settled exactly

§26's correction established that `LogPhaseChange` fires twice per phase and
that "the first reports the whole lobby" was false. What separates them is
`common.isGame`:

```
isGame - phase   ->  -0.9: 23    -0.5: 161    0.0: 178      (362 events, 23 matches)
```

Three values, no exceptions. `isGame == phase - 0.5` is the announcement,
`isGame == phase` is the close, and phase 1's announcement is the `-0.9` case —
it carries `isGame == 0.1`, the **plane phase**, which is why its roster is
large: the lobby is still airborne over the circle. The earlier event is the
announcement in **178 of 178** complete pairs.

`isGame` is literally `0.10000000149011612` on the wire, so `phase_kind` is
tolerance-compared. An exact `== 0.1` would misfile every phase 1 as a close.

**What the two instants mean, from the radii rather than the timings**: at
phase 2's announce the blue reads 1921 m and the new white 1056 m; eighty
seconds later at the close the blue reads **1835 m** — it has *started*
shrinking, not finished. So the close is the rotation deadline, and the
announce is when you first knew where to go. Both are stored.

6 of 184 phases have no close: a match can end on an announcement. Do not
assume pairs.

### 31.2 Two bugs, both of which produced plausible output

**The time bases differ.** `Sample.t_ms` is **absolute epoch milliseconds**;
`PhaseChange.t_s` is **seconds relative to t0**. The first version compared
them directly, so no sample was ever within any window — and the failure was
silent. Rows still appeared, `in_circle_*` was still correct because it comes
from the roster, and every geometry column was quietly NULL. It looked like
working output.

**The circle was read at the wrong instant.** `white_circle_at` snaps to the
last periodic sample *at or before* the time asked for, and the announcement
fires in the same second the white circle updates — so asking at the announce
returns the **previous** phase's circle about half the time.

That one was caught by the shape of the residual, not by the rate. Roster and
geometry agreed on only 52% of rows, and **the disagreements sat at *lower*
sample lag than the agreements** (1206 ms against 2441 ms). Staleness cannot
produce that: if the position track were merely old, disagreements would
cluster at high lag. Reading the circle at the close instead:

| | agree | disagree median lag | agree median lag |
|---|---:|---:|---:|
| before | 52.4% | 1206 ms | 2441 ms |
| after | **96.7%** | 3678 ms | 1775 ms |

Both numbers moved the right way, and the residual now behaves like staleness.
`tests/test_telemetry_zoneplay.py` asserts both the rate **and** that
disagreements are concentrated at higher lag — the second is what would catch a
wrong transform, since a wrong circle still draws a perfectly plausible one.

### 31.3 `playersInWhiteCircle` is trustworthy

Checked directly against raw `LogPlayerPosition`: of the players PUBG names as
inside the white circle, **155 of 156 are genuinely within the radius**. The
roster is right; the first 52% was our geometry, not PUBG's.

### 31.4 Phase 1 looks degenerate and is not

For the tracked squad, `in_circle_at_announce` and `in_circle_at_close` are
identical on all 122 phase-1 rows. That is real, not a bug:

* alive at the close, phase 1 — **3.6%** of rows differ (200 of 5,580)
* **not** alive at the close, phase 1 — **85%** differ (1,302 of 1,526)

The first circle is 1,921 m across and nobody moves far in four minutes of
looting, so a living player who landed inside is still inside. The squad shares
one drop decision per match, so 68 correlated matches with no difference is
unremarkable. The 85% for the dead is the plane roster at 91 s versus being
eliminated by 330 s.

### 31.5 What it says

Only players **alive at the close** count — a dead player is out of the match,
not out of position, and counting them would make discipline look worse the
more the squad lost.

| phase | announced | blue moves | lobby at the deadline |
|---:|---:|---:|---:|
| 2 | 20% /91 | 40% /91 | 39% /3065 |
| 3 | 49% /75 | 61% /75 | 45% /2492 |
| 4 | 33% /58 | 41% /58 | **47%** /1821 |
| 5 | 31% /35 | 34% /35 | **52%** /1147 |

The squad leads the lobby early and falls behind from phase 4. `lib/zone.ts`
states that in a sentence with both rates and the n, and **returns null when
there is no measurable gap** — the absence of one is not evidence of good
discipline, and a reassuring sentence would claim it is. Phase 4's five-point
gap is below the threshold and deliberately gets no sentence.

### 31.6 Reparse

`PARSER_VERSION` 14 -> 15, all 97 matches, no re-download. **No bundle change**,
so no replay needed re-rendering. Verified before and after:

| | before | after |
|---|---:|---:|
| `heatmap_bins` rows | 750,359 | 750,359 |
| `heatmap_bins` total | 2,214,264 | 2,214,264 |
| `kill_events` | 9,275 | 9,275 |
| `knock_events` | 7,489 | 7,489 |
| `strategy_metrics` | 9,309 | 9,309 |
| `participant_weapons` | 15,640 | 15,640 |
| `zone_play` | 0 | 20,503 |

Then reparsed **a second time** with `staleOnly=false` and every count above was
identical — including `zone_play`. That is the check worth running: these tables
have no ledger, so a double-insert would be silent.

### Verified

Backend suite green, `ruff` clean, migration 0009 inspected by hand (a plain
B-tree index, so nothing goes in `HAND_MANAGED_INDEXES`). Frontend
`npm run check` green — 206 tests across 15 files. Built, then driven in a real
browser: eight phase panels, the finding sentence, and the match page's pips.

---

## 32. Fights — parser v16, added 2026-07-29

Phase 4 of the gameplay-review plan. Two new tables, `engagements` and
`engagement_participants` (migration 0010), a `Fights` section on `/review`,
and `GET /api/review/engagements`.

**This is the first derived output in the parser that is a model rather than a
reading, and the whole design follows from admitting that.** Everything else
`telemetry/` writes is something PUBG states: a kill, a knock, a
`playersInWhiteCircle` roster, a position sample. PUBG does not record fights.
An "engagement" is a grouping this codebase invents.

### 32.1 The gap threshold, swept again and still with no knee

The plan flagged this as the riskiest piece on a 6-match sweep. Re-run over 25
matches and 3,922 → 12,600 cross-team blows, the shape is unchanged:

```
gap   5s -> 4559        gap  30s -> 2589
gap  10s -> 3791        gap  45s -> 2249
gap  15s -> 3311        gap  60s -> 2058
gap  20s -> 2992        gap  90s -> 1890
gap  25s -> 2762        gap 120s -> 1797
```

A smooth decay. 20 s versus 30 s is a **13% swing in the engagement count from
a ten-second choice**, and there is no fight length hiding in the data waiting
to be found.

So the constant is treated as what it is:

- `ENGAGEMENT_GAP_S` lives in `telemetry/engagements.py` with the sweep in its
  docstring, and it is part of `PARSER_VERSION`;
- `/api/review/engagements` **returns it** (`gapSeconds`), so the page prints
  the real number rather than hard-coding 20 and disagreeing with the parser
  the day someone changes one and not the other;
- every sentence `lib/engagements.ts` produces that quotes a count of fights
  carries the clause "grouped by a 20 s silence between the same two teams",
  built once by `caveat()` so no card can forget it — and a vitest asserts
  exactly that over every finding;
- the section leads with a bordered block saying the rows are a model.

`test_the_gap_has_no_knee` re-runs the sweep in CI and fails if a knee ever
appears, because that would mean the constant had stopped being arbitrary and
all of the above needs rewriting. Its anti-vacuous twin,
`test_the_gap_actually_changes_the_answer`, fails if 20 s and 30 s ever stop
differing — at which point the warnings would be noise and the constant could
go.

### 32.2 There is no `outcome` column, and that is the point

The plan said `outcome` was "the column to cut first". It was cut before it was
written. `won | lost | traded | broken_off` is a *reading* of `kills_a` and
`kills_b`, and a stored verdict outlives the reasoning behind it: a fight where
we killed two and lost three to a third party is not obviously ours to have
lost.

What is stored is the arithmetic — hits, damage, knocks and kills per side.
The API derives four buckets at query time and names them after what they
count: `ours_only` ("only they lost someone"), `theirs_only`, `both`,
`neither`. Three tests keep it that way: one asserts no `outcome`-ish key is in
the row dict, one asserts the API's labels contain no win/loss language, and a
vitest asserts no rendered sentence does either.

### 32.3 A death does not have to happen during the fight that caused it

This was the real find, and it would have quietly broken the whole feature.

`Damage_DBNO` bleed-out ticks are **self-attributed** — attacker == victim,
`attackId: -1` — so `CombatTracker._damage` drops them under its self-damage
guard and they produce no `Hit`. Measured across 25 matches: **on 16% of
cross-team kills the credited killer's last attributed hit on that victim is
20 s or more before the death**, reaching 122 s. Those are the players who were
knocked, crawled away, and ran out.

Segmenting on kills as well as hits would open a fresh one-event engagement for
each of them, reading as "team A killed team B with no exchange" a minute after
the fight that actually did it. So the exchange is built from **hits and knocks
only** and kills are *attached* afterwards, by three rules in order:

| rule | share at 20 s | threshold? |
|---|---:|---|
| the kill falls inside the exchange's span | 47.3% | exact |
| `dbno_maker`'s knock is in the exchange | 29.3% | **none** — PUBG's own link |
| the pair's last exchange, within the gap | 22.1% | reuses `ENGAGEMENT_GAP_S` |
| nothing fits | 1.3% | counted, not dropped |

The second rule is the same trick §29.1 used for knock conversion: where PUBG
has already resolved the link, use it instead of inventing a window. It carries
a median lag of 8 s past the end of the exchange, which no time-based rule
could reach without also swallowing unrelated fights.

The third turned out **not** to be a lookback at all — its median reach is
sub-second. It exists because the fatal `LogPlayerTakeDamage` and the
`LogPlayerKillV2` that follows are separate events a few milliseconds apart.

The 1.3% that attach to nothing are kills whose credited killer never landed an
attributed hit on the victim at all. They are counted in
`ParseResult.unattached_kills` and logged per parse.
`test_every_cross_team_kill_is_accounted_for` asserts attached + unattached
equals every cross-team kill exactly, because a kill that silently vanished
would make the fight review *kinder* than the match — the harder failure to
notice.

### 32.4 "Who landed the first blow", never "who opened the fight"

`LogPlayerAttack` carries an attacker and a weapon and **no victim**. A shot
that opened a fight and missed is attributable to nobody, so a team that fired
first and missed appears in this data as the team that got shot at. No column
can fix that.

The mitigation is entirely in the naming, so it is enforced in three places:
the column is `first_hit_account_id`, the docstrings say so, and a vitest bans
`opened`, `started`, `initiated` and `engaged first` from every rendered
sentence.

The finding it supports, measured: **the side that lands the first blow ends
ahead on kills in 75.9% of decided fights** (1,213 of 1,599). It is only ever
stated as a pair with its complement — "76% when you land first, 25% when they
do" — because a fight has one first hit and quoting either half alone turns a
base rate into an apparent effect. `test_the_first_hit_split_covers_every_decided_fight`
pins that the two halves genuinely partition, and a vitest refuses to emit the
sentence when only one half is measurable.

### 32.5 What an "engagement" actually is, most of the time

Worth stating because the word oversells the rows. At 20 s over 25 matches:

- median **4 events** and a median duration of **1.9 s**;
- 50.2% ended in a death, 13.9% had a knock and no death;
- **32.7% are one side landing hits and nothing coming of it** — somebody
  plinking at range;
- 12.9% had a third team fighting one of the two sides at the same time within
  200 m;
- ~120 engagements and ~338 participant rows per match, so ~11.6k and ~32.8k
  rows over the archive — negligible beside `heatmap_bins`' 2.2M.

`test_most_fights_are_small` pins it, and the page says it in words.

### 32.6 `damage_taken` exists nowhere else in the schema

`participants` records damage *dealt*; `kill_events` records who ended up dead.
Until `engagement_participants` there was no way to say a player took 180
damage and dealt 12 — the only measure of a fight going badly was somebody
losing it.

It is rendered as a contrast between two players and never as a judgement on
one: taking more damage is what an entry fragger does on purpose, and nothing
in the data says which of the two is playing badly. Same rule as §29.3.

### 32.7 The third party is a third *team*, nearby, at the same time

`third_party_team_id` is set when another exchange shares **exactly one** team
with this one, overlaps it in time, and sits within 200 m. Sharing a team is
what makes it a third party rather than an unrelated fight in the same town;
the radius is what stops a four-man squad fighting two teams 800 m apart from
counting as one. 200 m is deliberately the same constant as
`strategy.HOT_DROP_RADIUS_CM` and the review router's own third-party radius,
and `review.py` **imports** it rather than restating it so the page always
reports the number the parser actually segmented with.

Note this is a different measure from §29's third-party rate, which is "another
team's kill within 200 m in the 30 s before *our death*". Denominators are
fights and deaths respectively, and the page keeps them in separate sections
for that reason.

### 32.8 What the corpus tests can and cannot do

Stated in the test module's own docstring, because it changes how much the
green run is worth. `test_roster_agrees_with_the_geometry` in §31 compares two
independent event streams and either they agree or the transform is wrong.
**Nothing plays that role here.** No test can tell you the grouping is right.

What they do instead: pin the arithmetic (both sides sum to the header from
*both* directions, every cross-team kill accounted for exactly once), pin the
invariants the grouping claims (`team_a < team_b`, `seq` dense and in time
order, no silence inside an exchange longer than the gap — re-derived from the
raw stream, not read off the rows), pin **determinism**, and pin the thing the
model exists to fix (`test_kills_arrive_long_after_the_last_hit` fails if
bleed-outs stop being far away, i.e. if the attach rules have become dead code).

One test earned its place immediately.
`test_the_fight_centre_is_equidistant_from_both_sides` was first written as a
bounding-box check and would have passed a victim-only centroid, which at 300 m
puts the fight on top of the team that lost it. Equidistance is the property
that actually distinguishes the two, and it is exact because there is one
attacker and one victim per hit.

### 32.9 A cartesian product that read as a hang

`GET /api/review/engagements` took over 60 s on the first run. The aggregate
select was built over `select(e, ours.c.our_team).join_from(...).subquery()`
while its thirteen `func.count().filter(...)` expressions still referenced `e`
and `ours` directly — so SQLAlchemy put **all three** in the FROM clause: the
subquery, `engagements` again, and `ours` again. Postgres built the product:
506 x 11,158 x 506.

Aggregating straight off the join instead is 183 ms. Worth writing down
because the loud version was the lucky one — on a smaller archive it would
have returned quickly with every count multiplied by 11,158, and a fight count
of 5.6M would have looked like a bug while a *rate* over it would have looked
completely fine.

### 32.10 Reparse

`PARSER_VERSION` 15 -> 16, all 97 matches, no re-download. **No bundle
change** — `hits` already carried everything the model needs — so no replay
needed re-rendering.

| | before | after |
|---|---:|---:|
| `heatmap_bins` rows | 750,359 | 750,359 |
| `heatmap_bins` total | 2,214,264 | 2,214,264 |
| `kill_events` | 9,275 | 9,275 |
| `knock_events` | 7,489 | 7,489 |
| `strategy_metrics` | 9,309 | 9,309 |
| `participant_weapons` | 15,640 | 15,640 |
| `zone_play` | 20,503 | 20,503 |
| `engagements` | 0 | 11,158 |
| `engagement_participants` | 0 | 31,298 |

Then reparsed **a second time** with `staleOnly=false`: every count above
identical, including both new tables. That is the check that matters — neither
has a ledger, so a double-insert would be silent, and
`engagement_participants` has no FK to `engagements` to cascade from.

Across the archive: 11,158 engagements (115/match), 1,316 with a third party
(11.8%), 8,783 cross-team kills attached and **126 unattached (1.41%)** —
within a rounding error of the 1.3% measured on the 25-match sample, and zero
on 31 of 97 matches.

### 32.11 What it says

At 97 matches, 506 fights involving a tracked player over 83 of them:

- **When the squad lands the first blow it ends a fight ahead on kills in 114
  of 133 (86%); when the other side does, 43 of 142 (30%).** The largest split
  anything in this app has produced.
- It lands the first blow in **133 of 275 (48%)** of decided fights — an even
  break, so the advantage above is not something the squad is currently
  getting.
- **231 of 506 exchanges ended with nobody dying.** Most contact is a few shots
  at range.
- 63 of 506 (12%) had a third team fighting one of the two sides at once.
- Fights opening **beyond 150 m are the only band that trades negative**: 16
  kills against 20 deaths across 120 of them. Every closer band is 55-60%.
- DaddyGainz takes 53 damage in the average fight against 42 for AndAy, and
  goes down in 33% of fights against 20% — consistent with §29's independent
  finding that they are first of the squad down most often.

### Verified

`alembic upgrade head` (0010 inspected by hand — both indexes plain B-trees, so
nothing goes in `HAND_MANAGED_INDEXES`). Backend **951 passed, 1 skipped**
(the pre-existing missing-fixture skip), `ruff` clean. Frontend
`npm run check` green — 226 tests across 16 files. Built, then driven in a real
browser: no page errors, no failed requests, no sideways scroll, and the
Fights section rendering all four subsections.
