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

Frontend, from `frontend/` (Node via nvm: `. "$HOME/.nvm/nvm.sh"`):

```bash
npm run dev          # :5173, proxies /api to :8000
npm run build        # tsc -b && vite build  -> dist/, which the API serves
npm run typecheck
npm run lint         # oxlint
```

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
  primary key. Nullable "all" columns would make `ON CONFLICT DO UPDATE` never
  fire and every reparse would append duplicates.
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
- **Every PUBG enum is open**, and casing changes between patches. Dispatch on
  lowercased names; never write an exhaustive switch without a default.

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
