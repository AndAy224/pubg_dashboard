"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pubg_dashboard.api.routers import health, heatmap, ingest, matches, players
from pubg_dashboard.config import get_settings
from pubg_dashboard.db.session import dispose_engine, init_engine

log = structlog.get_logger(__name__)

API_PREFIX = "/api"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    init_engine()
    log.info("api.start", storage=settings.storage_backend)
    try:
        yield
    finally:
        # The engine must be disposed before the loop closes, or asyncpg
        # complains about connections abandoned on a dead loop at shutdown.
        await dispose_engine()
        log.info("api.stop")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="PUBG Dashboard API",
        version="0.1.0",
        summary="Match archive, career stats, heatmaps and telemetry replay.",
        lifespan=lifespan,
    )

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            # The replay route sets these and a browser cannot read them
            # cross-origin unless they are explicitly exposed.
            expose_headers=["Content-Encoding", "X-Parser-Version"],
        )

    for module in (health, players, matches, heatmap, ingest):
        app.include_router(module.router, prefix=API_PREFIX)

    return app


app = create_app()
