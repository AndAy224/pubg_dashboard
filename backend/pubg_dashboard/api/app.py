"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from pubg_dashboard.api.routers import (
    health,
    heatmap,
    ingest,
    matches,
    overview,
    players,
    tiles,
)
from pubg_dashboard.config import REPO_ROOT, get_settings
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

    # The heatmap endpoint returns a dense 256x256 Uint32 grid as base64 —
    # 350 KB on the wire, and mostly zeros, so it compresses ~25x. Starlette
    # skips any response that already carries Content-Encoding, which is what
    # keeps it from re-compressing the replay bundle (served still-gzipped
    # straight out of object storage).
    app.add_middleware(GZipMiddleware, minimum_size=1024)

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

    for module in (health, overview, players, matches, heatmap, ingest, tiles):
        app.include_router(module.router, prefix=API_PREFIX)

    _mount_frontend(app)
    return app


def _mount_frontend(app: FastAPI) -> None:
    """Serve the built SPA, if it has been built.

    Mounted **after** every router so it can never shadow `/api`. Absent in
    development, where Vite serves on :5173 and proxies `/api` here — so a
    missing `dist/` is normal, not an error.
    """
    dist = REPO_ROOT / "frontend" / "dist"
    index = dist / "index.html"
    if not index.is_file():
        log.info("api.no_frontend_build", path=str(dist), note="run `npm run build`")
        return

    assets = dist / "assets"
    if assets.is_dir():
        # Vite fingerprints these filenames, so they are safe to cache forever.
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    resolved_dist = dist.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        """Client-side routing: /matches/<id>/replay returns index.html.

        The path comes straight from the URL, and Starlette decodes `%2e%2e%2f`
        before it reaches here — so `dist / path` happily resolves outside the
        build directory. Verified before this guard existed:
        `GET /..%2f..%2f..%2f..%2f..%2fetc%2fpasswd` returned the real
        /etc/passwd. Resolve and confirm containment; anything outside falls
        through to the SPA shell rather than 404ing, because an unknown path is
        a client route until proven otherwise.
        """
        # An unknown /api path is a client error, not a client-side route.
        # Falling through would answer a mistyped endpoint with the HTML shell
        # and a 200, which is a genuinely confusing thing to debug.
        if path.startswith("api/"):
            raise HTTPException(404, f"no such endpoint: /{path}")

        if path:
            candidate = (dist / path).resolve()
            if candidate.is_relative_to(resolved_dist) and candidate.is_file():
                return FileResponse(candidate)
        return FileResponse(index)

    log.info("api.frontend_mounted", path=str(dist))


app = create_app()
