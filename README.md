# PUBG Dashboard

Self-hosted tracking for PUBG players: archived match history, full stats,
kill/landing/movement heatmaps, and a top-down telemetry-driven match replay.

The PUBG API only retains matches for ~14 days. This project polls
continuously so that history accumulates instead of evaporating.

## Stack

| Layer | Tech |
|---|---|
| Ingestion worker | Python 3.12+ · asyncio · httpx |
| Database | PostgreSQL 16 |
| Object storage | MinIO (S3) — raw telemetry, processed replays |
| Backend API | FastAPI · SQLAlchemy 2.0 async · asyncpg · Alembic |
| Frontend | React · Vite · TypeScript · PixiJS · TanStack Query/Table · Recharts |

## Quick start

Prerequisites: [Docker Desktop](https://www.docker.com/products/docker-desktop/),
[uv](https://docs.astral.sh/uv/), Node 20+.

```bash
cp .env.example .env
# edit .env — set PUBG_API_KEY, POSTGRES_PASSWORD, MINIO_ROOT_PASSWORD

docker compose -f docker/docker-compose.yml up -d   # Postgres + MinIO
```

Further setup steps land as each phase is built (see `docs/BUILD-SPEC.md`).

## Layout

```
backend/    ingestion worker, telemetry parser, FastAPI app
frontend/   dashboard SPA + replay renderer
docker/     compose stacks
docs/
  PLAN.md            the original project plan
  BUILD-SPEC.md      consolidated implementation spec
  reference/         verified PUBG API + telemetry schema references
```

`docs/reference/` is the source of truth for PUBG's API shapes. Those documents
were built by cross-checking the official docs against real payloads and
open-source consumers, because the official docs are incomplete and their field
casing is inconsistent. **Read them before touching the parser.**

## Documentation

**Picking this up mid-flight? Read [HANDOFF.md](HANDOFF.md) first.**

- [Handoff](HANDOFF.md) — current state, hard-won facts, what to do next
- [Project plan](docs/PLAN.md) — goals, architecture, milestones, design direction
- [Build spec](docs/BUILD-SPEC.md) — schema, module design, replay file format
- [Reference docs](docs/reference/) — verified PUBG API + telemetry schemas

## License / assets

Map images come from [`pubg/api-assets`](https://github.com/pubg/api-assets),
provided by PUBG for API developers. Personal, self-hosted use only.
