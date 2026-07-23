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
uv run ruff check . --fix                 # clean; keep it that way
uv run mypy pubg_dashboard                # NOT clean — 18 errors, see below

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

`ruff` and both frontend checks pass. **`mypy` does not** — it is configured
`strict = true` but the codebase has never satisfied it (currently 18 errors,
mostly `type-arg`, `import-untyped` from boto3, and SQLAlchemy statement
reassignment). Treat it as a source of hints, not a gate, and do not assume a
red run means you broke something.

Operator CLI (`pubgd`): `seed`, `poll`, `worker`, `import-archive`, `stats`,
`player`, `jobs`. Scripts: `scripts/panic_archive.py` (archive before the 14-day
window closes, idempotent), `scripts/extract_schema.py` (regenerate the observed
schema, ~3 min), `scripts/fetch_map_assets.py` (download + tile maps).

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
- **Bots are ~19% of all kills and just over half of the tracked players'.**
  `kills_human` is the default everywhere; raw `kills` roughly doubles some K/Ds.
- **`NULL != NULL` in Postgres**, so `heatmap_bins` uses `''` sentinels in its
  primary key for `account_id` and `game_mode`. Nullable "all" columns would
  make `ON CONFLICT DO UPDATE` never fire and every reparse would append
  duplicates. Note `match_type` deliberately does **not** follow this pattern —
  it stores the real value, and "all types" is a query omitting the predicate,
  because three values are cheaper to sum than to precompute.
- **`roster.attributes.won` is the string `"true"`/`"false"`.** `bool("false")`
  is `True`.
- **Zone field names are inverted.** `safetyZone*` is the **blue** damaging
  circle (interpolate); `poisonGasWarning*` is the **white** next circle
  (**snap** — it is a step function).
- **`common.isGame == 0.1` is never true**; the wire value is
  `0.10000000149011612`. Compare with tolerance. Gates plane-phase detection
  and the movement heatmap.
- **`LogItemDrop` never fires on death.** The victim emits a `LogItemDetach`
  burst at +0s and a `LogItemUnequip` burst at **exactly +60s**. Suppress item
  events after an account's **final** death — a player can die twice, and seven
  in the corpus died three times.
- **`y` is not inverted** (origin top-left, like canvas), and the
  `8160/8192` correction applies **only** to 816000-cm maps. Both verified
  against the map's own printed town names.
- **`distance = -1` is a "not applicable" sentinel**, 8.6% of kills. Filter
  `> 0` in any "longest kill" query.
- **`asset.attributes.URL` is uppercase.** It gates the entire replay feature.
- **`allWeaponStats` fields are `shots` and `hits`** (plus `dBNOHits`), not
  `shotsFired`/`hitCount`. Reading the wrong names produced `0` for all 5,978
  participants, and because the columns are NOT NULL, `count(shots_fired)`
  reported them fully populated. **`count()` of a non-nullable column proves
  nothing** — use `count(*) FILTER (WHERE col > 0)`. Coverage is also tiny:
  PUBG reports it for ~2 accounts per match and a *tracked* player in 3 of 65,
  so `shots_fired == 0` means "not reported", never "fired nothing".
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

**Point a real browser at it before theorising.** Three frontend bugs in a
row were invisible to `tsc`, `oxlint`, `vitest` and the server logs — the last
was a plain `TypeError` during render that React Router's error boundary
swallowed, taking the whole page with it, and it took ten seconds to find once
a browser was actually loading the page. `frontend/scripts/probe-replay.mjs`
prints page errors, failed requests and a DOM summary, and writes a
screenshot. HANDOFF §17 has the no-root setup for a headless Chrome.

**There is no frontend test runner**

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
