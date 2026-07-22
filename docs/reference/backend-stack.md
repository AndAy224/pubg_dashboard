# Backend Stack Reference — Python / FastAPI / Postgres

**Dimension:** `backend-stack`
**Verified:** 2026-07-22
**Scope:** the Python backend for the PUBG stats/replay dashboard — project layout, HTTP API, DB access, migrations, background job queue, PUBG API client (rate limiting + telemetry download), logging, testing.

Everything version-specific in this doc was read off the PyPI JSON API (`https://pypi.org/pypi/<name>/json`) on **2026-07-22**. Everything API-specific was read off the projects' own documentation. Anything I could not confirm is in the [⚠️ Unverified](#-unverified--needs-live-confirmation) section at the bottom and is tagged inline.

---

## Sources

Fetched directly (URL → what was taken from it):

| URL | Used for |
|---|---|
| `https://pypi.org/pypi/{uv,fastapi,sqlalchemy,alembic,pydantic,pydantic-settings,httpx,httpx2,httpcore,asyncpg,structlog,pytest-asyncio,tenacity,testcontainers,uvicorn,psycopg,greenlet,anyio,starlette,orjson,pytest,ruff,mypy,aiolimiter,pgqueuer,procrastinate,granian,uvloop,h11,h2}/json` | exact current stable versions, `requires_python`, `requires_dist`, classifiers, wheel tags |
| `https://pypi.org/pypi/sqlalchemy/2.0.51/json` | cp3xx wheel tags (confirms cp314 wheels ship despite stale classifiers) |
| `https://endoflife.date/api/python.json` | current Python release/EOL matrix |
| `https://api.github.com/repos/{astral-sh/uv,fastapi/fastapi,encode/starlette}/releases/latest` | corroborating release tags + dates |
| https://docs.astral.sh/uv/concepts/projects/layout/ | uv project layout, `.venv`, `uv.lock`, `[tool.uv] managed` |
| https://docs.astral.sh/uv/concepts/projects/dependencies/ | PEP 735 `[dependency-groups]`, `include-group`, `default-groups`, `[tool.uv.sources]`, extras, legacy `dev-dependencies` |
| https://docs.astral.sh/uv/concepts/projects/config/ | `[project.scripts]`, build-system, `tool.uv.package`, `requires-python`, hatchling src layout |
| https://docs.astral.sh/uv/reference/cli/ | `uv run/sync/lock/add/build/tool run/python pin` flags |
| https://fastapi.tiangolo.com/advanced/events/ | lifespan pattern, `on_event` deprecation |
| https://fastapi.tiangolo.com/tutorial/dependencies/ | `Annotated[..., Depends(...)]`, dependency type aliases |
| https://fastapi.tiangolo.com/tutorial/dependencies/dependencies-with-yield/ | yield-dependency + teardown/exception semantics |
| https://fastapi.tiangolo.com/tutorial/bigger-applications/ | `APIRouter` layout, `prefix`/`tags`/`dependencies`, `include_router` |
| https://pydantic.dev/docs/validation/latest/concepts/pydantic_settings/ | `BaseSettings`, `SettingsConfigDict`, source priority order |
| https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html | `create_async_engine`, `async_sessionmaker`, `expire_on_commit=False`, session-per-task, `selectinload`, `dispose()`, greenlet |
| https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#insert-on-conflict-upsert | `on_conflict_do_update`, `excluded`, `index_elements`, `constraint`, `index_where`, `where` |
| https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#module-sqlalchemy.dialects.postgresql.asyncpg | asyncpg DSN, prepared-statement cache, PGBouncer notes |
| https://docs.sqlalchemy.org/en/20/orm/queryguide/dml.html | ORM bulk insert, ORM upsert + `populate_existing`, bulk update by PK, `insertmanyvalues` limits |
| https://docs.sqlalchemy.org/en/20/core/selectable.html | `with_for_update` (listed on `GenerativeSelect`/`Select`) |
| https://raw.githubusercontent.com/sqlalchemy/alembic/main/alembic/templates/async/env.py | canonical async `env.py`, verbatim |
| https://alembic.sqlalchemy.org/en/latest/cookbook.html | `alembic init -t async`, `config.set_main_option`, sharing a connection via `Config.attributes` |
| https://alembic.sqlalchemy.org/en/latest/tutorial.html | template list, `[tool.alembic]` pyproject config (1.16+) |
| https://www.postgresql.org/docs/current/sql-select.html | `FOR UPDATE ... SKIP LOCKED` semantics, verbatim quotes |
| https://www.python-httpx.org/advanced/timeouts/ | `Timeout` semantics + defaults |
| https://www.python-httpx.org/advanced/resource-limits/ | `Limits` defaults |
| https://raw.githubusercontent.com/pydantic/httpx2/main/README.md | httpx2 = Pydantic-stewarded successor to httpx |
| https://httpx2.pydantic.dev/async/ | `AsyncClient`, `stream()`, `aiter_bytes`/`aiter_raw`/`aclose` |
| https://httpx2.pydantic.dev/quickstart/ | streaming, content decoding, `iter_raw` vs `iter_bytes` |
| https://httpx2.pydantic.dev/advanced/resource-limits/ | `httpx2.Limits` defaults (same as httpx) |
| https://httpx2.pydantic.dev/advanced/transports/ | `retries=` only covers `ConnectError`/`ConnectTimeout`; custom transports |
| https://github.com/encode/starlette/blob/master/docs/release-notes.md | Starlette 1.0 removals; 1.2 "Support httpx2 in the test client"; 1.3 httpx2 in `full` extra |
| https://tenacity.readthedocs.io/en/latest/ | `@retry`, `AsyncRetrying`, stop/wait/retry strategies |
| https://tenacity.readthedocs.io/en/latest/api.html | exact signatures incl. `wait_exponential_jitter(initial, max, exp_base, jitter)` |
| https://www.structlog.org/en/stable/standard-library.html | stdlib integration, `ProcessorFormatter`, `foreign_pre_chain` |
| https://www.structlog.org/en/stable/contextvars.html | `merge_contextvars`, `bind_contextvars`, sync/async isolation caveat |
| https://pytest-asyncio.readthedocs.io/en/latest/reference/configuration.html | `asyncio_mode`, `asyncio_default_fixture_loop_scope`, `asyncio_default_test_loop_scope` |
| https://testcontainers-python.readthedocs.io/en/latest/modules/postgres/README.html | `PostgresContainer` usage |
| `https://raw.githubusercontent.com/testcontainers/testcontainers-python/master/modules/postgres/testcontainers/postgres/__init__.py` | exact `PostgresContainer.__init__` / `get_connection_url` signatures |
| https://documentation.pubg.com/en/rate-limits.html | **`X-RateLimit-Limit` / `X-RateLimit-Remaining` / `X-RateLimit-Reset`**, 10 rpm default, 429 |
| https://documentation.pubg.com/en/making-requests.html | required `Authorization` / `Accept` headers, `Accept-Encoding: gzip`, shard URL shape, 14-day retention |

---

## 1. Version matrix (verified 2026-07-22)

| Package | Stable | Notes |
|---|---|---|
| `uv` | **0.11.31** | released 2026-07-22 |
| `fastapi` | **0.139.2** | `requires-python >=3.10`; depends on `starlette>=0.46.0` (no upper bound), `pydantic>=2.9.0`, `typing-inspection>=0.4.2`, `annotated-doc>=0.0.2` |
| `starlette` | **1.3.1** | 1.0 shipped 2026-03-22 — **hard removals**, see §3.4 |
| `pydantic` | **2.13.4** | |
| `pydantic-settings` | **2.14.2** | separate package; depends `pydantic>=2.7.0`, `python-dotenv>=0.21.0` |
| `sqlalchemy` | **2.0.51** | 2.1 is at **2.1.0b3** (beta — do not use yet) |
| `alembic` | **1.18.5** | `requires-python >=3.10` |
| `asyncpg` | **0.31.0** | cp310–cp314 wheels |
| `greenlet` | **3.5.4** | required by SQLAlchemy asyncio |
| `psycopg` (v3) | **3.3.4** | alternative async driver |
| `uvicorn` | **0.51.0** | |
| `httpx` | **0.28.1** | ⚠️ **last release 2024-12-06 — effectively unmaintained** |
| `httpx2` | **2.7.0** | Pydantic-stewarded successor, see §8 |
| `httpcore` | 1.0.9 | (httpx2 uses `httpcore2==2.7.0`) |
| `tenacity` | **9.1.4** | |
| `structlog` | **26.1.0** | |
| `orjson` | 3.11.9 | |
| `pytest` | **9.1.1** | |
| `pytest-asyncio` | **1.4.0** | 1.x line; requires `pytest>=8.4,<10` |
| `pytest-cov` | 7.1.0 | |
| `testcontainers` | **4.14.2** | |
| `ruff` | 0.15.22 | |
| `mypy` | 2.3.0 | |
| `anyio` | 4.14.2 | |
| `aiolimiter` | 1.2.1 | last release 2024-12-08 |
| `typer` | 0.27.0 | if you want a fancier CLI than argparse |

**Python runtime.** Latest stable is **3.14.6** (3.14 released 2025-10-07, EOL 2030-10-31). 3.13.14 is the conservative choice. 3.10 goes EOL **2026-10-31** — do not target it.

> `sqlalchemy` 2.0.51's PyPI *classifiers* stop at 3.13, but it **does ship `cp314` wheels** (verified from the 2.0.51 file list). asyncpg 0.31.0 ships cp314 too. **Recommended: `requires-python = ">=3.13"` and pin `.python-version` to `3.13`** — 3.14 works, but the free-threaded/JIT ecosystem around asyncpg + greenlet is not worth the risk for this project. See [Unverified](#-unverified--needs-live-confirmation).

---

## 2. uv project layout

### 2.1 Directory tree

```
pubg_dashboard/
├── .python-version              # written by `uv python pin 3.13`
├── pyproject.toml
├── uv.lock                      # COMMIT THIS. Managed by uv; never hand-edit.
├── .env                         # gitignored
├── .env.example                 # committed
├── alembic.ini
├── docs/reference/backend-stack.md
├── migrations/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
├── src/
│   └── pubgd/
│       ├── __init__.py
│       ├── __main__.py          # `python -m pubgd`
│       ├── settings.py
│       ├── logging.py
│       ├── db/
│       │   ├── __init__.py
│       │   ├── engine.py        # Database (engine + sessionmaker)
│       │   ├── base.py          # DeclarativeBase
│       │   ├── models.py
│       │   └── upsert.py
│       ├── api/
│       │   ├── __init__.py
│       │   ├── app.py           # create_app() + lifespan
│       │   ├── deps.py          # Annotated dependency aliases
│       │   └── routers/
│       │       ├── __init__.py
│       │       ├── health.py
│       │       ├── matches.py
│       │       └── players.py
│       ├── pubg/
│       │   ├── __init__.py
│       │   ├── client.py        # httpx2 AsyncClient
│       │   └── ratelimit.py     # TokenBucket
│       ├── jobs/
│       │   ├── __init__.py
│       │   ├── queue.py         # claim/complete/fail SQL
│       │   ├── worker.py
│       │   └── handlers/
│       └── cli.py               # console_scripts entry point
└── tests/
    ├── conftest.py
    ├── test_api.py
    └── test_queue.py
```

`src/` layout is deliberate: it stops `import pubgd` from accidentally resolving to the working directory instead of the installed package, which is exactly the failure mode that makes "works in tests, breaks in the wheel" bugs.

### 2.2 `pyproject.toml` (complete, copy-paste)

```toml
[project]
name = "pubgd"
version = "0.1.0"
description = "PUBG stats + replay dashboard backend"
readme = "README.md"
requires-python = ">=3.13"

dependencies = [
    "fastapi>=0.139.2",
    "uvicorn[standard]>=0.51.0",
    "pydantic>=2.13.4",
    "pydantic-settings>=2.14.2",
    "sqlalchemy[asyncio]>=2.0.51,<2.1",
    "asyncpg>=0.31.0",
    "alembic>=1.18.5",
    "httpx2>=2.7.0",
    "tenacity>=9.1.4",
    "structlog>=26.1.0",
    "orjson>=3.11.9",
]

[project.optional-dependencies]
# Runtime extras a *deployer* might opt into. Keep this small.
otel = ["opentelemetry-instrumentation-fastapi"]

[project.scripts]
pubgd = "pubgd.cli:main"                 # uv run pubgd ...
pubgd-worker = "pubgd.jobs.worker:main"  # uv run pubgd-worker
pubgd-api = "pubgd.api.app:main"         # uv run pubgd-api

[dependency-groups]
dev = [
    { include-group = "test" },
    { include-group = "lint" },
]
test = [
    "pytest>=9.1.1",
    "pytest-asyncio>=1.4.0",
    "pytest-cov>=7.1.0",
    "testcontainers[postgres]>=4.14.2",
    "httpx2>=2.7.0",
]
lint = [
    "ruff>=0.15.22",
    "mypy>=2.3.0",
    "asyncpg-stubs>=0.31.3",
]

[tool.uv]
default-groups = ["dev"]
package = true

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/pubgd"]

# ---------------------------------------------------------------- tooling ---
[tool.ruff]
src = ["src", "tests"]
line-length = 100
target-version = "py313"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "ASYNC", "SIM", "RUF", "TID"]

[tool.mypy]
python_version = "3.13"
strict = true
plugins = []                       # SQLAlchemy 2.0 needs NO mypy plugin
mypy_path = "src"

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
# MUST be "session", not "function": §10's `database` fixture is session-scoped and
# owns an AsyncEngine/asyncpg pool. With these pinned to "function" the engine is
# built inside the first test's loop, that loop is then closed, and every later test
# reuses pool connections bound to a dead loop -> intermittent, order-dependent
# `RuntimeError: Task got Future attached to a different loop` / `Event loop is
# closed`. pytest-asyncio 1.4.0 has no scope-mismatch guard, so this fails at
# runtime, never at collection. (Alternative: keep both "function" and make the
# engine fixture function-scoped too.)
asyncio_default_fixture_loop_scope = "session"
asyncio_default_test_loop_scope = "session"
addopts = "-ra --strict-markers --strict-config"
```

**Load-bearing details**

- `[dependency-groups]` is **PEP 735** and is the standard, portable form. `[tool.uv] dev-dependencies` is the *legacy* uv-only form — uv docs say, verbatim: "Eventually, the `dev-dependencies` field will be deprecated and removed." Use `[dependency-groups]`.
- Dependency groups are **not installed by consumers of your wheel** — they exist only for local/CI environments. Use `[project.optional-dependencies]` for anything a deployer must be able to `pip install pubgd[foo]`.
- `include-group` nests groups: `dev = [{ include-group = "test" }]`.
- `[tool.uv] default-groups = ["dev"]` is what makes plain `uv sync` install dev tooling. `"all"` enables every group.
- `[build-system]` presence is what tells uv "this project contains an installable package". `[tool.uv] package = true` forces it; `package = false` forces the opposite (a "virtual"/application project with no wheel).
- `[tool.hatch.build.targets.wheel] packages = ["src/pubgd"]` is **required** with the src layout — hatchling will not find the package otherwise.
- `sqlalchemy[asyncio]` pulls `greenlet`, which the asyncio extension hard-depends on.

### 2.3 uv commands you will actually run

| Command | Effect |
|---|---|
| `uv python pin 3.13` | writes `.python-version` |
| `uv sync` | create/update `.venv` from `uv.lock`, incl. `default-groups` |
| `uv sync --frozen` | sync **without** touching `uv.lock` — use in Docker builds |
| `uv sync --locked` | assert `uv.lock` is already up to date; **fail** otherwise — use in CI |
| `uv sync --no-dev` | runtime deps only — use in the production image layer |
| `uv sync --group lint` | add a non-default group |
| `uv lock --check` | verify the lockfile matches `pyproject.toml` without writing |
| `uv add asyncpg` / `uv add --group test pytest-cov` | edit `pyproject.toml` + relock + sync |
| `uv run pubgd-api` | run a `[project.scripts]` entry point in the project env |
| `uv run -- alembic upgrade head` | run any command in the env (`--` guards flags) |
| `uv run --frozen ...` | run without a relock check (hot path in containers) |
| `uv build` | build sdist + wheel |
| `uvx ruff check` | run a tool without adding it to the project |

**CI gate:** `uv lock --check` (or `uv sync --locked`) as the first CI step. Without it, a stale `uv.lock` silently gets rewritten on a developer machine and CI tests a different dependency set than production.

**Dockerfile shape** (multi-stage, cache-friendly):

```dockerfile
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS build
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
# 1) deps only -> cached layer
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project
# 2) source -> invalidated on every code change
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

FROM python:3.13-slim-bookworm
WORKDIR /app
COPY --from=build /app /app
ENV PATH="/app/.venv/bin:$PATH"
CMD ["pubgd-api"]
```

`--no-install-project` on the first `uv sync` is the whole trick: it resolves and installs third-party deps without needing your source tree, so editing `src/` does not bust the dependency layer.

---

## 3. FastAPI

### 3.1 Settings (`src/pubgd/settings.py`)

pydantic-settings source priority, **highest first** (from the official docs):

1. CLI arguments (when `cli_parse_args` is enabled)
2. Arguments passed to the initializer
3. Environment variables
4. Variables from the dotenv (`.env`) file
5. Variables from the secrets directory
6. Default field values

```python
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),   # later files win
        env_file_encoding="utf-8",
        env_prefix="PUBGD_",
        env_nested_delimiter="__",         # PUBGD_DB__POOL_SIZE -> db.pool_size
        case_sensitive=False,
        extra="ignore",                    # tolerate unrelated vars in .env
    )

    environment: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"
    log_json: bool = True

    # Keep the DSN a plain `str`. See "Implementation notes" for why not PostgresDsn.
    database_url: str = "postgresql+asyncpg://pubgd:pubgd@localhost:5432/pubgd"
    db_pool_size: int = 10
    db_max_overflow: int = 20
    sql_echo: bool = False

    pubg_api_key: SecretStr = Field(default=SecretStr(""))
    pubg_shard: str = "steam"
    pubg_rpm: int = 10                     # PUBG default is 10 req/min

    worker_concurrency: int = 4
    worker_batch_size: int = 10
    telemetry_dir: str = "./data/telemetry"

    @field_validator("database_url")
    @classmethod
    def _require_async_driver(cls, v: str) -> str:
        if not v.startswith("postgresql+asyncpg://"):
            raise ValueError("database_url must use the postgresql+asyncpg:// driver")
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
```

`.env.example`:

```dotenv
PUBGD_ENVIRONMENT=dev
PUBGD_DATABASE_URL=postgresql+asyncpg://pubgd:pubgd@localhost:5432/pubgd
PUBGD_PUBG_API_KEY=eyJ0eXAiOi...
PUBGD_PUBG_SHARD=steam
PUBGD_PUBG_RPM=10
PUBGD_LOG_JSON=true
```

### 3.2 Engine + session factory (`src/pubgd/db/engine.py`)

```python
from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


class Database:
    """Owns the engine + sessionmaker for one process."""

    def __init__(
        self,
        dsn: str,
        *,
        echo: bool = False,
        pool_size: int = 10,
        max_overflow: int = 20,
        application_name: str = "pubgd",
    ) -> None:
        self.engine: AsyncEngine = create_async_engine(
            dsn,
            echo=echo,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout=30,
            pool_recycle=1800,     # recycle before any proxy/idle timeout bites
            pool_pre_ping=True,    # cheap SELECT 1 before handing out a conn
            connect_args={
                "server_settings": {
                    "application_name": application_name,
                    "jit": "off",  # PG JIT hurts short OLTP queries far more than it helps
                },
                "timeout": 10,     # asyncpg TCP connect timeout (seconds)
            },
        )
        self.sessionmaker: async_sessionmaker[AsyncSession] = async_sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
            autoflush=False,
        )

    async def dispose(self) -> None:
        await self.engine.dispose()
```

`expire_on_commit=False` is not optional under asyncio. The SQLAlchemy docs state it plainly: it is set "so that we may access attributes on an object subsequent to a call to `AsyncSession.commit()`". With the default `True`, touching any attribute after commit triggers a lazy refresh, which under asyncio raises `MissingGreenlet`.

### 3.3 App factory + lifespan (`src/pubgd/api/app.py`)

```python
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TypedDict

import httpx2
from fastapi import FastAPI
from fastapi.responses import ORJSONResponse

from pubgd.db.engine import Database
from pubgd.logging import configure_logging
from pubgd.pubg.client import PubgClient
from pubgd.settings import Settings, get_settings


class AppState(TypedDict):
    settings: Settings
    db: Database
    pubg: PubgClient


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[AppState]:
    settings = get_settings()
    configure_logging(json=settings.log_json, level=settings.log_level)

    db = Database(
        settings.database_url,
        echo=settings.sql_echo,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        application_name="pubgd-api",
    )
    pubg = PubgClient(
        api_key=settings.pubg_api_key.get_secret_value(),
        shard=settings.pubg_shard,
        rpm=settings.pubg_rpm,
    )
    try:
        yield {"settings": settings, "db": db, "pubg": pubg}
    finally:
        # Teardown runs in reverse order of acquisition.
        await pubg.aclose()
        await db.dispose()


def create_app() -> FastAPI:
    from pubgd.api.routers import health, matches, players

    app = FastAPI(
        title="PUBG Dashboard API",
        version="0.1.0",
        lifespan=lifespan,
        default_response_class=ORJSONResponse,
    )
    app.include_router(health.router)
    app.include_router(matches.router, prefix="/api/v1")
    app.include_router(players.router, prefix="/api/v1")
    return app


app = create_app()


def main() -> None:
    """`pubgd-api` console script."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "pubgd.api.app:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.environment == "dev",
        log_config=None,  # we own logging; see §10
    )
```

**Yielding a `dict` from `lifespan` is the supported way to publish process-wide singletons.** Starlette merges the yielded mapping into the ASGI `state`, and it surfaces as `request.state.<key>` in handlers. That is strictly better than `app.state`, because it survives `TestClient`/`ASGITransport` app instances and does not require a module-level global.

### 3.4 Starlette 1.0 removals — check before copying old code

The 1.0 line removed the following. Note the changelog attributes these to the **1.0.0rc1 (2026-02-23)** entry, not to 1.0.0 final (2026-03-22), whose entry has only "Added" and "Fixed" sections. The practical conclusion is the same: 1.0.x does not have these APIs.

- `on_startup` / `on_shutdown` parameters from `Starlette` and `Router`
- the `on_event()` decorator
- `add_event_handler()`
- `Router.startup()` / `Router.shutdown()`
- `@app.route()` and `@app.websocket_route()` decorators
- `@app.exception_handler()` and `@app.middleware()` decorators on `Starlette`
- the deprecated `TemplateResponse(name, context)` signature
- the deprecated `method` parameter of `FileResponse`
- `iscoroutinefunction_or_partial()`

⚠️ **This does not mean FastAPI's `on_event` is broken.** Starlette removed `on_event()` from `Starlette`/`Router`, but FastAPI pre-empted that and re-implemented it on its own side in **0.128.3** (PR #14851, "Re-implement `on_event` in FastAPI for compatibility with the next Starlette, while keeping backwards compatibility"), so `@app.on_event()` still exists and still works on FastAPI 0.139.2 + Starlette 1.3.1. Existing FastAPI code is *not* broken by the upgrade.

FastAPI's own `@app.on_event("startup")` is nonetheless legacy — the docs say "If you provide a `lifespan` parameter, `startup` and `shutdown` event handlers will no longer be called. It's all `lifespan` or all events, not both." **Use `lifespan`. Nothing else.**

Also from the changelog: Starlette **1.2.0** added "Support httpx2 in the test client" and **1.3.0** added "`httpx2` to the `full` extra".

### 3.5 Dependencies (`src/pubgd/api/deps.py`)

```python
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from pubgd.db.engine import Database
from pubgd.pubg.client import PubgClient
from pubgd.settings import Settings


def get_settings_dep(request: Request) -> Settings:
    return request.state.settings


def get_database(request: Request) -> Database:
    return request.state.db


def get_pubg(request: Request) -> PubgClient:
    return request.state.pubg


async def get_session(
    db: Annotated[Database, Depends(get_database)],
) -> AsyncIterator[AsyncSession]:
    """Read-only session. Closing rolls back anything uncommitted."""
    async with db.sessionmaker() as session:
        yield session


async def get_tx(
    db: Annotated[Database, Depends(get_database)],
) -> AsyncIterator[AsyncSession]:
    """Write session: commits on success, rolls back on any exception."""
    async with db.sessionmaker() as session, session.begin():
        yield session


# Type aliases — declare once, use everywhere.
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
TxDep = Annotated[AsyncSession, Depends(get_tx)]
PubgDep = Annotated[PubgClient, Depends(get_pubg)]
```

Semantics that matter (from the yield-dependency docs):

- code before `yield` runs before the path operation; code after `yield` runs **after the response is sent**;
- teardown of sub-dependencies happens in the correct reverse order;
- "If you catch an exception in a dependency with `yield`, unless you are raising another `HTTPException` or similar, you should re-raise the original exception." (verbatim)

### 3.6 Routers (`src/pubgd/api/routers/matches.py`)

```python
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from pubgd.api.deps import SessionDep
from pubgd.api.schemas import MatchDetail, MatchSummary
from pubgd.db.models import Match

router = APIRouter(
    prefix="/matches",           # MUST NOT end with "/"
    tags=["matches"],
    responses={404: {"description": "Not found"}},
)


@router.get("", response_model=list[MatchSummary])
async def list_matches(
    session: SessionDep,
    shard: str = Query("steam"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[Match]:
    stmt = (
        select(Match)
        .where(Match.shard == shard)
        .order_by(Match.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list((await session.scalars(stmt)).all())


@router.get("/{match_id}", response_model=MatchDetail)
async def get_match(match_id: str, session: SessionDep) -> Match:
    stmt = (
        select(Match)
        .where(Match.id == match_id)
        .options(selectinload(Match.participants))  # NOT lazy loading — see §4.5
    )
    match = (await session.scalars(stmt)).one_or_none()
    if match is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="match not found")
    return match
```

Router-level `dependencies=[Depends(...)]` run **before** decorator-level, which run before parameter-level. `prefix` must not have a trailing `/`, or you get `//` in paths.

---

## 4. SQLAlchemy 2.0 async

### 4.1 Declarative base with a type-annotation map

```python
# src/pubgd/db/base.py
from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import BigInteger, DateTime, Double, MetaData, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_N_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    type_annotation_map = {
        str: Text,                        # PG: TEXT == VARCHAR, no length penalty
        float: Double,                    # DOUBLE PRECISION, not FLOAT
        int: BigInteger,                  # opt out per-column with mapped_column(SmallInteger)
        dt.datetime: DateTime(timezone=True),   # ALWAYS timestamptz
        dict[str, Any]: JSONB,
        list[Any]: JSONB,
    }
```

The naming convention is not cosmetic: **Alembic autogenerate cannot emit a `DROP CONSTRAINT` for an unnamed constraint.** Set it on day one or you will hand-write migrations forever.

### 4.2 Models (`src/pubgd/db/models.py`)

```python
from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import ForeignKey, Index, SmallInteger, String, desc, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pubgd.db.base import Base


class Match(Base):
    __tablename__ = "match"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    shard: Mapped[str] = mapped_column(String(32))
    game_mode: Mapped[str] = mapped_column(String(32))
    map_name: Mapped[str] = mapped_column(String(64))
    match_type: Mapped[str | None] = mapped_column(String(32))
    is_custom_match: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[dt.datetime]                      # timestamptz, from the API
    duration_s: Mapped[int] = mapped_column(SmallInteger)
    telemetry_url: Mapped[str | None]                    # bare annotation — see note below
    telemetry_path: Mapped[str | None]                   # local file once downloaded
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    ingested_at: Mapped[dt.datetime] = mapped_column(server_default=func.now())

    participants: Mapped[list[Participant]] = relationship(
        back_populates="match",
        cascade="all, delete-orphan",
        lazy="raise",     # see §4.5 — makes accidental lazy loads a loud error
    )

    __table_args__ = (
        # NOTE: must use the string form `desc("created_at")`, NOT `created_at.desc()`.
        # `created_at: Mapped[dt.datetime]` above is an annotation with no assignment, so
        # the name is never bound in the class body (PEP 526) — referencing it here raises
        # `NameError` at import time and the whole models module fails to import.
        Index("ix_match_shard_created_at", "shard", desc("created_at")),
    )


class Participant(Base):
    __tablename__ = "participant"

    match_id: Mapped[str] = mapped_column(
        ForeignKey("match.id", ondelete="CASCADE"), primary_key=True
    )
    participant_id: Mapped[str] = mapped_column(String(36), primary_key=True)

    account_id: Mapped[str | None] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(64))
    # ⚠️ NOT present on `participant.attributes.stats`. Verified against the PUBG API
    # entity shape: `teamId` and `rank` live on the **Roster** object
    # (`roster.attributes.stats.teamId`, `.rank`, `roster.attributes.won`), and roster
    # membership is expressed through the roster -> participants relationship. Both of
    # these columns must be DERIVED from the roster during adaptation. A naive
    # `stats.get("rosterId")` / `stats.get("teamId")` mapping yields silent NULLs.
    team_id: Mapped[int | None] = mapped_column(SmallInteger)
    roster_id: Mapped[str | None] = mapped_column(String(36))
    win_place: Mapped[int | None] = mapped_column(SmallInteger)
    kills: Mapped[int] = mapped_column(SmallInteger, default=0)
    assists: Mapped[int] = mapped_column(SmallInteger, default=0)
    dbnos: Mapped[int] = mapped_column(SmallInteger, default=0)
    headshot_kills: Mapped[int] = mapped_column(SmallInteger, default=0)
    damage_dealt: Mapped[float] = mapped_column(default=0.0)
    walk_distance: Mapped[float] = mapped_column(default=0.0)
    ride_distance: Mapped[float] = mapped_column(default=0.0)
    time_survived: Mapped[float] = mapped_column(default=0.0)
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB)   # full raw attributes.stats
    # Confirmed real `attributes.stats` keys with this exact casing: winPlace, DBNOs,
    # timeSurvived, damageDealt, walkDistance, rideDistance, swimDistance, headshotKills,
    # kills, assists, playerId, name (plus boosts, heals, revives, killPlace, killStreaks,
    # longestKill, roadKills, teamKills, vehicleDestroys, weaponsAcquired, deathType,
    # winPoints/killPoints and their *Delta variants). `swimDistance` has no dedicated
    # column — harmless, the JSONB retains it.

    match: Mapped[Match] = relationship(back_populates="participants")

    __table_args__ = (
        Index("ix_participant_account_id", "account_id"),
        Index("ix_participant_match_win_place", "match_id", "win_place"),
    )
```

> ⚠️ **Bare `Mapped[...]` annotations are not bound names.** `created_at`, `telemetry_url` and `telemetry_path` above are annotation-only (PEP 526), so they exist in `__annotations__` but the names are never bound in the class body. Referencing one later in the same class body — e.g. `created_at.desc()` inside `__table_args__` — raises `NameError` at *import* time and takes the entire models module down with it. Either assign `= mapped_column()`, or use the string form (`desc("created_at")`) inside `__table_args__`, which is what this file does.
>
> ⚠️ **PUBG field names.** `winPlace`, `DBNOs`, `timeSurvived`, `damageDealt`, `walkDistance`, `rideDistance`, `swimDistance`, `headshotKills`, `kills`, `assists`, `playerId`, `name` are confirmed real `attributes.stats` keys with that exact casing. `rosterId` and `teamId` are **not** participant stats — they come off the Roster object and must be derived during adaptation (see the inline note and Unverified #1). The `pubg-api` dimension remains the authority; map everything explicitly in one adapter function and confirm against a live payload.

### 4.3 Bulk upsert — the 100-participants-per-match path

```python
# src/pubgd/db/upsert.py
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from pubgd.db.models import Match, Participant

_PARTICIPANT_PK = ("match_id", "participant_id")
_PARTICIPANT_IMMUTABLE = frozenset(_PARTICIPANT_PK)
_PARTICIPANT_UPDATE_COLS: tuple[str, ...] = tuple(
    c.key for c in Participant.__table__.columns if c.key not in _PARTICIPANT_IMMUTABLE
)


def _dedupe(rows: Iterable[Mapping[str, Any]], keys: Sequence[str]) -> list[dict[str, Any]]:
    """Last write wins. REQUIRED: see the ON CONFLICT gotcha in §11."""
    out: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        out[tuple(row[k] for k in keys)] = dict(row)
    return list(out.values())


async def upsert_participants(
    session: AsyncSession,
    rows: Sequence[Mapping[str, Any]],
    *,
    chunk_size: int = 500,
) -> int:
    """One statement per chunk. 100 rows x ~18 cols = ~1800 bind params: one round trip."""
    if not rows:
        return 0

    values = _dedupe(rows, _PARTICIPANT_PK)
    total = 0
    for start in range(0, len(values), chunk_size):
        chunk = values[start : start + chunk_size]
        stmt = pg_insert(Participant).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=[Participant.match_id, Participant.participant_id],
            set_={name: stmt.excluded[name] for name in _PARTICIPANT_UPDATE_COLS},
        )
        result = await session.execute(stmt)
        total += result.rowcount or 0
    return total


async def upsert_match(session: AsyncSession, row: Mapping[str, Any]) -> None:
    stmt = pg_insert(Match).values([dict(row)])
    stmt = stmt.on_conflict_do_update(
        index_elements=[Match.id],
        set_={
            "telemetry_url": stmt.excluded.telemetry_url,
            "raw": stmt.excluded.raw,
            "map_name": stmt.excluded.map_name,
            "game_mode": stmt.excluded.game_mode,
        },
        # Skip the UPDATE entirely when nothing changed -> no dead tuple, no WAL.
        where=Match.raw.is_distinct_from(stmt.excluded.raw),
    )
    await session.execute(stmt)
```

Generated SQL for the participants path (single round trip, 100 rows):

```sql
INSERT INTO participant (match_id, participant_id, account_id, name, team_id, ...)
VALUES ($1,$2,$3,...), ($19,$20,$21,...), ...   -- 100 tuples
ON CONFLICT (match_id, participant_id) DO UPDATE
SET account_id = excluded.account_id,
    name       = excluded.name,
    team_id    = excluded.team_id,
    ...
```

**Facts this rests on** (all from the SQLAlchemy docs):

| Construct | Behaviour |
|---|---|
| `pg_insert(Model).values([{...}, {...}])` | ORM-compatible upsert; "interpreting parameter dictionaries as ORM mapped attribute keys rather than column names" |
| `stmt.excluded` | the proposed-insertion row; `stmt.excluded.col` or `stmt.excluded["col"]` |
| `index_elements=[...]` | infers the arbiter index from columns (accepts ORM attributes, e.g. `[User.name]`) |
| `constraint="pk_my_table"` / `constraint=tbl.primary_key` | name the arbiter constraint instead |
| `index_where=` | required to target a **partial** unique index |
| `where=` | extra predicate on the DO UPDATE — suppresses no-op updates |
| `.on_conflict_do_nothing(index_elements=[...])` | insert-if-absent |
| `stmt.returning(Model)` + `execution_options={"populate_existing": True}` | needed so already-loaded ORM objects refresh from updated rows |

**Do NOT** do `session.execute(stmt, list_of_dicts)` here. That form is "ORM Bulk Insert with SQL Expressions", where the values go through `executemany`; combining it with `on_conflict_do_update` is a different code path with different `RETURNING` behaviour. `pg_insert(...).values([...])` is the documented upsert form.

**Telemetry-scale inserts (10⁵–10⁶ rows) — use COPY, not INSERT.** `copy_records_to_table` is an asyncpg-only method, so you have to reach through SQLAlchemy to the driver connection. The **documented** bridge is `AdaptedConnection.run_async()`, which "provides access to an awaitable environment where the underlying driver level connection may be acted upon":

```python
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

STAGE_DDL = (
    "CREATE TEMP TABLE _stage_event "
    "(LIKE telemetry_event INCLUDING DEFAULTS) ON COMMIT DROP"
)
MERGE_SQL = (
    "INSERT INTO telemetry_event (match_id, seq, event_type, ts, payload) "
    "SELECT match_id, seq, event_type, ts, payload FROM _stage_event "
    "ON CONFLICT (match_id, seq) DO NOTHING"
)
COLUMNS = ["match_id", "seq", "event_type", "ts", "payload"]


async def copy_events(engine: AsyncEngine, records: list[tuple[Any, ...]]) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(STAGE_DDL))

        raw = await conn.get_raw_connection()   # PoolProxiedConnection
        # .dbapi_connection is the SQLAlchemy AdaptedConnection (the one with run_async).
        # .driver_connection is the ultimate asyncpg.Connection — it has NO run_async().
        adapted = raw.dbapi_connection          # AsyncAdapt_asyncpg_connection
        assert hasattr(adapted, "run_async")

        # run_async() hands us the true asyncpg.Connection inside an await-able scope.
        await adapted.run_async(
            lambda apg: apg.copy_records_to_table(
                "_stage_event", records=records, columns=COLUMNS
            )
        )

        await conn.execute(text(MERGE_SQL))
```

✅ **Resolved (was Unverified #6).** SQLAlchemy's pooling docs are explicit about the two hops: `ManagesConnection.dbapi_connection` is, "for asyncio dialects, … typically an adapter object provided by the SQLAlchemy dialect itself" — that adapter is the `AdaptedConnection` exposing `run_async()`. `PoolProxiedConnection.driver_connection` is instead "the ultimate 'connection' object used by that driver, such as the `asyncpg.Connection` object which will not have standard pep-249 methods". So `driver_connection` has **no** `run_async` and calling it raises `AttributeError` on the telemetry bulk-load path.

Equivalent and arguably simpler: since `engine.begin()` is already inside a real event loop, drive the driver directly and skip the adapter entirely:

```python
await raw.driver_connection.copy_records_to_table(
    "_stage_event", records=records, columns=COLUMNS
)
```

Keep the `assert hasattr(adapted, "run_async")` guard on `dbapi_connection` so a SQLAlchemy upgrade that changes the chain fails loudly.

### 4.4 Concurrency rules

- "A single instance of `AsyncSession` is **not safe for use in multiple, concurrent tasks**." Use a **separate session per task**. Do not share a session across `asyncio.gather` branches.
- One `AsyncEngine` per process is correct; the engine's pool is task-safe.
- `await engine.dispose()` before the event loop closes, or asyncpg leaves sockets dangling and you get "Event loop is closed" noise at shutdown.

### 4.5 Lazy loading does not exist under asyncio

Any attribute access that would emit IO outside a greenlet context raises `MissingGreenlet`. Two sanctioned escapes:

- `selectinload()` — "the most useful eager loading strategy" per the docs; issues one extra `SELECT ... WHERE id IN (...)`, which is exactly right for `Match -> participants`.
- `await session.refresh(obj, ["participants"])` — "a lazy-loaded relationship **can be loaded explicitly under asyncio** using `AsyncSession.refresh()`, **if** the desired attribute name is passed explicitly."

Setting `lazy="raise"` on every relationship turns a runtime `MissingGreenlet` (confusing) into an `InvalidRequestError` at the exact access site (obvious). Do it.

### 4.6 asyncpg dialect specifics

- DSN: `postgresql+asyncpg://user:pass@host:5432/db`
- asyncpg caches prepared statements; size is controlled by `prepared_statement_cache_size`.
- Behind **PgBouncer in transaction mode**: set `prepared_statement_cache_size=0`, use `prepared_statement_name_func` for unique statement names, and use `NullPool` (SQLAlchemy pooling on top of PgBouncer pooling is double-pooling).
- Extra libpq-ish settings go through `connect_args={"server_settings": {...}}`.

---

## 5. Alembic with an async engine

### 5.1 Bootstrap

```bash
uv run -- alembic init -t async migrations
```

Templates available to `alembic init --template <name>`: `generic`, `async`, `multidb`, `pyproject` (PEP 621, Alembic ≥ 1.16), and `pyproject_async`.

### 5.2 `migrations/env.py` — the exact asyncio pattern

The stock template (verbatim from `alembic/templates/async/env.py`) is:

```python
import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

The mechanism to internalise: **Alembic's migration API is synchronous.** `AsyncConnection.run_sync(do_run_migrations)` is what bridges it — it runs the sync callable inside SQLAlchemy's greenlet so that the sync `Connection` it receives can perform IO on the async driver. Never `await` anything inside `do_run_migrations`.

Project version, with settings-driven URL and a test hook:

```python
import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncConnection, async_engine_from_config

from alembic import context

from pubgd.db.base import Base
from pubgd.db import models  # noqa: F401  -- import for side effect: registers tables
from pubgd.settings import get_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# %-escape: alembic.ini values go through ConfigParser interpolation.
config.set_main_option("sqlalchemy.url", get_settings().database_url.replace("%", "%%"))

target_metadata = Base.metadata


def _include_object(obj, name, type_, reflected, compare_to) -> bool:
    # Never autogenerate against tables we do not own.
    if type_ == "table" and name in {"spatial_ref_sys"}:
        return False
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        include_object=_include_object,
        # Serialise concurrent `alembic upgrade` calls (k8s rollouts, multiple workers).
        transaction_per_migration=True,
    )
    with context.begin_transaction():
        connection.exec_driver_sql("SELECT pg_advisory_xact_lock(823041)")
        context.run_migrations()


async def run_async_migrations() -> None:
    # Tests inject a live AsyncConnection via Config.attributes["connection"].
    injected: AsyncConnection | None = config.attributes.get("connection")
    if injected is not None:
        await injected.run_sync(do_run_migrations)
        return

    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

Running it from application/test code:

```python
from alembic import command
from alembic.config import Config


def run_upgrade(sync_conn) -> None:
    cfg = Config("alembic.ini")
    cfg.attributes["connection"] = sync_conn
    command.upgrade(cfg, "head")
```

`alembic.ini` essentials:

```ini
[alembic]
script_location = migrations
prepend_sys_path = .
file_template = %%(year)d%%(month).2d%%(day).2d_%%(rev)s_%%(slug)s
# sqlalchemy.url is set from Settings inside env.py; leave it empty here.
sqlalchemy.url =

[loggers]
keys = root,sqlalchemy,alembic
```

---

## 6. Postgres-backed job queue (`FOR UPDATE SKIP LOCKED`)

PostgreSQL's own words on the semantics:

> "With `NOWAIT`, the statement reports an error, rather than waiting, if a selected row cannot be locked immediately. With `SKIP LOCKED`, any selected rows that cannot be immediately locked are skipped."

> "Skipping locked rows provides an inconsistent view of the data, so this is not suitable for general purpose work, but can be used to avoid lock contention with multiple consumers accessing a queue-like table."

> "Note that `NOWAIT` and `SKIP LOCKED` apply only to the row-level lock(s) — the required `ROW SHARE` table-level lock is still taken in the ordinary way."

### 6.1 Table design

```sql
CREATE TABLE job (
    id            bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind          text        NOT NULL,
    payload       jsonb       NOT NULL DEFAULT '{}'::jsonb,
    state         text        NOT NULL DEFAULT 'pending'
                              CHECK (state IN ('pending','running','done','dead')),
    priority      smallint    NOT NULL DEFAULT 0,      -- higher = sooner
    attempts      smallint    NOT NULL DEFAULT 0,
    max_attempts  smallint    NOT NULL DEFAULT 5,
    run_after     timestamptz NOT NULL DEFAULT now(),
    locked_at     timestamptz,
    locked_by     text,
    last_error    text,
    dedupe_key    text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    finished_at   timestamptz
);

-- The ONLY index the claim query needs. Partial => tiny even with millions of done rows.
CREATE INDEX job_claim_idx
    ON job (priority DESC, run_after, id)
    WHERE state = 'pending';

-- Idempotent enqueue: "download telemetry for match X" must not queue twice.
CREATE UNIQUE INDEX job_dedupe_idx
    ON job (kind, dedupe_key)
    WHERE dedupe_key IS NOT NULL AND state IN ('pending', 'running');

-- Reaper lookup for crashed workers.
CREATE INDEX job_reaper_idx ON job (locked_at) WHERE state = 'running';

-- Dead-letter browsing.
CREATE INDEX job_dead_idx ON job (kind, updated_at DESC) WHERE state = 'dead';

-- Queue tables are extreme-churn tables. Default autovacuum is far too lazy.
ALTER TABLE job SET (
    fillfactor = 70,                          -- leave room for HOT updates
    autovacuum_vacuum_scale_factor  = 0.0,
    autovacuum_vacuum_threshold     = 1000,
    autovacuum_analyze_scale_factor = 0.0,
    autovacuum_analyze_threshold    = 1000,
    autovacuum_vacuum_cost_delay    = 0
);
```

| Column | Type | Meaning |
|---|---|---|
| `id` | `bigint` identity | PK; also the tiebreaker for FIFO within a priority |
| `kind` | `text` | handler discriminator, e.g. `fetch_match`, `download_telemetry`, `parse_telemetry` |
| `payload` | `jsonb` | handler arguments. Keep small — it is copied on every update |
| `state` | `text` + CHECK | `pending` \| `running` \| `done` \| `dead` |
| `priority` | `smallint` | higher runs first; user-triggered work > backfill |
| `attempts` | `smallint` | incremented **at claim time**, not at failure time |
| `max_attempts` | `smallint` | per-job cap; `attempts >= max_attempts` ⇒ dead-letter |
| `run_after` | `timestamptz` | not eligible before this instant — this is both the scheduler and the backoff timer |
| `locked_at` | `timestamptz` | set at claim; used by the reaper to detect crashed workers |
| `locked_by` | `text` | `"{hostname}:{pid}:{task}"` — invaluable in an incident |
| `last_error` | `text` | truncated repr of the last failure |
| `dedupe_key` | `text` | e.g. the match id; enforced by the partial unique index |
| `finished_at` | `timestamptz` | for latency metrics + a retention sweep |

**Why `text` + `CHECK` rather than a Postgres `ENUM`:** adding a state to an `ENUM` requires `ALTER TYPE ... ADD VALUE`, which does not compose well with Alembic's transactional migrations. A CHECK constraint is a one-line `ALTER TABLE`.

**Why `attempts` increments at claim, not at failure:** a worker that is `SIGKILL`ed mid-job never runs the failure path. Incrementing at claim means a job that reliably crashes the process still dead-letters after `max_attempts` instead of poisoning the queue forever.

### 6.2 The claim query

```sql
WITH claimed AS (
    SELECT id
      FROM job
     WHERE state = 'pending'
       AND run_after <= now()
       AND ($2::text IS NULL OR kind = ANY (string_to_array($2, ',')))
     ORDER BY priority DESC, run_after, id
     LIMIT $1
       FOR UPDATE SKIP LOCKED
)
UPDATE job AS j
   SET state      = 'running',
       attempts   = j.attempts + 1,
       locked_at  = now(),
       locked_by  = $3,
       updated_at = now()
  FROM claimed AS c
 WHERE j.id = c.id
RETURNING j.id, j.kind, j.payload, j.attempts, j.max_attempts;
```

Why this exact shape:

- `FOR UPDATE SKIP LOCKED` **must** be inside the CTE. It is a `SELECT` clause; you cannot attach it to an `UPDATE`.
- `LIMIT` is applied *after* skipping, so a batch of `$1` is filled with `$1` genuinely-unlocked rows even under heavy contention.
- `ORDER BY priority DESC, run_after, id` matches `job_claim_idx` exactly, so the claim is an index-only-ish scan of the pending sliver.
- The `UPDATE ... FROM claimed` and the CTE run in **one statement, one transaction** — a worker cannot claim a row and then die before marking it `running`.
- `RETURNING` hands the worker its work without a second round trip.
- Keep this transaction to *just the claim*. Do **not** hold it open for the duration of the job — that is what `locked_at` + the reaper are for. A long-open transaction blocks vacuum on the whole database.

Python:

```python
# src/pubgd/jobs/queue.py
from __future__ import annotations

import dataclasses
import os
import socket
from collections.abc import Sequence
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"

_CLAIM_SQL = text("""
WITH claimed AS (
    SELECT id
      FROM job
     WHERE state = 'pending'
       AND run_after <= now()
       AND (:kinds::text IS NULL OR kind = ANY (string_to_array(:kinds, ',')))
     ORDER BY priority DESC, run_after, id
     LIMIT :batch
       FOR UPDATE SKIP LOCKED
)
UPDATE job AS j
   SET state = 'running',
       attempts = j.attempts + 1,
       locked_at = now(),
       locked_by = :worker,
       updated_at = now()
  FROM claimed AS c
 WHERE j.id = c.id
RETURNING j.id, j.kind, j.payload, j.attempts, j.max_attempts
""")

_COMPLETE_SQL = text("""
UPDATE job
   SET state = 'done', locked_at = NULL, locked_by = NULL,
       finished_at = now(), updated_at = now(), last_error = NULL
 WHERE id = :id AND state = 'running'
""")

# Exponential backoff, capped at 1h, with up to 30s of jitter to break thundering herds.
_FAIL_SQL = text("""
UPDATE job
   SET state      = CASE WHEN attempts >= max_attempts THEN 'dead' ELSE 'pending' END,
       run_after  = now()
                  + (least(power(2, attempts), 3600) + random() * 30) * interval '1 second',
       last_error = left(:err, 4000),
       locked_at  = NULL,
       locked_by  = NULL,
       finished_at = CASE WHEN attempts >= max_attempts THEN now() ELSE NULL END,
       updated_at = now()
 WHERE id = :id AND state = 'running'
RETURNING state
""")

# Explicit non-retryable failure (bad payload, 404 from upstream, parse error).
_KILL_SQL = text("""
UPDATE job
   SET state = 'dead', last_error = left(:err, 4000),
       locked_at = NULL, locked_by = NULL, finished_at = now(), updated_at = now()
 WHERE id = :id
""")

# Reaper: a worker that died holding a job never released it.
_REAP_SQL = text("""
UPDATE job
   SET state = 'pending', locked_at = NULL, locked_by = NULL,
       run_after = now(),
       last_error = coalesce(last_error || ' | ', '') || 'reaped from ' || coalesce(locked_by, '?'),
       updated_at = now()
 WHERE state = 'running'
   AND locked_at < now() - make_interval(secs => :lease_s)
RETURNING id
""")

_ENQUEUE_SQL = text("""
INSERT INTO job (kind, payload, priority, max_attempts, run_after, dedupe_key)
VALUES (:kind, :payload, :priority, :max_attempts,
        coalesce(:run_after, now()), :dedupe_key)
ON CONFLICT DO NOTHING
RETURNING id
""")


@dataclasses.dataclass(frozen=True, slots=True)
class ClaimedJob:
    id: int
    kind: str
    payload: dict[str, Any]
    attempts: int
    max_attempts: int


async def claim(
    session: AsyncSession,
    *,
    batch: int = 10,
    kinds: Sequence[str] | None = None,
    worker: str = WORKER_ID,
) -> list[ClaimedJob]:
    result = await session.execute(
        _CLAIM_SQL,
        {
            "batch": batch,
            "kinds": ",".join(kinds) if kinds else None,
            "worker": worker,
        },
    )
    jobs = [ClaimedJob(**row) for row in result.mappings()]
    await session.commit()   # release the row locks IMMEDIATELY
    return jobs


async def complete(session: AsyncSession, job_id: int) -> None:
    await session.execute(_COMPLETE_SQL, {"id": job_id})
    await session.commit()


async def fail(session: AsyncSession, job_id: int, err: str) -> str:
    result = await session.execute(_FAIL_SQL, {"id": job_id, "err": err})
    state = result.scalar_one_or_none() or "unknown"
    await session.commit()
    return state          # "pending" (will retry) or "dead" (dead-lettered)


async def kill(session: AsyncSession, job_id: int, err: str) -> None:
    await session.execute(_KILL_SQL, {"id": job_id, "err": err})
    await session.commit()


async def reap(session: AsyncSession, *, lease_s: float = 900.0) -> int:
    result = await session.execute(_REAP_SQL, {"lease_s": lease_s})
    n = len(result.fetchall())
    await session.commit()
    return n


async def enqueue(
    session: AsyncSession,
    kind: str,
    payload: dict[str, Any],
    *,
    priority: int = 0,
    max_attempts: int = 5,
    run_after: Any = None,
    dedupe_key: str | None = None,
) -> int | None:
    import json

    result = await session.execute(
        _ENQUEUE_SQL,
        {
            "kind": kind,
            "payload": json.dumps(payload),
            "priority": priority,
            "max_attempts": max_attempts,
            "run_after": run_after,
            "dedupe_key": dedupe_key,
        },
    )
    job_id = result.scalar_one_or_none()   # None => deduped away
    # Commit, like every other helper in this module (claim/complete/fail/kill/reap).
    # Without this, `async with sessionmaker() as s:` closes the session on exit and
    # rolls the INSERT back — the row silently never exists.
    await session.commit()
    return job_id
```

**`enqueue()` self-commits**, matching `claim`/`complete`/`fail`/`kill`/`reap`. If you want to batch many enqueues into one transaction, pass a session you commit yourself and drop the internal `commit()`; just keep it consistent across all six helpers, because callers assume it.

Backoff schedule produced by `least(power(2, attempts), 3600) + random() * 30`:

| `attempts` after claim | base delay | actual `run_after` offset |
|---|---|---|
| 1 | 2 s | 2–32 s |
| 2 | 4 s | 4–34 s |
| 3 | 8 s | 8–38 s |
| 4 | 16 s | 16–46 s |
| 5 | 32 s | → `dead` when `max_attempts = 5` |
| 12 | 3600 s (capped) | 60–60.5 min |

### 6.3 Worker loop

```python
# src/pubgd/jobs/worker.py
from __future__ import annotations

import asyncio
import contextlib
import signal
from collections.abc import Awaitable, Callable

import structlog

from pubgd.db.engine import Database
from pubgd.jobs import queue
from pubgd.jobs.errors import PermanentError
from pubgd.settings import get_settings

log = structlog.get_logger(__name__)

Handler = Callable[[queue.ClaimedJob], Awaitable[None]]
HANDLERS: dict[str, Handler] = {}


async def _run_one(db: Database, job: queue.ClaimedJob) -> None:
    structlog.contextvars.bind_contextvars(
        job_id=job.id, job_kind=job.kind, attempt=job.attempts
    )
    try:
        handler = HANDLERS.get(job.kind)
        if handler is None:
            async with db.sessionmaker() as s:
                await queue.kill(s, job.id, f"no handler for kind={job.kind!r}")
            return

        await handler(job)

        async with db.sessionmaker() as s:
            await queue.complete(s, job.id)
        log.info("job.done")

    except PermanentError as exc:
        async with db.sessionmaker() as s:
            await queue.kill(s, job.id, repr(exc))
        log.warning("job.dead_letter", error=str(exc))

    except asyncio.CancelledError:
        # Shutdown: release the lease so another worker picks it up right away.
        async with db.sessionmaker() as s:
            await queue.fail(s, job.id, "worker shutting down")
        raise

    except Exception as exc:  # noqa: BLE001 - the worker must never die
        async with db.sessionmaker() as s:
            state = await queue.fail(s, job.id, repr(exc))
        log.exception("job.failed", next_state=state)

    finally:
        structlog.contextvars.clear_contextvars()


async def run_worker(db: Database, *, concurrency: int, batch: int) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):   # Windows has no add_signal_handler
            loop.add_signal_handler(sig, stop.set)

    sem = asyncio.Semaphore(concurrency)
    idle_backoff = 0.25

    async with asyncio.TaskGroup() as tg:
        while not stop.is_set():
            async with db.sessionmaker() as s:
                await queue.reap(s, lease_s=900.0)
                jobs = await queue.claim(s, batch=batch)

            if not jobs:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=idle_backoff)
                idle_backoff = min(idle_backoff * 2, 5.0)
                continue

            idle_backoff = 0.25
            for job in jobs:
                async def _guarded(j: queue.ClaimedJob = job) -> None:
                    async with sem:
                        await _run_one(db, j)

                tg.create_task(_guarded())


def main() -> None:
    settings = get_settings()
    db = Database(settings.database_url, application_name="pubgd-worker")

    async def _main() -> None:
        try:
            await run_worker(
                db,
                concurrency=settings.worker_concurrency,
                batch=settings.worker_batch_size,
            )
        finally:
            await db.dispose()

    asyncio.run(_main())
```

**Notes.** Poll-with-backoff is fine at this scale. To go event-driven, add `LISTEN job_new` on a dedicated raw asyncpg connection (`asyncpg.Connection.add_listener`) and `NOTIFY job_new` from `enqueue()`; keep the poll loop as a safety net, because NOTIFY is fire-and-forget and is lost if no listener is connected.

Each handler must own its own `AsyncSession` — never pass the worker-loop session into a handler (§4.4).

---

## 7. Token-bucket rate limiting that honours `X-RateLimit-Reset`

Verified PUBG behaviour (from https://documentation.pubg.com/en/rate-limits.html):

| Header (documented casing) | Contents |
|---|---|
| `X-RateLimit-Limit` | "Request limit per day / per minute" |
| `X-RateLimit-Remaining` | "The number of requests left for the time window" |
| `X-RateLimit-Reset` | "The time that the rate limit will be reset, as a UNIX timestamp" |

Default allowance: **10 requests per minute** for testing/development keys. On exhaustion you get **HTTP 429**, and "you should be able to make requests again within a minute."

HTTP header names are case-insensitive and httpx/httpx2 normalise them, so `response.headers["x-ratelimit-reset"]` and `["X-RateLimit-Reset"]` are equivalent. Do **not** hand-roll a dict lookup on `dict(response.headers)` with the documented casing — that is a real way to silently never see the header.

```python
# src/pubgd/pubg/ratelimit.py
from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping

import structlog

log = structlog.get_logger(__name__)


class TokenBucket:
    """
    Client-side token bucket, overridable by server-sent reset instructions.

    Two independent gates:
      1. local bucket  -- refills at `rate_per_minute / 60` tokens/second
      2. server hold   -- a hard monotonic deadline set from X-RateLimit-Reset / Retry-After

    acquire() is serialised by an asyncio.Lock, which asyncio grants FIFO, so
    concurrent callers are admitted in arrival order rather than starving.
    """

    def __init__(self, rate_per_minute: int, *, burst: int | None = None) -> None:
        if rate_per_minute <= 0:
            raise ValueError("rate_per_minute must be > 0")
        self._capacity = float(burst if burst is not None else rate_per_minute)
        self._refill_per_s = rate_per_minute / 60.0
        self._tokens = self._capacity
        self._updated = time.monotonic()
        self._hold_until = 0.0            # monotonic deadline
        self._lock = asyncio.Lock()

    # -- internals ---------------------------------------------------------
    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._updated
        if elapsed > 0:
            self._tokens = min(self._capacity, self._tokens + elapsed * self._refill_per_s)
            self._updated = now

    # -- public ------------------------------------------------------------
    async def acquire(self, amount: float = 1.0) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                if now < self._hold_until:
                    await asyncio.sleep(self._hold_until - now)
                    continue
                self._refill()
                if self._tokens >= amount:
                    self._tokens -= amount
                    return
                deficit = amount - self._tokens
                await asyncio.sleep(deficit / self._refill_per_s)

    def observe(self, headers: Mapping[str, str], *, status_code: int = 200) -> None:
        """Feed a response's rate-limit headers back into the bucket.

        Safe to call without the lock: asyncio is single-threaded and every
        assignment below is atomic w.r.t. other coroutines.
        """
        limit = _as_int(headers.get("x-ratelimit-limit"))
        remaining = _as_int(headers.get("x-ratelimit-remaining"))
        reset_epoch = _as_int(headers.get("x-ratelimit-reset"))

        # Adopt the server's advertised limit if it differs from our guess.
        if limit and limit > 0:
            server_rate = limit / 60.0
            if abs(server_rate - self._refill_per_s) > 1e-9:
                log.info("ratelimit.adopt_server_limit", limit=limit)
                self._refill_per_s = server_rate
                self._capacity = float(limit)
                self._tokens = min(self._tokens, self._capacity)

        # Trust the server's remaining count over our local estimate, downward only.
        if remaining is not None:
            self._tokens = min(self._tokens, float(remaining))

        # Hard stop until the window resets.
        should_hold = status_code == 429 or (remaining is not None and remaining <= 0)
        if should_hold:
            seconds = None
            if reset_epoch is not None:
                # X-RateLimit-Reset is WALL-CLOCK epoch; convert to monotonic.
                seconds = reset_epoch - time.time()
            if seconds is None:
                seconds = _retry_after_seconds(headers.get("retry-after"))
            if seconds is None:
                seconds = 60.0                       # PUBG: "again within a minute"
            seconds = max(0.0, min(seconds, 300.0))  # clamp: never trust a wild header
            self._hold_until = max(self._hold_until, time.monotonic() + seconds + 0.25)
            self._tokens = 0.0
            log.warning(
                "ratelimit.hold",
                seconds=round(seconds, 2),
                status_code=status_code,
                remaining=remaining,
            )


def _as_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value.strip()))
    except (ValueError, AttributeError):
        return None


def _retry_after_seconds(value: str | None) -> float | None:
    """Retry-After is either delta-seconds or an HTTP-date (RFC 9110)."""
    if value is None:
        return None
    try:
        return float(value.strip())
    except ValueError:
        pass
    from email.utils import parsedate_to_datetime

    try:
        return max(0.0, parsedate_to_datetime(value).timestamp() - time.time())
    except (TypeError, ValueError):
        return None
```

**The two traps this code is written around:**

1. **`X-RateLimit-Reset` is wall-clock epoch seconds; `asyncio.sleep` needs a monotonic delta.** Converting via `reset - time.time()` is correct *and* it means clock skew between your host and PUBG's edge translates directly into over/under-waiting. The `+0.25` fudge and the `min(..., 300)` clamp cover skew and a garbage header respectively. A NTP-drifted container that computes a negative delta would otherwise spin.
2. **A shared bucket must be shared.** One `TokenBucket` instance per **API key**, not per client object, per worker task, or per event loop. If you run N worker processes on one key, the client-side bucket cannot coordinate them — either give each process `rpm // N`, or move the bucket into Postgres/Redis. This is the single most common way a "rate-limited" ingester still gets 429s.

`aiolimiter.AsyncLimiter(max_rate, time_period=60)` is a fine off-the-shelf leaky bucket (`async with limiter:` / `await limiter.acquire(n)` / `limiter.has_capacity(n)`), but it has **no hook to consume server headers** and its last release was 2024-12-08. For an API whose whole contract is "obey my reset header", write the ~60 lines.

---

## 8. HTTP client: `httpx` vs `httpx2`

**This is the biggest stack change since 2024 and it will not be in an LLM's default assumptions.**

- `httpx` is at **0.28.1**, released **2024-12-06**, with no release since.
- `httpx2` is at **2.7.0** (2026-07-14), lives at **github.com/pydantic/httpx2**, docs at **httpx2.pydantic.dev**. Its README: *"HTTPX2 is a continuation of the wonderful work started by [@lovelydinosaur]"* … *"with HTTPX itself seeing limited activity recently, Pydantic is picking up stewardship under the HTTPX2 name so that users have a reliably maintained path forward."*
- Starlette **1.2.0** added "Support httpx2 in the test client"; **1.3.0** added `httpx2` to its `full` extra.
- FastAPI 0.139.2's `standard` extra still pins `httpx<1.0.0,>=0.23.0`.

| | `httpx` 0.28.1 | `httpx2` 2.7.0 |
|---|---|---|
| module name | `httpx` | `httpx2` |
| core dep | `httpcore==1.*` | `httpcore2==2.7.0` |
| TLS trust | `certifi` | `truststore>=0.10` (OS trust store) |
| API | — | "broadly requests-compatible", same design; migration is essentially `s/httpx/httpx2/` |
| maintenance | stalled since 2024-12 | active |

**Recommendation:** use `httpx2` for your own outbound PUBG client. Both packages can be installed simultaneously (different top-level module names), so FastAPI pulling in legacy `httpx` for `TestClient` does not conflict. Everything below is written against `httpx2`; to stay on legacy `httpx`, replace `httpx2` with `httpx` — the `AsyncClient`, `Limits`, `Timeout`, `stream()`, `aiter_bytes()`, `aiter_raw()`, `aclose()` surface is identical.

### 8.1 Pool + timeout tuning

Defaults you are overriding (identical in both libraries):

| Setting | Default | Set it to |
|---|---|---|
| overall timeout | 5 s of network inactivity | see below |
| `Limits.max_connections` | 100 | 20 (you are rate-limited to ~10 rpm anyway) |
| `Limits.max_keepalive_connections` | 20 | 10 |
| `Limits.keepalive_expiry` | 5 s | 30 s |

The four timeout dimensions, per the docs: **connect** = "maximum amount of time to wait until a socket connection to the requested host is established"; **read** = "maximum duration to wait for a chunk of data to be received"; **write** = "maximum duration to wait for a chunk of data to be sent"; **pool** = "maximum duration to wait for acquiring a connection from the connection pool". Each raises its own exception (`ConnectTimeout`, `ReadTimeout`, `WriteTimeout`, `PoolTimeout`), all subclasses of `TimeoutException` → `TransportError`.

### 8.2 The PUBG client

```python
# src/pubgd/pubg/client.py
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx2
import structlog
from tenacity import (
    AsyncRetrying,
    before_sleep_log,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from pubgd.pubg.ratelimit import TokenBucket

log = structlog.get_logger(__name__)

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class RetryableStatusError(Exception):
    def __init__(self, status_code: int, url: str) -> None:
        super().__init__(f"retryable HTTP {status_code} from {url}")
        self.status_code = status_code


class PermanentStatusError(Exception):
    def __init__(self, status_code: int, url: str, body: str) -> None:
        super().__init__(f"HTTP {status_code} from {url}: {body[:500]}")
        self.status_code = status_code


class PubgClient:
    BASE = "https://api.pubg.com"

    def __init__(
        self,
        *,
        api_key: str,
        shard: str = "steam",
        rpm: int = 10,
        max_attempts: int = 5,
    ) -> None:
        self.shard = shard
        self.max_attempts = max_attempts
        self.limiter = TokenBucket(rate_per_minute=rpm)
        self._client = httpx2.AsyncClient(
            base_url=f"{self.BASE}/shards/{shard}",
            headers={
                # Verified against documentation.pubg.com/en/making-requests.html
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/vnd.api+json",
                "Accept-Encoding": "gzip",
                "User-Agent": "pubgd/0.1 (+https://github.com/AndAy224/pubg_dashboard)",
            },
            timeout=httpx2.Timeout(connect=5.0, read=30.0, write=10.0, pool=30.0),
            limits=httpx2.Limits(
                max_connections=20,
                max_keepalive_connections=10,
                keepalive_expiry=30.0,
            ),
            follow_redirects=True,
            http2=False,   # requires the h2 extra; not worth it for this workload
        )
        # SEPARATE client for telemetry CDN downloads: no base_url and, critically,
        # NO Authorization header. Client-level default headers are merged into
        # *every* request regardless of host — an absolute URL bypasses `base_url`
        # but does NOT bypass default headers, so reusing `self._client` would leak
        # the PUBG API key to a third-party CDN on every telemetry fetch. (httpx
        # only strips auth on cross-origin *redirects*, which is not this case.)
        self._cdn = httpx2.AsyncClient(
            headers={
                "Accept-Encoding": "gzip",
                "User-Agent": "pubgd/0.1 (+https://github.com/AndAy224/pubg_dashboard)",
            },
            timeout=httpx2.Timeout(connect=5.0, read=60.0, write=10.0, pool=30.0),
            follow_redirects=True,
        )

    async def aclose(self) -> None:
        await self._client.aclose()
        await self._cdn.aclose()

    # ------------------------------------------------------------------ core
    async def request(self, method: str, url: str, **kwargs: Any) -> httpx2.Response:
        stdlib_log = logging.getLogger("pubgd.http")
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self.max_attempts),
            wait=wait_exponential_jitter(initial=1.0, max=60.0, exp_base=2.0, jitter=2.0),
            retry=retry_if_exception_type((httpx2.TransportError, RetryableStatusError)),
            before_sleep=before_sleep_log(stdlib_log, logging.WARNING),
            reraise=True,
        ):
            with attempt:
                await self.limiter.acquire()
                response = await self._client.request(method, url, **kwargs)
                self.limiter.observe(response.headers, status_code=response.status_code)

                if response.status_code in RETRYABLE_STATUS:
                    # The limiter already parked us until X-RateLimit-Reset on a 429,
                    # so tenacity's own backoff is just belt-and-braces here.
                    raise RetryableStatusError(response.status_code, str(response.url))
                if response.status_code >= 400:
                    raise PermanentStatusError(
                        response.status_code, str(response.url), response.text
                    )
                return response
        raise AssertionError("unreachable")  # pragma: no cover

    async def get_json(self, url: str, **kwargs: Any) -> dict[str, Any]:
        response = await self.request("GET", url, **kwargs)
        return response.json()

    async def get_match(self, match_id: str) -> dict[str, Any]:
        return await self.get_json(f"/matches/{match_id}")

    # ------------------------------------------------------- large downloads
    async def download(
        self,
        url: str,
        dest: Path,
        *,
        keep_compressed: bool = True,
        chunk_size: int = 1 << 16,
    ) -> int:
        """Stream a (gzipped) file straight to disk. Never buffers the whole body.

        `keep_compressed=True`  -> aiter_raw(): bytes exactly as the server sent them.
        `keep_compressed=False` -> aiter_bytes(): Content-Encoding transparently decoded.
        """
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        total = 0

        await self.limiter.acquire()
        # Telemetry lives on a CDN, NOT api.pubg.com. An absolute URL bypasses
        # base_url but NOT client default headers, so this uses `self._cdn` (no
        # Authorization) — never `self._client`, which would ship the API key to
        # a third party. It also makes it trivial to stop spending rate-limit
        # tokens on CDN fetches once Unverified #5 is answered.
        async with self._cdn.stream("GET", url) as response:
            if response.status_code >= 400:
                body = (await response.aread()).decode("utf-8", "replace")
                raise PermanentStatusError(response.status_code, url, body)

            iterator = response.aiter_raw() if keep_compressed else response.aiter_bytes()
            with tmp.open("wb") as fh:
                async for chunk in iterator:
                    fh.write(chunk)
                    total += len(chunk)

        tmp.replace(dest)   # atomic on the same filesystem; no half-written files
        log.info("telemetry.downloaded", url=url, path=str(dest), bytes=total)
        return total
```

**Gzip: the one decision that silently corrupts your cache.**

Per the httpx2 docs: *"Any content encoding that the web server has applied such as gzip, deflate, brotli, or zstd will not be automatically decoded"* when you use `iter_raw()` / `aiter_raw()`. `aiter_bytes()` **does** decode it. So:

| Server response | `aiter_raw()` writes | `aiter_bytes()` writes |
|---|---|---|
| `Content-Encoding: gzip`, body is gzipped JSON | a valid `.gz` file | plain JSON |
| no `Content-Encoding`, body is already a `.gz` object | a valid `.gz` file | **the same `.gz` file** (nothing to decode) |

`keep_compressed=True` (i.e. `aiter_raw()`) is therefore the safe default — it produces a gzip file in **both** cases, and `gzip.open(path)` reads it either way. Using `aiter_bytes()` and naming the output `.json.gz` produces a file that is plain JSON in one case and gzip in the other, and every downstream reader has to guess. Whichever you pick, verify the actual `Content-Encoding` / `Content-Type` on a live telemetry URL before you commit — see [Unverified](#-unverified--needs-live-confirmation).

**Blocking `fh.write()` in an async function** is a real (if usually small) event-loop stall. For multi-MB telemetry files it is acceptable; if you see latency spikes, wrap it:

```python
import anyio

async for chunk in iterator:
    await anyio.to_thread.run_sync(fh.write, chunk)
```

**Do not rely on `AsyncHTTPTransport(retries=N)`.** The httpx2 transport docs are explicit: *"Requests will be retried the given number of times in case an `httpx2.ConnectError` or an `httpx2.ConnectTimeout` occurs."* It does not retry reads, 429s, or 5xx. Tenacity does the real work.

**Tenacity signatures used above** (verified against the API reference):

| Callable | Signature |
|---|---|
| `stop_after_attempt` | `(max_attempt_number)` |
| `stop_after_delay` | `(max_delay)` |
| `wait_exponential` | `(multiplier, max, exp_base, min)` |
| `wait_exponential_jitter` | `(initial=1, max=4.611686018427388e+18, exp_base=2, jitter=1)` |
| `wait_random_exponential` | `(multiplier, max, exp_base, min)` |
| `retry_if_exception_type` | `(exception_types)` |
| `before_sleep_log` | `(logger, log_level, exc_info)` — takes a **stdlib** logger, not a structlog one |

---

## 9. Structured logging

Use **structlog 26.1.0** with `ProcessorFormatter`, so that uvicorn's, SQLAlchemy's and Alembic's stdlib log records come out in the same JSON shape as yours. Rendering only structlog's own calls leaves half your production logs unparseable.

```python
# src/pubgd/logging.py
from __future__ import annotations

import logging
import logging.config
import sys
from typing import Any

import structlog


def configure_logging(*, json: bool = True, level: str = "INFO") -> None:
    # Runs for BOTH structlog events and foreign (stdlib) records.
    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,   # must be first
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    structlog.configure(
        processors=[
            *shared,
            structlog.stdlib.PositionalArgumentsFormatter(),
            # Hand off to ProcessorFormatter instead of rendering here.
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    renderer = (
        structlog.processors.JSONRenderer()
        if json
        else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,     # applied to records from logging.getLogger(...)
        processors=[
            structlog.processors.ExceptionPrettyPrinter()
            if not json
            else structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())

    # Tame the noisy libraries; let ours through.
    logging.getLogger("uvicorn").handlers.clear()
    logging.getLogger("uvicorn.access").handlers.clear()
    logging.getLogger("uvicorn.error").handlers.clear()
    for name, lvl in {
        "uvicorn.access": logging.WARNING,       # we emit our own access log
        "sqlalchemy.engine": logging.WARNING,
        "httpx": logging.WARNING,
        "httpx2": logging.WARNING,
        "httpcore2": logging.WARNING,
        "alembic": logging.INFO,
    }.items():
        logging.getLogger(name).setLevel(lvl)
```

Structlog's own warning, quoted: when using `ProcessorFormatter` you *"**must not** use `render_to_log_kwargs()` or `render_to_log_args_and_kwargs()` in your processor chain"*. And `merge_contextvars` goes first: *"Use `structlog.configure()` with `structlog.contextvars.merge_contextvars()` as your first processor"*.

Request-scoped context via ASGI middleware:

```python
# src/pubgd/api/middleware.py
from __future__ import annotations

import time
import uuid

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

log = structlog.get_logger("pubgd.access")


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        structlog.contextvars.clear_contextvars()
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        request_id = headers.get("x-request-id") or uuid.uuid4().hex
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=scope["method"],
            path=scope["path"],
        )

        status_code = 500
        started = time.perf_counter()

        async def _send(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                message.setdefault("headers", []).append(
                    (b"x-request-id", request_id.encode("latin-1"))
                )
            await send(message)

        try:
            await self.app(scope, receive, _send)
        finally:
            log.info(
                "http.request",
                status_code=status_code,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            structlog.contextvars.clear_contextvars()
```

Register with `app.add_middleware(RequestContextMiddleware)`.

⚠️ **contextvars caveat, quoted from the structlog docs:** *"Since the storage mechanics of your context variables is different for each concurrency method, they are isolated from each other"* — creating problems in Starlette/FastAPI where *"context variables set in a synchronous context don't appear in logs from an async context and vice versa."* Concretely: a `def` (non-`async`) path operation runs in a threadpool and **will not see** contextvars bound by async middleware. **Make every path operation `async def`** and this never bites you.

---

## 10. Testing

`pytest-asyncio` **1.4.0** configuration (all three keys — leaving `asyncio_default_fixture_loop_scope` unset emits a deprecation warning, since the docs say "in future versions of pytest-asyncio, the value will default to `function` when unset"):

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"                          # no @pytest.mark.asyncio needed
asyncio_default_fixture_loop_scope = "session"
asyncio_default_test_loop_scope = "session"
```

Allowed loop-scope values: `function`, `class`, `module`, `package`, `session`.

⚠️ **The loop scope must match the engine fixture's scope.** The `database` fixture below is `scope="session"` and holds an `AsyncEngine` (and therefore an asyncpg pool). If the fixture loop scope is left at `function`, that engine is created inside the *first test's* event loop, which is then closed; every subsequent test runs in a fresh loop while reusing pooled connections bound to the dead one, and asyncpg raises `RuntimeError: Task got Future attached to a different loop` or `Event loop is closed` — intermittently and order-dependently. pytest-asyncio 1.4.0 contains no scope-mismatch guard, so nothing catches this at collection time. Either set both keys to `session` as above, or decorate explicitly: `@pytest.fixture(scope="session", loop_scope="session")` on `database` and `@pytest.mark.asyncio(loop_scope="session")` on tests that touch it. Keeping both keys at `function` requires a function-scoped engine.

`testcontainers` 4.14.2 — verified constructor from source:

```python
class PostgresContainer(DbContainer):
    def __init__(
        self,
        image: str = "postgres:latest",
        port: int = 5432,
        username: str | None = None,      # else $POSTGRES_USER, else "test"
        password: str | None = None,      # else $POSTGRES_PASSWORD, else "test"
        dbname: str | None = None,        # else $POSTGRES_DB, else "test"
        driver: str | None = "psycopg2",  # !! DEFAULT IS psycopg2. Pass "asyncpg".
        **kwargs,
    ) -> None: ...

    def get_connection_url(self, host=None, driver=_UNSET) -> str: ...
```

`conftest.py`:

```python
from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import httpx2
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from testcontainers.postgres import PostgresContainer

from pubgd.api.app import create_app
from pubgd.db.base import Base
from pubgd.db.engine import Database


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    # driver="asyncpg" -> "postgresql+asyncpg://test:test@localhost:PORT/test"
    with PostgresContainer("postgres:17-alpine", driver="asyncpg") as pg:
        yield pg.get_connection_url()


@pytest.fixture(scope="session")
async def database(postgres_url: str) -> AsyncIterator[Database]:
    db = Database(postgres_url, application_name="pubgd-tests")
    async with db.engine.begin() as conn:
        # Fast path. For migration fidelity, run Alembic instead:
        #   await conn.run_sync(lambda sync_conn: run_upgrade(sync_conn))
        await conn.run_sync(Base.metadata.create_all)
    yield db
    await db.dispose()


@pytest.fixture
async def session(database: Database) -> AsyncIterator[AsyncSession]:
    """Per-test session wrapped in a transaction that is always rolled back.

    Nothing a test writes survives, so tests do not need to clean up and can
    run in any order.
    """
    async with database.engine.connect() as conn:
        trans = await conn.begin()
        async_session = AsyncSession(bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint")
        try:
            yield async_session
        finally:
            await async_session.close()
            await trans.rollback()


@pytest.fixture
async def client(database: Database) -> AsyncIterator[httpx2.AsyncClient]:
    app = create_app()
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
```

⚠️ **Do not add an `autouse` `_truncate` fixture.** An earlier draft of this doc had:

```python
@pytest.fixture(autouse=True)
async def _truncate(session: AsyncSession) -> AsyncIterator[None]:
    yield
    await session.execute(text("TRUNCATE job RESTART IDENTITY CASCADE"))   # NO-OP
```

It is a pure no-op: the `TRUNCATE` runs inside the very transaction the `session` fixture is about to `rollback()`, so it is discarded. And being `autouse=True` it drags *every* test in the suite — including pure unit tests — into starting the Postgres container and opening a DB session. The rollback envelope already guarantees isolation. If you ever need a real truncate (for a test that deliberately commits outside the envelope), write it as an opt-in fixture without `autouse`.

A queue test that actually proves `SKIP LOCKED` works — two *concurrent connections*, because a single session cannot contend with itself:

```python
import asyncio

from pubgd.db.engine import Database
from pubgd.jobs import queue


async def test_skip_locked_never_double_claims(database: Database) -> None:
    async with database.sessionmaker() as s:
        for i in range(50):
            await queue.enqueue(s, "noop", {"i": i}, dedupe_key=f"noop-{i}")
        # `enqueue()` self-commits (§6.2). The explicit commit here is belt-and-braces:
        # if you ever make enqueue() non-committing, `async with sessionmaker() as s`
        # closes the session on exit, rolls the inserts back, the workers claim zero
        # jobs, and this test fails with `0 == 0 == 50`.
        await s.commit()

    async def worker(name: str) -> list[int]:
        claimed: list[int] = []
        async with database.sessionmaker() as s:
            for _ in range(10):
                jobs = await queue.claim(s, batch=5, worker=name)
                if not jobs:
                    break
                claimed.extend(j.id for j in jobs)
        return claimed

    results = await asyncio.gather(*(worker(f"w{i}") for i in range(4)))
    all_ids = [i for r in results for i in r]
    assert len(all_ids) == len(set(all_ids)) == 50   # every job claimed exactly once
```

Notes:

- `ASGITransport(app=app)` is the current form; the old `AsyncClient(app=app)` shortcut is removed/deprecated. On legacy httpx it is `httpx.ASGITransport`.
- Do **not** call `TestClient(app)` for async tests — it spins its own loop and will fight pytest-asyncio's.
- `join_transaction_mode="create_savepoint"` is what lets application code call `session.commit()` inside the test while the outer transaction still rolls everything back.
- The session-scoped container costs ~2 s once. Do not put `PostgresContainer` at function scope.
- Testcontainers needs a working Docker socket. On CI runners without one, fall back to a service container and read the DSN from an env var — gate the fixture on `os.getenv("TEST_DATABASE_URL")`.

---

## 11. Implementation notes (gotchas that will silently break things)

**uv / packaging**

1. `[tool.hatch.build.targets.wheel] packages = ["src/pubgd"]` is mandatory with a `src/` layout. Without it the wheel builds *empty* and the failure only shows up in the container.
2. `uv sync` (no flags) installs `default-groups`; a production image needs `--no-dev`. Forgetting it ships pytest and testcontainers into prod.
3. `uv.lock` **must** be committed, and CI **must** run `uv lock --check`. Otherwise CI silently relocks and tests a different dependency graph than the image.
4. Dependency groups are not visible to consumers of your wheel. Anything a *deployer* installs goes in `[project.optional-dependencies]`.

**pydantic / settings**

5. `PostgresDsn` looks like the right type for `database_url`, but pydantic v2 URL types normalise and re-encode — they can add a trailing `/` and percent-encode a password containing `@`, `#`, or `/`, producing a DSN that no longer authenticates. Use `str` + a `field_validator`. If you insist on `PostgresDsn`, always pass `str(settings.database_url)` to `create_async_engine` and assert round-trip equality in a test.
6. `env_prefix` applies to top-level fields only. With `env_prefix="PUBGD_"` and `env_nested_delimiter="__"`, a nested field is `PUBGD_DB__POOL_SIZE`, not `DB__PUBGD_POOL_SIZE`.
7. `extra="ignore"` is not the default. Without it, one unrelated line in a shared `.env` raises `ValidationError` at startup.
8. `.env` sits **below** real environment variables in priority. A stale `.env` on a dev box will not override `PUBGD_*` exported in the shell — which surprises people in the wrong direction.
9. Wrap `Settings()` in `@lru_cache` — instantiating it re-reads and re-parses `.env` every time.

**SQLAlchemy / asyncpg**

10. `expire_on_commit=False` is mandatory. The default `True` makes every post-commit attribute access lazy-refresh, which under asyncio raises `MissingGreenlet` at a location far from the cause.
11. **One `AsyncSession` per task.** Sharing a session across `asyncio.gather` branches produces `InterfaceError: cannot perform operation: another operation is in progress` — intermittently, under load, in production.
12. `lazy="raise"` on relationships. `MissingGreenlet` from a template render is one of the least debuggable errors in this stack; `lazy="raise"` moves the failure to the exact attribute access.
13. Set `MetaData(naming_convention=...)` before the first migration. Alembic cannot autogenerate a drop for an unnamed constraint, and retrofitting names means hand-writing every constraint rename.
14. **`ON CONFLICT DO UPDATE command cannot affect row a second time`** — if a single `INSERT ... VALUES (...), (...)` contains the *same* conflict key twice, Postgres aborts the whole statement. The PUBG participants array can contain repeats across a retried/merged payload. `_dedupe()` in §4.3 is not optional.
15. `pg_insert(Model).values([d1, d2, ...])` derives the column list from the **first** dict. Heterogeneous dicts either error or silently drop columns. Normalise every row to the same key set (fill missing with `None`) before calling.
16. The Postgres wire protocol caps a statement at **65535 bind parameters** — the frontend/backend protocol `Bind` message encodes "the number of parameter values that follow" as an `Int16` (source: the PostgreSQL *Message Formats* page, **not** the SQLAlchemy ORM DML query guide, which never mentions the number). 100 participants × 18 columns = 1800, fine; 5000 telemetry events × 15 columns = 75000, which fails. Chunk, or use `COPY`. *(The `chunk_size=500` default and this row/column arithmetic are engineering choices sized against that protocol limit, not documented limits themselves.)*
17. If you set `json_serializer=orjson.dumps`, it returns **`bytes`** and SQLAlchemy needs **`str`**. Use `lambda v: orjson.dumps(v).decode()`.
18. Always `timestamptz`, never `timestamp`. `Mapped[dt.datetime]` maps to naive `TIMESTAMP WITHOUT TIME ZONE` unless you put `dt.datetime: DateTime(timezone=True)` in `type_annotation_map`. Mixed naive/aware datetimes in one column is a bug you find months later.
19. `pool_pre_ping=True` and `pool_recycle=1800`. Cloud Postgres proxies drop idle connections without a FIN; without pre-ping the first query after an idle period raises `ConnectionDoesNotExistError`.
20. Behind PgBouncer transaction pooling: `prepared_statement_cache_size=0`, `poolclass=NullPool`, and `prepared_statement_name_func` for unique names. Otherwise `DuplicatePreparedStatementError` under concurrency.
21. `await engine.dispose()` in the lifespan `finally`. Without it you get `Task was destroyed but it is pending` / "Event loop is closed" spam at shutdown, which masks real errors.

**Alembic**

22. `sqlalchemy.url` goes through ConfigParser interpolation — a `%` in your password must be doubled. `config.set_main_option("sqlalchemy.url", dsn.replace("%", "%%"))`.
23. `env.py` must import the models module for its side effect, or `Base.metadata` is empty and autogenerate cheerfully generates a migration that **drops every table**. Guard it with `# noqa: F401` so the linter does not remove it.
24. Alembic's migration API is synchronous; the bridge is `await connection.run_sync(do_run_migrations)`. Never `await` inside `do_run_migrations`.
25. `compare_type=True` and `compare_server_default=True` are off by default, so column type changes are silently omitted from autogenerated migrations.
26. Always read the generated migration before committing. Autogenerate does not detect renames (it emits drop + add, losing data) and cannot see `CREATE INDEX CONCURRENTLY` needs.
27. Take `pg_advisory_xact_lock` in `do_run_migrations` if more than one replica may run `alembic upgrade head` on boot.

**Job queue**

28. `FOR UPDATE SKIP LOCKED` must live in a subquery/CTE `SELECT`; it cannot be attached to an `UPDATE`.
29. **Commit the claim transaction immediately.** Holding it open for the job duration blocks `VACUUM` across the whole database and turns one slow job into cluster-wide table bloat.
30. Increment `attempts` at **claim** time, not at failure time — a `SIGKILL`ed worker never reaches the failure path, and a job that crashes the process would otherwise retry forever.
31. Without a reaper, a crashed worker's jobs stay `running` forever. `locked_at < now() - lease` + reset to `pending` is the whole fix; the lease must exceed your slowest job.
32. The claim index must be **partial** (`WHERE state = 'pending'`) and its column order must match the `ORDER BY` exactly. A non-partial index degrades linearly as `done` rows accumulate.
33. `ALTER TABLE job SET (autovacuum_vacuum_scale_factor = 0.0, autovacuum_vacuum_threshold = 1000)`. Default autovacuum triggers at 20% of table size — on a queue table that means bloat grows unboundedly at steady state.
34. Add a retention sweep (`DELETE FROM job WHERE state='done' AND finished_at < now() - interval '7 days'`) or the table grows forever. Delete in batches with `LIMIT`, not one giant statement.
35. `LISTEN`/`NOTIFY` is fire-and-forget — a notification sent while no worker is connected is gone. Keep the polling loop as the source of truth and treat NOTIFY purely as a latency optimisation.

**HTTP / rate limiting**

36. `X-RateLimit-Reset` is a **wall-clock UNIX timestamp**, and `asyncio.sleep` takes a monotonic delta. Convert with `reset - time.time()`, then clamp to `[0, 300]` — clock skew or a malformed header otherwise produces either a busy-spin or a five-hour hang.
37. HTTP header names are case-insensitive and httpx normalises them. `documentation.pubg.com` documents `X-RateLimit-Reset`; the wire may send `x-ratelimit-reset`. Use `response.headers[...]` (a case-insensitive mapping), never `dict(response.headers)[...]`.
38. **One bucket per API key, process-wide.** N worker processes sharing one key each with a full-rate local bucket will get 429s no matter how correct the bucket is. Divide the rate, or centralise the bucket.
39. `AsyncHTTPTransport(retries=N)` only retries `ConnectError` / `ConnectTimeout`. It will not retry a 429 or a 503. Use tenacity.
40. `aiter_raw()` does **not** decode `Content-Encoding`; `aiter_bytes()` does. Picking the wrong one gives you files whose format depends on how the CDN felt that day. See the table in §8.2.
41. Inside a `client.stream(...)` block, `response.text` / `response.content` raise. To include an error body, `await response.aread()` first.
42. Write to `dest.name + ".part"` then `Path.replace()`. A killed download otherwise leaves a truncated file that looks valid to the next run.
43. `before_sleep_log(logger, level)` wants a **stdlib** `logging.Logger`, not a structlog `BoundLogger`.
44. `httpx` and `httpx2` are different top-level modules and coexist fine. Do not spend effort forcing FastAPI's `TestClient` off legacy `httpx`.

**FastAPI / logging**

45. Make every path operation `async def`. A `def` handler runs in a threadpool, and structlog contextvars bound by async middleware are invisible there (structlog documents this isolation explicitly).
46. `APIRouter(prefix=...)` must not end in `/`, or every path gets a `//`.
47. `uvicorn.run(..., log_config=None)` — otherwise uvicorn installs its own `dictConfig` at startup and stomps your handlers, and half your logs stop being JSON.
48. Do not use `@app.on_event("startup")`. Starlette 1.0 removed `on_event()` from `Starlette`/`Router`; FastAPI re-implemented it on its own side in **0.128.3** (PR #14851), so it still works on 0.139.2 — but it is legacy, and FastAPI ignores its own event handlers entirely if `lifespan` is set: "It's all `lifespan` or all events, not both." Use `lifespan`.
49. If you catch an exception inside a `yield` dependency, **re-raise the original exception** (unless you are raising another `HTTPException` or similar), or FastAPI never learns the request failed and the error goes unlogged.

---

## ⚠️ Unverified / needs live confirmation

Everything below was **not** confirmed against an authoritative source during this research pass. Treat it as a hypothesis and verify before depending on it.

1. **PUBG participant field names and casing — partially resolved.** Checked against `pubg-typescript-api`'s `Participant` / `Roster` entities:
   - **Confirmed real, with this exact casing**, on `participant.attributes.stats`: `winPlace`, `DBNOs`, `timeSurvived`, `damageDealt`, `walkDistance`, `rideDistance`, `swimDistance`, `headshotKills`, `kills`, `assists`, `playerId`, `name` (plus `boosts`, `heals`, `revives`, `killPlace`, `killStreaks`, `longestKill`, `mostDamage`, `roadKills`, `teamKills`, `vehicleDestroys`, `weaponsAcquired`, `deathType`, `killPoints`/`winPoints`/`lastKillPoints`/`lastWinPoints` and the `*Delta` variants).
   - **Refuted:** there is **no** `rosterId` and **no** `teamId` on a participant. `teamId` and `rank` live on the **Roster** (`roster.attributes.stats.teamId`, `.rank`, `roster.attributes.won`), with membership expressed through the roster → participants relationship. The `roster_id` / `team_id` columns in §4.2 must be **derived from the roster during adaptation**; a naive `stats.get("rosterId")` yields silent NULLs.
   - **Still open:** `swimDistance` has no dedicated column (harmless — the `stats` JSONB retains it), and none of this has been checked against a *live* payload. Confirm against a real `GET /shards/steam/matches/{id}` response once the API key is wired up, since a third-party client library can lag the API.

2. **PUBG telemetry `Content-Encoding` on the CDN URL.** `documentation.pubg.com/en/making-requests.html` recommends `Accept-Encoding: gzip` for API requests, but I did not confirm whether the `assets` telemetry URL returns `Content-Encoding: gzip` (→ `aiter_raw()` yields gzip bytes, `aiter_bytes()` yields JSON) or serves a pre-gzipped object with no `Content-Encoding` (→ both yield gzip bytes). **Fetch one telemetry URL with `curl -sI` and read the actual headers before choosing `keep_compressed`.**

3. **Whether PUBG sends a `Retry-After` header on 429.** Not documented on the rate-limits page. The `_retry_after_seconds` fallback in §7 is defensive only.

4. **Whether `X-RateLimit-Limit` is per-minute or per-day for a given key.** The docs literally say "Request limit per day / per minute" — ambiguous. §7 assumes per-minute (matching the documented "10 requests per minute" default). Log the observed `X-RateLimit-Limit` on the first live call and confirm.

5. **Whether the telemetry CDN host counts against the API rate limit.** §8.2 conservatively takes a token for downloads. If telemetry is served from a separate un-limited CDN, that costs you throughput unnecessarily. Verify empirically.

6. **`sqlalchemy` 2.0.51 on Python 3.14.** cp314 wheels ship, but the PyPI classifiers stop at 3.13 and I found no explicit 3.14-support statement in the SQLAlchemy docs. Combined with asyncpg 0.31.0 + greenlet 3.5.4 this is *probably* fine, but **`requires-python = ">=3.13"` is the recommendation** until you can run the suite on 3.14 yourself.

7. ~~**The `raw.driver_connection` hop in the `COPY` path (§4.3).**~~ **RESOLVED — moved to "Confirmed" below.** The doc's original code was wrong, not merely unverified; §4.3 has been corrected to use `raw.dbapi_connection`.

8. **`tenacity` `AsyncRetrying` + `return` from inside `with attempt:`.** This is a widely used pattern and matches the docs' `async for attempt in AsyncRetrying(...)` example, but the docs do not show a `return` from inside the loop. If it misbehaves, switch to the `@retry` decorator form, which is unambiguously documented.

9. ~~**Alembic `path_separator` / `version_path_separator`.**~~ **RESOLVED — moved to "Confirmed" below.** The `async` template emits `path_separator = os`.

10. ~~**`starlette` 1.3.1 vs `fastapi` 0.139.2 resolution.**~~ **RESOLVED — moved to "Confirmed" below.** This is intentional forward support, not an unbounded-range accident. Run the suite once after the first `uv sync` as routine hygiene; **do not** pin `starlette` defensively — that is more likely to cause a resolution conflict than to prevent one.

11. **`granian` as a uvicorn alternative** (2.7.9 on PyPI). Mentioned only for awareness; no evaluation performed.

### Confirmed during this pass (previously suspect, now verified)

- **`httpx2.ASGITransport` exists.** Read directly from `src/httpx2/httpx2/__init__.py` on `main`: `__all__` includes `ASGITransport`, `WSGITransport`, `MockTransport`, `AsyncBaseTransport`, `AsyncHTTPTransport`, `BaseTransport`, `HTTPTransport`, `Limits`, `Timeout`, `TimeoutException`, `TransportError`, `ConnectTimeout`, `ReadTimeout`, `WriteTimeout`, `PoolTimeout`. The `_transports/` package contains `asgi.py`, `base.py`, `default.py`, `mock.py`, `wsgi.py`.
- **`join_transaction_mode` is a real `Session`/`AsyncSession` parameter** with exactly four values: `"conditional_savepoint"` (default), `"create_savepoint"`, `"control_fully"`, `"rollback_only"`. `"create_savepoint"` makes the Session "establish its own nested transaction via `Connection.begin_nested()` in all cases, riding atop any existing transaction on the `Connection` without affecting it" — which is precisely the rollback-per-test fixture behaviour. `Session(bind=...)` accepts "an optional `Engine` **or `Connection`**".
- **PUBG rate-limit header names** `X-RateLimit-Limit` / `X-RateLimit-Remaining` / `X-RateLimit-Reset`, the UNIX-timestamp semantics of `Reset`, the 10 rpm default and the 429 behaviour are all quoted verbatim from `documentation.pubg.com/en/rate-limits.html`.
- **SQLAlchemy 2.0.51 ships `cp314` wheels** despite classifiers stopping at 3.13 (read from the 2.0.51 PyPI file list).
- **Alembic `pyproject` / `pyproject_async` templates exist** (1.16+), alongside `generic`, `async`, `multidb`.
- **The Alembic `async` template emits `path_separator = os`** (read from `alembic/templates/async/alembic.ini.mako` on `main`). Its own comments state that `version_path_separator` is only a legacy fallback: "Parsing of the version_locations option falls back to using the legacy 'version_path_separator' key, which if absent then falls back to the legacy…". Documented valid values: `:`, `;`, `space`, `newline`, `os`.
- **The `COPY` adapter chain (§4.3).** `PoolProxiedConnection.dbapi_connection` is the SQLAlchemy-supplied `AdaptedConnection` carrying `run_async()`; `PoolProxiedConnection.driver_connection` is "the ultimate 'connection' object used by that driver, such as the `asyncpg.Connection` object which will not have standard pep-249 methods" — i.e. it has no `run_async()`. Use `dbapi_connection.run_async(...)`, or call the asyncpg method directly on `driver_connection`.
- **FastAPI 0.139.2 supports Starlette 1.3.1 deliberately.** FastAPI re-implemented `on_event` "for compatibility with the next Starlette" (PR #14851, shipped 0.128.3), raised its range to `starlette>=0.40.0,<1.0.0` in that release as an explicit staging step, and 0.139.2's live PyPI metadata declares `starlette>=0.46.0` with the ceiling deliberately dropped. FastAPI CI also runs against Starlette `main`.
