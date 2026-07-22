# HANDOFF — start here

Written 2026-07-22 at the point where development moves from a Windows
workstation to the Ubuntu deploy server. If you are the next agent picking this
up: **read this file, then `docs/BUILD-SPEC.md`, then start at "What to do
next".**

---

## 1. What this project is

A self-hosted PUBG dashboard for three tracked players — match archive, stats,
heatmaps, and a top-down telemetry-driven match replay. Full goals and design
direction in [`docs/PLAN.md`](docs/PLAN.md); the consolidated implementation
spec is [`docs/BUILD-SPEC.md`](docs/BUILD-SPEC.md).

Tracked players (Steam/PC): **AndAy**, **DaddyGainz**, **SIERIUS_**

| Layer | Choice | Status |
|---|---|---|
| Backend | Python 3.12+, FastAPI, asyncio, uv | Phase 1 partially built |
| DB | Postgres 16 (Docker) | schema written, **never migrated** |
| Storage | MinIO (Docker) | abstraction written, untested |
| Frontend | React + Vite + TS + PixiJS | not started |

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

### Written but NOT reviewed, NOT integrated, NOT run
The Phase 1 build workflow was interrupted partway. These files exist and are
plausible but **no integration pass ever ran, so imports and signatures across
modules were never reconciled**:

```
backend/pubg_dashboard/pubg/{client,ratelimit,errors,schemas}.py
backend/pubg_dashboard/storage/{base,minio,filesystem,factory}.py
backend/pubg_dashboard/queue/{jobs,worker}.py
backend/pubg_dashboard/ingest/{upsert,poller,handlers,importer,ports,queue}.py
backend/pubg_dashboard/db/session.py
backend/pubg_dashboard/cli.py
backend/tests/{conftest,test_ratelimit,test_schemas}.py
```

Note `ingest/queue.py` **and** `queue/jobs.py` both exist — two agents likely
solved the same problem. Reconcile them; don't assume either is correct.

Missing: `tests/test_upsert.py`, `test_client.py`, `test_storage.py`,
`logging.py`, `backend/README.md`, and the Alembic migration (see below).

### Deliberately deleted
`backend/alembic/versions/0001_initial.py` was generated against a schema that
had two data-corrupting defects (§4). It was removed rather than left in place,
because a stale migration is worse than no migration — someone runs it.
**Regenerate it against the current `models.py` once Postgres is reachable.**

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

## 7. Moving to the Ubuntu server

`data/` is **gitignored** (134 MB) and will not clone. It contains the archived
corpus — every test fixture and the entire schema-verification basis.

```bash
# on the server
git clone https://github.com/AndAy224/pubg_dashboard.git
cd pubg_dashboard
cp .env.example .env      # then paste PUBG_API_KEY + set passwords
```

Then get the corpus across, either:

```bash
# preferred — preserves matches that may since have expired
rsync -avz --progress /c/Users/avogt.THEANDAY/Github/pubg_dashboard/data/ \
    user@server:~/pubg_dashboard/data/
```

or re-archive on the server (`uv run scripts/panic_archive.py`, ~14 s) —
but that **only recovers matches still inside PUBG's 14-day window**. Anything
archived on 2026-07-22 that has since aged out is gone. Prefer rsync.

Bring-up:

```bash
docker compose -f docker/docker-compose.yml up -d
cd backend && uv sync
uv run alembic revision --autogenerate -m "initial"   # regenerate; see §3
uv run alembic upgrade head
uv run pubgd import-archive     # load the 61 archived matches, no API calls
uv run pubgd seed               # track the three players
```

---

## 8. What to do next

In order:

1. **Integrate Phase 1.** Nothing has ever been run end to end. Reconcile
   `ingest/queue.py` vs `queue/jobs.py`, fix cross-module imports and signature
   mismatches, add the missing `logging.py`. Target: `uv run pytest -q` green
   and every module importable.
2. **Regenerate the Alembic migration** against the fixed `models.py`, then
   `upgrade head` against real Postgres. Verify the partial indexes and the
   `players` CHECK actually landed — autogenerate handles partial indexes badly,
   so inspect the generated file before applying.
3. **`import-archive`** the 61 matches. This is the first real end-to-end
   exercise of the upsert path, and it runs entirely offline.
4. **Verify against the corpus**, don't trust green tests: after import, assert
   61 matches / 5,584 participants / 1,128 bots / 0 rows in `players` with an
   `ai.` prefix. Those numbers are measured facts, so they're a real oracle.
5. **Start the poller + worker** as systemd units. This is the point at which
   the retention race is finally won permanently.
6. Then Phase 2 (API + frontend shell) per `docs/BUILD-SPEC.md`.

### One thing to confirm early
`X-RateLimit-Reset` units (s / ms / µs) are genuinely ambiguous across sources.
One authenticated request and a comparison against `time.time()` settles it.
Get it wrong and the limiter either never sleeps (constant 429s) or sleeps for
decades.

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
docker/docker-compose.yml    Postgres + MinIO
data/                        GITIGNORED — corpus, fixtures, telemetry
```
