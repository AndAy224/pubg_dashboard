"""Token bucket: budget exhaustion, `x-ratelimit-reset` reconciliation, 429.

Nothing here sleeps for real. The bucket's clock and its `asyncio.sleep` are
replaced by a fake that *advances* the clock instead of waiting, so a test that
proves "the client parks for 37 seconds" runs in microseconds — and a bug that
would park it for 1.7 *billion* seconds fails instead of hanging CI forever.

The two facts under test, both verified live and both easy to regress:

* PUBG's rate-limit headers are lowercase on the wire (`x-ratelimit-reset`),
  while the docs write `X-RateLimit-Reset`. HTTP headers are case-insensitive
  and httpx normalises them, so the bucket must read through a case-insensitive
  mapping and never `dict(response.headers)[...]`.
* `x-ratelimit-reset` is an absolute **UNIX epoch in seconds**, not a delta.
  Sleeping for its face value parks the process until the year 2057.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from types import SimpleNamespace

import httpx
import pytest

from pubg_dashboard.pubg import ratelimit
from pubg_dashboard.pubg.ratelimit import TokenBucket

# Arbitrary but realistic: a monotonic clock well away from 0 (so a bug that
# treats a monotonic value as wall-clock is obvious) and a wall clock in 2026.
START_MONOTONIC = 10_000.0
START_WALL = 1_784_000_000.0


class FakeClock:
    """Stands in for both `time.monotonic()` and `time.time()`.

    They advance together, which is exactly the assumption the reset-header
    conversion (`reset_epoch - time.time()`, then slept on a monotonic
    deadline) relies on. Skew between them is a separate, real concern; it is
    modelled explicitly by `skew_wall()` below rather than by accident.
    """

    def __init__(self) -> None:
        self._mono = START_MONOTONIC
        self._wall = START_WALL
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self._mono

    def time(self) -> float:
        return self._wall

    def advance(self, seconds: float) -> None:
        self._mono += seconds
        self._wall += seconds

    def skew_wall(self, seconds: float) -> None:
        """Move wall-clock only — an NTP correction mid-flight."""
        self._wall += seconds

    @property
    def total_slept(self) -> float:
        return sum(self.slept)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeClock]:
    """Patch the `time` and `asyncio` names *inside the ratelimit module*.

    Patching the module's own globals rather than `time.monotonic` /
    `asyncio.sleep` themselves keeps the fake from leaking into pytest,
    pytest-asyncio or anything else running on the same loop.
    """
    fake = FakeClock()

    async def fake_sleep(delay: float) -> None:
        assert delay >= 0, f"negative sleep ({delay}) — a reset delta was mis-signed"
        assert delay < 3600, f"sleep of {delay}s — an epoch value leaked in as a delta"
        fake.slept.append(delay)
        fake.advance(delay)
        await asyncio.sleep(0)  # still yield, so FIFO lock fairness is preserved

    monkeypatch.setattr(
        ratelimit, "time", SimpleNamespace(monotonic=fake.monotonic, time=fake.time)
    )
    # `Lock` must stay real: the bucket constructs one in __init__.
    monkeypatch.setattr(ratelimit, "asyncio", SimpleNamespace(sleep=fake_sleep, Lock=asyncio.Lock))
    yield fake


def headers(**kwargs: object) -> httpx.Headers:
    """Build headers the way httpx hands them to us: case-insensitive mapping.

    Deliberately not a plain dict — a plain dict would let a `.get("X-RateLimit-Reset")`
    lookup pass in tests and silently return `None` in production.
    """
    return httpx.Headers({k.replace("_", "-"): str(v) for k, v in kwargs.items()})


# ===========================================================================
# Local budget
# ===========================================================================
async def test_burst_is_free_then_the_bucket_throttles(clock: FakeClock) -> None:
    bucket = TokenBucket(rate_per_minute=10)

    for _ in range(10):
        await bucket.acquire()
    assert clock.slept == [], "a full bucket must not sleep"

    await bucket.acquire()
    # 10/min -> one token every 6s.
    assert clock.total_slept == pytest.approx(6.0, abs=0.01)


async def test_sustained_rate_matches_the_configured_budget(clock: FakeClock) -> None:
    """30 requests on a 10/min key must take ~2 minutes of simulated time."""
    bucket = TokenBucket(rate_per_minute=10)
    for _ in range(30):
        await bucket.acquire()

    # 10 free from the initial burst, 20 paid for at 6s each.
    assert clock.total_slept == pytest.approx(120.0, abs=0.1)


async def test_refill_credits_idle_time(clock: FakeClock) -> None:
    bucket = TokenBucket(rate_per_minute=10)
    for _ in range(10):
        await bucket.acquire()

    clock.advance(30.0)  # 5 tokens' worth of doing nothing
    for _ in range(5):
        await bucket.acquire()
    assert clock.slept == []


async def test_bucket_never_exceeds_capacity(clock: FakeClock) -> None:
    """An hour idle does not buy an hour's worth of burst."""
    bucket = TokenBucket(rate_per_minute=10)
    clock.advance(3600.0)

    for _ in range(10):
        await bucket.acquire()
    assert clock.slept == []
    await bucket.acquire()
    assert clock.total_slept == pytest.approx(6.0, abs=0.01)


async def test_concurrent_acquirers_are_admitted_in_arrival_order(clock: FakeClock) -> None:
    """The lock is what stops N tasks all deciding they have the last token."""
    bucket = TokenBucket(rate_per_minute=10)
    order: list[int] = []

    async def caller(n: int) -> None:
        await bucket.acquire()
        order.append(n)

    async with asyncio.TaskGroup() as tg:
        for i in range(20):
            tg.create_task(caller(i))

    assert order == list(range(20))
    assert clock.total_slept == pytest.approx(60.0, abs=0.5)  # 10 paid tokens


# ===========================================================================
# Server reconciliation
# ===========================================================================
async def test_reset_header_is_an_epoch_not_a_delta(clock: FakeClock) -> None:
    """The single most expensive possible bug in this module.

    `x-ratelimit-reset` is ~1.78e9. Sleeping on it directly wedges the poller
    for 56 years; the fake sleeper's guard rail would trip long before the
    assertion below.
    """
    bucket = TokenBucket(rate_per_minute=10)
    reset_at = clock.time() + 37.0

    bucket.observe(
        headers(x_ratelimit_limit=10, x_ratelimit_remaining=0, x_ratelimit_reset=int(reset_at)),
    )

    await bucket.acquire()
    assert 37.0 <= clock.total_slept < 40.0, (
        f"slept {clock.total_slept}s for a reset 37s away — epoch treated as a delta?"
    )


async def test_documented_header_casing_also_works(clock: FakeClock) -> None:
    """Docs say `X-RateLimit-Reset`; the wire sends lowercase. Both must land.

    This only holds if the bucket reads through httpx's case-insensitive
    `Headers`. It breaks the moment someone writes `dict(response.headers)`.
    """
    bucket = TokenBucket(rate_per_minute=10)
    bucket.observe(
        httpx.Headers(
            {
                "X-RateLimit-Limit": "10",
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(int(clock.time() + 20.0)),
            }
        )
    )

    await bucket.acquire()
    assert 20.0 <= clock.total_slept < 23.0


async def test_server_remaining_lowers_the_local_estimate(clock: FakeClock) -> None:
    """The server is authoritative when it says we have *less* than we think.

    Another process on the same key has been spending budget; our local count
    is optimistic and the header is the only way to find out.
    """
    bucket = TokenBucket(rate_per_minute=10)
    bucket.observe(headers(x_ratelimit_limit=10, x_ratelimit_remaining=2))

    for _ in range(2):
        await bucket.acquire()
    assert clock.slept == []

    await bucket.acquire()
    assert clock.total_slept == pytest.approx(6.0, abs=0.01)


async def test_server_remaining_never_inflates_the_bucket(clock: FakeClock) -> None:
    """A bogus high `remaining` must not hand us free requests.

    Trusting it upward turns one malformed header into a burst that gets the
    key throttled — the failure the limiter exists to prevent.
    """
    bucket = TokenBucket(rate_per_minute=10)
    for _ in range(10):
        await bucket.acquire()  # bucket now empty

    bucket.observe(headers(x_ratelimit_limit=10, x_ratelimit_remaining=9999))

    await bucket.acquire()
    assert clock.total_slept == pytest.approx(
        6.0, abs=0.01
    ), "the bucket was refilled from a header"


async def test_bucket_adopts_a_larger_server_limit(clock: FakeClock) -> None:
    """PUBG grants raised limits per key; the client should not stay at 10/min.

    Only the *refill rate* is adopted — the header raises the ceiling, it does
    not mint tokens, so the burst still has to be earned.
    """
    bucket = TokenBucket(rate_per_minute=10)
    for _ in range(10):
        await bucket.acquire()

    bucket.observe(headers(x_ratelimit_limit=60, x_ratelimit_remaining=60))

    await bucket.acquire()
    assert clock.total_slept == pytest.approx(1.0, abs=0.01)  # 60/min -> 1s/token, was 6s


# ===========================================================================
# 429
# ===========================================================================
async def test_429_parks_until_the_reset(clock: FakeClock) -> None:
    bucket = TokenBucket(rate_per_minute=10)
    bucket.observe(
        headers(x_ratelimit_remaining=0, x_ratelimit_reset=int(clock.time() + 45.0)),
        status_code=429,
    )

    await bucket.acquire()
    assert 45.0 <= clock.total_slept < 48.0


async def test_429_without_headers_falls_back_to_a_minute(clock: FakeClock) -> None:
    """PUBG's own wording: "you should be able to make requests again within a minute"."""
    bucket = TokenBucket(rate_per_minute=10)
    bucket.observe(httpx.Headers({}), status_code=429)

    await bucket.acquire()
    assert 59.0 <= clock.total_slept <= 61.0


async def test_retry_after_is_honoured_when_reset_is_absent(clock: FakeClock) -> None:
    bucket = TokenBucket(rate_per_minute=10)
    bucket.observe(headers(retry_after=12), status_code=429)

    await bucket.acquire()
    assert 12.0 <= clock.total_slept < 15.0


async def test_a_wild_reset_header_is_clamped(clock: FakeClock) -> None:
    """A garbage or wildly skewed reset must not park the poller for a day."""
    bucket = TokenBucket(rate_per_minute=10)
    bucket.observe(
        headers(x_ratelimit_remaining=0, x_ratelimit_reset=int(clock.time() + 86_400)),
        status_code=429,
    )

    await bucket.acquire()
    assert clock.total_slept <= 301.0


async def test_a_reset_already_in_the_past_does_not_spin(clock: FakeClock) -> None:
    """Host clock ahead of PUBG's edge yields a negative delta.

    Unclamped that is either a negative sleep (ValueError) or a busy loop that
    burns a core; both have been seen in the wild on NTP-drifted containers.
    """
    bucket = TokenBucket(rate_per_minute=10)
    bucket.observe(
        headers(x_ratelimit_remaining=0, x_ratelimit_reset=int(clock.time() - 500)),
        status_code=429,
    )

    await bucket.acquire()
    assert clock.total_slept < 10.0


async def test_clock_skew_after_a_hold_still_terminates(clock: FakeClock) -> None:
    """The hold deadline is monotonic, so an NTP jump cannot extend it.

    If the deadline were stored as wall-clock epoch, a backwards NTP correction
    during the hold would re-park the poller for the same window all over again.
    """
    bucket = TokenBucket(rate_per_minute=10)
    bucket.observe(
        headers(x_ratelimit_remaining=0, x_ratelimit_reset=int(clock.time() + 30.0)),
        status_code=429,
    )
    clock.skew_wall(-600.0)

    await bucket.acquire()
    assert clock.total_slept < 60.0


async def test_junk_header_values_are_ignored(clock: FakeClock) -> None:
    """Never let a malformed header raise out of `observe` — it runs per response."""
    bucket = TokenBucket(rate_per_minute=10)
    bucket.observe(
        headers(x_ratelimit_limit="", x_ratelimit_remaining="n/a", x_ratelimit_reset="soon")
    )

    for _ in range(10):
        await bucket.acquire()
    assert clock.slept == []


async def test_unrelated_response_headers_change_nothing(clock: FakeClock) -> None:
    """`GET /matches/{id}` returns no rate-limit headers at all and is unlimited."""
    bucket = TokenBucket(rate_per_minute=10)
    bucket.observe(httpx.Headers({"content-type": "application/vnd.api+json"}))

    for _ in range(10):
        await bucket.acquire()
    assert clock.slept == []


def test_rate_must_be_positive() -> None:
    with pytest.raises(ValueError):
        TokenBucket(rate_per_minute=0)
