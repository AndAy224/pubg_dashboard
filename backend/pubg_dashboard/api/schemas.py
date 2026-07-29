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
class AlertRow(ApiModel):
    """One currently-true operational problem."""

    kind: str
    detail: str
    opened_at: dt.datetime
    last_seen_at: dt.datetime
    observations: int


class Health(ApiModel):
    db: bool
    storage: bool
    matches: int
    parsed: int
    queue_pending: int
    queue_failed: int
    #: Seconds since the **freshest** tracked player was polled — `min()` of
    #: the ages, with never-polled players excluded. A reasonable summary and a
    #: poor alarm: it agrees with the stalest player while everything works and
    #: diverges exactly when one account enters exponential backoff. Use
    #: `alerts` for the alarm; `pubgd doctor` checks `max()` and NULLs.
    poller_lag_s: float | None
    parser_version: int
    #: Everything currently wrong, from `ops_alerts`. Empty is the good case.
    alerts: list[AlertRow] = []
    #: Seconds since `pubgd doctor` last ran, or None if it never has. **None
    #: is not "fine"** — a watchdog that has never run and one that stopped an
    #: hour ago are both reasons to look. The API is the only component in a
    #: position to notice that a periodic process stopped.
    watchdog_age_s: float | None = None


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
    #: Set only for players tracking was deliberately turned off for, which is
    #: what distinguishes them from the thousands of opponents that also have
    #: `players` rows.
    untracked_at: dt.datetime | None = None


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
    #: Σ`shots_hit` / Σ`shots_fired`, 0.0 when nothing was fired.
    #:
    #: **Derived from LogPlayerAttack** since parser v10, not copied from
    #: LogMatchEnd.allWeaponStats — PUBG reports that for a median of two
    #: accounts per match, so this used to be missing for 97% of participants
    #: and every surface had to render 0 as "not reported". Throwables are
    #: excluded by attackId, which is what makes counting attack events safe.
    #:
    #: These are **trigger pulls**, not pellets.
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

    # --- accuracy, derived from LogPlayerAttack (parser v10) ---------------
    #: Trigger pulls, and trigger pulls that produced at least one attributed
    #: damage event. Deliberately not pellets: PUBG counts 90 "shots" for 10
    #: Berreta686 attacks, so a pellet ratio reads as several hundred percent
    #: accuracy on a shotgun.
    shots: int
    shots_landed: int
    #: Pellet-level hits, kept because it is what PUBG's own `hits` counts.
    hit_events: int
    #: `shots_landed / shots`, or None when the weapon was never fired — which
    #: is a real case here: a weapon can appear with kills and no shots if the
    #: kill was a finishing blow recorded under a different causer.
    accuracy: float | None


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

    # --- stored since the parser was written, never previously served -------
    #: e.g. `Damage_Gun`, `Damage_BlueZone`, `Damage_Explosion_Grenade`. This
    #: is how a zone or fall death names itself when there is no killer.
    damage_type: str | None
    #: Who knocked the victim, and who landed the finishing blow. Both differ
    #: from the credited killer often enough to matter: `dBNOMaker` is present
    #: on 5,009 of 9,275 rows, and **51% of victims are still knocked at the
    #: moment of death**, so "who won this fight" and "who got the kill" are
    #: routinely different players.
    dbno_maker_account_id: str | None
    dbno_maker_name: str | None
    finisher_account_id: str | None
    finisher_name: str | None

    # `through_wall` is deliberately **not** here. It is `False` on 9,275 of
    # 9,275 rows and on 18,492 of 18,492 raw damage blocks — shipping it would
    # ship a constant, which is the same defect as the always-zero red-zone
    # fields in reverse.


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


# ---------------------------------------------------------------------------
# strategy
# ---------------------------------------------------------------------------
class StrategyMetrics(ApiModel):
    """Telemetry-derived behavior for one player in one match.

    Every field is nullable: each has a real "not measurable" case (no
    landing, no teammates, no fights, no circle while alive) that must stay
    distinguishable from zero.
    """

    blue_s: float | None
    blue_damage: float | None
    rotate_lag_s: float | None
    teammate_dist_avg_cm: float | None
    teammate_near_pct: float | None
    hot_drop_n: int | None
    first_engage_s: float | None
    dmg_dealt_early: float | None
    dmg_taken_early: float | None
    first_weapon_s: float | None
    early_pickups_n: int | None


class StrategyMatchRow(StrategyMetrics):
    """One official match's metrics + enough context to contrast by placement."""

    match_id: str
    played_at: dt.datetime
    map_name: str
    game_mode: str
    team_size: int | None
    win_place: int
    time_survived: float
    kills: int
    damage_dealt: float
    ride_distance: float
    walk_distance: float


class SquadPlayerCohesion(StrategyMetrics):
    account_id: str
    name: str


class SquadMatchRow(ApiModel):
    """A match at least two tracked players played on the same team."""

    match_id: str
    played_at: dt.datetime
    map_name: str
    game_mode: str
    win_place: int
    players: list[SquadPlayerCohesion]


class MatchStrategyRow(StrategyMetrics):
    account_id: str
    name: str


class BaselineMetric(ApiModel):
    """One metric's distribution across the lobby, for comparison."""

    metric: str
    p25: float | None
    median: float | None
    p75: float | None
    #: Rows that had a value. **Per metric, not per row**: every metric here
    #: has a real "not measurable" case (no landing, no teammates, no fights),
    #: and in a solo match `teammate_dist_avg_cm` is NULL for the whole lobby.
    #: A single shared row count would overstate every one of them.
    n: int


class StrategyBaseline(ApiModel):
    """What the rest of the lobby does, from rows already being computed.

    `strategy_metrics` has a row for **every** participant, including the
    opponents — that is free, because the parser walks the whole match anyway.
    Every strategy endpoint then filtered to tracked players, so the comparison
    the page most wants was sitting in the table unused.
    """

    metrics: list[BaselineMetric]
    #: Bots are excluded and this says so rather than leaving it to a comment.
    #: They are 19% of participants, they never rotate, never loot properly and
    #: never contest a drop — a baseline including them makes any human look
    #: elite against a lobby that does not exist.
    excludes_bots: bool = True
    #: Tracked players are excluded too, so the squad is not compared partly
    #: against itself.
    excludes_tracked: bool = True
    #: Matches contributing, and the placement band if one was requested.
    matches: int
    place_max: int | None = None



# ---------------------------------------------------------------------------
# review — squad retrospective
# ---------------------------------------------------------------------------
class Rate(ApiModel):
    """A count over a denominator, never pre-divided.

    Both halves travel so the frontend can print "144 of 200" rather than
    "72%". A percentage alone hides its sample, and with 41-93 matches per
    player the sample is the part most likely to make a claim worthless.
    `pct` is None when `total` is 0 — never 0.0, which would read as a real
    measured zero.
    """

    n: int
    total: int
    pct: float | None = None


class KnockConversion(ApiModel):
    """Both directions of the knock-to-kill funnel.

    The two sides are the point: finishing your own knocks and surviving
    theirs are different skills, and only the contrast says which one is
    costing the squad. Humans only on both sides — bots are just over half
    the tracked players' kills and would drown the signal.
    """

    #: Knocks we landed on humans, and how many we converted to a kill.
    made: Rate
    #: Knocks landed on us, and how many became deaths. The complement is the
    #: revive-or-escape rate.
    taken: Rate


class FirstDeathRow(ApiModel):
    """How often one player is the first of the squad to go down."""

    account_id: str
    name: str
    died_first: int
    #: Matches where at least two tracked players were on the roster, so
    #: "first" means something. Solo and duo-with-strangers matches are out.
    squad_matches: int


class RangeBandRow(ApiModel):
    """Kills for and against inside one distance band.

    `distance_cm` carries a **-1 "not applicable" sentinel on 8.6% of kills**,
    filtered out here rather than bucketed into the 0 m band.
    """

    lo_m: int
    #: None on the open-ended top band.
    hi_m: int | None
    we_killed: int
    we_died: int


class DeathCauseRow(ApiModel):
    """One classified cause, with the count that earns it a place."""

    cause: str
    n: int
    label: str


class SquadReview(ApiModel):
    """Everything the Review page states about how the squad plays.

    Deliberately rows and counts, not conclusions: the sentences are built in
    `lib/findings.ts` where they are hermetically testable, exactly as the
    best-vs-worst contrast already is.
    """

    matches: int
    #: Deaths of tracked players in career matches — the denominator behind
    #: `third_party` and `death_causes`.
    deaths: int
    #: Deaths with another team's kill nearby and just before. See
    #: `THIRD_PARTY_RADIUS_CM` / `THIRD_PARTY_WINDOW_S` for the thresholds,
    #: which are a judgement call and are reported so the page can say so.
    third_party: Rate
    third_party_radius_m: int
    third_party_window_s: int
    knocks: KnockConversion
    first_deaths: list[FirstDeathRow]
    range_bands: list[RangeBandRow]
    death_causes: list[DeathCauseRow]
    #: Deaths to the blue zone. **Not a `death_causes` bucket** — 6 in 195
    #: measured, which is a footnote, not a category.
    zone_deaths: int


class SessionRow(ApiModel):
    """One evening of play, squad-wide."""

    started_at: dt.datetime
    ended_at: dt.datetime
    matches: int
    best_place: int
    wins: int
    top10: int
    kills: int
    deaths: int
    damage: float
    #: Placement of each match, newest first — the session's shape at a glance.
    places: list[int]


# ---------------------------------------------------------------------------
# drops — where we land, joined to how it went
# ---------------------------------------------------------------------------
class DropRow(ApiModel):
    """One squad's landing in one match.

    Keyed on **(match, team)**, never on participant. The three tracked players
    are always on the same roster when they play together, so a per-participant
    row would count one team drop up to three times and turn n = 19 into a
    confident n = 48.
    """

    match_id: str
    played_at: dt.datetime
    map_name: str
    game_mode: str
    team_id: int
    #: Team centroid, centimetres. The individual landings are averaged, and
    #: `spread_cm` says how far apart they were — a split drop stays visible
    #: instead of being averaged into a point nobody landed on.
    x: float
    y: float
    spread_cm: float
    landed_at_s: float | None
    #: The roster's placement. Shared, so it is one value per row.
    win_place: int
    #: Summed over the tracked players on the roster, human victims only.
    kills: int
    #: Best (longest) survival among them, seconds.
    time_survived: float
    #: Off-team players who landed within 200 m and 60 s — the maximum over the
    #: squad, since a drop is contested if anyone lands on top of any of them.
    contested: int | None
    #: Seconds from landing to first weapon equipped, averaged over the squad.
    first_weapon_s: float | None
    names: list[str]


class PlaceCell(ApiModel):
    gx: int
    gy: int
    name: str
    support: int


class Gazetteer(ApiModel):
    """PUBG's own place names, binned to the heatmap grid.

    Built offline by `scripts/build_gazetteer.py` and committed, because the
    one event that says where a player dropped — `LogParachuteLanding` —
    carries a zone name only ~1.2% of the time.
    """

    map_name: str
    grid: int
    world_size: int
    cells: list[PlaceCell]
    #: Provenance, so the client can say what the names were derived from.
    matches: int
    samples: int
    modal_purity: float
