"""Adding and removing tracked players.

The one place that decides what "tracked" means, because the CLI
(`pubgd player add|remove`) and the Settings page both do it and the details are
easy to get subtly wrong in one of two copies:

* **The account id is the stable key, the name is not.** PUBG lets people
  rename, so a re-track refreshes `name` on the existing row rather than
  creating a second one.
* **Re-tracking resets the poll failure counters.** `select_due_players` backs
  off exponentially on `consecutive_poll_failures`, up to six hours. A player
  who was untracked *because* their name stopped resolving would otherwise come
  back already deep in that backoff and appear to be ignored by the poller.
* **Untracking never deletes anything.** The row stays, `tracked` goes false,
  and every match, participant and telemetry blob is untouched — an untracked
  player's history is still readable at `/api/players/{id}/stats`.

Resolving a name costs **one rate-limit token** of the 10/min budget; adding by
account id costs nothing, which is what makes re-tracking free.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from pubg_dashboard.db.models import Player, utcnow
from pubg_dashboard.ingest.poller import parse_players_payload, status_code_of
from pubg_dashboard.ingest.ports import PubgApi
from pubg_dashboard.ingest.queue import JOB_BACKFILL_PLAYER, dedupe_key, enqueue

__all__ = [
    "PlayerNameNotResolved",
    "TrackOutcome",
    "apply_track",
    "track_by_account_id",
    "track_by_name",
    "untrack",
]

TrackStatus = Literal["added", "re-tracked", "already tracked"]


class PlayerNameNotResolved(LookupError):
    """`GET /players` returned no account for this name.

    Carries the name and shard so every caller can say the same thing: the two
    causes are a case mismatch and a wrong shard, and guessing between them
    helps nobody.
    """

    def __init__(self, name: str, shard: str) -> None:
        self.name = name
        self.shard = shard
        super().__init__(f"no player named {name!r} on shard {shard!r}")


@dataclass(frozen=True, slots=True)
class TrackOutcome:
    account_id: str
    name: str
    status: TrackStatus
    #: False when an identical job was already live — the normal result of a
    #: double click, not a failure.
    backfill_queued: bool


async def track_by_name(
    session: AsyncSession, api: PubgApi, name: str, shard: str
) -> TrackOutcome:
    """Resolve a name, track the account, queue its backfill.

    Costs one rate-limit token. Raises `PlayerNameNotResolved` when the name
    does not exist on this shard — which includes the case being wrong, since
    PUBG's name lookup is case-sensitive.

    Does **not** commit; the caller owns the transaction.
    """
    try:
        payload = await api.get_players_by_names([name])
    except Exception as exc:
        # **An unknown name 404s** — `ports.PubgApi.get_players_by_names` says so
        # and the live API confirms it. Left to propagate, the client's generic
        # 404 message reaches the operator as "unknown resource, or outside the
        # 14-day retention window", which is a true sentence about matches and a
        # actively misleading one about a mistyped player name.
        #
        # Asked by status code, not `isinstance`: `ingest` reaches the API
        # through a Protocol and must not import the concrete error classes.
        if status_code_of(exc) == 404:
            raise PlayerNameNotResolved(name, shard) from exc
        raise

    # `parse_players_payload` is the corpus-verified reader for this shape and
    # the only one that should exist. PUBG *also* answers 200 with an empty
    # `data` array for some unknown names, so an empty list is a miss too.
    refs = [ref for ref in parse_players_payload(payload) if ref.account_id]
    if not refs:
        raise PlayerNameNotResolved(name, shard)

    ref = refs[0]
    return await apply_track(session, ref.account_id, name=ref.name or name, shard=shard)


async def track_by_account_id(
    session: AsyncSession, account_id: str, *, shard: str | None = None
) -> TrackOutcome | None:
    """Track an account already known to the database. Spends no API budget.

    This is what makes re-tracking free: the row survives an untrack, so the
    account id — the thing a name lookup would have cost a token to discover —
    is already on hand. Returns None when there is no such player.
    """
    player = await session.get(Player, account_id)
    if player is None:
        return None
    return await apply_track(
        session, account_id, name=player.name, shard=shard or player.shard
    )


async def apply_track(
    session: AsyncSession, account_id: str, *, name: str, shard: str
) -> TrackOutcome:
    """Upsert the row as tracked and queue its backfill. No API call.

    Split out from `track_by_name` because the CLI resolves names in batches of
    ten and has to isolate the one bad name out of a 404 that condemns the whole
    request — that batching is a CLI concern, while everything below is the part
    that must not differ between the CLI and the API.
    """
    player = await session.get(Player, account_id)
    status: TrackStatus
    if player is None:
        player = Player(account_id=account_id, name=name, shard=shard, tracked=True)
        session.add(player)
        status = "added"
    else:
        status = "already tracked" if player.tracked else "re-tracked"
        # A rename shows up here as a name change on an existing row.
        player.name = name
        player.shard = shard
        player.tracked = True
        player.untracked_at = None
        # Start clean, or the poller's exponential backoff keeps punishing this
        # account for failures that predate the re-track.
        player.last_poll_error = None
        player.consecutive_poll_failures = 0

    queued = await enqueue(
        session,
        JOB_BACKFILL_PLAYER,
        {"account_id": account_id, "shard": shard, "name": name},
        key=dedupe_key(JOB_BACKFILL_PLAYER, account_id),
    )
    return TrackOutcome(
        account_id=account_id, name=name, status=status, backfill_queued=queued
    )


async def untrack(session: AsyncSession, account_id: str) -> Player | None:
    """Stop polling a player. Returns None if they were not tracked.

    `untracked_at` is what separates "someone I stopped tracking" from the
    ~4,300 opponents that also have `players` rows, so the UI can offer a free
    re-track without listing every stranger who was ever in a lobby.
    """
    player = await session.get(Player, account_id)
    if player is None or not player.tracked:
        return None
    player.tracked = False
    player.untracked_at = utcnow()
    return player
