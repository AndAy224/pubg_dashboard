# PUBG Dashboard — Build Spec

Consolidated implementation spec. This is the document you build from.

- **Inputs:** `docs/PLAN.md` (goals/design), `docs/reference/*.md` (verified PUBG shapes).
- **Authority order when two documents disagree:**
  1. `docs/reference/telemetry-observed-schema.md` — machine-generated from **61 real archived
     matches / 2,257,170 events** on the current patch. It outranks everything, including PUBG.
  2. The hand-written reference docs (`pubg-rest-api.md`, `telemetry-*.md`, `match-stats-schema.md`,
     `maps-and-assets.md`).
  3. PUBG's official documentation. It is wrong in several load-bearing places, enumerated in §6.
- **Already true in this repo (do not re-derive):** `data/matches/*.json` (61 raw match payloads),
  `data/telemetry/*.json.gz` (61 raw telemetry files, 134 MB), `scripts/extract_schema.py`,
  `scripts/panic_archive.py`, `backend/pubg_dashboard/{config.py,db/models.py}`,
  `docker/docker-compose.yml`, `.env.example`.

Everything below is decided. Where the research left genuine ambiguity, the option chosen is the
one that survives PUBG changing their schema, and the reason is given in one line.

---

## 1. Directory layout

Monorepo, one repo root, three deployables (api, worker, web).

```
pubg_dashboard/
├── .env                              # gitignored, real secrets
├── .env.example                      # committed, documented template  [EXISTS]
├── .gitignore                        # [EXISTS] — already excludes data/, *.telemetry.json.gz
├── .python-version                   # "3.12"  (uv python pin)
├── README.md                         # [EXISTS]
├── Makefile                          # up / migrate / seed / poll / parse / dev / test
│
├── docs/
│   ├── PLAN.md                       # ← rename of `pubg-dashboard-plan(1).md` (README links here)
│   ├── BUILD-SPEC.md                 # this file
│   └── reference/                    # [EXISTS] 9 verified reference docs — read before parsing
│
├── docker/
│   ├── docker-compose.yml            # [EXISTS] postgres:16-alpine + minio + minio-init
│   ├── docker-compose.prod.yml       # adds api/worker/web containers + caddy
│   ├── Dockerfile.backend            # uv-based multi-stage (deps layer, then source layer)
│   ├── Dockerfile.frontend           # node build → nginx/caddy static serve
│   └── Caddyfile                     # reverse proxy: / → web, /api → api
│
├── scripts/
│   ├── extract_schema.py             # [EXISTS] regenerates telemetry-observed-schema.md
│   ├── panic_archive.py              # [EXISTS] emergency raw archive before the 14-day window closes
│   ├── fetch_map_assets.py           # pull api-assets maps via media.githubusercontent.com (LFS)
│   └── replay_dump.py                # decode a .replay bundle to JSON for eyeballing
│
├── assets/
│   └── maps/                         # gitignored build output of fetch_map_assets.py
│       ├── <MapName>/{0,1,2,3}/x_y.webp   # pyramid tiles, 512px
│       └── manifest.json
│
├── data/                             # gitignored  [EXISTS]
│   ├── fixtures/                     # [EXISTS] committed-by-hand samples used in tests
│   ├── matches/                      # [EXISTS] 61 raw /matches/{id} payloads
│   └── telemetry/                    # [EXISTS] 61 raw telemetry .json.gz
│
├── backend/
│   ├── pyproject.toml                # [EXISTS]
│   ├── uv.lock                       # COMMIT THIS
│   ├── alembic.ini
│   ├── migrations/{env.py,script.py.mako,versions/}
│   ├── tests/
│   │   ├── conftest.py               # testcontainers postgres, fixture loaders
│   │   ├── test_pubg_client.py
│   │   ├── test_parser_golden.py     # runs the parser over data/telemetry/*.gz
│   │   ├── test_inventory_fsm.py
│   │   └── test_api.py
│   └── pubg_dashboard/
│       ├── __init__.py
│       ├── __main__.py
│       ├── config.py                 # [EXISTS] pydantic-settings
│       ├── logging.py                # structlog config
│       ├── cli.py                    # typer: player add/rm/list, backfill, reparse, worker, api
│       ├── db/
│       │   ├── engine.py             # AsyncEngine + async_sessionmaker
│       │   ├── models.py             # [EXISTS — see §2 for required corrections]
│       │   ├── upsert.py             # bulk ON CONFLICT upserts for participants/rosters/bins
│       │   └── queries.py            # read-side SQL for the API (stats aggregates, heatmap fetch)
│       ├── pubg/
│       │   ├── client.py             # httpx AsyncClient wrapper
│       │   ├── ratelimit.py          # token bucket honouring X-RateLimit-*
│       │   ├── shapes.py             # TypedDicts for the JSON:API payloads
│       │   └── errors.py             # PubgNotFound / PubgRateLimited / TelemetryGone
│       ├── ingest/
│       │   ├── poller.py             # tracked-player loop → enqueue fetch_match
│       │   ├── match_fetcher.py      # GET /matches/{id} → matches/rosters/participants
│       │   ├── telemetry_fetcher.py  # CDN download → object storage
│       │   ├── seasons.py            # /seasons cache + player season/ranked/mastery refresh
│       │   └── backfill.py           # new-player bootstrap
│       ├── telemetry/
│       │   ├── reader.py             # gzip + orjson + case-insensitive event access
│       │   ├── events.py             # canonical event-name constants + normaliser
│       │   ├── parse.py              # orchestrator: one pass → all outputs
│       │   ├── frames.py             # position/frame-index builder
│       │   ├── world.py              # zone track, care packages, vehicles, plane path
│       │   ├── combat.py             # kills/knocks/revives/damage → event track + kill_events rows
│       │   ├── inventory.py          # per-player item state machine → delta track + keyframes
│       │   ├── heatmap.py            # bin accumulation
│       │   ├── bundle.py             # MessagePack replay bundle writer (§4)
│       │   └── maps.py               # MAP_WORLD_SIZE / MAP_ASSET_BASE / cm→px
│       ├── storage/
│       │   ├── base.py               # ObjectStore protocol (put/get/exists/delete)
│       │   ├── s3.py                 # MinIO/S3 via boto3
│       │   └── fs.py                 # filesystem fallback
│       ├── jobs/
│       │   ├── queue.py              # claim/complete/fail/reap (FOR UPDATE SKIP LOCKED)
│       │   ├── worker.py             # dispatch loop
│       │   └── handlers/{fetch_match.py,fetch_telemetry.py,parse_telemetry.py,refresh_player.py}
│       └── api/
│           ├── app.py                # create_app() + lifespan
│           ├── deps.py               # Annotated[AsyncSession, Depends(...)] aliases
│           ├── schemas.py            # pydantic response models
│           └── routers/{health,players,matches,replay,heatmap,maps,ingest}.py
│
└── frontend/
    ├── package.json
    ├── vite.config.ts                # proxy /api → localhost:8000
    ├── tsconfig{,.app,.node}.json    # typescript ~6.0.2 — NOT 7.x
    ├── index.html
    ├── public/
    └── src/
        ├── main.tsx  App.tsx  routes.tsx
        ├── styles/{tokens.css,base.css}
        ├── api/{client.ts,queries.ts,types.ts}
        ├── lib/{maps.ts,format.ts,palette.ts,msgpack.ts,replayBundle.ts}
        ├── components/…              # AppShell, DataTable, StatPanel, MatchStrip, …
        ├── replay/                   # the Pixi renderer, zero React inside the loop
        │   ├── ReplayCanvas.tsx      # the only React↔Pixi boundary
        │   ├── engine/{Renderer.ts,Clock.ts,Viewport.ts,layers/*.ts}
        │   └── store.ts              # external store; panels subscribe at ~10 Hz
        ├── pages/{Home,Player,Match,Replay,Compare,Heatmaps,Settings}.tsx
        └── heatmap/{HeatmapCanvas.tsx,blur.ts,ramp.ts}
```

**Why one repo, two package managers:** `uv` and `npm` do not need to know about each other; the
`Makefile` is the only coupling. Do not add a JS monorepo tool for one frontend package.

---

## 2. Postgres schema (final DDL)

Target: **PostgreSQL 16** (already pinned in `docker/docker-compose.yml`). Alembic owns migrations;
this DDL is the target state that `models.py` must produce.

### 2.0 Type conventions

- **`text` everywhere, never `varchar(n)`.** Postgres stores them identically, and every `String(n)`
  in the current `models.py` is a future migration waiting for PUBG to lengthen an ID.
- **No `ENUM` types, no `CHECK` on any PUBG-supplied vocabulary** (`map_name`, `game_mode`,
  `match_type`, `death_type`). The corpus already contains `matchType='tutorialatoz'`, which is in
  no official enum; PUBG ships values before docs. CHECKs are used only on values *we* generate.
- **All timestamps `timestamptz`.** All distances stored as PUBG sends them: participant stats in
  **metres**, telemetry-derived coordinates in **centimetres**. Never mix; the column comment says which.

### 2.1 `players`

```sql
CREATE TABLE players (
    account_id                text        PRIMARY KEY,   -- 'account.<32 hex>'
    name                      text        NOT NULL,      -- current IGN (mutable)
    shard                     text        NOT NULL DEFAULT 'steam',
    tracked                   boolean     NOT NULL DEFAULT false,
    added_at                  timestamptz NOT NULL DEFAULT now(),
    last_polled_at            timestamptz,
    last_seen_match_at        timestamptz,               -- newest match we hold for them
    last_poll_error           text,
    consecutive_poll_failures integer     NOT NULL DEFAULT 0,
    -- Raw season/ranked/mastery blobs live in player_stat_snapshots, not here.
    CONSTRAINT ck_players_is_account CHECK (account_id LIKE 'account.%')
);

-- Poller work query: tracked players, stalest first. Partial => index is ~#tracked rows.
CREATE INDEX ix_players_poll_queue ON players (last_polled_at NULLS FIRST) WHERE tracked;
-- Case-insensitive name search from the UI.
CREATE INDEX ix_players_name_lower ON players (lower(name));
```

> **CORRECTION to the existing `models.py` — this is a data-corrupting bug, fix it before the first
> migration.** The current model gives bots a `players` row and FKs `participants.account_id` to it.
> **Bot account IDs are `ai.<n>` and are only unique *within a match*.** Verified against the
> archive: `ai.322` appears in **4 different matches** as 4 different bots; across 20 matches, 96 of
> 98 `ai.*` IDs recur. A shared `players` row would merge unrelated bots into one fictional player
> whose lifetime stats are the sum of dozens of bots — and would silently poison every aggregate.
>
> **Decision:** `players` holds **human accounts only** (enforced by the CHECK above).
> `participants.account_id` is **plain text with no foreign key**. Bots are identified by
> `participants.is_bot` and never leave the match they were in.
> *Why:* it is the only shape where a bot ID collision is structurally impossible, and dropping one
> FK costs nothing (we always know the match we are inserting into).

### 2.2 `matches`

```sql
CREATE TABLE matches (
    match_id             text        PRIMARY KEY,       -- PUBG UUID; also the object-storage key
    shard                text        NOT NULL,          -- match shard; a match id is shard-scoped
    map_name             text        NOT NULL,          -- Baltic_Main, Desert_Main, Range_Main, …
    game_mode            text        NOT NULL,          -- squad-fpp | duo-fpp | solo | …
    match_type           text        NOT NULL,          -- official | airoyale | tutorialatoz | …
    is_custom_match      boolean     NOT NULL DEFAULT false,
    season_state         text,
    title_id             text,
    duration_s           integer     NOT NULL,
    played_at            timestamptz NOT NULL,          -- = attributes.createdAt (API ingest time!)

    -- telemetry lifecycle
    telemetry_url        text,
    telemetry_key        text,                          -- object-storage key, NULL until fetched
    telemetry_bytes      bigint,
    telemetry_fetched_at timestamptz,
    telemetry_parsed_at  timestamptz,
    parser_version       integer,
    parse_error          text,
    replay_key           text,                          -- object-storage key of the .replay bundle
    replay_bytes         integer,

    -- denormalised from telemetry, cheap and constantly queried
    telemetry_t0         timestamptz,                   -- LogMatchStart._D  (replay epoch)
    team_size            smallint,
    weather_id           text,
    camera_view          text,                          -- FpsOnly | FpsAndTps
    num_start_players    smallint,
    num_start_teams      smallint,
    bot_count            smallint,

    ingested_at          timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT ck_matches_duration_sane CHECK (duration_s >= 0 AND duration_s < 10000)
);

CREATE INDEX ix_matches_played_at ON matches (played_at DESC);
CREATE INDEX ix_matches_map        ON matches (map_name, played_at DESC);
-- Career stats count `official` only; that is the hot aggregate scan.
CREATE INDEX ix_matches_official   ON matches (played_at DESC) WHERE match_type = 'official';
-- Worker backlog queries. Partial => empty once caught up, so they cost nothing.
CREATE INDEX ix_matches_need_tele  ON matches (played_at)
    WHERE telemetry_key IS NULL;
CREATE INDEX ix_matches_need_parse ON matches (played_at)
    WHERE telemetry_key IS NOT NULL AND telemetry_parsed_at IS NULL;
-- Reparse sweep after a parser bump.
CREATE INDEX ix_matches_parser_ver ON matches (parser_version) WHERE telemetry_parsed_at IS NOT NULL;
```

Notes:
- `duration_s < 10000` copies pubg.sh's production corruption filter. It is our constraint, not
  PUBG's vocabulary, so a CHECK is appropriate here.
- `played_at` is `attributes.createdAt`, which is **API ingest time, not match start**. Label it
  that way in the UI; use `telemetry_t0` when you need the real start.
- `Range_Main` (Camp Jackal / training) and `tutorialatoz` matches are **stored but excluded from
  stats by default** — the exclusion is a query-time predicate, never a delete.

### 2.3 `rosters`

```sql
CREATE TABLE rosters (
    match_id text     NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
    team_id  integer  NOT NULL,        -- roster.attributes.stats.teamId; NOT 1..N (245 observed)
    rank     integer  NOT NULL,        -- roster.attributes.stats.rank == participant.winPlace
    won      boolean  NOT NULL,        -- parsed from the STRING "true"/"false"
    PRIMARY KEY (match_id, team_id)
);
CREATE INDEX ix_rosters_match_rank ON rosters (match_id, rank);
```

> The API's `roster.id` is **regenerated per response** — never a key. `(match_id, team_id)` is the
> only stable roster identity, and `teamId` is also what telemetry's `Character.teamId` carries, so
> this PK joins the two data sources for free.

### 2.4 `participants` — exactly the 23 real stat fields

Verified twice: union of stat keys over 5,584 real participants across 61 matches = these 23, no
more, no fewer. `killPoints`, `winPoints`, `rankPoints`, `rankPointsTitle`, `mostDamage`,
`killPlacePoints`, `winPlacePoints` **do not exist** and get no columns.

```sql
CREATE TABLE participants (
    match_id         text    NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
    account_id       text    NOT NULL,        -- 'account.<hex>' OR 'ai.<n>'; NO FK (see §2.1)
    team_id          integer NOT NULL,
    name             text    NOT NULL,        -- IGN snapshot at match time; not a join key
    shard            text,                    -- per-player shard (cross-play console)
    is_bot           boolean NOT NULL DEFAULT false,

    -- the 23 API stat fields, verbatim -------------------------------------
    dbnos            integer          NOT NULL DEFAULT 0,   -- stats.DBNOs (capital DBNO, lower s)
    assists          integer          NOT NULL DEFAULT 0,
    boosts           integer          NOT NULL DEFAULT 0,
    damage_dealt     double precision NOT NULL DEFAULT 0,   -- self-damage already subtracted
    death_type       text             NOT NULL,             -- alive|byplayer|byzone|suicide|logout
    headshot_kills   integer          NOT NULL DEFAULT 0,
    heals            integer          NOT NULL DEFAULT 0,
    kill_place       integer          NOT NULL DEFAULT 0,   -- rank BY KILLS. observed > 100.
    kill_streaks     integer          NOT NULL DEFAULT 0,
    kills            integer          NOT NULL DEFAULT 0,
    longest_kill     double precision NOT NULL DEFAULT 0,   -- METRES
    revives          integer          NOT NULL DEFAULT 0,
    ride_distance    double precision NOT NULL DEFAULT 0,   -- METRES
    road_kills       integer          NOT NULL DEFAULT 0,
    swim_distance    double precision NOT NULL DEFAULT 0,   -- METRES
    team_kills       integer          NOT NULL DEFAULT 0,
    time_survived    double precision NOT NULL DEFAULT 0,   -- SECONDS
    vehicle_destroys integer          NOT NULL DEFAULT 0,
    walk_distance    double precision NOT NULL DEFAULT 0,   -- METRES
    weapons_acquired integer          NOT NULL DEFAULT 0,
    win_place        integer          NOT NULL DEFAULT 0,

    -- telemetry-derived, filled by parse_telemetry (NULL until parsed) ------
    kills_human      integer,          -- kills excluding user_ai victims — the default stat surface
    knocks_human     integer,
    landing_x        double precision, -- CENTIMETRES
    landing_y        double precision,
    landed_at_s      double precision, -- seconds since telemetry_t0
    death_x          double precision, -- CENTIMETRES
    death_y          double precision,
    died_at_s        double precision,
    killer_account_id text,
    death_weapon     text,             -- killerDamageInfo.damageCauserName
    shots_fired      integer,          -- from LogMatchEnd.allWeaponStats (not re-derived)
    shots_hit        integer,
    time_in_vehicle_s double precision,

    PRIMARY KEY (match_id, account_id),
    FOREIGN KEY (match_id, team_id) REFERENCES rosters(match_id, team_id) ON DELETE CASCADE
);

-- The player match-history query: one account, newest match first.
CREATE INDEX ix_participants_account ON participants (account_id, match_id);
-- Scoreboard render: all rows of one match grouped by team.
CREATE INDEX ix_participants_match_team ON participants (match_id, team_id);
-- Every aggregate excludes bots; keep them out of the index entirely.
CREATE INDEX ix_participants_human ON participants (account_id) INCLUDE (match_id) WHERE NOT is_bot;
```

- `participant.id` from the API is regenerated per response — **never** a key.
  `(match_id, account_id)` is correct and is also unique for bots (`ai.N` is unique per match).
- Insert order per match is **matches → rosters → participants**, because of the composite FK.
- `is_bot` is set from telemetry (`Character.type == 'user_ai'`) when available, and falls back to
  `NOT account_id LIKE 'account.%'` before telemetry lands. Both are correct; the telemetry one also
  catches bots that PUBG hands a real-looking ID.

### 2.5 `kill_events` — the one telemetry table that lives in SQL

Everything else telemetry-derived goes into the replay bundle or `heatmap_bins`. Kills are the
exception because the UI must filter and aggregate them by weapon, distance and time in SQL
("longest kills", "kills with the Beryl", weapon-filtered heatmaps) and the bundle cannot answer
cross-match questions.

```sql
CREATE TABLE kill_events (
    match_id           text     NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
    seq                integer  NOT NULL,            -- index in the parsed kill list; stable per parse
    t_s                double precision NOT NULL,    -- seconds since telemetry_t0
    victim_account_id  text     NOT NULL,
    victim_team_id     integer  NOT NULL,
    victim_is_bot      boolean  NOT NULL,
    victim_x           double precision NOT NULL,    -- CENTIMETRES
    victim_y           double precision NOT NULL,
    killer_account_id  text,                         -- NULL: zone / fall / drown / suicide
    killer_team_id     integer,
    killer_is_bot      boolean,
    killer_x           double precision,
    killer_y           double precision,
    dbno_maker_account_id text,                      -- who knocked; 53 % populated
    finisher_account_id   text,                      -- who finished; 97 % populated
    weapon             text,                         -- killerDamageInfo.damageCauserName
    damage_type        text,                         -- killerDamageInfo.damageTypeCategory
    damage_reason      text,                         -- HeadShot | TorsoShot | …
    distance_cm        double precision,             -- CENTIMETRES; -1 means "not applicable"
    is_suicide         boolean  NOT NULL DEFAULT false,
    is_team_kill       boolean  NOT NULL DEFAULT false,
    through_wall       boolean,
    assists            text[]   NOT NULL DEFAULT '{}',  -- assists_AccountId
    PRIMARY KEY (match_id, seq)
);

CREATE INDEX ix_kill_killer  ON kill_events (killer_account_id, match_id) WHERE killer_account_id IS NOT NULL;
CREATE INDEX ix_kill_victim  ON kill_events (victim_account_id, match_id);
CREATE INDEX ix_kill_weapon  ON kill_events (weapon) WHERE killer_account_id IS NOT NULL;
```

> `killer`, `finisher` and `dBNOMaker` are **`dict | null`** in the real corpus (presence 0.96 /
> 0.97 / 0.53). All three columns are nullable and every read must cope. Zone deaths have
> `killer = null` with `damage_type = 'Damage_BlueZone'`.
>
> `distance_cm = -1` occurs and is a sentinel, not a distance. Filter `distance_cm > 0` in any
> "longest kill" query.

### 2.6 `heatmap_bins`

```sql
CREATE TABLE heatmap_bins (
    map_name   text     NOT NULL,
    kind       text     NOT NULL,   -- kill|death|knock|landing|movement|care_package|vehicle_destroy
    account_id text     NOT NULL,   -- '' = global aggregate (NOT NULL — see below)
    game_mode  text     NOT NULL,   -- '' = all modes
    day        date     NOT NULL,
    grid_x     smallint NOT NULL,   -- 0..255
    grid_y     smallint NOT NULL,   -- 0..255
    count      integer  NOT NULL DEFAULT 0,
    PRIMARY KEY (map_name, kind, account_id, game_mode, day, grid_x, grid_y)
);

CREATE INDEX ix_heatmap_lookup ON heatmap_bins (map_name, kind, account_id, day);
CREATE INDEX ix_heatmap_global ON heatmap_bins (map_name, kind, day) WHERE account_id = '';
```

> **CORRECTION to the existing `models.py`.** It declares
> `UNIQUE (map_name, kind, account_id, game_mode, day, grid_x, grid_y)` with `account_id` and
> `game_mode` **nullable**. In Postgres, `NULL` is distinct from `NULL` in a unique constraint, so
> `ON CONFLICT DO UPDATE` on the global rows would **never fire** and every reparse would append a
> duplicate set of bins — silently doubling every global heatmap.
>
> **Decision:** `NOT NULL` with `''` as the "all" sentinel, and the tuple promoted to the primary
> key. *Why:* `UNIQUE NULLS NOT DISTINCT` (PG15+) would also work, but a sentinel makes the upsert,
> the index and the read query identical in every code path and does not depend on the PG version.

Sizing: 256×256 grid × 7 kinds × (N tracked players + 1 global) × modes × days. Sparse in practice —
a match touches a few thousand cells. Roll `day` up to month for rows older than 90 days if it grows.

### 2.7 `player_stat_snapshots` — season / ranked / mastery

Every field in these payloads is either deprecated, being deprecated, or has an undocumented value
vocabulary (`tier`, `subTier`, `rankPointsTitle`). Modelling them as columns guarantees migrations.

```sql
CREATE TABLE player_stat_snapshots (
    account_id  text        NOT NULL,
    kind        text        NOT NULL,   -- season | lifetime | ranked | weapon_mastery | survival_mastery
    season_id   text        NOT NULL DEFAULT '',   -- '' for lifetime/mastery
    fetched_at  timestamptz NOT NULL DEFAULT now(),
    payload     jsonb       NOT NULL,   -- data.attributes, verbatim
    PRIMARY KEY (account_id, kind, season_id)
);
CREATE INDEX ix_snapshots_stale ON player_stat_snapshots (fetched_at);
```

Extract to columns **only** in a view/query, never in the table. `payload -> 'gameModeStats' ->
'squad-fpp' ->> 'kills'` is fast enough at this scale and costs zero migrations when PUBG deprecates
another eight fields.

```sql
CREATE TABLE seasons (
    season_id         text PRIMARY KEY,
    shard             text NOT NULL,
    is_current_season boolean NOT NULL,
    is_offseason      boolean NOT NULL,
    fetched_at        timestamptz NOT NULL DEFAULT now()
);
```
Docs ask for ≤1 request/month against `/seasons`. Refresh weekly at most.

### 2.8 `jobs`

Matches the design in `docs/reference/backend-stack.md` §6, with the state vocabulary fixed.

```sql
CREATE TABLE jobs (
    id           bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind         text        NOT NULL,
    payload      jsonb       NOT NULL DEFAULT '{}'::jsonb,
    dedupe_key   text        NOT NULL,
    state        text        NOT NULL DEFAULT 'pending'
                             CHECK (state IN ('pending','running','done','dead')),
    priority     smallint    NOT NULL DEFAULT 0,
    attempts     smallint    NOT NULL DEFAULT 0,
    max_attempts smallint    NOT NULL DEFAULT 5,
    run_after    timestamptz NOT NULL DEFAULT now(),
    locked_at    timestamptz,
    locked_by    text,
    last_error   text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    finished_at  timestamptz
);

CREATE INDEX        ix_jobs_claim  ON jobs (priority DESC, run_after, id) WHERE state = 'pending';
CREATE UNIQUE INDEX uq_jobs_live   ON jobs (kind, dedupe_key)  WHERE state IN ('pending','running');
CREATE INDEX        ix_jobs_reaper ON jobs (locked_at)         WHERE state = 'running';
CREATE INDEX        ix_jobs_dead   ON jobs (kind, updated_at DESC) WHERE state = 'dead';

ALTER TABLE jobs SET (
    fillfactor = 70,
    autovacuum_vacuum_scale_factor = 0.0,  autovacuum_vacuum_threshold  = 1000,
    autovacuum_analyze_scale_factor = 0.0, autovacuum_analyze_threshold = 1000
);
```

- `state` uses `'dead'`, not `'failed'` — the existing `models.py` comment says `failed`; align on
  `dead` so the CHECK and the reaper agree.
- The unique index is on `(kind, dedupe_key)`, not `dedupe_key` alone: `fetch_telemetry` and
  `parse_telemetry` for the same match legitimately coexist.
- `attempts` increments **at claim time**, so a job that SIGKILLs the worker still dead-letters.
- Reaper: `state='running' AND locked_at < now() - interval '15 minutes'` → back to `pending`.

### 2.9 Aggregates

No `player_daily_stats` table in phase 1–3. `participants` at 100 rows/match × ~50 matches/day is
~5k rows/day; the aggregate scans are milliseconds. Add a materialised view only when a query is
measured slow — precomputed aggregates that can drift are worse than a 20 ms scan.

---

## 3. Backend module design

### 3.1 `pubg/ratelimit.py` — `TokenBucket`

Single shared async token bucket for **keyed** endpoints only. Capacity from
`settings.pubg_rate_limit_per_min` (default 10/min).

- `async acquire()` → sleeps until a token is free.
- `observe(headers)` → case-insensitive read of `X-RateLimit-Limit` / `-Remaining` / `-Reset`;
  resizes the bucket if the granted limit differs from config, and hard-waits on `Remaining == 0`.
- **`X-RateLimit-Reset` units are disputed** (docs say UNIX seconds; issue #61 says microseconds).
  `_normalise_reset()` sniffs magnitude: `>1e15` → µs, `>1e12` → ms, else seconds. Never do raw
  arithmetic on the header.
- On 429: honour `Retry-After` if present, else exponential backoff from 5 s, cap 60 s.
- **`/matches/{id}` and telemetry CDN downloads bypass the bucket entirely.** This is the single
  most important architectural fact: 3 tracked players cost ~3 requests per poll cycle, and fanning
  out to 150 matches + 150 telemetry files costs **zero quota**.

### 3.2 `pubg/client.py` — `PubgClient`

One `httpx.AsyncClient`, `http2=False`, `limits=(max_connections=20, max_keepalive=10)`,
`timeout=Timeout(connect=5, read=60, write=10, pool=5)` (60 s read because telemetry is 3–5 MB gz).

Methods, each returning parsed dicts (not ORM objects):

| Method | Quota | Notes |
|---|---|---|
| `get_players_by_name(names: list[str], shard)` | 1 | ≤10 names/call. **Names are case sensitive.** Handle both 404 and 200-with-empty-`data`. |
| `get_players_by_id(ids, shard)` | 1 | ≤10. Prefer this once IDs are cached. |
| `get_match(match_id, shard)` | **0** | No `Authorization` header at all. |
| `get_season_stats(account_id, season_id, shard)` | 1 | |
| `get_ranked_stats(...)` / `get_weapon_mastery(...)` / `get_survival_mastery(...)` | 1 each | Parse `rankedGameModeStats` / `weaponSummaries` as **open maps**. |
| `get_seasons(shard)` | 1 | Cached ≥7 days in `seasons`. |
| `download_telemetry(url) -> bytes` | **0** | `Accept-Encoding: gzip`. Use the asset's `URL` **verbatim** — never reconstruct the CDN path, never allowlist a host. |

Headers: `Accept: application/vnd.api+json`, `Accept-Encoding: gzip`, `Authorization: Bearer …`
(omitted on `/matches` and telemetry). Retries via `tenacity`: 3 attempts, exponential, retry only on
5xx / connect / read timeout. **404 is terminal** (14-day retention), **403 on telemetry is terminal**
(purged) — both mark the job `dead` immediately rather than burning 5 attempts.

`pubg/shapes.py` holds `TypedDict`s and the two casing landmines as named constants:
`ASSET_URL_KEY = "URL"`, `PARTICIPANT_DBNO_KEY = "DBNOs"` (vs season-stats `dBNOs`).

### 3.3 `ingest/poller.py`

Loop every `POLL_INTERVAL_SECONDS` (default 300):

1. `SELECT account_id FROM players WHERE tracked ORDER BY last_polled_at NULLS FIRST LIMIT 10`.
2. One batched `get_players_by_id` call (1 token for up to 10 players).
3. For each returned player: `relationships.matches.data[].id` minus the IDs already in `matches`.
4. Enqueue `fetch_match` per new ID, `dedupe_key = match_id`, `priority = 10`.
5. Update `last_polled_at`; on failure bump `consecutive_poll_failures` and back off
   `min(2^n * interval, 6h)` — a renamed account 404s forever otherwise.

**Do not trust the match-list ordering.** It is empirically newest-first but documented nowhere; the
diff-against-DB approach does not depend on order at all.

### 3.4 `ingest/match_fetcher.py` (handler `fetch_match`)

1. `GET /matches/{id}` on the match's shard — **free**.
2. Build `id -> object` map from `included[]`. It is a **flat interleaved heterogeneous array**;
   filter by `type`, never index positionally.
3. Upsert `matches` from `data.attributes`.
4. Rosters from `included[type == 'roster']`:
   `team_id = attributes.stats.teamId`, `rank = attributes.stats.rank`,
   **`won = (attributes.won == "true")`** — it is the *string* `"false"`, and `bool("false")` is
   `True` in Python and truthy in JS.
5. Participants: for each roster, walk `relationships.participants.data[].id` into the map. This is
   the **only** participant→team linkage; participants carry no `teamId`. Drop rosters and you lose
   teams permanently.
6. Telemetry asset: `data.relationships.assets.data[0].id` → `included` → **`attributes.URL`**
   (all caps). Index `assets.data` defensively; the schema types it as an array.
7. Bulk upsert (single `INSERT … ON CONFLICT DO UPDATE` with `executemany` bindparams — one round
   trip for ~100 participants).
8. Enqueue `fetch_telemetry` (`dedupe_key = match_id`, priority 5).

### 3.5 `ingest/telemetry_fetcher.py` (handler `fetch_telemetry`)

Stream the CDN response to a temp file, keep it **gzip-compressed on disk**, `put` to object storage
at `telemetry/{shard}/{YYYY}/{MM}/{match_id}.json.gz`, record `telemetry_key` / `telemetry_bytes` /
`telemetry_fetched_at`, enqueue `parse_telemetry` (priority 1). Never `JSON.parse` here — the
fetcher's only job is durability, because the source disappears in 14 days.

If the client already decompressed (httpx does when the server sends `Content-Encoding: gzip`),
re-gzip at level 6 before storing. Store the *compressed* form regardless of what the wire did:
3–5 MB vs 37–39 MB per match.

### 3.6 `telemetry/reader.py` + `events.py`

```python
def load(raw_gz: bytes) -> list[dict]:      # gzip.decompress + orjson.loads
def norm(name: str) -> str:                 # lowercase, for _T dispatch
def ts(d: str) -> float:                    # tolerant ISO-8601 → epoch seconds
```

- `_T` dispatch is via a **lowercased** dict. Non-negotiable: the docs say
  `LogItemPickupFromLootbox`, the wire says `LogItemPickupFromLootBox` (capital B) — 24,974 events
  in our corpus. PC/console casing also differs per PUBG's own changelog.
- `ts()` regex-truncates the fractional part to 6 digits before parsing: `LogMatchDefinition` carries
  **7** fractional digits and Python's `%f` accepts at most 6.
- Unknown `_T` → counted and logged at INFO, never raised. `LogSpecialZoneInCharacters` (13,167
  events in the corpus) is in no official documentation.
- **Never sort by `_D` alone.** File order is authoritative; if you must sort, sort stably on
  `(_D, index)`. `LogMatchDefinition` is element 0 with a timestamp ~84 s *later* than element 1, and
  the last element is **not** `LogMatchEnd`.

### 3.7 `telemetry/parse.py` — the orchestrator (handler `parse_telemetry`)

One streaming pass over ~37k events, fanning out to five accumulators. Never load the file twice.

```
pass 0 (cheap prescan): LogMatchStart → t0, mapName, teamSize, weatherId, blueZoneCustomOptions
                        LogPlayerCreate → roster {accountId: (name, teamId, isBot)}
pass 1 (main):          frames.feed(e) | world.feed(e) | combat.feed(e)
                        | inventory.feed(e) | heatmap.feed(e)
finalise:               LogMatchEnd → final rankings (unwrap CharacterWrapper!)
                        allWeaponStats → per-participant shots/hits
outputs:                bundle.write() → object storage
                        kill_events rows, heatmap_bins upserts,
                        participants telemetry-derived column update,
                        matches.telemetry_parsed_at + parser_version
```

`PARSER_VERSION` is a module constant. Bumping it and running `pubgd reparse` re-derives everything
from stored raw telemetry — **no re-download**, which is the whole reason raw is archived.

Memory: ~40–60 MB peak per match if fully materialised. The worker runs `PARSE_CONCURRENCY=2`.

### 3.8 `telemetry/frames.py` — the frame index

Source: `LogPlayerPosition` (~10.0 s median cadence, 405k events across the corpus — 18 % of the
whole stream), **enriched** with the `Character` snapshots embedded in `LogPlayerAttack`,
`LogPlayerTakeDamage`, `LogPlayerMakeGroggy`, `LogPlayerKillV2`, `LogParachuteLanding`,
`LogVehicleRide`, `LogVehicleLeave`. Those fire at combat time and give sub-10 s fidelity exactly
where the viewer is looking.

Per player, append `(t_ms, x_cm, y_cm, health, flags)` and at the end:
sort by `t`, dedupe samples within 100 ms (keep the last), quantise, emit.

`flags` bitfield: `1 alive`, `2 dbno` (`Character.isDBNO`), `4 inVehicle`, `8 inBlueZone`,
`16 inRedZone`, `32 parachuting` (`common.isGame ≈ 0.1` or before `LogParachuteLanding`).

Clamp `x`/`y` into `[0, worldSize)` before quantising — telemetry legitimately emits negative x
(observed `-11623` cm) and above-range values for aircraft and out-of-bounds.

### 3.9 `telemetry/world.py`

- **Zone track** from `LogGameStatePeriodic` (~10 s). Emit both circles per sample.
  **The names are inverted:** `safetyZone*` is the **BLUE** (current damaging boundary),
  `poisonGasWarning*` is the **WHITE** (next circle). Confirmed by two independent production
  renderers and by the corpus (`safetyZoneRadius` is high-cardinality/continuous;
  `poisonGasWarningRadius` takes 7 discrete values — exactly what a step function looks like).
- Blue circle → **interpolate** between samples. White circle → **snap**, never interpolate.
- `redZoneRadius` and `blackZoneRadius` are **0 in all 61 archived matches**. Emit the tracks anyway
  (one line of code) but guard `radius > 0` before drawing and do not block on them.
- `LogRedZoneEnded` is the only red-zone lifecycle event; there is no start event. Derive activation
  from `redZoneRadius > 0`.
- **Care packages:** `LogCarePackageSpawn` → `LogCarePackageLand` have **no shared id**
  (`itemPackageId` is a class name). Pair by nearest **XY-only** distance (z differs by 30 km).
  Exclude `itemPackageId == 'Uaz_Armored_C'` — it is a flare-gun vehicle delivery, not a crate.
  Note the deliberate misspelling `Carapackage_*`.
- **Vehicles:** there is no periodic vehicle-position event and **`vehicleUniqueId` no longer
  exists** (removed ~v17). Model vehicles as *attached to occupants*: a vehicle's path is its
  driver's `LogPlayerPosition.vehicle` chain between `LogVehicleRide` and `LogVehicleLeave`. Empty
  vehicles are invisible; drop the icon at the last `LogVehicleLeave` position and fade it.
  `feulPercent` — the typo is real.
- **Plane path:** PCA/total-least-squares fit over `LogPlayerPosition` where
  `abs(common.isGame - 0.1) < 1e-6`, direction from `_D` ordering, extended to map bounds. Do **not**
  use ordinary least squares — a north–south flight makes `y = mx + c` explode. Fallback: sorted
  `LogParachuteLanding` locations.

### 3.10 `telemetry/combat.py`

- Kill feed from `LogPlayerKillV2`; keep a `LogPlayerKill` (V1) fallback branch for archived
  pre-v21 matches. V2 has **no** `assistant`, **no** top-level `damageCauserName`/`distance` —
  those live inside `dBNODamageInfo` / `finishDamageInfo` / `killerDamageInfo`.
- `killer` / `finisher` / `dBNOMaker` are nullable objects. `victimVehicle` / `killerVehicle` are
  **zeroed sentinels, not null**, when on foot — test `vehicleType != ""`.
- A player can die **twice** in one match (comeback modes). Key deaths on `accountId` and take the
  **latest** event; keying on the first discards a whole second life.
- `kills_human` = kills where `victim.type != 'user_ai'`. This is the number every stat view shows
  by default; bots are up to ~20 % of a lobby (213 of 1,486 `LogPlayerCreate` in a 15-match sample).
- Damage stats from `LogPlayerTakeDamage` **filtered to `attacker != null`** — the large majority of
  damage events are blue-zone ticks with a null attacker and `attackId = -1`.
- Prefer `LogMatchEnd.allWeaponStats` (a **list** of `{accountId, stats[]}`) over re-deriving
  accuracy from attack/damage events. Also de-dupe throwables: every throw emits **both**
  `LogPlayerAttack` and `LogPlayerUseThrowable` with the same `attackId`.

### 3.11 `telemetry/inventory.py` — the state machine

Per-account state: `slots{primary1, primary2, sidearm, melee, throwable, helmet, vest, backpack}`,
`loose: Multiset[(itemId, tuple(sorted(attachedItems)))]`, `dead_at: float | None`.

Rules, all measured against real data — each one is a class of silent corruption if omitted:

1. **Quantity comes only from `LogItemPickup`.** 100 % of `LogItemPickupFromLootBox` and
   `LogItemPickupFromCarepackage` events are *also* emitted as a plain `LogItemPickup` within 50 ms
   (but **not** at the identical timestamp — exact `_D` matching misses ~22 %). Use the specialised
   events for **provenance only**. Exception: `LogItemPickupFromVehicleTrunk` — apply it only when no
   `LogItemPickup` for the same `(accountId, itemId)` falls within 50 ms (~11 % have no pair).
2. **`LogItemEquip` usually precedes `LogItemPickup`.** Equip must implicitly create an unseen item.
   Same for `LogItemAttach` on an attachment not yet picked up.
3. **`LogItemDrop` never fires on death.** Instead: a `LogItemDetach` burst at +0…1 s and a
   `LogItemUnequip` burst at **exactly +60 s**. Both are engine bookkeeping. **Suppress all item
   events for an account after its final death** or every dead player's gear vanishes 60 s later and
   their weapons lose all attachments.
4. **Attach/detach payloads are authoritative pre-state.** Overwrite the weapon's attachment list
   from `parentItem.attachedItems ± childItem.itemId` rather than mutating your own accumulator —
   it self-heals drift.
5. **`LogItemUse.stackCount` is the pre-deduction count.** `loose.set(item, stackCount)`, never
   `-= 1`: a cancelled use re-emits the event without consuming anything.
6. **Ammo:** `LogItemUse` with `category == 'Ammunition'` is the *reload* event and its `stackCount`
   is exact reserve at that instant. There is no per-shot consumption event. Ship reserve-at-reload;
   mark magazine contents as derived/approximate or omit them.
7. **`LogHeal.item` is uninitialised garbage** ~81–99 % of the time (blank `itemId`, `stackCount` in
   the hundreds of millions). Never display it; correlate with the preceding `LogItemUse`.
8. **Items have no instance id.** The inventory is a multiset keyed on
   `(itemId, sorted(attachedItems))`, never a dict keyed on `itemId` — two identical AKs are
   indistinguishable except by their attachments.
9. `stackCount: 0` is real on genuine items. Do not assert `> 0`, and do not let 0 delete a stack.
10. `subCategory` for backpacks is **`"BackPack"`** (capital P) on the current patch and `"Backpack"`
    on 2018 data — and the official enum file still says `"Backpack"`. Normalise casing before
    comparing. Same for the whole enum: `Bluechip`, `CamoNetting` already exist outside it.

Output: a delta track + periodic keyframes (§4.5).

### 3.12 `telemetry/heatmap.py`

`GRID = 256`. `bin = floor(clamp(coord, 0, worldSize - 1) / worldSize * 256)` — clamp first, or a
single out-of-bounds aircraft position indexes past the array.

| kind | source |
|---|---|
| `kill` | `kill_events.killer_x/y` (null killer → skipped) |
| `death` | `kill_events.victim_x/y` |
| `knock` | `LogPlayerMakeGroggy.victim.location` |
| `landing` | `LogParachuteLanding.character.location` |
| `movement` | `LogPlayerPosition` where `common.isGame >= 1` — **excluding the plane phase**, or every heatmap shows the flight line, not where people go |
| `care_package` | `LogCarePackageLand.itemPackage.location` |
| `vehicle_destroy` | `LogVehicleDestroy.vehicle` occupant position |

Each event increments **two** rows: `account_id = <player>` and `account_id = ''` (global), and
similarly `game_mode = <mode>` and `game_mode = ''`. Accumulate in a dict in-process, then one
`INSERT … ON CONFLICT (…) DO UPDATE SET count = heatmap_bins.count + EXCLUDED.count`.

**Reparse safety:** a reparse would double-count. `parse_telemetry` therefore deletes this match's
contribution first — which requires knowing it. Simplest correct approach: keep the per-match bin
deltas inside the replay bundle (`heat` section, a few KB), and on reparse subtract the old bundle's
deltas before adding the new ones. If the old bundle is missing, refuse to reparse and log.

### 3.13 `api/routers/*`

All under `/api`. Read-only except `players` and `ingest`.

```
GET    /api/health                               → {db, storage, queue_depth, poller_lag_s}
GET    /api/maps                                 → [{mapName, display, worldSize, assetBase, tileUrl}]

GET    /api/players?tracked=&q=                  → tracked cards + search
POST   /api/players            {name, shard}     → resolve → insert → enqueue backfill (202)
DELETE /api/players/{accountId}                  → untrack (never deletes match history)
GET    /api/players/{accountId}                  → profile + latest snapshots
GET    /api/players/{accountId}/matches          ?limit&before&gameMode&mapName&from&to
GET    /api/players/{accountId}/stats            ?window=lifetime|season|range&from&to
GET    /api/players/{accountId}/timeseries       ?metric=kills|damage|winPlace&bucket=day
GET    /api/players/{accountId}/weapons          → from kill_events + allWeaponStats
GET    /api/players/{accountId}/mastery

GET    /api/matches/{matchId}                    → match + rosters + participants (full scoreboard)
GET    /api/matches/{matchId}/strip              → match-strip: phases, kill ticks, alive spans
GET    /api/matches/{matchId}/replay             → the .replay bundle, Content-Encoding: gzip

GET    /api/heatmap  ?map&kind&accountId&gameMode&from&to&grid=256
                                                 → {grid, max, cells: base64 Uint32Array}
GET    /api/compare  ?accountIds=a,b,c

GET    /api/ingest/status                        → queue depth by kind/state, rate-limit headroom,
                                                   oldest unparsed match, last poll per player
POST   /api/ingest/backfill/{accountId}
POST   /api/ingest/reparse    {matchIds?|all}
```

`/replay` streams straight from object storage with `Cache-Control: public, max-age=31536000,
immutable` — a parsed replay for a given `parser_version` never changes. Include `parser_version` in
the object key (`replays/v{N}/{match_id}.replay.gz`) so a parser bump invalidates cleanly.

---

## 4. The processed-replay bundle format

**Container: MessagePack, then gzip.** (`msgpack` is already a backend dependency.)
Extension `.replay.gz`. One file per match per parser version.

**Why MessagePack and not JSON:** the payload is 95 % numeric arrays. MessagePack's `bin` type lets
the server write a raw little-endian typed-array buffer and the browser wrap it with
`new Uint16Array(buf.buffer, buf.byteOffset, n)` — **zero copy, zero parse** for the hot data. JSON
would require parsing ~200k numbers into boxed JS values on the main thread on every seek.

**Endianness is little-endian, always.** Every target platform is LE; the header records it so a
future BE reader can fail loudly instead of rendering noise.

### 4.1 Top level

```
{
  v: 1,                       // bundle format version
  parserVersion: 3,           // telemetry/parse.py PARSER_VERSION
  matchId: "…",  shard: "steam",
  mapName: "Baltic_Main",     // telemetry mapName, NOT the display name
  worldSize: 816000,          // cm; from MAP_WORLD_SIZE[mapName]
  t0: 1753200000000,          // LogMatchStart._D, epoch ms — the replay origin
  durationMs: 1830000,        // last event _D − t0
  tickMs: 100,                // time quantum for every `t` array in this bundle
  teamSize: 4, weatherId: "Clear", cameraView: "FpsOnly",
  le: true,                   // little-endian
  players: [...],             // §4.2
  pos:     {...},             // §4.3
  events:  [...],             // §4.4
  zones:   {...},             // §4.4
  inv:     {...},             // §4.5
  dicts:   {...},             // §4.6
  heat:    {...}              // per-match heatmap deltas, for idempotent reparse (§3.12)
}
```

`tickMs = 100` copies pubg.sh's proven 100 ms bucketing. All `t` values in the bundle are
**Uint16 counts of `tickMs` since `t0`** → 2 bytes, max 6553.5 s (109 min). Matches run ~30 min. The
writer asserts `durationMs / tickMs < 65000` and falls back to `tickMs = 1000` if a freak match
exceeds it; readers must respect the header rather than assuming 100.

### 4.2 `players` — the index that every other array refers to

Array of objects, **position is the player index `p`** used everywhere else. Ordered by `teamId`
then `accountId` so the ordering is deterministic across reparses.

```
[{ a: "account.…" | "ai.322",   // accountId
   n: "PlayerName",             // IGN at match time
   t: 14,                       // teamId
   b: false,                    // isBot  (Character.type == 'user_ai')
   r: 7,                        // final team ranking   (LogMatchEnd, may be 0 if absent)
   ir: 23,                      // final individualRanking
   c: 6 }, …]                   // palette colour index, precomputed team→colour
```

At most 100 entries, so plain maps beat a struct-of-arrays here. `p` is a `Uint8`.

### 4.3 `pos` — the frame index (struct of arrays)

```
pos: {
  n:      18432,             // total sample count across all players
  off:    <bin>,             // Uint32Array[players.length + 1] — CSR offsets into the arrays below
  t:      <bin>,             // Uint16Array[n]  ticks since t0
  x:      <bin>,             // Uint16Array[n]  quantised: round(x_cm / worldSize * 65535)
  y:      <bin>,             // Uint16Array[n]  same
  hp:     <bin>,             // Uint8Array[n]   round(health), 0..100
  flags:  <bin>              // Uint8Array[n]   bit 0 alive, 1 dbno, 2 inVehicle,
                             //                 3 blueZone, 4 redZone, 5 parachuting
}
```

- **CSR layout, not per-player arrays.** Player `p`'s samples are `[off[p], off[p+1])` in every
  array. One allocation per field instead of 100 × 6 = 600 tiny typed arrays; the renderer's inner
  loop keeps a `cursor[p]` integer that only ever advances forward.
- **Samples are per-player time-sorted, globally interleaved by player, not globally time-sorted.**
  That is what makes CSR work.
- **Quantisation:** `worldSize / 65535` = 12.45 cm on an 8×8 km map, 1.56 cm on Haven. Positional
  error is at most half a step — invisible on a map where one screen pixel is ≥ 1 m. Halves the
  bundle vs `Float32`. Decode: `x_cm = x_u16 / 65535 * worldSize`.
- **Do not flip `y`.** Telemetry origin is top-left with `y` growing downward — identical to canvas,
  CSS, SVG and WebGPU screen space. Flip only for a bottom-left renderer (matplotlib, GL NDC).
- Size: ~18k samples × 8 B ≈ **145 KB**, ~40 KB gzipped.

### 4.4 `events` and `zones` — the event track

`events` is a plain array of maps (a few hundred entries; readability beats 4 KB).
Sorted by `t`. Every entry has `{ t, k }` where `k` is a small string kind.

```
{ t: 4213, k: "kill",   v: 22, p: 7, f: 7, d: 12,     // victimIdx, killerIdx, finisherIdx, dbnoMakerIdx
  w: 41, dt: 3, dr: 1, dist: 8564, sui: false, tk: false,
  vx: 41022, vy: 30117, kx: 41890, ky: 29440 }        // Uint16-quantised positions
{ t: 4180, k: "knock",  v: 22, p: 7, w: 41, dist: 8420, vx: …, vy: … }
{ t: 4990, k: "revive", v: 22, p: 9 }
{ t: 3011, k: "cp",     x: …, y: …, land: 3180, items: [41, 88, 88] }   // spawn t, land t
{ t: 1200, k: "ride",   p: 7, veh: 3, x: …, y: … }
{ t: 1460, k: "leave",  p: 7, veh: 3, x: …, y: …, dist: 122000 }
{ t: 900,  k: "land",   p: 7, x: …, y: … }            // LogParachuteLanding
{ t: 2400, k: "phase",  ph: 3 }
```

`w`/`veh`/item values are **indices into `dicts`** (§4.6), not strings — a 4-byte varint instead of a
40-character class name repeated 100 times.

`killerIdx` etc. use `255` as the null sentinel (there is no player 255 in a ≤100-player lobby),
because `killer`, `finisher` and `dBNOMaker` are genuinely nullable in real data.

```
zones: {
  n: 183,
  t:  <bin>,                 // Uint16Array[n]
  bx: <bin>, by: <bin>, br: <bin>,   // Uint16 blue circle  = safetyZone*      (INTERPOLATE)
  wx: <bin>, wy: <bin>, wr: <bin>,   // Uint16 white circle = poisonGasWarning* (SNAP — step fn)
  rx: <bin>, ry: <bin>, rr: <bin>,   // red zone; all-zero on the current patch
  alive: <bin>,              // Uint8Array[n]  numAlivePlayers
  teams: <bin>               // Uint8Array[n]  numAliveTeams
}
plane: { x0, y0, x1, y1 }    // Uint16-quantised entry/exit points of the fitted flight line
```

Radii use the same `worldSize/65535` quantisation as positions, so one decode helper serves both.

### 4.5 `inv` — inventory delta track + keyframes

```
inv: {
  kfEveryMs: 60000,
  kf: [                       // keyframes, ascending by t
    { t: 0,   s: [ /* per player, see below */ ] },
    { t: 600, s: [ … ] }, …
  ],
  n: 9120,                    // delta count
  t:    <bin>,   // Uint16Array[n]
  p:    <bin>,   // Uint8Array[n]   player index
  op:   <bin>,   // Uint8Array[n]   see table
  a:    <bin>,   // Uint16Array[n]  primary item index (dicts.items)
  b:    <bin>,   // Uint16Array[n]  secondary item index (attach child / parent), 0xFFFF = none
  q:    <bin>,   // Uint16Array[n]  quantity (clamped to 65535)
  slot: <bin>    // Uint8Array[n]   slot id, 0xFF = loose
}
```

| `op` | meaning | fields used |
|---:|---|---|
| 0 | `ADD_LOOSE` | `a`, `q` |
| 1 | `REMOVE_LOOSE` | `a`, `q` |
| 2 | `SET_LOOSE` | `a`, `q` — from `LogItemUse` (pre-deduction resync) |
| 3 | `EQUIP` | `a`, `slot` |
| 4 | `UNEQUIP` | `a`, `slot` |
| 5 | `ATTACH` | `a` = parent, `b` = child |
| 6 | `DETACH` | `a` = parent, `b` = child |
| 7 | `CLEAR` | player died — wipe everything, freeze |
| 8 | `ARMOR_DESTROY` | `a`, `slot` (helmet/vest) |
| 9 | `PROVENANCE` | `a`, `b` = source player index (looted from whose crate) — display only |

Slot ids: `0 primary1, 1 primary2, 2 sidearm, 3 melee, 4 throwable, 5 helmet, 6 vest, 7 backpack`.

Keyframe entry, per player (index-aligned with `players`):

```
{ sl: [[itemIdx, [attachIdx, …]] | null, × 8],     // the 8 slots, in slot-id order
  lo: [[itemIdx, qty], …] }                        // loose multiset
```

**Why deltas + keyframes rather than full per-frame snapshots:** a full snapshot per player per
100 ms tick is ~18 000 × 100 snapshots. Deltas are ~9k records = **~70 KB**. Keyframes every 60 s
(31 per match, ~40 KB total) bound the cost of a backwards seek: rewind to the nearest keyframe
≤ `t`, then apply forward deltas — worst case 600 records, sub-millisecond. The alternative
(rebuild from `t = 0`) is 9k records and visibly janky when scrubbing.

An extra keyframe is emitted at every player death, so "what did they have when they died" and the
death-crate view are exact rather than reconstructed.

### 4.6 `dicts`

```
dicts: {
  items:   ["Item_Weapon_AK47_C", "Item_Attach_…", …],   // every itemId in this match
  weapons: ["WeapHK416_C", …],                           // damageCauserName vocabulary
  dmgType: ["Damage_Gun", "Damage_BlueZone", …],
  dmgReason:["TorsoShot","HeadShot", …],
  vehicles:["Dacia_A_03_v2_C", …],
  zones:   ["pochinki","school", …]
}
```

The frontend maps these to display names via the `api-assets` dictionaries, **always with
`dict[id] ?? id`** — the asset repo has been frozen since Oct 2024 and ~11 % of live itemIds are
already missing from it. Never drop a row because a lookup missed.

### 4.7 Budget

| Section | Bytes (100-player squad match) | gz |
|---|---:|---:|
| `pos` | ~145 KB | ~40 KB |
| `inv` deltas + keyframes | ~110 KB | ~35 KB |
| `events` | ~40 KB | ~10 KB |
| `zones` + `plane` + `dicts` + `players` | ~15 KB | ~5 KB |
| **total** | **~310 KB** | **~90 KB** |

Against 37 MB of raw telemetry: a **~400× reduction**, and the browser does one fetch and zero JSON
parsing on the hot path.

---

## 5. Frontend

### 5.1 Routes

| Path | Page | Notes |
|---|---|---|
| `/` | `Home` | tracked-player cards, recent-match feed, ingest health strip |
| `/players/:accountId` | `Player` | tabs: Overview · Matches · Heatmaps · Weapons · Mastery |
| `/matches/:matchId` | `Match` | scoreboard, match strip, per-match heatmap, "Watch Replay" |
| `/matches/:matchId/replay` | `Replay` | full-bleed; the flagship |
| `/compare` | `Compare` | 2–4 players side by side |
| `/heatmaps` | `Heatmaps` | global/aggregate explorer with filters |
| `/settings` | `Settings` | add/remove tracked players, queue + rate-limit status |

`AppShell` = fixed left nav + content + optional right rail, identical on every page except
`/replay`, which mounts bare (`<Outlet>` with no shell) so the canvas is edge-to-edge.

### 5.2 Component tree (the parts that matter)

```
App
└── QueryClientProvider
    └── RouterProvider
        ├── AppShell
        │   ├── LeftNav · TopBar(SearchPlayer, IngestBadge)
        │   └── <Outlet/>
        │       ├── Home        → PlayerCard[] · RecentMatchFeed · IngestHealth
        │       ├── Player      → StatPanelRow · MatchTable(TanStack Table+Virtual)
        │       │                 · TrendChart(Recharts) · PlacementHistogram
        │       │                 · HeatmapCanvas · WeaponTable · MasteryGrid
        │       ├── Match       → MatchHeader · MatchStrip · Scoreboard(grouped by roster)
        │       │                 · KillList · HeatmapCanvas · WatchReplayButton
        │       ├── Compare     → CompareTable · RadarChart
        │       ├── Heatmaps    → FilterBar · HeatmapCanvas · MapPicker
        │       └── Settings    → TrackedPlayerList · AddPlayerForm · QueueTable
        └── Replay (no shell)
            ├── ReplayCanvas          ← the ONLY React↔Pixi boundary
            ├── ReplayTimeline        (match strip + scrubber + kill ticks)
            ├── ReplayControls        (play/pause, 1×–20×, follow-cam toggle)
            ├── KillFeedPanel         subscribes at ~10 Hz
            ├── InventoryPanel        subscribes at ~10 Hz
            ├── TeamListPanel         collapsible right rail
            └── ReplayHotkeys         space / ←→ / ↑↓ / F / Esc
```

### 5.3 Replay renderer architecture

**Rule zero: React never renders at 60 Hz.** The playhead is a `ref`; Pixi is mounted imperatively;
DOM panels subscribe to an external store that ticks at 10 Hz.

```
ReplayCanvas.tsx
  useEffect(() => {
    const app = new Application(); await app.init({ canvas, antialias, preference:'webgpu',
                                                    resolution: devicePixelRatio, autoDensity:true })
    const r = new Renderer(app, bundle); r.start()
    return () => { r.destroy(); app.destroy(true, {children:true, texture:true}) }
  }, [bundle])           // remounts only when the match changes
```

`engine/Renderer.ts` owns a fixed layer stack, bottom to top:

| Layer | Container | Contents | Rebuild cadence |
|---|---|---|---|
| 0 `map` | Sprite/tile grid | map tiles from `assets/maps/<Map>/<z>/x_y.webp` | on zoom-level change |
| 1 `grid` | Graphics, `cacheAsTexture(true)` | 1 km grid + letters | once |
| 2 `heat` | Sprite (optional) | per-match heat overlay | on toggle |
| 3 `trail` | Sprite over a `RenderTexture` | last 30 s of movement | append-only per frame; full redraw on seek |
| 4 `zones` | one Graphics | blue (lerp) + white (snap) + red | every frame, ~0.1 ms |
| 5 `world` | Container, `isRenderGroup = true` | care packages, vehicles, death markers | on event crossing |
| 6 `dots` | Container | 100 pooled Sprites, one atlas, `tint` by team | every frame |
| 7 `labels` | Container of `BitmapText` | names; `visible = false` below a zoom threshold | every frame when visible |
| 8 `fx` | Container, blend `add` | kill flashes, damage lines | on event crossing |

`engine/Clock.ts` — `app.ticker` callback:
```
nowMs += ticker.deltaMS * speed;  tick = nowMs / bundle.tickMs
for p in 0..nPlayers:
    advance cursor[p] while pos.t[cursor[p]+1] <= tick     // O(1), monotonic
    lerp between cursor and cursor+1 → sprite.position.set(...)
```
Backwards seek resets `cursor[]` with a binary search per player (100 searches, ~microseconds) and
clears the trail RenderTexture.

`engine/Viewport.ts` — hand-rolled pan/zoom (`pointerdown/move/up` + `wheel` on the canvas,
applying scale+position to the world container). **Do not take `pixi-viewport`**: last commit
Feb 2025, README still v7-era, and the whole feature is ~80 lines.

**Do not use `@pixi/react`.** Every hot object here is imperative and pooled; the wrapper is 6 months
stale and its `useTick` is not memoised.

**PixiJS v8 API only.** `beginFill`/`drawRect`/`lineStyle`/`app.view`/`cacheAsBitmap` and the
ticker's delta argument are all **gone**. Use `.rect().fill()/.stroke()`, `app.canvas`,
`cacheAsTexture()`, `ticker.deltaMS`.

**Coordinate transform** (`lib/maps.ts`), one function, used by the replay and the heatmap alike:

```ts
const K = worldSize === 816000 ? 0.99609375 : 1      // 8160/8192 — see gotcha #12
const px = (cm: number) => (cm / worldSize) * imageSizePx * K
// no y flip
```

**Store (`replay/store.ts`)** — `useSyncExternalStore`. The renderer writes
`{ tick, selectedPlayer, aliveCount, recentKills }` into it and calls listeners on a 100 ms interval,
not per frame. `KillFeedPanel` and `InventoryPanel` read from it. `InventoryPanel` resolves state by
`applyDeltas(nearestKeyframe(t), t)` — never by replaying from zero.

### 5.4 Heatmap rendering

Offscreen `<canvas>` 256×256 → manual **separable box blur ×3** (a good gaussian approximation) →
256-entry colour LUT → `Texture.from(canvas)` → Pixi Sprite over the map, or a plain positioned
`<canvas>` on non-replay pages.

**Do not use `ctx.filter = 'blur()'`** — it is disabled by default in Safari desktop and iOS
18.0–26.5, so the heatmap would silently render unblurred for a chunk of users. Blurring 65 k cells
by hand is < 5 ms and runs once per filter change.

### 5.5 Frontend pins

`typescript ~6.0.2` (**not** 7.x — no programmatic API, breaks typescript-eslint), `vite 8.1.5`,
`@vitejs/plugin-react 6.x` (Babel removed; skip React Compiler), `react 19.2.x`, `pixi.js 8.19.x`,
`@tanstack/react-query 5.x`, `@tanstack/react-table 8.x` (not the v9 beta), `recharts 3.x`,
lint with `oxlint` (ships in the template, sidesteps the TS-7 lint problem entirely).

---

## 6. Critical gotchas

The things that produce a plausible-looking, wrong result. Ordered by how expensive they are to
discover late.

**Data-model**

1. **Bot account IDs (`ai.<n>`) repeat across matches.** `ai.322` is 4 different bots in our
   archive. Never give bots a `players` row, never FK to one. (§2.1)
2. **`heatmap_bins` uniqueness with NULLs never conflicts** in Postgres → duplicate bins on every
   reparse. Use `''` sentinels. (§2.6)
3. **`roster.attributes.won` is the string `"false"`.** `bool("false")` is `True`;
   `if (roster.won)` is always truthy in JS. Compare to `"true"`.
4. **Participants carry no team ID.** The only participant→team link is
   `roster.relationships.participants`. Drop rosters and teams are gone permanently.
5. **`participant.id` and `roster.id` are regenerated per API response.** Key on
   `(match_id, account_id)` and `(match_id, team_id)`.
6. **`DBNOs` (participant) vs `dBNOs` (season/ranked)** — same concept, two casings, same API. A
   shared TypeScript interface yields `undefined` silently.
7. **`asset.attributes.URL` is all-caps.** The single most-mistyped field in the API, and it is the
   one that gates the entire replay feature.
8. Reparsing without subtracting the previous run's heatmap contribution double-counts every bin.

**Telemetry semantics**

9. **Zone names are inverted.** `safetyZone*` renders as the **blue** circle,
   `poisonGasWarning*` as the **white**. Getting it backwards produces a replay that looks almost
   right and is completely wrong. Interpolate blue; **snap** white.
10. **`LogItemDrop` never fires on death.** The victim emits a `LogItemDetach` burst at +1 s and a
    `LogItemUnequip` burst at **+60 s**. Apply them and every dead player's gear evaporates one
    minute after they die and their weapons lose all attachments.
11. **A player can die twice in one match.** Freeze on the **last** `LogPlayerKillV2` per account,
    not the first — the first discards their entire second life (1,586 item events in one measured
    match).
12. **The `0.99609375` (8160/8192) correction applies only to 816,000-cm maps.** Skip it and every
    point drifts ~0.4 % — 32 m at the edge of Erangel, enough to put kills in the ocean. It is
    **single-sourced** (pubg.sh); verify it against a landmark on the first render.
13. **`y` is NOT inverted.** Origin is top-left, y grows downward — same as canvas/SVG/CSS. Flipping
    it produces a mirrored heatmap that still looks like a heatmap.
14. **Coordinates are centimetres and can go out of range** (negative x observed; aircraft z at
    150,000). Clamp before binning or you index past the array.
15. **`px` per metre differs on every map.** Derive it; never hard-code.
16. **Positions fire only every ~10 s per player.** Interpolation is mandatory, and enriching from
    combat events is what makes fights look right.
17. **100 % of loot-box/care-package pickups are duplicated as a plain `LogItemPickup`** within
    50 ms — but **not** at the same millisecond. De-duping on timestamp equality double-counts ~22 %.
18. **`LogHeal.item` is uninitialised memory** in ~81–99 % of events (`stackCount` in the hundreds
    of millions). Never display it.
19. **`killer`/`finisher`/`dBNOMaker` are nullable; `victimVehicle`/`killerVehicle` are zeroed
    sentinels, not null.** Test `vehicleType !== ""`, not `!= null`.
20. **`LogMatchEnd.gameResultOnFinished.results[]` holds the winning team only** (~4 of 98 players).
    Using it as a scoreboard silently drops 96 % of the lobby. Use
    `characters[].character.ranking` — and **unwrap the `CharacterWrapper`**: reading
    `characters[].ranking` on modern data raises `KeyError`.
21. **`common.isGame === 0.1` is never true** — the value is `0.10000000149011612`. Compare with a
    tolerance. This gates the entire plane-phase detection and the movement heatmap filter.
22. **`_D` has 7 fractional digits on `LogMatchDefinition`.** Python's `%f` accepts 6 and raises.
23. **The array is not strictly time-sorted, and the last element is not `LogMatchEnd`.**
24. **`blueZoneCustomOptions` is a JSON *string*** requiring a second parse (`"[]"` in our corpus).
25. ~~**`LogParachuteLanding.distance` is `0` in all 61 archived matches.**~~ **FALSE — corrected
    2026-07-22.** Measured over the 65-match corpus, `distance` is a real float in 1,429 of 1,430
    sampled events (4.7 to 2,391.7); only 27 of 8,198 are integer `0`.
    The claim came from misreading `telemetry-observed-schema.md`, whose generator collected enum
    candidates from strings/bools/ints **only** — floats were counted in `types` but never in
    `values`, so a 99.7%-float field rendered as `` `0` `` and read as a constant. 219 fields were
    affected the same way, including `common.isGame` (213,056 hidden floats — the very values that
    gotcha #21 is about). `scripts/extract_schema.py` now prints
    "plus N non-enumerated (float) value(s)" so a value list can never again pass for a full range.
    *Still derive landing spots from the event's `location`* — it is the authoritative position and
    `distance` is a scalar, not a coordinate. The advice was right; the stated reason was not.
26. **`redZoneRadius`/`blackZoneRadius` are `0` in all 61 archived matches.** Ship the code paths,
    do not ship a UI that assumes they exist.
27. **Event names: `LogItemPickupFromLootBox` (capital B), `LogItemPickupFromCarepackage`,
    `healAmount` (not `healamount`), `feulPercent`, `atackId`-or-`attackId` on `LogVehicleDestroy`,
    `dBNOId`, `assists_AccountId`, `finishDamageInfo` (not `finisher…`).** Dispatch on lowercased
    names and read both spellings where they conflict.
28. **`LogSpecialZoneInCharacters` (13,167 events) is in no documentation.** An exhaustive `_T`
    switch that throws will die on the first real match.

**Operational**

29. **14-day retention is absolute.** Anything not ingested is gone forever. Phase 1 ships first.
30. **`Item_Ammo_12Guage_C`, `BP_Eragel_CargoShip01_C`, `Carapackage_*` — typos are load-bearing.**
    Never "fix" a key.
31. **`api-assets` High_Res PNGs are Git-LFS pointers on `raw.githubusercontent.com`** (133 bytes of
    ASCII). Use `media.githubusercontent.com/media/…`. Files are 50–95 MB each — tile them at build
    time, never ship them to a browser. `Rondo_Main_Low_Res.png` is a **JPEG** with a `.png`
    extension; `Boardwalk_No_Text_High_Res.png` is 4096², not 8192².
32. **`Assets/Maps` filenames are keyed by display name; `Assets/Icons/Map` by `mapName` code.** Two
    conventions in one repo — the `MAP_ASSET_BASE` table is mandatory.
33. **`api-assets` has been frozen since Oct 2024.** Always render `dict[id] ?? id`.
34. **Every PUBG enum is open.** `matchType='tutorialatoz'` is already in our corpus and in no
    official list. No DB enums, no CHECKs, no exhaustive switches without a default.

---

## 7. Open questions for the user

1. **Actual rate limit.** Is the key still the default 10 req/min, or was a higher limit granted?
   With 3 tracked players 10/min is generous; at 15+ players the poll interval has to stretch. A
   single live probe of `X-RateLimit-Limit` settles it — and would also settle whether
   `X-RateLimit-Reset` is seconds, ms or µs (the docs and issue #61 disagree).
2. **Bots in stats.** Bots are ~14–20 % of a lobby and inflate K/D substantially. Spec assumes
   **`kills_human` is the default everywhere**, with a "include bots" toggle. Confirm, or say if
   raw API `kills` should be the headline number instead.
3. **Which match types count as "career".** Spec excludes `Range_Main`, `tutorialatoz` and custom
   matches from stats by default; `airoyale` (8 of 61 archived matches) is *included*. Should Air
   Royale be excluded too?
4. **Raw telemetry retention.** `.env` currently says keep forever (`RAW_TELEMETRY_RETENTION_DAYS=0`)
   ≈ 3.5 MB/match ≈ 6 GB/year at 50 matches/day. Keep forever (enables reparsing after every parser
   improvement) or expire after N months (processed replays are ~90 KB and always kept)?
5. **Ranked stats.** Worth the quota? The endpoint returns only `squad`/`squad-fpp` per the schema,
   half its fields are deprecated, and the `tier`/`subTier` string vocabulary is undocumented. It is
   one extra request per player per refresh. Ship it in phase 2 or defer?
6. **Map tiles.** The build step downloads 8192² map images (50–95 MB each) and tiles them. Tile
   every map up front (~600 MB of source, ~80 MB of webp output) or lazily on first match seen on
   that map? Only Erangel and Camp Jackal appear in the archive so far.
7. **Auth.** Self-hosted on Proxmox — is the dashboard on a trusted LAN (no auth, spec's assumption)
   or exposed to the internet (needs at minimum basic auth in front of `/api/players` and
   `/api/ingest`, which mutate state and spend quota)?
8. **Second life / comeback modes.** A player who dies, respawns and dies again gets two death
   markers and two crates. Should the replay show both, or only the final death?
9. **`docs/PLAN.md`.** README links to it; the file is currently `pubg-dashboard-plan(1).md` at the
   repo root. Confirm the rename (it is assumed in §1).
