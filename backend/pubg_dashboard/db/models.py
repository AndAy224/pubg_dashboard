"""SQLAlchemy models.

The participant stat columns mirror **exactly** the 23 fields the current PUBG
API returns, verified against 5,584 real participants in `data/fixtures/`.
Fields still widely documented online — killPoints, winPoints, rankPoints,
rankPointsTitle, killPlacePoints, winPlacePoints, mostDamage — were removed by
PUBG and are deliberately absent. Adding them back would create columns that
are permanently NULL.

See `docs/reference/telemetry-observed-schema.md` for the derivation.
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

if TYPE_CHECKING:
    pass


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Players
# ---------------------------------------------------------------------------
class Player(Base):
    """A real PUBG account. Rows exist for human opponents too, not only
    tracked players — that is what makes opponent lookup and aggregate
    heatmaps free.

    BOTS ARE DELIBERATELY NOT STORED HERE. PUBG's bot ids ("ai.<n>") are
    scoped to a single match and are recycled aggressively: measured against
    the archive, 98 of 106 distinct ai.* ids (92%) recur across matches, and
    `ai.322` alone is 14 unrelated bots with 14 different names. Giving them
    Player rows would merge them into one fictional account whose lifetime
    stats are the sum of dozens of bots, silently poisoning every aggregate.
    Bots live only as `participants` rows flagged `is_bot`.
    """

    __tablename__ = "players"

    # PUBG's native id, e.g. "account.662de5f2cecc4998886b83be6582ed12".
    account_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), index=True)
    shard: Mapped[str] = mapped_column(String(16), default="steam")

    # Tracked players are the ones the poller spends rate-limit budget on.
    tracked: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), index=True
    )
    added_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_polled_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    # Set when a poll fails so we can back off a name that no longer resolves
    # (renamed accounts 404 forever otherwise).
    last_poll_error: Mapped[str | None] = mapped_column(Text)
    consecutive_poll_failures: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0")
    )

    participations: Mapped[list[Participant]] = relationship(
        back_populates="player",
        primaryjoin="foreign(Participant.account_id) == Player.account_id",
        viewonly=True,
    )

    __table_args__ = (
        # Poller's work query: tracked players ordered by staleness.
        Index(
            "ix_players_poll_queue",
            "last_polled_at",
            postgresql_where=text("tracked"),
        ),
        Index("ix_players_name_lower", text("lower(name)")),
        # Belt and braces: makes it impossible for an ingest bug to ever
        # insert a match-scoped bot id as a durable player identity.
        CheckConstraint("account_id LIKE 'account.%'", name="ck_players_human_only"),
    )


# ---------------------------------------------------------------------------
# Matches
# ---------------------------------------------------------------------------
class Match(Base):
    __tablename__ = "matches"

    # PUBG match UUID used verbatim as the PK — it is the join key everywhere,
    # including in filenames on object storage, so a surrogate int would only
    # add a lookup.
    match_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    shard: Mapped[str] = mapped_column(String(16), index=True)

    # Observed values: Baltic_Main (Erangel), Range_Main (training), plus the
    # other maps once they're played. Kept as text, not an enum, because PUBG
    # ships new maps and an enum would require a migration to ingest one.
    map_name: Mapped[str] = mapped_column(String(32), index=True)
    # squad-fpp | duo-fpp | solo | solo-fpp | squad | duo
    game_mode: Mapped[str] = mapped_column(String(24), index=True)
    # official | airoyale | tutorialatoz | custom | event | competitive ...
    match_type: Mapped[str] = mapped_column(String(24), index=True)
    is_custom_match: Mapped[bool] = mapped_column(Boolean, default=False)
    season_state: Mapped[str | None] = mapped_column(String(16))
    title_id: Mapped[str | None] = mapped_column(String(32))

    duration_s: Mapped[int] = mapped_column(Integer)
    played_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)

    # --- telemetry lifecycle ------------------------------------------------
    telemetry_url: Mapped[str | None] = mapped_column(Text)
    # Object-storage key for the raw gzipped event stream. NULL until fetched.
    telemetry_key: Mapped[str | None] = mapped_column(Text)
    telemetry_bytes: Mapped[int | None] = mapped_column(BigInteger)
    telemetry_fetched_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    # Set once the parser has emitted heatmap bins + the replay bundle. The
    # parser version lets us re-process everything after a parser change
    # without re-downloading 100 MB of telemetry.
    telemetry_parsed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    parser_version: Mapped[int | None] = mapped_column(Integer)
    parse_error: Mapped[str | None] = mapped_column(Text)
    replay_key: Mapped[str | None] = mapped_column(Text)
    replay_bytes: Mapped[int | None] = mapped_column(Integer)
    # Object-storage key of the per-match heatmap ledger. A reparse subtracts
    # this match's previous contribution before adding the new one; without the
    # ledger every reparse double-counts every bin, so a missing key means
    # "refuse to reparse", not "reparse anyway".
    heat_ledger_key: Mapped[str | None] = mapped_column(Text)

    # --- denormalised from telemetry, cheap and constantly queried ----------
    # LogMatchStart._D — the replay epoch. `played_at` is the API's ingest
    # time, not the match start, so this is the one to use for real timing.
    telemetry_t0: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    team_size: Mapped[int | None] = mapped_column(Integer)
    weather_id: Mapped[str | None] = mapped_column(String(32))
    camera_view: Mapped[str | None] = mapped_column(String(16))
    num_start_players: Mapped[int | None] = mapped_column(Integer)
    num_start_teams: Mapped[int | None] = mapped_column(Integer)
    bot_count: Mapped[int | None] = mapped_column(Integer)

    ingested_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    participants: Mapped[list[Participant]] = relationship(
        back_populates="match", cascade="all, delete-orphan"
    )
    rosters: Mapped[list[Roster]] = relationship(
        back_populates="match", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # Career stats count `official` only (user decision), so the common
        # aggregate scan is over that subset ordered by time.
        Index(
            "ix_matches_official_played_at",
            "played_at",
            postgresql_where=text("match_type = 'official'"),
        ),
        # Work queue for the telemetry fetcher / parser.
        Index(
            "ix_matches_needs_telemetry",
            "played_at",
            postgresql_where=text("telemetry_key IS NULL"),
        ),
        Index(
            "ix_matches_needs_parse",
            "played_at",
            postgresql_where=text("telemetry_key IS NOT NULL AND telemetry_parsed_at IS NULL"),
        ),
    )


# ---------------------------------------------------------------------------
# Rosters (teams)
# ---------------------------------------------------------------------------
class Roster(Base):
    __tablename__ = "rosters"

    match_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("matches.match_id", ondelete="CASCADE"), primary_key=True
    )
    team_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rank: Mapped[int] = mapped_column(Integer)
    # PUBG sends the string "true"/"false" here, NOT a JSON boolean.
    # bool("false") is True, so this must be parsed with an explicit
    # comparison. Stored as a real boolean once converted.
    won: Mapped[bool] = mapped_column(Boolean, default=False)

    match: Mapped[Match] = relationship(back_populates="rosters")

    __table_args__ = (Index("ix_rosters_match_rank", "match_id", "rank"),)


# ---------------------------------------------------------------------------
# Participants
# ---------------------------------------------------------------------------
class Participant(Base):
    """One player's result in one match. All 100 are stored, bots included."""

    __tablename__ = "participants"

    match_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("matches.match_id", ondelete="CASCADE"), primary_key=True
    )
    # NO foreign key to players: bot ids ("ai.<n>") are match-scoped and would
    # violate it. For humans this still equals players.account_id, so joins
    # work — they just aren't enforced by the database. See Player's docstring.
    account_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    team_id: Mapped[int] = mapped_column(Integer)

    # ~20% of participants overall, and up to 93% in TPP squad. Every stat
    # surface defaults to excluding these; see docs/BUILD-SPEC.md.
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))

    # --- the 23 real stat fields -------------------------------------------
    dbnos: Mapped[int] = mapped_column("dbnos", Integer, default=0)
    assists: Mapped[int] = mapped_column(Integer, default=0)
    boosts: Mapped[int] = mapped_column(Integer, default=0)
    damage_dealt: Mapped[float] = mapped_column(Float, default=0.0)
    # alive | byplayer | byzone | suicide | logout
    death_type: Mapped[str] = mapped_column(String(16))
    headshot_kills: Mapped[int] = mapped_column(Integer, default=0)
    heals: Mapped[int] = mapped_column(Integer, default=0)
    # Observed up to 107 — it is a rank among *participants*, and PUBG has
    # emitted values above 100. Do not constrain it to <= 100.
    kill_place: Mapped[int] = mapped_column(Integer, default=0)
    kill_streaks: Mapped[int] = mapped_column(Integer, default=0)
    kills: Mapped[int] = mapped_column(Integer, default=0)
    longest_kill: Mapped[float] = mapped_column(Float, default=0.0)
    revives: Mapped[int] = mapped_column(Integer, default=0)
    ride_distance: Mapped[float] = mapped_column(Float, default=0.0)
    road_kills: Mapped[int] = mapped_column(Integer, default=0)
    swim_distance: Mapped[float] = mapped_column(Float, default=0.0)
    team_kills: Mapped[int] = mapped_column(Integer, default=0)
    time_survived: Mapped[float] = mapped_column(Float, default=0.0)
    vehicle_destroys: Mapped[int] = mapped_column(Integer, default=0)
    walk_distance: Mapped[float] = mapped_column(Float, default=0.0)
    weapons_acquired: Mapped[int] = mapped_column(Integer, default=0)
    win_place: Mapped[int] = mapped_column(Integer, default=0)

    # --- telemetry-derived, filled by the parser ----------------------------
    # Human-only kill count, which is what the default stat views show.
    kills_human: Mapped[int | None] = mapped_column(Integer)
    knocks_human: Mapped[int | None] = mapped_column(Integer)
    # From LogMatchEnd.allWeaponStats, never re-derived: every throwable emits
    # both LogPlayerAttack and LogPlayerUseThrowable under one attackId, so
    # counting attack events double-counts them.
    shots_fired: Mapped[int | None] = mapped_column(Integer)
    shots_hit: Mapped[int | None] = mapped_column(Integer)
    landing_x: Mapped[float | None] = mapped_column(Float)
    landing_y: Mapped[float | None] = mapped_column(Float)
    landed_at_s: Mapped[float | None] = mapped_column(Float)
    death_x: Mapped[float | None] = mapped_column(Float)
    death_y: Mapped[float | None] = mapped_column(Float)
    died_at_s: Mapped[float | None] = mapped_column(Float)
    killer_account_id: Mapped[str | None] = mapped_column(String(64))
    death_weapon: Mapped[str | None] = mapped_column(String(64))

    match: Mapped[Match] = relationship(back_populates="participants")
    # viewonly + explicit join: there is no real FK (see account_id above), and
    # for bot rows this simply resolves to None.
    player: Mapped[Player | None] = relationship(
        back_populates="participations",
        primaryjoin="foreign(Participant.account_id) == Player.account_id",
        viewonly=True,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["match_id", "team_id"],
            ["rosters.match_id", "rosters.team_id"],
            ondelete="CASCADE",
            name="fk_participants_roster",
        ),
        # The player-match-history query: one player's matches, newest first.
        Index("ix_participants_account", "account_id", "match_id"),
        Index("ix_participants_match_team", "match_id", "team_id"),
        # Aggregate stat scans skip bots entirely.
        Index(
            "ix_participants_human",
            "account_id",
            postgresql_where=text("NOT is_bot"),
        ),
        CheckConstraint("kills >= 0", name="ck_participants_kills_nonneg"),
    )


# ---------------------------------------------------------------------------
# Job queue (Postgres SKIP LOCKED — no Redis needed at this scale)
# ---------------------------------------------------------------------------
class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # fetch_match | fetch_telemetry | parse_telemetry | backfill_player
    kind: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict] = mapped_column(JSONB)
    # A stable key per logical unit of work, so enqueueing the same match twice
    # is a no-op instead of a double download. This is the whole idempotency
    # story for concurrent pollers.
    dedupe_key: Mapped[str] = mapped_column(String(128))

    state: Mapped[str] = mapped_column(
        String(16), default="pending", server_default=text("'pending'")
    )  # pending | running | done | failed
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, server_default=text("5"))
    run_after: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    locked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(64))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        # Only one live job per unit of work. Completed rows are excluded so a
        # match can legitimately be re-parsed after a parser upgrade.
        Index(
            "uq_jobs_dedupe_live",
            "dedupe_key",
            unique=True,
            postgresql_where=text("state IN ('pending', 'running')"),
        ),
        # The claim query: oldest runnable job of any kind.
        Index(
            "ix_jobs_claim",
            "run_after",
            postgresql_where=text("state = 'pending'"),
        ),
    )


# ---------------------------------------------------------------------------
# Kill events
# ---------------------------------------------------------------------------
class KillEvent(Base):
    """The one telemetry-derived table that lives in SQL.

    Everything else the parser produces goes into the replay bundle or
    `heatmap_bins`. Kills are the exception because the UI filters and
    aggregates them by weapon, distance and time ("longest kills", "kills with
    the Beryl", weapon-filtered heatmaps) and a per-match bundle cannot answer
    a cross-match question.
    """

    __tablename__ = "kill_events"

    match_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("matches.match_id", ondelete="CASCADE"), primary_key=True
    )
    # Index within this match's parsed kill list, stable for a parser version.
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    t_s: Mapped[float] = mapped_column(Float)  # seconds since telemetry_t0

    # No `index=True` — ix_kill_victim below already leads with this column.
    victim_account_id: Mapped[str] = mapped_column(String(64))
    victim_team_id: Mapped[int] = mapped_column(Integer)
    victim_is_bot: Mapped[bool] = mapped_column(Boolean, default=False)
    victim_x: Mapped[float] = mapped_column(Float)  # CENTIMETRES
    victim_y: Mapped[float] = mapped_column(Float)

    # NULL for zone / fall / drown deaths — 2.9% of kills in the corpus.
    # `killer`, `finisher` and `dBNOMaker` are all genuinely nullable, at
    # measured presence 0.96 / 0.97 / 0.52.
    killer_account_id: Mapped[str | None] = mapped_column(String(64))
    killer_team_id: Mapped[int | None] = mapped_column(Integer)
    killer_is_bot: Mapped[bool | None] = mapped_column(Boolean)
    killer_x: Mapped[float | None] = mapped_column(Float)
    killer_y: Mapped[float | None] = mapped_column(Float)
    dbno_maker_account_id: Mapped[str | None] = mapped_column(String(64))
    finisher_account_id: Mapped[str | None] = mapped_column(String(64))

    weapon: Mapped[str | None] = mapped_column(String(64))
    damage_type: Mapped[str | None] = mapped_column(String(48))
    damage_reason: Mapped[str | None] = mapped_column(String(24))
    # CENTIMETRES. **-1 is a sentinel meaning "not applicable"**, not a
    # distance — 8.6% of kills carry it, so every "longest kill" query must
    # filter `> 0` or a melee kill wins.
    distance_cm: Mapped[float | None] = mapped_column(Float)
    is_suicide: Mapped[bool] = mapped_column(Boolean, default=False)
    is_team_kill: Mapped[bool] = mapped_column(Boolean, default=False)
    through_wall: Mapped[bool | None] = mapped_column(Boolean)
    assists: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list, server_default=text("'{}'")
    )

    __table_args__ = (
        Index(
            "ix_kill_killer",
            "killer_account_id",
            "match_id",
            postgresql_where=text("killer_account_id IS NOT NULL"),
        ),
        Index("ix_kill_victim", "victim_account_id", "match_id"),
        Index(
            "ix_kill_weapon",
            "weapon",
            postgresql_where=text("killer_account_id IS NOT NULL"),
        ),
    )


# ---------------------------------------------------------------------------
# Heatmap bins (telemetry-derived, precomputed)
# ---------------------------------------------------------------------------
class HeatmapBin(Base):
    """Pre-binned position counts.

    `account_id = ''` means "everyone" — the global aggregate for that
    map/kind, which is what makes the site-wide heatmaps cheap. Likewise
    `game_mode = ''` means "all modes".

    Those empty-string sentinels are load-bearing, NOT laziness. Postgres
    treats NULL as distinct from NULL in a unique constraint, so a nullable
    account_id would make `ON CONFLICT DO UPDATE` silently never match: every
    reparse would append a whole fresh set of global bins instead of
    incrementing, and the heatmaps would inflate without ever erroring.
    """

    __tablename__ = "heatmap_bins"

    map_name: Mapped[str] = mapped_column(String(32), primary_key=True)
    # kill | death | landing | movement | knock | care_package
    kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String(64), primary_key=True, server_default=text("''")
    )
    game_mode: Mapped[str] = mapped_column(
        String(24), primary_key=True, server_default=text("''")
    )
    # Bucketed so heatmaps can be filtered by date without storing per-match.
    day: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    grid_x: Mapped[int] = mapped_column(Integer, primary_key=True)
    grid_y: Mapped[int] = mapped_column(Integer, primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        Index("ix_heatmap_lookup", "map_name", "kind", "account_id"),
    )
