"""Asyncio token bucket for the PUBG API key budget.

Why a hand-rolled bucket instead of ``aiolimiter``
--------------------------------------------------
PUBG's rate-limit contract is not "N requests per minute" — it is "N requests
per minute *and also* whatever ``x-ratelimit-remaining`` says, *and* stop until
``x-ratelimit-reset`` when I tell you to". An off-the-shelf leaky bucket has no
hook to feed response headers back in, which means it can only ever be a guess.
This one has two independent gates:

1. **Local bucket** — refills at ``capacity / 60`` tokens per second, so a cold
   client can burst up to `capacity` and then settles at the steady rate.
2. **Server hold** — a hard monotonic deadline set from ``x-ratelimit-reset``
   (or ``Retry-After``). While the hold is active, `acquire()` sleeps; no
   amount of local token accounting can get past it.

The reconciliation rule: server truth wins, downward only
---------------------------------------------------------
Our local count is only ever *wrong in one direction*. If another process (a
second worker, a teammate's script, a cron job) shares the API key, requests
are being spent that we never counted, so our local `tokens` is always an
**over**-estimate of what is really left. Therefore:

* ``tokens = min(tokens, x-ratelimit-remaining)`` — clamp down to server truth.
* We never clamp *up*. A header can arrive from a response that raced with our
  own in-flight requests, so a "remaining: 9" header may already be stale by the
  time we read it. Raising the local count from a stale header is precisely how
  a "rate limited" ingester still eats 429s.

Header facts this file is built on (verified live, lowercase as sent):

======================== ==================================================
``x-ratelimit-limit``     requests allowed per window (default 10)
``x-ratelimit-remaining`` requests left in the current window
``x-ratelimit-reset``     **UNIX epoch seconds** — an absolute wall-clock
                          timestamp, NOT a delta and NOT milliseconds
======================== ==================================================

Two endpoints send **no** rate-limit headers at all and are not rate limited:
``GET /shards/{shard}/matches/{id}`` and the telemetry CDN. Never call
`acquire()` for those — spending a token on a free request is the difference
between archiving 10 matches a minute and archiving all of them at once.

Scope: **one bucket per API key, per process.** Use :func:`shared_bucket` so
every :class:`~pubg_dashboard.pubg.client.PubgClient` built from the same key
in one process shares state. Across *processes* client-side limiting cannot
coordinate — either give each process ``rate // N``, or move the bucket into
Postgres. The `observe()` clamp is what keeps a multi-process setup honest.
"""

from __future__ import annotations

import asyncio
import hashlib
import threading
import time
from collections.abc import Mapping
from types import TracebackType
from typing import Final, Self

import structlog

log: Final = structlog.get_logger(__name__)

# Never trust a header far enough to park a worker for an hour.
_MAX_HOLD_SECONDS: Final = 300.0
# Small pad for clock skew between our host and PUBG's edge: `reset` is their
# wall clock, ours may be a second behind, and waking up early just earns a
# second 429.
_HOLD_SKEW_PAD: Final = 0.25
# Floor a 429 hold so a reset timestamp already in the past (NTP drift, or a
# window that rolled while the response was in flight) cannot become a hot
# retry loop.
_MIN_429_HOLD: Final = 1.0
# PUBG's docs: "you should be able to make requests again within a minute."
_FALLBACK_HOLD: Final = 60.0


class TokenBucket:
    """Client-side token bucket that lets the server overrule it.

    `acquire()` is serialised by an :class:`asyncio.Lock`, which asyncio grants
    in FIFO order — concurrent callers are admitted in arrival order instead of
    one unlucky coroutine starving forever.

    Usage::

        async with limiter:            # blocks until a token is available
            response = await client.get(url)
        limiter.observe(response.headers, status_code=response.status_code)
    """

    def __init__(
        self, rate_per_minute: int, *, burst: int | None = None, name: str = "pubg"
    ) -> None:
        if rate_per_minute <= 0:
            raise ValueError("rate_per_minute must be > 0")
        self.name = name
        self._capacity = float(burst if burst is not None else rate_per_minute)
        self._refill_per_s = rate_per_minute / 60.0
        self._tokens = self._capacity
        self._updated = time.monotonic()
        self._hold_until = 0.0  # monotonic deadline, 0.0 == no hold
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ state
    @property
    def capacity(self) -> float:
        return self._capacity

    @property
    def tokens(self) -> float:
        """Best-effort estimate of remaining budget (not refilled on read)."""
        return self._tokens

    @property
    def held_for(self) -> float:
        """Seconds remaining on the server-imposed hold, 0.0 if none."""
        return max(0.0, self._hold_until - time.monotonic())

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._updated
        if elapsed > 0:
            self._tokens = min(self._capacity, self._tokens + elapsed * self._refill_per_s)
            self._updated = now

    # ----------------------------------------------------------------- public
    async def acquire(self, amount: float = 1.0) -> None:
        """Block until `amount` tokens are available and the hold has expired."""
        if amount <= 0:
            return
        async with self._lock:
            while True:
                now = time.monotonic()
                if now < self._hold_until:
                    await asyncio.sleep(self._hold_until - now)
                    # Re-check rather than fall through: `observe()` may have
                    # extended the hold while we slept.
                    continue
                self._refill()
                if self._tokens >= amount:
                    self._tokens -= amount
                    return
                deficit = amount - self._tokens
                await asyncio.sleep(deficit / self._refill_per_s)

    def observe(self, headers: Mapping[str, str], *, status_code: int = 200) -> None:
        """Reconcile local accounting against a keyed response's headers.

        Call this after **every** response from an endpoint that consumes key
        budget. Do not call it for ``/matches`` or telemetry — they send no
        rate-limit headers, and reading absent headers as "0 remaining" would
        park the client for a minute for no reason.

        Safe to call without holding the lock: asyncio is single-threaded and
        every assignment below is atomic with respect to other coroutines.
        """
        limit = _as_int(_header(headers, "x-ratelimit-limit"))
        remaining = _as_int(_header(headers, "x-ratelimit-remaining"))
        reset_epoch = _as_int(_header(headers, "x-ratelimit-reset"))

        # The key's real allowance may differ from settings (a production key is
        # not 10/min). Adopt whatever the server advertises.
        if limit is not None and limit > 0:
            server_rate = limit / 60.0
            if abs(server_rate - self._refill_per_s) > 1e-9:
                log.info("ratelimit.adopt_server_limit", bucket=self.name, limit=limit)
                self._refill_per_s = server_rate
                self._capacity = float(limit)
                self._tokens = min(self._tokens, self._capacity)

        # Downward-only clamp — see the module docstring for why never upward.
        if remaining is not None:
            self._tokens = min(self._tokens, float(remaining))

        should_hold = status_code == 429 or (remaining is not None and remaining <= 0)
        if not should_hold:
            return

        seconds: float | None = None
        if reset_epoch is not None:
            # x-ratelimit-reset is wall-clock epoch seconds; asyncio.sleep wants
            # a delta. Subtracting time.time() is the whole conversion — and it
            # is why host clock skew shows up directly as over/under-waiting.
            seconds = reset_epoch - time.time()
        if seconds is None:
            seconds = _retry_after_seconds(_header(headers, "retry-after"))
        if seconds is None:
            seconds = _FALLBACK_HOLD
        if status_code == 429:
            seconds = max(seconds, _MIN_429_HOLD)
        seconds = max(0.0, min(seconds, _MAX_HOLD_SECONDS))

        self._hold_until = max(self._hold_until, time.monotonic() + seconds + _HOLD_SKEW_PAD)
        self._tokens = 0.0
        log.warning(
            "ratelimit.hold",
            bucket=self.name,
            seconds=round(seconds, 2),
            status_code=status_code,
            remaining=remaining,
        )

    # ------------------------------------------------------- context manager
    async def __aenter__(self) -> Self:
        await self.acquire()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        # Nothing to release: a token is spent the moment the request goes out,
        # whether or not it succeeded. PUBG counts failed requests too.
        return None


# ---------------------------------------------------------------------------
# Per-key process-wide registry
# ---------------------------------------------------------------------------
_BUCKETS: dict[str, TokenBucket] = {}
_BUCKETS_LOCK = threading.Lock()


def key_fingerprint(api_key: str) -> str:
    """Short, non-reversible id for an API key — safe to log and to use as a dict key.

    The raw key is a JWT and must never appear in logs or in a registry key that
    might get dumped in a traceback.
    """
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:12]


def shared_bucket(api_key: str, rate_per_minute: int) -> TokenBucket:
    """Return the process-wide bucket for `api_key`, creating it on first use.

    The rate limit is a property of the *key*, not of the client object. Two
    ``PubgClient`` instances (say, the API process's and the poller's) built
    from the same key must share one bucket or they will each happily spend the
    full allowance.

    The first caller's `rate_per_minute` wins; later callers do not resize the
    bucket, because `observe()` will adopt the server's real limit anyway.
    """
    fingerprint = key_fingerprint(api_key)
    with _BUCKETS_LOCK:
        bucket = _BUCKETS.get(fingerprint)
        if bucket is None:
            bucket = TokenBucket(rate_per_minute, name=f"key:{fingerprint}")
            _BUCKETS[fingerprint] = bucket
        return bucket


# ---------------------------------------------------------------------------
# Header helpers
# ---------------------------------------------------------------------------
def _header(headers: Mapping[str, str], name: str) -> str | None:
    """Case-insensitive lookup that also works on a plain dict.

    ``httpx.Headers`` is already case-insensitive, but tests (and any code that
    does ``dict(response.headers)``) hand us a plain dict. PUBG sends these
    headers lowercase; the docs write them ``X-RateLimit-*``. Looking up the
    documented casing in a plain dict is a silent "header never seen".
    """
    value = headers.get(name)
    if value is not None:
        return value
    lowered = name.lower()
    for key, val in headers.items():
        if key.lower() == lowered:
            return val
    return None


def _as_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value.strip()))
    except (AttributeError, ValueError):
        return None


def _retry_after_seconds(value: str | None) -> float | None:
    """`Retry-After` is either delta-seconds or an HTTP-date (RFC 9110)."""
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
