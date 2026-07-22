"""Async PUBG API client.

Rate-limit reasoning (the whole architecture of this file)
----------------------------------------------------------
PUBG's public API has an unusual property that dictates the design: **only some
endpoints cost quota.**

============================================ ============ ====================
Endpoint                                     Costs quota?  Sends rl headers?
============================================ ============ ====================
``GET /shards/{shard}/players``              yes           yes
``GET /shards/{shard}/seasons``              yes           yes
``.../players/{id}/seasons/{seasonId}``      yes           yes
``.../players/{id}/weapon_mastery``          yes           yes
``GET /shards/{shard}/matches/{id}``         **no**        **no**
telemetry CDN                                **no**        **no**
============================================ ============ ====================

That was verified live: the match endpoint returns no ``x-ratelimit-*`` headers
at all and never 429s. So the budget a dashboard actually spends is proportional
to the number of *tracked players*, not to the number of matches — fanning out
to 100 matches and 100 telemetry files for those players is free. Every keyed
call here goes through :class:`~pubg_dashboard.pubg.ratelimit.TokenBucket`;
:meth:`PubgClient.get_match` and :meth:`PubgClient.download_telemetry`
deliberately do **not**, and calling `limiter.acquire()` in them would throttle
the archiver to 10 matches/minute for no reason at all.

Two clients, one class
----------------------
`self._api` carries the ``Authorization: Bearer`` header; `self._cdn` does not.
This is not tidiness. httpx merges client-level default headers into *every*
request regardless of host — an absolute URL bypasses `base_url` but **not**
default headers — so reusing the API client for a telemetry download would ship
our API key into a third party's access logs on every fetch. httpx only strips
auth on cross-origin *redirects*, which is not this case.

Retries
-------
tenacity retries transport errors, 5xx and 429 with exponential backoff+jitter.
404 is never retried: PUBG 404s a renamed account and an expired match forever,
and each retry would spend another token to learn the same thing.

The API key is never logged. Where a key identity is useful (which bucket is
holding), a 12-hex-char sha256 fingerprint is logged instead.
"""

from __future__ import annotations

import asyncio
import gzip
import logging
import pathlib
from collections.abc import Iterator, Sequence
from types import TracebackType
from typing import Any, Final, Literal, Protocol, Self

import httpx
import structlog
from tenacity import (
    AsyncRetrying,
    RetryCallState,
    before_sleep_log,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from pubg_dashboard.config import Settings, get_settings
from pubg_dashboard.pubg.errors import (
    PlayerNotFound,
    PubgApiError,
    PubgServerError,
    RateLimited,
    TelemetryUnavailable,
)
from pubg_dashboard.pubg.ratelimit import TokenBucket, key_fingerprint, shared_bucket
from pubg_dashboard.pubg.schemas import (
    MatchResponse,
    Player,
    PlayerSeasonResponse,
    PlayersResponse,
    SeasonsResponse,
    WeaponMasteryResponse,
)

log: Final = structlog.get_logger(__name__)
# tenacity's before_sleep_log wants a *stdlib* logger, not a structlog one.
_retry_log: Final = logging.getLogger("pubg_dashboard.pubg.http")

BASE_URL: Final = "https://api.pubg.com"
# "Get a collection of up to 10 players." Ten names is one token; ten separate
# requests is a whole minute of budget.
PLAYER_BATCH_SIZE: Final = 10
GZIP_MAGIC: Final = b"\x1f\x8b"
_MAX_ERROR_DETAIL: Final = 500

_USER_AGENT: Final = "pubg-dashboard/0.1 (+https://github.com/AndAy224/pubg_dashboard)"
_BACKOFF: Final = wait_exponential_jitter(initial=1.0, max=60.0, exp_base=2.0, jitter=2.0)


class _ByteSink(Protocol):
    def write(self, data: bytes, /) -> int: ...


def _wait(retry_state: RetryCallState) -> float:
    """Backoff that yields to the token bucket on a 429.

    On :class:`RateLimited` the bucket has already parked us until
    ``x-ratelimit-reset``, and the next `acquire()` will sleep there. Adding
    tenacity's own exponential wait on top would roughly double every 429 delay
    while buying nothing.
    """
    exc = retry_state.outcome.exception() if retry_state.outcome is not None else None
    if isinstance(exc, RateLimited):
        return 0.0
    return float(_BACKOFF(retry_state))


def _chunked(items: Sequence[str], size: int) -> Iterator[Sequence[str]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _error_detail(response: httpx.Response) -> str | None:
    """Pull a short message out of a ``{"errors": [{"title": ...}]}`` envelope."""
    try:
        payload = response.json()
    except (ValueError, UnicodeDecodeError):
        text = response.text.strip()
        return text[:_MAX_ERROR_DETAIL] or None
    if isinstance(payload, dict):
        errors = payload.get("errors")
        if isinstance(errors, list) and errors:
            parts = [
                " ".join(
                    str(v)
                    for v in (e.get("title"), e.get("description"))
                    if isinstance(e, dict) and v
                )
                for e in errors
                if isinstance(e, dict)
            ]
            joined = "; ".join(p for p in parts if p)
            if joined:
                return joined[:_MAX_ERROR_DETAIL]
    return str(payload)[:_MAX_ERROR_DETAIL] or None


class PubgClient:
    """Thin, rate-limit-aware wrapper over the PUBG public API.

    One instance per shard is enough; the token bucket is shared per API key
    across the process, so constructing several clients from the same key does
    not multiply the request budget.

    Close it (or use it as an async context manager) — httpx keeps connections
    alive and leaks sockets otherwise.
    """

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        api_key: str | None = None,
        shard: str | None = None,
        rate_limit_per_min: int | None = None,
        max_attempts: int = 5,
        limiter: TokenBucket | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        cfg = settings or get_settings()
        self._api_key = api_key if api_key is not None else cfg.pubg_api_key
        self.shard = shard or cfg.pubg_default_shard
        self.max_attempts = max_attempts
        rate = rate_limit_per_min if rate_limit_per_min is not None else cfg.pubg_rate_limit_per_min
        # One bucket per key, not per client: the limit belongs to the key.
        self.limiter = limiter or shared_bucket(self._api_key, rate)
        self.key_fingerprint = key_fingerprint(self._api_key)

        self._api = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={
                # Verified live. `Accept` must be the vnd.api+json media type or
                # PUBG answers 415.
                "Authorization": f"Bearer {self._api_key}",
                "Accept": "application/vnd.api+json",
                "Accept-Encoding": "gzip",
                "User-Agent": _USER_AGENT,
            },
            timeout=httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=30.0),
            limits=httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10,
                keepalive_expiry=30.0,
            ),
            follow_redirects=True,
            transport=transport,
        )
        # NO Authorization header here — see the module docstring. The CDN is
        # public, unauthenticated and unmetered; sending the key would leak it
        # into a third party's logs for zero benefit.
        self._cdn = httpx.AsyncClient(
            headers={"Accept-Encoding": "gzip", "User-Agent": _USER_AGENT},
            # Long read timeout: telemetry payloads run ~19 MB uncompressed.
            timeout=httpx.Timeout(connect=5.0, read=120.0, write=10.0, pool=30.0),
            follow_redirects=True,
            transport=transport,
        )

    # ------------------------------------------------------------- lifecycle
    async def aclose(self) -> None:
        await self._api.aclose()
        await self._cdn.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    def _path(self, suffix: str, shard: str | None = None) -> str:
        return f"/shards/{shard or self.shard}{suffix}"

    # ------------------------------------------------------------------ core
    async def _request(
        self,
        method: str,
        url: str,
        *,
        keyed: bool,
        params: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Issue one request with retries, spending a token only when `keyed`.

        Args:
            keyed: True for endpoints that consume the API key's rate-limit
                budget. False for ``/matches`` — it is unmetered and sends no
                ``x-ratelimit-*`` headers, so both the acquire and the observe
                are skipped. (Observing absent headers is not harmless: a
                missing ``x-ratelimit-remaining`` is indistinguishable from
                nothing, but a defensive reader that treats it as 0 would park
                the whole client for a minute.)
        """
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self.max_attempts),
            wait=_wait,
            retry=retry_if_exception_type(
                (httpx.TransportError, PubgServerError, RateLimited)
            ),
            before_sleep=before_sleep_log(_retry_log, logging.WARNING),
            reraise=True,
        ):
            with attempt:
                if keyed:
                    async with self.limiter:
                        response = await self._api.request(method, url, params=params)
                    self.limiter.observe(response.headers, status_code=response.status_code)
                else:
                    response = await self._api.request(method, url, params=params)
                log.debug(
                    "pubg.request",
                    method=method,
                    path=url,
                    status=response.status_code,
                    keyed=keyed,
                    attempt=attempt.retry_state.attempt_number,
                )
                return _raise_for_status(response)
        raise AssertionError("unreachable: AsyncRetrying(reraise=True) always exits")

    async def _get_json(
        self,
        url: str,
        *,
        keyed: bool = True,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        response = await self._request("GET", url, keyed=keyed, params=params)
        payload = response.json()
        if not isinstance(payload, dict):
            raise PubgApiError(
                f"expected a JSON object from {url}, got {type(payload).__name__}",
                url=str(response.url),
            )
        return payload

    # --------------------------------------------------------------- players
    async def get_players(self, names: Sequence[str], *, shard: str | None = None) -> list[Player]:
        """Resolve in-game names to player objects, 10 per request.

        Names are **case-sensitive** — `chocotaco` is not `chocoTaco` — so the
        dedupe below is case-sensitive too.

        A single unknown name 404s the **entire batch**, taking nine valid
        lookups down with it. When that happens we re-probe the batch one name
        at a time to identify the culprit(s) and raise :class:`PlayerNotFound`
        naming them. That probe costs up to one token per name (i.e. up to a
        full minute of budget on a 10/min key), which is exactly why the caller
        should persist name -> accountId and prefer
        :meth:`get_players_by_ids` afterwards.
        """
        # dict.fromkeys: ordered dedupe, and case-sensitive on purpose.
        unique = list(dict.fromkeys(n for n in names if n))
        return await self._get_players_filtered(
            unique, filter_key="filter[playerNames]", kind="name", shard=shard
        )

    async def get_players_by_ids(
        self, account_ids: Sequence[str], *, shard: str | None = None
    ) -> list[Player]:
        """Resolve account ids to player objects, 10 per request.

        Preferred over :meth:`get_players` for anything already in the database:
        account ids never change, whereas a rename makes a stored name 404
        permanently.

        The two filters are mutually exclusive — PUBG rejects a request carrying
        both ``filter[playerIds]`` and ``filter[playerNames]``.
        """
        unique = list(dict.fromkeys(i for i in account_ids if i))
        return await self._get_players_filtered(
            unique, filter_key="filter[playerIds]", kind="id", shard=shard
        )

    async def _get_players_filtered(
        self,
        identifiers: Sequence[str],
        *,
        filter_key: str,
        kind: str,
        shard: str | None,
    ) -> list[Player]:
        if not identifiers:
            return []
        path = self._path("/players", shard)
        players: list[Player] = []
        # Batches run sequentially: each costs a token, and with a 10/min budget
        # concurrency here would only queue on the limiter anyway.
        for chunk in _chunked(identifiers, PLAYER_BATCH_SIZE):
            try:
                payload = await self._get_json(path, params={filter_key: ",".join(chunk)})
            except PubgApiError as exc:
                if exc.status_code != 404:
                    raise
                missing = await self._probe_missing(chunk, filter_key=filter_key, shard=shard)
                if not missing:
                    # Every identifier resolves on its own, so the batch 404 was
                    # not a bad identifier. Surface it rather than looping.
                    raise PubgApiError(
                        f"batch lookup 404'd but all {len(chunk)} identifiers resolve "
                        "individually — transient PUBG behaviour, retry the batch",
                        status_code=404,
                        url=exc.url,
                        detail=exc.detail,
                    ) from exc
                raise PlayerNotFound(
                    missing, kind=kind, shard=shard or self.shard, url=exc.url
                ) from exc
            players.extend(PlayersResponse.model_validate(payload).data)
        return players

    async def _probe_missing(
        self, identifiers: Sequence[str], *, filter_key: str, shard: str | None
    ) -> list[str]:
        """One request per identifier to find which ones PUBG does not know.

        Runs under a TaskGroup: the limiter admits them FIFO so this is no
        faster than a loop, but every identifier gets probed even if several are
        bad, which turns "one of these ten names is wrong" into a precise list.
        404s are swallowed inside each task so the group never tears itself down
        over an expected outcome.
        """
        path = self._path("/players", shard)
        missing: list[str] = []

        async def probe(identifier: str) -> None:
            try:
                await self._get_json(path, params={filter_key: identifier})
            except PubgApiError as exc:
                if exc.status_code != 404:
                    raise
                missing.append(identifier)

        log.warning(
            "pubg.players.batch_404",
            count=len(identifiers),
            filter=filter_key,
            note="probing individually to identify the bad identifier(s)",
        )
        async with asyncio.TaskGroup() as tg:
            for identifier in identifiers:
                tg.create_task(probe(identifier))
        # Preserve the caller's ordering; list.append order is completion order.
        missing_set = set(missing)
        ordered = [i for i in identifiers if i in missing_set]
        log.warning("pubg.players.missing", identifiers=ordered)
        return ordered

    # ------------------------------------------------------- raw JSON:API
    # The ingestion pipeline persists the JSON:API payload *verbatim*: `upsert`
    # walks `included[]` by `type` and `parse_players_payload` reads
    # `relationships.matches.data[]`. Both are verified directly against the
    # archived corpus, so handing them a re-serialised pydantic model would
    # swap a measured contract for a derived one — and the aliases that carry
    # the casing landmines (`URL`, `DBNOs`) are exactly what a round-trip is
    # most likely to lose. These return what PUBG actually sent.
    async def get_players_payload(
        self,
        identifiers: Sequence[str],
        *,
        by: Literal["names", "ids"] = "names",
        shard: str | None = None,
    ) -> dict[str, Any]:
        """One `GET /players` page, unparsed. Costs one token.

        At most ``PLAYER_BATCH_SIZE`` identifiers — this does **not** chunk, so
        the caller controls how much budget it spends. A 404 propagates as a
        :class:`PubgApiError`; unlike :meth:`get_players` there is no
        individual re-probe, because the poller does its own binary split.
        """
        filter_key = "filter[playerNames]" if by == "names" else "filter[playerIds]"
        unique = list(dict.fromkeys(i for i in identifiers if i))
        return await self._get_json(
            self._path("/players", shard), params={filter_key: ",".join(unique)}
        )

    async def get_match_payload(self, match_id: str, *, shard: str | None = None) -> dict[str, Any]:
        """One `GET /matches/{id}`, unparsed. **Costs no rate-limit budget.**"""
        return await self._get_json(self._path(f"/matches/{match_id}", shard), keyed=False)

    # --------------------------------------------------------------- matches
    async def get_match(self, match_id: str, *, shard: str | None = None) -> MatchResponse:
        """Fetch one match. **Costs no rate-limit budget.**

        Verified live: this endpoint returns no ``x-ratelimit-*`` headers and is
        not rate limited (PUBG documents it twice). Spending a token here is the
        single most expensive mistake an ingester can make — it turns a free
        61-match backfill into a six-minute one.

        Authorization is not required either, but it is harmless to send to
        PUBG's own host, so this reuses the API client rather than the CDN one.

        Raises:
            PubgApiError: with ``status_code == 404`` when the match has aged
                out of PUBG's 14-day retention window. That is permanent — do
                not requeue it.
        """
        payload = await self._get_json(self._path(f"/matches/{match_id}", shard), keyed=False)
        return MatchResponse.model_validate(payload)

    # ------------------------------------------------------------- telemetry
    async def download_telemetry(
        self,
        url: str,
        dest: pathlib.Path,
        *,
        match_id: str | None = None,
        chunk_size: int = 1 << 16,
    ) -> int:
        """Stream a telemetry event stream to `dest`. Returns bytes written to disk.

        Costs no rate-limit budget and sends no ``Authorization`` header: the
        CDN is public and unmetered, and the host is not PUBG's API host, so the
        key would end up in someone else's logs.

        The body is never buffered in memory — a single match is ~19 MB of JSON
        and a backfill runs several concurrently.

        The file on disk is **always** valid gzip, matching ``data/telemetry/
        *.json.gz``. This needs care: ``aiter_raw()`` hands back exactly what the
        server sent, which is gzip when ``Content-Encoding: gzip`` is set *and*
        gzip when the stored object is already compressed — but if PUBG ever
        serves it as identity plain JSON, a file named ``.json.gz`` would not be
        one. So the first bytes are checked for the gzip magic number and the
        stream is wrapped in a gzip writer if it is absent. `gzip.open(dest)`
        then works unconditionally downstream.

        Raises:
            TelemetryUnavailable: 403/404 from the CDN (the object aged out of
                the 14-day window) or an empty body. Permanent; do not requeue.
        """
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self.max_attempts),
            wait=_BACKOFF,
            retry=retry_if_exception_type((httpx.TransportError, PubgServerError)),
            before_sleep=before_sleep_log(_retry_log, logging.WARNING),
            reraise=True,
        ):
            with attempt:
                try:
                    written = await self._stream_to_file(
                        url, tmp, match_id=match_id, chunk_size=chunk_size
                    )
                except BaseException:
                    # Never leave a half-written .part behind for a retry (or a
                    # later run) to mistake for a complete download.
                    tmp.unlink(missing_ok=True)
                    raise
                # Same-filesystem rename: readers never observe a partial file.
                tmp.replace(dest)
                log.info(
                    "pubg.telemetry.downloaded",
                    match_id=match_id,
                    path=str(dest),
                    bytes=written,
                )
                return written
        raise AssertionError("unreachable: AsyncRetrying(reraise=True) always exits")

    async def _stream_to_file(
        self, url: str, tmp: pathlib.Path, *, match_id: str | None, chunk_size: int = 1 << 16
    ) -> int:
        received = 0
        async with self._cdn.stream("GET", url) as response:
            if response.status_code >= 400:
                body = (await response.aread()).decode("utf-8", "replace")[:_MAX_ERROR_DETAIL]
                if response.status_code in (403, 404):
                    raise TelemetryUnavailable(
                        f"telemetry expired or missing (HTTP {response.status_code})",
                        match_id=match_id,
                        url=url,
                        status_code=response.status_code,
                        detail=body,
                    )
                if response.status_code >= 500:
                    raise PubgServerError(
                        f"telemetry CDN returned HTTP {response.status_code}",
                        status_code=response.status_code,
                        url=url,
                        detail=body,
                    )
                raise PubgApiError(
                    f"telemetry CDN returned HTTP {response.status_code}",
                    status_code=response.status_code,
                    url=url,
                    detail=body,
                )

            with tmp.open("wb") as fh:
                sink: _ByteSink = fh
                gz: gzip.GzipFile | None = None
                head = b""
                decided = False
                # Blocking writes inside an async loop: acceptable for a handful
                # of concurrent multi-MB downloads. Wrap in anyio.to_thread if
                # this ever shows up as event-loop latency.
                async for raw in response.aiter_raw(chunk_size):
                    received += len(raw)
                    if not decided:
                        head += raw
                        if len(head) < len(GZIP_MAGIC):
                            continue
                        decided = True
                        if not head.startswith(GZIP_MAGIC):
                            gz = gzip.GzipFile(fileobj=fh, mode="wb", compresslevel=6)
                            sink = gz
                        sink.write(head)
                        head = b""
                        continue
                    sink.write(raw)
                if not decided and head:  # body shorter than the magic number
                    fh.write(head)
                if gz is not None:
                    gz.close()

        if received == 0:
            raise TelemetryUnavailable(
                "telemetry CDN returned an empty body",
                match_id=match_id,
                url=url,
                status_code=204,
            )
        return tmp.stat().st_size

    # ----------------------------------------------------------- season data
    async def get_seasons(self, *, shard: str | None = None) -> SeasonsResponse:
        """List seasons. Rate limited — **cache the result for weeks**.

        The season list changes about every two months and PUBG explicitly asks
        applications not to query it more than once a month. Calling this per
        poll would waste 1 of 10 tokens per minute on a constant.
        """
        payload = await self._get_json(self._path("/seasons", shard))
        return SeasonsResponse.model_validate(payload)

    async def get_player_season_stats(
        self, account_id: str, season_id: str, *, shard: str | None = None
    ) -> PlayerSeasonResponse:
        """Per-season aggregate stats for one player. Rate limited (1 token).

        Uses the modern platform shard. Seasons at or before
        ``division.bro.official.2018-09`` (PC/PSN) need the deprecated
        platform-*region* shard instead — pass it explicitly if you ever need
        that far back.
        """
        payload = await self._get_json(
            self._path(f"/players/{account_id}/seasons/{season_id}", shard)
        )
        return PlayerSeasonResponse.model_validate(payload)

    async def get_lifetime_stats(
        self, account_id: str, *, shard: str | None = None
    ) -> PlayerSeasonResponse:
        """Lifetime aggregate stats. Same payload shape as a season, ``type`` is
        ``"lifetime"``.

        "Lifetime" starts at the platform's first Survival-Title season, not at
        account creation, so it will not match a hand-count of archived matches.
        """
        payload = await self._get_json(
            self._path(f"/players/{account_id}/seasons/lifetime", shard)
        )
        return PlayerSeasonResponse.model_validate(payload)

    async def get_weapon_mastery(
        self, account_id: str, *, shard: str | None = None
    ) -> WeaponMasteryResponse:
        """Weapon mastery summary. Rate limited (1 token).

        Note the snake_case path segment — ``weapon_mastery``, not
        ``weaponMastery`` — the only snake_case path in the API.
        """
        payload = await self._get_json(
            self._path(f"/players/{account_id}/weapon_mastery", shard)
        )
        return WeaponMasteryResponse.model_validate(payload)


def _raise_for_status(response: httpx.Response) -> httpx.Response:
    """Translate an HTTP status into this package's exception hierarchy."""
    status = response.status_code
    if status < 400:
        return response

    url = str(response.url)
    detail = _error_detail(response)

    match status:
        case 401:
            # Deliberately says nothing about the key itself beyond "rejected".
            raise PubgApiError(
                "PUBG rejected the API key (HTTP 401)", status_code=401, url=url, detail=detail
            )
        case 404:
            raise PubgApiError(
                "PUBG returned 404 — unknown resource, or outside the 14-day "
                "retention window",
                status_code=404,
                url=url,
                detail=detail,
            )
        case 415:
            raise PubgApiError(
                "PUBG returned 415 — the Accept header must be "
                "application/vnd.api+json",
                status_code=415,
                url=url,
                detail=detail,
            )
        case 429:
            # x-ratelimit-reset is absolute epoch seconds; the bucket has
            # already been told to hold until then by observe().
            reset_raw = response.headers.get("x-ratelimit-reset")
            reset_at: float | None = None
            if reset_raw is not None:
                try:
                    reset_at = float(reset_raw)
                except ValueError:
                    reset_at = None
            raise RateLimited(
                "PUBG rate limit exceeded (HTTP 429)",
                reset_at=reset_at,
                url=url,
                detail=detail,
            )
        case _ if status >= 500:
            raise PubgServerError(
                f"PUBG returned HTTP {status}", status_code=status, url=url, detail=detail
            )
        case _:
            raise PubgApiError(
                f"PUBG returned HTTP {status}", status_code=status, url=url, detail=detail
            )
