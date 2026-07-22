"""Exception hierarchy for the PUBG API client.

The split that matters is **retryable vs. permanent**, because the whole client
is wrapped in tenacity:

* :class:`PubgServerError` (5xx) and :class:`RateLimited` (429) are transient —
  retry them.
* :class:`PlayerNotFound` (404) is permanent. PUBG 404s a renamed or deleted
  account forever, so retrying one burns rate-limit budget to learn nothing.
* :class:`TelemetryUnavailable` is permanent too: telemetry is deleted after the
  14-day retention window and never comes back.

Nothing here ever carries the API key. `detail` holds a *truncated* response
body, which for this API is a `{"errors": [{"title": ...}]}` envelope.
"""

from __future__ import annotations

from collections.abc import Iterable


class PubgApiError(Exception):
    """Base class for every failure originating from the PUBG API or its CDN.

    Args:
        message: Human-readable summary. Safe to log.
        status_code: HTTP status, when the failure was an HTTP response.
        url: Request URL. Never contains the key — PUBG authenticates by header.
        detail: Truncated server-supplied error text, if any.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        url: str | None = None,
        detail: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.url = url
        self.detail = detail

    def __str__(self) -> str:
        parts = [self.message]
        if self.detail:
            parts.append(f"({self.detail})")
        return " ".join(parts)


class PlayerNotFound(PubgApiError):
    """One or more requested player names / account ids do not exist on the shard.

    `GET /players?filter[playerNames]=` 404s the **entire batch** when any single
    name is unknown, so this exception names the specific offenders — the client
    re-probes the batch one name at a time to work out which ones they are.

    Names are case-sensitive: `chocotaco` is a different, non-existent player
    from `chocoTaco`. A "not found" here is very often a casing mistake.
    """

    def __init__(
        self,
        identifiers: Iterable[str],
        *,
        kind: str = "name",
        shard: str | None = None,
        url: str | None = None,
    ) -> None:
        self.identifiers = list(identifiers)
        self.kind = kind
        self.shard = shard
        label = "player name" if kind == "name" else "account id"
        plural = "s" if len(self.identifiers) != 1 else ""
        where = f" on shard '{shard}'" if shard else ""
        super().__init__(
            f"unknown {label}{plural}{where}: {', '.join(self.identifiers) or '<none>'}",
            status_code=404,
            url=url,
        )

    @property
    def names(self) -> list[str]:
        return self.identifiers if self.kind == "name" else []

    @property
    def account_ids(self) -> list[str]:
        return self.identifiers if self.kind == "id" else []


class RateLimited(PubgApiError):
    """HTTP 429 — the key's request budget for the current window is spent.

    `reset_at` is a **wall-clock UNIX epoch in seconds** taken straight from
    `x-ratelimit-reset`. It is an absolute timestamp, not a delta: sleeping for
    `reset_at` seconds instead of `reset_at - time.time()` parks the process
    until the year 2057.
    """

    def __init__(
        self,
        message: str = "rate limited by the PUBG API",
        *,
        reset_at: float | None = None,
        retry_after: float | None = None,
        url: str | None = None,
        detail: str | None = None,
    ) -> None:
        super().__init__(message, status_code=429, url=url, detail=detail)
        self.reset_at = reset_at
        self.retry_after = retry_after


class TelemetryUnavailable(PubgApiError):
    """The telemetry event stream for a match cannot be fetched.

    Three real causes, all permanent:

    1. the match response carried no `asset` in `included[]`;
    2. the asset had no `URL` attribute;
    3. the CDN answered 403/404 — the object aged out of the 14-day window.
    """

    def __init__(
        self,
        message: str,
        *,
        match_id: str | None = None,
        url: str | None = None,
        status_code: int | None = None,
        detail: str | None = None,
    ) -> None:
        super().__init__(message, status_code=status_code, url=url, detail=detail)
        self.match_id = match_id


class PubgServerError(PubgApiError):
    """A 5xx from PUBG (or its CDN). Transient by assumption — safe to retry.

    Kept separate from :class:`PubgApiError` purely so `retry_if_exception_type`
    can select it without also selecting 404s.
    """
