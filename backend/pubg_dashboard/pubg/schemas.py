"""Pydantic v2 models for PUBG's JSON:API responses.

Validation policy
-----------------
``extra="allow"`` everywhere: PUBG ships new attributes with patches and a
strict model would start rejecting live traffic on a Tuesday. Unknown keys stay
reachable via ``model_extra``.

Strict where it counts: the 23 participant stat fields are all **required**. All
23 were present in 5,584/5,584 participants across the 61-match corpus, and each
one backs a database column. If a patch removes one we want a loud
`ValidationError` at ingest, not a column silently filling with zeros and
poisoning every career aggregate.

Casing traps encoded here — do not "fix" these
----------------------------------------------
* ``asset.attributes.URL`` is **fully uppercase**. Typing it ``url`` yields
  ``None`` and a dashboard with no telemetry. Accepted here via
  ``AliasChoices("URL", "url")`` so a future normalisation by PUBG still works.
* Participant knocks are ``DBNOs``; the *same concept* in season stats is
  ``dBNOs`` (lowercase d). Two different casings, one API.
* ``roster.attributes.won`` is the **string** ``"true"``/``"false"``.
  ``bool("false")`` is ``True``, so it is parsed with an explicit comparison.
* Weapon mastery is the one PascalCase corner of the API (``XPTotal``,
  ``StatsTotal``, ``Kills``).
* ``playerSeason`` responses have **no** ``data.id`` — a model requiring `id`
  raises on every season fetch.

Structural traps
----------------
* ``included[]`` is interleaved, never grouped by type. :class:`MatchResponse`
  partitions it by ``type`` in a before-validator and drops unknown types, so
  callers never index positionally and a new resource type cannot break a parse.
* Bots are ordinary participants whose ``playerId`` starts with ``"ai."``.
  ~20% of participants overall, up to 93% in TPP squad — they are real rows,
  not noise to discard.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Final

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

# matchType values worth counting toward career stats. 'airoyale' and
# 'tutorialatoz' were both observed in the corpus and are deliberately excluded.
OFFICIAL_MATCH_TYPE: Final = "official"
BOT_ACCOUNT_PREFIX: Final = "ai."


class PubgModel(BaseModel):
    """Base for every PUBG payload model.

    ``populate_by_name`` lets tests and fixtures construct models with the
    pythonic field names while live payloads come in with PUBG's casing.
    """

    model_config = ConfigDict(
        extra="allow",
        populate_by_name=True,
        str_strip_whitespace=False,
    )


# ---------------------------------------------------------------------------
# JSON:API primitives
# ---------------------------------------------------------------------------
class ResourceRef(PubgModel):
    """A ``{"type": ..., "id": ...}`` pointer into ``included[]`` or elsewhere."""

    type: str
    id: str


class ResourceRefList(PubgModel):
    """A relationship's ``{"data": [...]}`` wrapper."""

    data: list[ResourceRef] = Field(default_factory=list)

    @field_validator("data", mode="before")
    @classmethod
    def _null_is_empty(cls, value: object) -> object:
        # Several relationships (`team`, and `matches` for a fresh account) come
        # back as `{"data": null}` rather than an empty array.
        return [] if value is None else value

    @property
    def ids(self) -> list[str]:
        return [ref.id for ref in self.data]


class ErrorMember(PubgModel):
    """One member of the ``{"errors": [...]}`` envelope.

    `title` is documented as "the HTTP status code as a string" but observed as
    a reason phrase ("Not Found"). Treat it as opaque; switch on the status code.
    """

    title: str | None = None
    description: str | None = None


class ErrorResponse(PubgModel):
    errors: list[ErrorMember] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Players
# ---------------------------------------------------------------------------
class PlayerAttributes(PubgModel):
    name: str
    shard_id: str | None = Field(default=None, alias="shardId")
    title_id: str | None = Field(default=None, alias="titleId")
    # Observed lowercase `clanId` on a live 2026 payload. Undocumented in
    # PUBG's own schema, so optional.
    clan_id: str | None = Field(default=None, alias="clanId")
    # 'Innocent' | 'TemporaryBan' | 'PermanentBan'. Absent on older payloads.
    ban_type: str | None = Field(default=None, alias="banType")
    patch_version: str | None = Field(default=None, alias="patchVersion")
    # Documented "N/A", observed null on every real response.
    stats: Any | None = None


class PlayerRelationships(PubgModel):
    matches: ResourceRefList = Field(default_factory=ResourceRefList)
    assets: ResourceRefList = Field(default_factory=ResourceRefList)


class Player(PubgModel):
    type: str = "player"
    # "account.<32 hex>" for humans; bots never appear here, only in matches.
    id: str
    attributes: PlayerAttributes
    relationships: PlayerRelationships = Field(default_factory=PlayerRelationships)

    @property
    def account_id(self) -> str:
        return self.id

    @property
    def name(self) -> str:
        return self.attributes.name

    @property
    def match_ids(self) -> list[str]:
        """Recent match ids, newest first — up to ~50, capped at 14 days.

        Ordering is undocumented but consistently newest-first in real payloads.
        Do not rely on it for anything that matters; sort by the match's own
        ``createdAt`` once fetched.
        """
        return self.relationships.matches.ids


class PlayersResponse(PubgModel):
    data: list[Player] = Field(default_factory=list)

    @field_validator("data", mode="before")
    @classmethod
    def _single_to_list(cls, value: object) -> object:
        # GET /players/{accountId} returns a bare object where the collection
        # endpoint returns an array.
        return [value] if isinstance(value, dict) else value

    @property
    def by_name(self) -> dict[str, Player]:
        """Name -> player. Keys are case-sensitive, exactly as PUBG treats them."""
        return {player.name: player for player in self.data}

    @property
    def by_id(self) -> dict[str, Player]:
        return {player.id: player for player in self.data}


# ---------------------------------------------------------------------------
# Matches
# ---------------------------------------------------------------------------
class MatchAttributes(PubgModel):
    created_at: dt.datetime = Field(alias="createdAt")
    duration: int
    game_mode: str = Field(alias="gameMode")
    # Internal key, e.g. Baltic_Main == Erangel Remastered. Never an enum here:
    # PUBG ships new maps before the dictionaries update.
    map_name: str = Field(alias="mapName")
    # Observed: official | airoyale | tutorialatoz.
    match_type: str = Field(alias="matchType")
    is_custom_match: bool = Field(default=False, alias="isCustomMatch")
    season_state: str | None = Field(default=None, alias="seasonState")
    shard_id: str | None = Field(default=None, alias="shardId")
    title_id: str | None = Field(default=None, alias="titleId")
    # Documented "N/A"; observed null, not {}.
    stats: Any | None = None
    tags: Any | None = None


class MatchData(PubgModel):
    type: str = "match"
    id: str
    attributes: MatchAttributes


class ParticipantStats(PubgModel):
    """The 23 stat fields the current API actually returns.

    Every field is required on purpose — see the module docstring. Fields still
    documented all over the internet (killPoints, winPoints, rankPoints,
    rankPointsTitle, killPlacePoints, winPlacePoints, mostDamage) no longer
    exist and must not be added back.
    """

    # Knocks. All-caps prefix; `dbnos`/`DBNOS` both silently yield nothing.
    dbnos: int = Field(alias="DBNOs")
    assists: int
    boosts: int
    damage_dealt: float = Field(alias="damageDealt")
    # alive | byplayer | byzone | suicide | logout
    death_type: str = Field(alias="deathType")
    headshot_kills: int = Field(alias="headshotKills")
    heals: int
    # Rank among participants by kills. Observed up to 107 — it is NOT bounded
    # by 100, so no ge/le constraint here.
    kill_place: int = Field(alias="killPlace")
    kill_streaks: int = Field(alias="killStreaks")
    kills: int
    longest_kill: float = Field(alias="longestKill")
    name: str
    # "account.<hex>" for humans, "ai.<n>" for bots (unique only within a match).
    player_id: str = Field(alias="playerId")
    revives: int
    ride_distance: float = Field(alias="rideDistance")
    road_kills: int = Field(alias="roadKills")
    swim_distance: float = Field(alias="swimDistance")
    team_kills: int = Field(alias="teamKills")
    time_survived: float = Field(alias="timeSurvived")
    vehicle_destroys: int = Field(alias="vehicleDestroys")
    walk_distance: float = Field(alias="walkDistance")
    weapons_acquired: int = Field(alias="weaponsAcquired")
    win_place: int = Field(alias="winPlace")

    @property
    def is_bot(self) -> bool:
        """Bots use ``ai.<n>`` account ids; telemetry corroborates with
        ``character.type == "user_ai"``."""
        return self.player_id.startswith(BOT_ACCOUNT_PREFIX)


class ParticipantAttributes(PubgModel):
    stats: ParticipantStats
    # Both live on `attributes`, not on `attributes.stats`. `actor` is "".
    actor: str | None = None
    shard_id: str | None = Field(default=None, alias="shardId")


class Participant(PubgModel):
    type: str = "participant"
    # A per-match UUID, NOT the account id. Rosters reference participants by
    # this id, so it is the only join key between a player and their team.
    id: str
    attributes: ParticipantAttributes

    @property
    def stats(self) -> ParticipantStats:
        return self.attributes.stats

    @property
    def account_id(self) -> str:
        return self.attributes.stats.player_id

    @property
    def name(self) -> str:
        return self.attributes.stats.name

    @property
    def is_bot(self) -> bool:
        return self.attributes.stats.is_bot


class RosterStats(PubgModel):
    rank: int
    # Unique per match across all 61 archived matches — safe as part of a
    # (match_id, team_id) primary key.
    team_id: int = Field(alias="teamId")


class RosterRelationships(PubgModel):
    participants: ResourceRefList = Field(default_factory=ResourceRefList)


class RosterAttributes(PubgModel):
    stats: RosterStats
    won: bool = False
    shard_id: str | None = Field(default=None, alias="shardId")

    @field_validator("won", mode="before")
    @classmethod
    def _parse_won(cls, value: object) -> bool:
        # PUBG sends the STRING "true"/"false". bool("false") is True, so a
        # truthiness check marks every single roster in the match a winner.
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() == "true"


class Roster(PubgModel):
    type: str = "roster"
    # Random UUID, meaningful only inside this one match response.
    id: str
    attributes: RosterAttributes
    relationships: RosterRelationships = Field(default_factory=RosterRelationships)

    @property
    def team_id(self) -> int:
        return self.attributes.stats.team_id

    @property
    def rank(self) -> int:
        return self.attributes.stats.rank

    @property
    def won(self) -> bool:
        return self.attributes.won

    @property
    def participant_ids(self) -> list[str]:
        return self.relationships.participants.ids


class AssetAttributes(PubgModel):
    name: str = ""
    description: str = ""
    created_at: dt.datetime | None = Field(default=None, alias="createdAt")
    # 🔴 Uppercase `URL` in every real payload. `url` is the defensive fallback
    # for the day PUBG normalises it.
    url: str | None = Field(default=None, validation_alias=AliasChoices("URL", "url"))


class Asset(PubgModel):
    type: str = "asset"
    id: str
    attributes: AssetAttributes = Field(default_factory=AssetAttributes)


class MatchResponse(PubgModel):
    """``GET /shards/{shard}/matches/{id}``.

    ``included[]`` arrives interleaved — participants, rosters and the telemetry
    asset in arbitrary order — so it is partitioned by ``type`` at validation
    time into three typed lists. Unknown resource types are dropped rather than
    raising, so a future ``team`` or ``clan`` entry cannot break ingestion.
    """

    data: MatchData
    participants: list[Participant] = Field(default_factory=list)
    rosters: list[Roster] = Field(default_factory=list)
    assets: list[Asset] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _partition_included(cls, value: object) -> object:
        if not isinstance(value, dict) or "included" not in value:
            return value
        payload = dict(value)
        included = payload.pop("included") or []
        buckets: dict[str, list[Any]] = {"participant": [], "roster": [], "asset": []}
        for item in included:
            if isinstance(item, dict):
                bucket = buckets.get(str(item.get("type")))
                if bucket is not None:
                    bucket.append(item)
        payload["participants"] = buckets["participant"]
        payload["rosters"] = buckets["roster"]
        payload["assets"] = buckets["asset"]
        return payload

    # -- convenience ------------------------------------------------------
    @property
    def match_id(self) -> str:
        return self.data.id

    @property
    def attributes(self) -> MatchAttributes:
        return self.data.attributes

    @property
    def is_official(self) -> bool:
        """Only 'official' matches count toward career stats (project decision)."""
        return self.data.attributes.match_type == OFFICIAL_MATCH_TYPE

    @property
    def telemetry_url(self) -> str | None:
        """The telemetry event-stream URL, or None if the asset is gone.

        Prefers the asset literally named "telemetry" (matched case-insensitively
        — the schema's description text says "Telemetry", payloads say
        "telemetry"), and falls back to the sole asset, since every observed
        match carries exactly one.
        """
        named = [a for a in self.assets if a.attributes.name.lower() == "telemetry"]
        candidates = named or self.assets
        for asset in candidates:
            if asset.attributes.url:
                return asset.attributes.url
        return None

    @property
    def participants_by_id(self) -> dict[str, Participant]:
        """Participant UUID -> participant. The map rosters resolve through."""
        return {p.id: p for p in self.participants}

    def roster_membership(self) -> dict[str, Roster]:
        """Participant UUID -> its roster.

        `teamId`, `rank` and `won` live on the roster, never on the participant.
        Reading them off ``participant.attributes.stats`` yields silent NULLs.
        """
        return {pid: roster for roster in self.rosters for pid in roster.participant_ids}


# ---------------------------------------------------------------------------
# Seasons
# ---------------------------------------------------------------------------
class SeasonAttributes(PubgModel):
    is_current_season: bool = Field(default=False, alias="isCurrentSeason")
    is_offseason: bool = Field(default=False, alias="isOffseason")


class Season(PubgModel):
    type: str = "season"
    id: str  # e.g. "division.bro.official.pc-2018-01"
    attributes: SeasonAttributes = Field(default_factory=SeasonAttributes)


class SeasonsResponse(PubgModel):
    data: list[Season] = Field(default_factory=list)

    @property
    def current(self) -> Season | None:
        """The live season, or None during the gap when PUBG marks none current."""
        return next((s for s in self.data if s.attributes.is_current_season), None)


class GameModeStats(PubgModel):
    """One entry of ``gameModeStats`` (season or lifetime).

    Unlike participant stats these are *not* strict: PUBG keeps deprecated
    members (killPoints, winPoints, rankPoints, rankPointsTitle) around and adds
    new ones, so everything defaults and unknown keys land in ``model_extra``.
    """

    assists: int = 0
    boosts: int = 0
    # 🔴 lowercase 'd' here; the participant-stats spelling is `DBNOs`.
    dbnos: int = Field(default=0, alias="dBNOs")
    daily_kills: int = Field(default=0, alias="dailyKills")
    daily_wins: int = Field(default=0, alias="dailyWins")
    damage_dealt: float = Field(default=0.0, alias="damageDealt")
    days: int = 0
    headshot_kills: int = Field(default=0, alias="headshotKills")
    heals: int = 0
    kills: int = 0
    longest_kill: float = Field(default=0.0, alias="longestKill")
    longest_time_survived: float = Field(default=0.0, alias="longestTimeSurvived")
    losses: int = 0
    max_kill_streaks: int = Field(default=0, alias="maxKillStreaks")
    most_survival_time: float = Field(default=0.0, alias="mostSurvivalTime")
    revives: int = 0
    ride_distance: float = Field(default=0.0, alias="rideDistance")
    road_kills: int = Field(default=0, alias="roadKills")
    round_most_kills: int = Field(default=0, alias="roundMostKills")
    rounds_played: int = Field(default=0, alias="roundsPlayed")
    suicides: int = 0
    swim_distance: float = Field(default=0.0, alias="swimDistance")
    team_kills: int = Field(default=0, alias="teamKills")
    time_survived: float = Field(default=0.0, alias="timeSurvived")
    top10s: int = Field(default=0, alias="top10s")
    vehicle_destroys: int = Field(default=0, alias="vehicleDestroys")
    walk_distance: float = Field(default=0.0, alias="walkDistance")
    weapons_acquired: int = Field(default=0, alias="weaponsAcquired")
    weekly_kills: int = Field(default=0, alias="weeklyKills")
    weekly_wins: int = Field(default=0, alias="weeklyWins")
    wins: int = 0


class PlayerSeasonAttributes(PubgModel):
    best_rank_point: float | None = Field(default=None, alias="bestRankPoint")
    game_mode_stats: dict[str, GameModeStats] = Field(
        default_factory=dict, alias="gameModeStats"
    )


class PlayerSeasonData(PubgModel):
    # "playerSeason" for a season, "lifetime" for the lifetime endpoint.
    type: str = "playerSeason"
    # 🔴 Optional on purpose: playerSeason payloads carry NO `id`. A generic
    # JSON:API model that requires one throws on every season fetch.
    id: str | None = None
    attributes: PlayerSeasonAttributes = Field(default_factory=PlayerSeasonAttributes)
    # Relationship keys are camelCase with uppercase FPP (`matchesSquadFPP`) and
    # do not match the hyphenated gameModeStats keys (`squad-fpp`). Left raw
    # rather than mapped, so nobody is tempted to join them by name.
    relationships: dict[str, Any] = Field(default_factory=dict)


class PlayerSeasonResponse(PubgModel):
    data: PlayerSeasonData

    @property
    def game_mode_stats(self) -> dict[str, GameModeStats]:
        return self.data.attributes.game_mode_stats


# ---------------------------------------------------------------------------
# Weapon mastery
# ---------------------------------------------------------------------------
class WeaponSummary(PubgModel):
    """One ``weaponSummaries`` entry, keyed by ``Item_Weapon_*_C``.

    The stat blocks are left as plain dicts: their members differ between the
    three blocks (StatsTotal uses ``LongestDefeat``, the 18.2+ blocks use
    ``LongestKill``) and PUBG adds more. Nothing downstream needs them typed.
    """

    # 🔴 PascalCase — the only corner of the API that uses it.
    xp_total: int = Field(default=0, alias="XPTotal")
    level_current: int = Field(default=0, alias="LevelCurrent")
    tier_current: int = Field(default=0, alias="TierCurrent")
    # Frozen since patch 18.2; kept because historical totals still live here.
    stats_total: dict[str, float] = Field(default_factory=dict, alias="StatsTotal")
    official_stats_total: dict[str, float] = Field(
        default_factory=dict, alias="OfficialStatsTotal"
    )
    competitive_stats_total: dict[str, float] = Field(
        default_factory=dict, alias="CompetitiveStatsTotal"
    )
    # Deprecated as of v22.0.0.
    medals: list[dict[str, Any]] = Field(default_factory=list, alias="Medals")


class WeaponMasteryAttributes(PubgModel):
    platform: str | None = None
    # Present in real payloads, absent from PUBG's own schema.
    season_id: str | None = Field(default=None, alias="seasonId")
    latest_match_id: str | None = Field(default=None, alias="latestMatchId")
    weapon_summaries: dict[str, WeaponSummary] = Field(
        default_factory=dict, alias="weaponSummaries"
    )


class WeaponMasteryData(PubgModel):
    type: str = "weaponMasterySummary"
    id: str | None = None
    attributes: WeaponMasteryAttributes = Field(default_factory=WeaponMasteryAttributes)


class WeaponMasteryResponse(PubgModel):
    data: WeaponMasteryData

    @property
    def weapon_summaries(self) -> dict[str, WeaponSummary]:
        return self.data.attributes.weapon_summaries
