"""The checks that answer one question: is anything about to be lost forever?

PUBG retains matches for **~14 days**. Everything else this system can get
wrong is recoverable by re-running something — a bad parse reparses, a wrong
number is a bump and a reparse away. A poller that stops and is not noticed is
not recoverable, and after fourteen days the matches simply do not exist any
more.

This runs as a **separate process** on a systemd timer, and that is the design,
not a convenience: the poller cannot report its own death, and the API only
does work when someone asks it to. It also stamps its own heartbeat so the API
can answer "the watchdog has not run", because something has to watch the
watcher.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pubg_dashboard.config import get_settings
from pubg_dashboard.db.models import Job, Match, Player, utcnow
from pubg_dashboard.ops.alerts import beat, raise_alert, resolve_alert

log = structlog.get_logger(__name__)

__all__ = ["WATCHDOG_NAME", "Finding", "run_checks"]

WATCHDOG_NAME = "doctor"

#: PUBG's retention window. Anything unfetched for longer than this is gone.
RETENTION_DAYS = 14

#: How close to the edge is close enough to shout about.
AT_RISK_DAYS = 10


@dataclass(slots=True)
class Finding:
    kind: str
    ok: bool
    detail: str


async def run_checks(session: AsyncSession) -> list[Finding]:
    """Evaluate every check, raise or resolve each alert, return the findings."""
    settings = get_settings()
    findings = [
        await _check_poller(session, settings.poll_interval_seconds),
        await _check_never_polled(session),
        await _check_failed_jobs(session),
        await _check_unparsed(session),
        await _check_retention(session),
    ]
    for f in findings:
        if f.ok:
            await resolve_alert(session, f.kind)
        else:
            await raise_alert(session, f.kind, f.detail)
    await beat(session, WATCHDOG_NAME)
    return findings


async def _check_poller(session: AsyncSession, interval_s: int) -> Finding:
    """How stale is the **stalest** tracked player.

    `/health` computes `min(now() - last_polled_at)`, which is the *freshest*
    player, and filters out anyone never polled. That is a reasonable summary
    and a poor alarm: with one batched request per cycle the two agree while
    everything works, and diverge exactly when one account enters exponential
    backoff — which is the case worth catching, because backoff reaches six
    hours and the account quietly rots while the badge stays green.
    """
    threshold = max(interval_s * 4, get_settings().alert_poller_lag_s)
    row = (
        await session.execute(
            select(
                func.max(func.extract("epoch", func.now() - Player.last_polled_at)),
                func.count(),
            ).where(Player.tracked, Player.last_polled_at.is_not(None))
        )
    ).one()
    worst, n = row
    if not n:
        return Finding("poller_stalled", True, "no tracked players with a poll time")
    worst_s = float(worst or 0.0)
    if worst_s > threshold:
        return Finding(
            "poller_stalled",
            False,
            f"stalest tracked player last polled {worst_s / 60:.0f} min ago "
            f"(threshold {threshold / 60:.0f} min)",
        )
    return Finding("poller_stalled", True, f"stalest poll {worst_s / 60:.0f} min ago")


async def _check_never_polled(session: AsyncSession) -> Finding:
    """A tracked player who has never been polled at all.

    Invisible to any lag calculation, because there is no timestamp to subtract
    from — `/health` filters these rows out entirely. A player added and then
    never successfully resolved sits here forever looking like nothing.
    """
    names = (
        (
            await session.execute(
                select(Player.name).where(Player.tracked, Player.last_polled_at.is_(None))
            )
        )
        .scalars()
        .all()
    )
    if names:
        return Finding(
            "player_never_polled",
            False,
            f"tracked but never polled: {', '.join(sorted(names))}",
        )
    return Finding("player_never_polled", True, "every tracked player has been polled")


async def _check_failed_jobs(session: AsyncSession) -> Finding:
    rows = (
        await session.execute(
            select(Job.kind, func.count())
            .where(Job.state == "failed")
            .group_by(Job.kind)
        )
    ).all()
    if rows:
        detail = ", ".join(f"{kind}: {n}" for kind, n in rows)
        return Finding("queue_failed", False, f"dead-lettered jobs — {detail}")
    return Finding("queue_failed", True, "no dead-lettered jobs")


async def _check_unparsed(session: AsyncSession) -> Finding:
    """Matches fetched but not parsed for over an hour, or parsed with an error.

    Not urgent the way a stalled poller is — the raw telemetry is already
    archived, so a parse can be retried indefinitely — but a growing backlog
    means the worker is wedged, and the worker is what fetches telemetry too.
    """
    cutoff = utcnow() - dt.timedelta(hours=1)
    stuck = await session.scalar(
        select(func.count())
        .select_from(Match)
        .where(
            Match.telemetry_key.is_not(None),
            Match.telemetry_parsed_at.is_(None),
            Match.ingested_at < cutoff,
        )
    )
    errored = await session.scalar(
        select(func.count()).select_from(Match).where(Match.parse_error.is_not(None))
    )
    if stuck or errored:
        return Finding(
            "parse_failing",
            False,
            f"{stuck or 0} match(es) fetched but unparsed for >1 h, "
            f"{errored or 0} with a recorded parse error",
        )
    return Finding("parse_failing", True, "nothing unparsed")


async def _check_retention(session: AsyncSession) -> Finding:
    """Matches approaching the 14-day window with no telemetry archived.

    This is the check the whole module exists for. Once `played_at` is 14 days
    old the telemetry URL stops resolving and that match can never be replayed,
    heat-mapped or re-derived — there is no recovery, only prevention.
    """
    edge = utcnow() - dt.timedelta(days=AT_RISK_DAYS)
    rows = (
        await session.execute(
            select(Match.match_id, Match.played_at)
            .where(Match.telemetry_key.is_(None), Match.played_at < edge)
            .order_by(Match.played_at)
            .limit(5)
        )
    ).all()
    if rows:
        oldest = rows[0][1]
        days = (utcnow() - oldest).days
        return Finding(
            "telemetry_at_risk",
            False,
            f"{len(rows)}+ match(es) have no archived telemetry and the oldest is "
            f"{days} days old; PUBG drops it at {RETENTION_DAYS}",
        )
    return Finding("telemetry_at_risk", True, "all matches have telemetry archived")
