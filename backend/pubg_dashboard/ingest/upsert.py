"""Persistence: turn one JSON:API match payload into rows.

Insert order is **players -> match -> rosters -> participants** and is not
negotiable: `participants` carries an FK to `players.account_id` *and* a
composite FK to `(rosters.match_id, rosters.team_id)`, so both parents must be
committed-visible before the children go in.

Everything here is one statement per entity kind, not one per row: a match has
up to 100 participants and 100 round trips per match would dominate ingest
time. Nothing commits — the caller owns the transaction, which is what lets a
handler enqueue the follow-up job atomically with the data.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

import structlog
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import Insert as PgInsert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from pubg_dashboard.config import get_settings
from pubg_dashboard.db.models import Match, Participant, Player, Roster, utcnow

log = structlog.get_logger(__name__)

# Bots use account ids of the form "ai.<n>". They are unique only *within* a
# match, so one Player row is shared by every bot that ever carried that id;
# the row exists purely so the participant FK resolves.
BOT_ACCOUNT_PREFIX: Final = "ai."

# 65535 bind parameters is the Postgres wire-protocol ceiling (Int16 in the
# Bind message). 100 participants x ~26 columns = 2600, so a match never comes
# close; the chunking exists so a future bulk caller cannot trip over it.
_CHUNK_ROWS: Final = 500

# API stat key -> (Participant attribute, coercion).
#
# These are EXACTLY the 21 numeric/enum stat fields the current API returns
# (the other two of the 23 are `name` and `playerId`, handled separately).
# killPoints / winPoints / rankPoints / rankPointsTitle / killPlacePoints /
# winPlacePoints / mostDamage no longer exist — do not add them back.
_STAT_FIELDS: Final[tuple[tuple[str, str, Callable[[Any], Any]], ...]] = (
    ("DBNOs", "dbnos", int),  # all-caps prefix in the API, not "dbnos"/"DBNOS"
    ("assists", "assists", int),
    ("boosts", "boosts", int),
    ("damageDealt", "damage_dealt", float),
    ("deathType", "death_type", str),  # alive|byplayer|byzone|suicide|logout
    ("headshotKills", "headshot_kills", int),
    ("heals", "heals", int),
    ("killPlace", "kill_place", int),  # observed up to 107; never clamp to 100
    ("killStreaks", "kill_streaks", int),
    ("kills", "kills", int),
    ("longestKill", "longest_kill", float),
    ("revives", "revives", int),
    ("rideDistance", "ride_distance", float),
    ("roadKills", "road_kills", int),
    ("swimDistance", "swim_distance", float),
    ("teamKills", "team_kills", int),
    ("timeSurvived", "time_survived", float),
    ("vehicleDestroys", "vehicle_destroys", int),
    ("walkDistance", "walk_distance", float),
    ("weaponsAcquired", "weapons_acquired", int),
    ("winPlace", "win_place", int),
)

_STAT_DEFAULTS: Final[dict[Callable[[Any], Any], Any]] = {int: 0, float: 0.0, str: ""}

# Columns the telemetry parser owns. A re-fetch of the match payload must never
# blank them, so they are excluded from the ON CONFLICT update set.
_PARTICIPANT_PARSER_COLUMNS: Final = frozenset(
    {
        "kills_human",
        "landing_x",
        "landing_y",
        "landed_at_s",
        "death_x",
        "death_y",
        "died_at_s",
        "killer_account_id",
        "death_weapon",
    }
)
_PARTICIPANT_PK: Final = frozenset({"match_id", "account_id"})

# Ingest-owned match columns. Everything about the telemetry lifecycle
# (telemetry_key/bytes/fetched_at/parsed_at/parser_version/replay_key) is owned
# by later stages: re-fetching a match must not undo a completed download.
_MATCH_UPDATE_COLUMNS: Final = (
    "shard",
    "map_name",
    "game_mode",
    "match_type",
    "is_custom_match",
    "season_state",
    "title_id",
    "duration_s",
    "played_at",
    "telemetry_url",
)


@dataclass(slots=True)
class ParsedMatch:
    """Flat row dicts extracted from a JSON:API match payload."""

    match_id: str
    telemetry_url: str | None
    match: dict[str, Any]
    players: list[dict[str, Any]] = field(default_factory=list)
    rosters: list[dict[str, Any]] = field(default_factory=list)
    participants: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Payload parsing (pure — no session, trivially unit-testable)
# ---------------------------------------------------------------------------
def _as_bool(value: Any) -> bool:
    """Parse PUBG's inconsistent booleans.

    `roster.attributes.won` is the STRING "true"/"false", and `bool("false")`
    is True — a truthiness check here silently marks every team a winner.
    `isCustomMatch` really is a JSON bool; both shapes go through this.
    """
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


def _parse_ts(value: str) -> dt.datetime:
    """PUBG sends `2026-07-21T16:42:09Z`; fromisoformat handles Z on 3.11+."""
    parsed = dt.datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


def telemetry_url_from_payload(payload: Mapping[str, Any]) -> str | None:
    """Pull the telemetry asset URL out of `included[]`.

    The attribute is **`URL`**, fully uppercase — not `url`, not `Url`. The
    lowercase fallback is defensive in case PUBG ever normalises it.
    """
    for item in payload.get("included") or ():
        if item.get("type") != "asset":
            continue
        attrs = item.get("attributes") or {}
        url = attrs.get("URL") or attrs.get("url")
        if url:
            return str(url)
    return None


def parse_match_payload(payload: Mapping[str, Any]) -> ParsedMatch:
    """Flatten `data` + `included` into insertable row dicts."""
    data = payload["data"]
    attrs = data["attributes"]
    match_id = str(data["id"])
    now = utcnow()

    shard = attrs.get("shardId") or get_settings().pubg_default_shard
    telemetry_url = telemetry_url_from_payload(payload)

    parsed = ParsedMatch(
        match_id=match_id,
        telemetry_url=telemetry_url,
        match={
            "match_id": match_id,
            "shard": shard,
            "map_name": attrs["mapName"],
            "game_mode": attrs["gameMode"],
            # official | airoyale | tutorialatoz — only 'official' counts
            # toward career stats, so it is stored verbatim and filtered later.
            "match_type": attrs["matchType"],
            "is_custom_match": _as_bool(attrs.get("isCustomMatch")),
            "season_state": attrs.get("seasonState"),
            "title_id": attrs.get("titleId"),
            "duration_s": int(attrs.get("duration") or 0),
            "played_at": _parse_ts(attrs["createdAt"]),
            "telemetry_url": telemetry_url,
            "ingested_at": now,
        },
    )

    included: Sequence[Mapping[str, Any]] = payload.get("included") or ()

    # `included[]` interleaves participants, rosters and the asset in arbitrary
    # order — always filter by type, never index positionally.
    rosters = [item for item in included if item.get("type") == "roster"]
    participants = [item for item in included if item.get("type") == "participant"]

    # roster.relationships.participants.data[] is the ONLY link from a
    # participant to its team: there is no teamId on participant.stats.
    team_of_participant: dict[str, int] = {}
    roster_rows: dict[int, dict[str, Any]] = {}
    for roster in rosters:
        stats = roster["attributes"]["stats"]
        team_id = int(stats["teamId"])  # unique per match, verified over 61 matches
        roster_rows[team_id] = {
            "match_id": match_id,
            "team_id": team_id,
            "rank": int(stats["rank"]),
            "won": _as_bool(roster["attributes"].get("won")),
        }
        refs = (roster.get("relationships", {}).get("participants", {}) or {}).get("data") or ()
        for ref in refs:
            team_of_participant[str(ref["id"])] = team_id

    player_rows: dict[str, dict[str, Any]] = {}
    participant_rows: dict[str, dict[str, Any]] = {}
    for participant in participants:
        stats = participant["attributes"]["stats"]
        account_id = str(stats["playerId"])
        name = str(stats.get("name") or account_id)
        team_id = team_of_participant.get(str(participant["id"]))
        if team_id is None:
            # Would violate fk_participants_roster and abort the whole match.
            # Never observed in 5,584 participants; log rather than crash.
            log.warning(
                "ingest.participant_without_roster",
                match_id=match_id,
                participant_id=participant.get("id"),
                account_id=account_id,
            )
            continue

        is_bot = account_id.startswith(BOT_ACCOUNT_PREFIX)
        player_rows[account_id] = {
            "account_id": account_id,
            "name": name,
            "shard": shard,
            "is_bot": is_bot,
            "added_at": now,
        }

        row: dict[str, Any] = {
            "match_id": match_id,
            "account_id": account_id,
            "name": name,
            "team_id": team_id,
            "is_bot": is_bot,
        }
        for api_key, column, coerce in _STAT_FIELDS:
            raw = stats.get(api_key)
            row[column] = _STAT_DEFAULTS[coerce] if raw is None else coerce(raw)
        # Last write wins if the API ever repeats an account inside one match;
        # a duplicate conflict key in a single INSERT aborts the statement.
        participant_rows[account_id] = row

    # Sorting by primary key gives every worker the same row-lock order, which
    # is what keeps two workers ingesting the same match from deadlocking.
    parsed.players = [player_rows[key] for key in sorted(player_rows)]
    parsed.rosters = [roster_rows[key] for key in sorted(roster_rows)]
    parsed.participants = [participant_rows[key] for key in sorted(participant_rows)]
    return parsed


# ---------------------------------------------------------------------------
# Upsert
# ---------------------------------------------------------------------------
def _excluded_set(stmt: PgInsert, model: type[Any], columns: Iterable[str]) -> dict[str, Any]:
    """Build `set_={attr: excluded.<column>}`, honouring attr/column renames.

    `Participant.dbnos` maps to a column explicitly named "dbnos"; `excluded`
    is keyed by *column* name while `set_` takes attribute names, so the two
    sides are resolved separately instead of assuming they match.
    """
    mapper = sa_inspect(model)
    wanted = set(columns)
    return {
        attr.key: stmt.excluded[attr.columns[0].name]
        for attr in mapper.column_attrs
        if attr.key in wanted
    }


def _chunked(
    rows: Sequence[dict[str, Any]], size: int = _CHUNK_ROWS
) -> Iterable[list[dict[str, Any]]]:
    for start in range(0, len(rows), size):
        yield list(rows[start : start + size])


async def _upsert_players(session: AsyncSession, rows: Sequence[dict[str, Any]]) -> None:
    """Persist the **human** accounts from one match payload.

    Bots are dropped here and live only as `participants` rows flagged
    `is_bot`. See Player's docstring: `ai.<n>` ids are match-scoped and
    recycled, so a shared `players` row would merge dozens of unrelated bots
    into one fictional account and poison every aggregate. `players` also has a
    `ck_players_human_only` CHECK, so an `ai.` row would be rejected outright.

    `is_bot` is a discriminator carried on the parsed row, not a `players`
    column — it has to come off before the INSERT or SQLAlchemy raises
    `CompileError: Unconsumed column names: is_bot`.
    """
    humans = [
        {key: value for key, value in row.items() if key != "is_bot"}
        for row in rows
        if not row["is_bot"]
    ]

    for chunk in _chunked(humans):
        stmt = pg_insert(Player).values(chunk)
        # Only the identity fields are refreshed. `tracked`, `last_polled_at`,
        # `consecutive_poll_failures` and `added_at` belong to the poller and
        # to player CRUD — a match payload must never reset them.
        stmt = stmt.on_conflict_do_update(
            index_elements=[Player.account_id],
            set_={"name": stmt.excluded.name, "shard": stmt.excluded.shard},
            # Suppress the UPDATE when the name is unchanged: no dead tuple, no
            # WAL, and no row lock for the ~99% case.
            where=Player.name.is_distinct_from(stmt.excluded.name),
        )
        await session.execute(stmt)


async def _upsert_rosters(session: AsyncSession, rows: Sequence[dict[str, Any]]) -> None:
    for chunk in _chunked(rows):
        stmt = pg_insert(Roster).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=[Roster.match_id, Roster.team_id],
            set_=_excluded_set(stmt, Roster, ("rank", "won")),
        )
        await session.execute(stmt)


async def _upsert_participants(session: AsyncSession, rows: Sequence[dict[str, Any]]) -> None:
    if not rows:
        return
    mapper = sa_inspect(Participant)
    updatable = [
        attr.key
        for attr in mapper.column_attrs
        if attr.key not in _PARTICIPANT_PK | _PARTICIPANT_PARSER_COLUMNS
    ]
    for chunk in _chunked(rows):
        stmt = pg_insert(Participant).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=[Participant.match_id, Participant.account_id],
            set_=_excluded_set(stmt, Participant, updatable),
        )
        await session.execute(stmt)


async def upsert_match(session: AsyncSession, match_payload: Mapping[str, Any]) -> Match:
    """Persist one `GET /matches/{id}` payload and return the Match row.

    Idempotent and safe to run concurrently with itself: every write is an
    ON CONFLICT upsert and rows are inserted in primary-key order so two
    workers racing on the same match cannot deadlock. Does not commit.
    """
    parsed = parse_match_payload(match_payload)

    # Order matters: participants FK both players and rosters.
    await _upsert_players(session, parsed.players)

    stmt = pg_insert(Match).values(parsed.match)
    # No suppressing `where` here: with one row the saved write is worthless,
    # and a suppressed DO UPDATE returns no row, which would break RETURNING.
    stmt = stmt.on_conflict_do_update(
        index_elements=[Match.match_id],
        set_=_excluded_set(stmt, Match, _MATCH_UPDATE_COLUMNS),
    ).returning(Match)
    result = await session.scalars(stmt, execution_options={"populate_existing": True})
    match = result.one()

    await _upsert_rosters(session, parsed.rosters)
    await _upsert_participants(session, parsed.participants)

    log.debug(
        "ingest.match_upserted",
        match_id=parsed.match_id,
        players=len(parsed.players),
        rosters=len(parsed.rosters),
        participants=len(parsed.participants),
    )
    return match


async def unknown_match_ids(session: AsyncSession, match_ids: Iterable[str]) -> list[str]:
    """Return the subset of `match_ids` we have never ingested.

    One query for the whole list, not one per id — the poller hands this up to
    a few thousand ids per cycle.
    """
    ordered = list(dict.fromkeys(match_ids))
    if not ordered:
        return []

    known: set[str] = set()
    # Keep each IN list well inside the 65535 bind-parameter ceiling.
    for start in range(0, len(ordered), 1000):
        chunk = ordered[start : start + 1000]
        rows = await session.scalars(select(Match.match_id).where(Match.match_id.in_(chunk)))
        known.update(rows.all())
    return [match_id for match_id in ordered if match_id not in known]
