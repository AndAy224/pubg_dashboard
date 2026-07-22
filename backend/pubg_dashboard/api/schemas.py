"""Response models.

Field names are **camelCase on the wire** and snake_case in Python, via an
alias generator. That keeps the frontend idiomatic without anyone hand-writing
a mapping — and hand-written mappings are exactly where `DBNOs` vs `dBNOs`
style bugs breed.
"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


# ---------------------------------------------------------------------------
# health / maps
# ---------------------------------------------------------------------------
class Health(ApiModel):
    db: bool
    storage: bool
    matches: int
    parsed: int
    queue_pending: int
    queue_failed: int
    #: Seconds since the stalest tracked player was polled. The number that
    #: matters operationally: PUBG drops match history after ~14 days, so a
    #: poller lag creeping upward is the early warning for permanent loss.
    poller_lag_s: float | None
    parser_version: int


class MapInfo(ApiModel):
    map_name: str
    display: str
    world_size: int
    asset_base: str
    #: 8160/8192 on the 816000-cm maps, 1.0 everywhere else.
    image_scale: float


# ---------------------------------------------------------------------------
# players
# ---------------------------------------------------------------------------
class PlayerCard(ApiModel):
    account_id: str
    name: str
    shard: str
    tracked: bool
    matches: int
    last_seen: dt.datetime | None
    last_polled_at: dt.datetime | None
    consecutive_poll_failures: int


class PlayerStats(ApiModel):
    """Career aggregate.

    `official` match types only, and **human-only kills by default** — bots are
    ~19% of all kills and just over half of the tracked players' kills, so raw
    `kills` roughly doubles some K/Ds.
    """

    account_id: str
    name: str
    matches: int
    wins: int
    top10: int
    kills: int
    kills_human: int
    knocks: int
    assists: int
    headshot_kills: int
    revives: int
    damage_dealt: float
    longest_kill_m: float
    avg_damage: float
    avg_place: float
    kd: float
    kd_human: float
    win_rate: float
    time_survived_s: float
    walk_distance_m: float
    ride_distance_m: float
    include_bots: bool


class MatchSummary(ApiModel):
    match_id: str
    played_at: dt.datetime
    map_name: str
    map_display: str
    game_mode: str
    match_type: str
    duration_s: int
    team_id: int
    win_place: int
    roster_won: bool
    kills: int
    kills_human: int | None
    assists: int
    damage_dealt: float
    time_survived: float
    death_type: str
    has_replay: bool


class WeaponStat(ApiModel):
    weapon: str
    kills: int
    headshots: int
    longest_m: float
    avg_distance_m: float


class TimeseriesPoint(ApiModel):
    day: dt.date
    matches: int
    value: float


# ---------------------------------------------------------------------------
# matches
# ---------------------------------------------------------------------------
class ParticipantRow(ApiModel):
    account_id: str
    name: str
    team_id: int
    is_bot: bool
    kills: int
    kills_human: int | None
    assists: int
    dbnos: int
    damage_dealt: float
    headshot_kills: int
    heals: int
    boosts: int
    revives: int
    longest_kill: float
    time_survived: float
    walk_distance: float
    ride_distance: float
    win_place: int
    death_type: str
    tracked: bool


class RosterRow(ApiModel):
    team_id: int
    rank: int
    won: bool
    participants: list[ParticipantRow]


class MatchDetail(ApiModel):
    match_id: str
    shard: str
    played_at: dt.datetime
    #: `played_at` is the API's *ingest* time. This is the real match start,
    #: taken from LogMatchStart, and is NULL until the match has been parsed.
    telemetry_t0: dt.datetime | None
    map_name: str
    map_display: str
    world_size: int
    game_mode: str
    match_type: str
    duration_s: int
    team_size: int | None
    weather_id: str | None
    is_custom_match: bool
    parsed: bool
    has_replay: bool
    bot_count: int | None
    rosters: list[RosterRow]


class KillRow(ApiModel):
    seq: int
    t_s: float
    victim_account_id: str
    victim_name: str | None
    victim_is_bot: bool
    killer_account_id: str | None
    killer_name: str | None
    weapon: str | None
    damage_reason: str | None
    #: METRES, and `None` when the source value was the -1 "not applicable"
    #: sentinel rather than a real distance.
    distance_m: float | None
    is_suicide: bool
    is_team_kill: bool


# ---------------------------------------------------------------------------
# heatmap
# ---------------------------------------------------------------------------
class Heatmap(ApiModel):
    map_name: str
    kind: str
    grid: int
    world_size: int
    max: int
    total: int
    #: base64 of a little-endian `Uint32Array[grid*grid]`, row-major (y*grid+x).
    #: Dense rather than sparse because 256x256x4 B is 256 KB before gzip and
    #: ~10 KB after, and the client wants a texture, not a list.
    cells: str


# ---------------------------------------------------------------------------
# ingest
# ---------------------------------------------------------------------------
class QueueRow(ApiModel):
    kind: str
    state: str
    count: int


class IngestStatus(ApiModel):
    queue: list[QueueRow]
    tracked_players: int
    matches: int
    unparsed: int
    oldest_unparsed: dt.datetime | None
    poller_lag_s: float | None
    rate_limit_per_min: int
