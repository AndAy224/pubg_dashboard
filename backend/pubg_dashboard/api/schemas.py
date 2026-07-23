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

    # --- telemetry-derived, present on every parsed match ------------------
    #: Σ`shots_hit` / Σ`shots_fired`, 0.0 when nothing was fired. Taken from
    #: LogMatchEnd.allWeaponStats rather than counted from attack events —
    #: every throwable emits both LogPlayerAttack and LogPlayerUseThrowable
    #: under one attackId, so counting events double-counts them.
    accuracy: float
    shots_fired: int
    shots_hit: int
    #: Headshot kills over *raw* kills: `headshot_kills` is the API's own
    #: figure and counts bots, so dividing it by `kills_human` would overstate
    #: the rate wherever bots were shot in the head.
    headshot_rate: float
    knocks_human: int
    road_kills: int
    vehicle_destroys: int
    team_kills: int
    avg_survived_s: float
    #: Best (numerically lowest) placement over the filtered set.
    best_place: int


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
    knocks: int
    headshot_kills: int
    #: Who killed them, resolved through `participants`: ~19% of killers are
    #: bots and have no `players` row at all, so joining there would blank
    #: them rather than name them.
    killed_by: str | None
    killed_by_is_bot: bool | None
    death_weapon: str | None
    shots_fired: int | None
    shots_hit: int | None
    #: Teams in the lobby, for rendering "#8 / 25" rather than a bare rank.
    num_start_teams: int | None


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


class PlacementBucket(ApiModel):
    """One bar of the placement histogram."""

    label: str
    #: Inclusive placement range this bucket covers; `hi` is None for the tail.
    lo: int
    hi: int | None
    matches: int


class Nemesis(ApiModel):
    """A human opponent, and the two-way kill record against them.

    Names come from `participants`, never `players` — an opponent may have no
    player row, and bots have none by construction.
    """

    account_id: str
    name: str
    #: Times they killed this player.
    killed_by: int
    #: Times this player killed them.
    killed: int
    last_seen: dt.datetime | None


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

    # --- telemetry-derived; NULL until the match is parsed -----------------
    shots_fired: int | None
    shots_hit: int | None
    knocks_human: int | None
    #: CENTIMETRES, origin top-left, y growing downward. **No y flip** — the
    #: telemetry origin already matches canvas convention.
    landing_x: float | None
    landing_y: float | None
    death_x: float | None
    death_y: float | None
    died_at_s: float | None
    killer_account_id: str | None
    death_weapon: str | None
    weapons_acquired: int
    kill_streaks: int
    road_kills: int
    vehicle_destroys: int
    team_kills: int
    swim_distance: float


class TrackedResult(ApiModel):
    """One tracked player's result in one match — the feed's payload.

    This is the fix for a feed that listed matches without saying who played
    or how they did.
    """

    account_id: str
    name: str
    team_id: int
    win_place: int
    kills: int
    kills_human: int | None
    knocks: int
    assists: int
    damage_dealt: float
    time_survived: float
    death_type: str
    headshot_kills: int
    shots_fired: int | None
    shots_hit: int | None
    killed_by: str | None
    killed_by_is_bot: bool | None
    death_weapon: str | None


class MatchFeedRow(ApiModel):
    """A match, plus what the tracked players did in it.

    The tracked players are **always on the same roster** when they play
    together — verified across the whole archive, 0 counterexamples — so one
    `win_place` describes the row and the per-player detail is kills, not
    competing placements.
    """

    match_id: str
    played_at: dt.datetime
    #: The real match start (LogMatchStart). `played_at` is the API's ingest
    #: time and runs a few minutes late.
    telemetry_t0: dt.datetime | None
    map_name: str
    map_display: str
    game_mode: str
    match_type: str
    duration_s: int
    has_replay: bool
    parsed: bool
    weather_id: str | None
    bot_count: int | None
    num_start_players: int | None
    num_start_teams: int | None
    team_size: int | None
    #: The tracked roster's placement, NULL when no tracked player was in it.
    win_place: int | None
    won: bool
    results: list[TrackedResult]


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
    num_start_players: int | None
    num_start_teams: int | None
    camera_view: str | None
    rosters: list[RosterRow]


class KillRow(ApiModel):
    seq: int
    t_s: float
    victim_account_id: str
    victim_name: str | None
    victim_is_bot: bool
    victim_team_id: int
    killer_account_id: str | None
    killer_name: str | None
    killer_is_bot: bool | None
    killer_team_id: int | None
    weapon: str | None
    damage_reason: str | None
    #: METRES, and `None` when the source value was the -1 "not applicable"
    #: sentinel rather than a real distance.
    distance_m: float | None
    is_suicide: bool
    is_team_kill: bool
    #: CENTIMETRES. Killer coordinates are NULL for zone/fall/drown deaths.
    #: **No y flip**: telemetry's origin is top-left like canvas.
    victim_x: float
    victim_y: float
    killer_x: float | None
    killer_y: float | None
    #: Display names of assisting players, already resolved.
    assists: list[str]


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


# ---------------------------------------------------------------------------
# overview — one request for the whole home page
# ---------------------------------------------------------------------------
class FormEntry(ApiModel):
    """One square of the form strip: a recent result, newest last."""

    match_id: str
    played_at: dt.datetime
    win_place: int
    num_start_teams: int | None
    kills: int
    map_display: str
    game_mode: str


class PlayerSummary(ApiModel):
    """A tracked player's home-page card.

    `stats` is None when the player has no `official` matches yet — career
    aggregates exclude `airoyale` and `tutorialatoz`, so a player who has only
    played those is legitimately statless rather than broken.
    """

    card: PlayerCard
    #: All-time over whatever the archive holds. PUBG drops match history
    #: after ~14 days, so "all-time" is a rolling fortnight in practice.
    stats: PlayerStats | None
    form: list[FormEntry]
    #: The two trailing windows the trend arrows compare. Either may be None
    #: when that window contains no career matches — which is normal, not an
    #: error, and must render as "no trend" rather than as a fall to zero.
    recent: PlayerStats | None
    previous: PlayerStats | None


class SessionSummary(ApiModel):
    """The most recent play session — matches separated by less than a gap.

    Sessions are what people actually remember ("how did we do tonight"),
    and a calendar day splits a session that runs past midnight.
    """

    matches: int
    started_at: dt.datetime
    ended_at: dt.datetime
    best_place: int
    wins: int
    kills_human: int
    damage: float
    #: Wall-clock from first match start to last match end, not summed
    #: durations — the gaps between matches are part of the session.
    span_s: float


class Overview(ApiModel):
    players: list[PlayerSummary]
    matches: list[MatchFeedRow]
    health: Health
    session: SessionSummary | None
