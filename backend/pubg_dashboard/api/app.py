"""FastAPI application factory."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Final

import structlog
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response
from starlette.types import Scope

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


#: Fingerprinted by Vite, so the name changes whenever the bytes do.
_IMMUTABLE: Final = "public, max-age=31536000, immutable"

#: The SPA shell. **Not** `no-store` — `no-cache` still lets the browser keep a
#: copy, it just has to revalidate before using it, which the ETag turns into a
#: cheap 304. Without this header there is no freshness information at all and
#: browsers fall back to a *heuristic*: they invent a lifetime from
#: `Last-Modified`. A shell served from that heuristic references the previous
#: build's chunk hashes, and if those are cached too the whole stale app boots
#: happily — the page works, it is simply the old one. That is indistinguishable
#: from a feature that was never deployed, and it is how a steering wheel that
#: renders correctly on the server can be invisible in a tab that was already
#: open.
_REVALIDATE: Final = "no-cache"


class _FingerprintedStatic(StaticFiles):
    """`/assets` with a real immutable header rather than just an ETag.

    `StaticFiles` sends `ETag` and `Last-Modified` but no `Cache-Control`, so
    every asset costs a revalidation round trip on every navigation. The names
    are content hashes, so they can be cached permanently.
    """

    def file_response(
        self,
        full_path: Any,
        stat_result: os.stat_result,
        scope: Scope,
        status_code: int = 200,
    ) -> Response:
        response = super().file_response(full_path, stat_result, scope, status_code)
        response.headers["cache-control"] = _IMMUTABLE
        return response


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
        app.mount("/assets", _FingerprintedStatic(directory=assets), name="assets")

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
                # Anything reached by name here is unfingerprinted (favicon,
                # manifest), so it revalidates like the shell.
                return FileResponse(candidate, headers={"cache-control": _REVALIDATE})
        return FileResponse(index, headers={"cache-control": _REVALIDATE})

    log.info("api.frontend_mounted", path=str(dist))


app = create_app()
