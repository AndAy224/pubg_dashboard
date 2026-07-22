"""Parse the whole archived corpus through `pubg_dashboard.pubg.schemas`.

This is the highest-value module in the suite. Every other test exercises code
we wrote against inputs we invented; this one runs the real models over 61 real
`GET /matches/{id}` responses covering every game mode and match type we have
ever seen, and checks the four things the PUBG API has actually burned us on:

1. participant stats are **exactly** 23 fields — the seven that every blog post
   and half the client libraries still list were deleted by PUBG;
2. `roster.attributes.won` is the *string* `"true"`/`"false"`, and `bool("false")`
   is `True`;
3. bots (`accountId` prefix `ai.`) are ~20% of participants and up to 95% of a
   single TPP squad lobby, so "just filter them later" is not viable;
4. the telemetry asset URL lives under the uppercase key `URL`.

The parametrised tests name the offending match uuid on failure, which matters
when one match out of 61 has a field the others do not.
"""

from __future__ import annotations

import copy
import datetime as dt
from typing import Any

import pytest

from pubg_dashboard.pubg.schemas import MatchResponse, ParticipantStats

# ---------------------------------------------------------------------------
# Ground truth, restated here on purpose.
#
# These maps are the *test's* independent copy of the wire format. They are
# duplicated from the schema module deliberately: a test that derives its
# expectations from the code under test cannot catch a rename in that code.
# ---------------------------------------------------------------------------

# python attribute on ParticipantStats -> raw key in `attributes.stats`.
# Attribute names mirror the columns in db/models.py::Participant one for one.
STAT_FIELDS: dict[str, str] = {
    "dbnos": "DBNOs",  # not `DBNOS`, not `dbnos` — PUBG's own casing is irregular
    "assists": "assists",
    "boosts": "boosts",
    "damage_dealt": "damageDealt",
    "death_type": "deathType",
    "headshot_kills": "headshotKills",
    "heals": "heals",
    "kill_place": "killPlace",
    "kill_streaks": "killStreaks",
    "kills": "kills",
    "longest_kill": "longestKill",
    "name": "name",
    "player_id": "playerId",  # the account id; `id` on the participant is a per-match uuid
    "revives": "revives",
    "ride_distance": "rideDistance",
    "road_kills": "roadKills",
    "swim_distance": "swimDistance",
    "team_kills": "teamKills",
    "time_survived": "timeSurvived",
    "vehicle_destroys": "vehicleDestroys",
    "walk_distance": "walkDistance",
    "weapons_acquired": "weaponsAcquired",
    "win_place": "winPlace",
}
RAW_STAT_KEYS = frozenset(STAT_FIELDS.values())

# Removed by PUBG, still documented all over the internet. If one of these ever
# shows up again it is a schema change worth a migration, not something to
# quietly absorb.
DEAD_STAT_KEYS = frozenset(
    {
        "killPoints",
        "winPoints",
        "rankPoints",
        "rankPointsTitle",
        "killPlacePoints",
        "winPlacePoints",
        "mostDamage",
    }
)

OBSERVED_MATCH_TYPES = frozenset({"official", "airoyale", "tutorialatoz"})
OBSERVED_DEATH_TYPES = frozenset({"alive", "byplayer", "byzone", "suicide", "logout"})
BOT_ACCOUNT_PREFIX = "ai."


# --- raw-payload accessors, independent of the code under test -------------
def raw_participants(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [i for i in payload["included"] if i["type"] == "participant"]


def raw_rosters(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [i for i in payload["included"] if i["type"] == "roster"]


def raw_assets(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [i for i in payload["included"] if i["type"] == "asset"]


# ===========================================================================
# The corpus-wide parse
# ===========================================================================
def test_every_archived_match_parses(match_payload: dict[str, Any]) -> None:
    """Each of the 61 real responses validates, and the identity survives."""
    match = MatchResponse.model_validate(match_payload)

    assert match.match_id == match_payload["data"]["id"]
    assert len(match.participants) == len(raw_participants(match_payload))
    assert len(match.rosters) == len(raw_rosters(match_payload))


def test_match_attributes_round_trip(match_payload: dict[str, Any]) -> None:
    attrs = match_payload["data"]["attributes"]
    match = MatchResponse.model_validate(match_payload)
    a = match.attributes

    assert a.game_mode == attrs["gameMode"]
    assert a.map_name == attrs["mapName"]
    assert a.match_type == attrs["matchType"]
    assert a.is_custom_match == attrs["isCustomMatch"]
    assert a.duration == attrs["duration"]
    assert a.shard_id == attrs["shardId"]
    assert a.season_state == attrs["seasonState"]
    assert a.title_id == attrs["titleId"]

    # `createdAt` is Zulu on the wire and the DB column is timestamptz; a naive
    # datetime here would be silently reinterpreted as local time on insert.
    assert a.created_at.tzinfo is not None
    assert a.created_at.utcoffset() == dt.timedelta(0)


# ===========================================================================
# The 23 stat fields
# ===========================================================================
def test_wire_carries_exactly_the_23_known_stats(match_payload: dict[str, Any]) -> None:
    """Guards the corpus itself: if PUBG adds a field, this is where we find out."""
    for participant in raw_participants(match_payload):
        stats = participant["attributes"]["stats"]
        assert set(stats) == RAW_STAT_KEYS, (
            f"participant {participant['id']} stat keys drifted; "
            f"unexpected={sorted(set(stats) - RAW_STAT_KEYS)} "
            f"missing={sorted(RAW_STAT_KEYS - set(stats))}"
        )
        assert not (DEAD_STAT_KEYS & set(stats))


def test_model_maps_every_stat_field_and_no_extras() -> None:
    """The model's alias set must equal the wire's key set — both directions.

    Catches a dropped field (data silently lost on ingest) *and* a resurrected
    dead field (a column that would be permanently NULL).
    """
    fields = ParticipantStats.model_fields
    assert len(fields) == 23, f"expected 23 stat fields, got {len(fields)}: {sorted(fields)}"

    # pydantic v2 fills `alias` whether it was set explicitly or by an
    # alias_generator, so this works either way.
    mapped = {name: (f.alias or name) for name, f in fields.items()}
    assert mapped == STAT_FIELDS
    assert not (DEAD_STAT_KEYS & set(fields))


def test_stat_values_are_not_transposed(match_payload: dict[str, Any]) -> None:
    """Every parsed value equals its raw counterpart, for every participant.

    An alias typo that swaps `walkDistance` and `rideDistance` parses cleanly,
    validates cleanly, and produces plausible-looking numbers forever. Only a
    field-by-field comparison against the raw payload catches it.
    """
    match = MatchResponse.model_validate(match_payload)
    by_id = {p.id: p for p in match.participants}

    for raw in raw_participants(match_payload):
        stats = by_id[raw["id"]].stats
        raw_stats = raw["attributes"]["stats"]
        for attr, key in STAT_FIELDS.items():
            got = getattr(stats, attr)
            assert got == raw_stats[key], (
                f"{raw['id']}.{attr} == {got!r} but wire {key} == {raw_stats[key]!r}"
            )


def test_kill_place_above_100_is_accepted(all_match_payloads: list[dict[str, Any]]) -> None:
    """`killPlace` is a rank among participants and PUBG has emitted 107.

    A `le=100` constraint (an easy, wrong-looking-right thing to add) would
    reject real matches outright.
    """
    high = [
        p["attributes"]["stats"]["killPlace"]
        for payload in all_match_payloads
        for p in raw_participants(payload)
        if p["attributes"]["stats"]["killPlace"] > 100
    ]
    assert high, "corpus no longer contains a killPlace > 100 — weaken this test, not the model"

    for payload in all_match_payloads:
        MatchResponse.model_validate(payload)  # would raise on a le=100 constraint


# ===========================================================================
# `won` — the bool("false") trap
# ===========================================================================
def test_won_is_a_real_bool_not_a_truthy_string(match_payload: dict[str, Any]) -> None:
    match = MatchResponse.model_validate(match_payload)
    by_id = {r.id: r for r in match.rosters}

    for raw in raw_rosters(match_payload):
        raw_won = raw["attributes"]["won"]
        # Restating the wire fact: it is a JSON string, never a JSON boolean.
        assert isinstance(raw_won, str), f"roster {raw['id']}.won is {type(raw_won).__name__}"

        won = by_id[raw["id"]].won
        assert won is True or won is False, f"won parsed to {won!r} ({type(won).__name__})"
        assert won == (raw_won == "true")


def test_losing_rosters_do_not_all_win(all_match_payloads: list[dict[str, Any]]) -> None:
    """The regression `bool("false") is True` would make every roster a winner.

    Asserted at corpus scale because a single match cannot distinguish "parsed
    correctly" from "happened to have one roster".
    """
    won_count = 0
    total = 0
    for payload in all_match_payloads:
        match = MatchResponse.model_validate(payload)
        for roster in match.rosters:
            total += 1
            won_count += roster.won

    assert total > 100
    # 61 matches -> at most 61 winning rosters. `bool("false")` would give `total`.
    assert won_count < total / 10, f"{won_count}/{total} rosters won — `won` is being coerced"


def test_won_true_roster_is_rank_one(all_match_payloads: list[dict[str, Any]]) -> None:
    """Cross-check the parse against an independent invariant of the data."""
    for payload in all_match_payloads:
        for roster in MatchResponse.model_validate(payload).rosters:
            if roster.won:
                assert roster.stats.rank == 1


# ===========================================================================
# Bots
# ===========================================================================
def test_bots_detected_by_account_prefix(match_payload: dict[str, Any]) -> None:
    match = MatchResponse.model_validate(match_payload)
    for participant in match.participants:
        expected = participant.stats.player_id.startswith(BOT_ACCOUNT_PREFIX)
        assert participant.is_bot is expected, (
            f"{participant.stats.player_id} -> is_bot={participant.is_bot}"
        )


def test_corpus_bot_share_is_substantial(all_match_payloads: list[dict[str, Any]]) -> None:
    """Bots are ~20% overall and can be >90% of a TPP squad lobby.

    If this ever collapses toward zero the detection rule broke, not PUBG's
    matchmaking — and every "kills" figure on the site becomes a lie.
    """
    per_match_ratio: list[float] = []
    bots = humans = 0
    for payload in all_match_payloads:
        match = MatchResponse.model_validate(payload)
        n_bot = sum(p.is_bot for p in match.participants)
        bots += n_bot
        humans += len(match.participants) - n_bot
        per_match_ratio.append(n_bot / len(match.participants))

    assert 0.10 < bots / (bots + humans) < 0.40  # observed 20.2%
    assert max(per_match_ratio) > 0.85  # observed 94.9% in one squad-fpp lobby


def test_telemetry_agrees_with_the_ai_prefix(
    telemetry_events: list[dict[str, Any]],
    telemetry_match_id: str,
    all_match_payloads: list[dict[str, Any]],
) -> None:
    """`accountId` prefix and telemetry `character.type` are two views of one fact.

    Telemetry labels bots `user_ai`; the match endpoint only gives us the `ai.`
    prefix. Persisting `is_bot` from the prefix is only safe because the two
    agree, so pin that here rather than assuming it.
    """
    actor_keys = ("character", "attacker", "victim", "killer", "finisher", "dBNOMaker")
    seen: dict[str, str] = {}
    for event in telemetry_events:
        for key in actor_keys:
            actor = event.get(key)
            if isinstance(actor, dict) and "accountId" in actor:
                seen[actor["accountId"]] = actor.get("type", "")

    for account_id, kind in seen.items():
        if not account_id:
            continue  # world/environment actors carry an empty accountId
        assert account_id.startswith(BOT_ACCOUNT_PREFIX) == (kind == "user_ai"), (
            f"{account_id!r} has telemetry type {kind!r}"
        )

    payload = next(p for p in all_match_payloads if p["data"]["id"] == telemetry_match_id)
    match = MatchResponse.model_validate(payload)
    # Every scoreboard participant must appear in telemetry; the reverse does
    # not hold (telemetry also names spectators and the empty world actor).
    assert {p.stats.player_id for p in match.participants} <= set(seen)


# ===========================================================================
# Telemetry asset URL — uppercase `URL`
# ===========================================================================
def test_telemetry_url_read_from_uppercase_key(match_payload: dict[str, Any]) -> None:
    assets = raw_assets(match_payload)
    assert assets, "every archived match carries exactly one telemetry asset"
    expected = assets[0]["attributes"]["URL"]  # uppercase — `url` is absent on the wire

    match = MatchResponse.model_validate(match_payload)
    assert match.telemetry_url == expected
    assert match.telemetry_url.startswith("https://")


def test_telemetry_url_falls_back_to_lowercase(real_match_payload: dict[str, Any]) -> None:
    """Defensive fallback, kept because the casing is undocumented and odd.

    PUBG ships `URL`; nothing guarantees they will not normalise it one patch.
    """
    payload = copy.deepcopy(real_match_payload)
    asset = next(i for i in payload["included"] if i["type"] == "asset")
    asset["attributes"]["url"] = asset["attributes"].pop("URL")

    assert MatchResponse.model_validate(payload).telemetry_url == asset["attributes"]["url"]


def test_missing_asset_is_none_not_an_error(real_match_payload: dict[str, Any]) -> None:
    """A match with no telemetry must still parse.

    Telemetry ages out after ~14 days, and the fetcher — not the parser — is
    what decides that is a problem (`TelemetryUnavailable`).
    """
    payload = copy.deepcopy(real_match_payload)
    payload["included"] = [i for i in payload["included"] if i["type"] != "asset"]
    payload["data"]["relationships"].pop("assets", None)

    assert MatchResponse.model_validate(payload).telemetry_url is None


# ===========================================================================
# Rosters <-> participants
# ===========================================================================
def test_team_id_is_unique_within_a_match(match_payload: dict[str, Any]) -> None:
    """`(match_id, team_id)` is the roster PK in db/models.py.

    Verified unique across all 61 matches; if PUBG ever repeats a teamId the
    insert fails on a constraint at 3am instead of here.
    """
    team_ids = [r.stats.team_id for r in MatchResponse.model_validate(match_payload).rosters]
    assert len(team_ids) == len(set(team_ids))


def test_every_participant_belongs_to_exactly_one_roster(match_payload: dict[str, Any]) -> None:
    """Participants get their `team_id` through the roster, never directly.

    `attributes.stats` has no teamId — the only link is
    `roster.relationships.participants.data[]`, so an orphan participant would
    become a row with no team.
    """
    match = MatchResponse.model_validate(match_payload)

    owners: dict[str, int] = {}
    for roster in match.rosters:
        for pid in roster.participant_ids:
            assert pid not in owners, f"participant {pid} listed by two rosters"
            owners[pid] = roster.stats.team_id

    assert set(owners) == {p.id for p in match.participants}


def test_enum_like_values_stay_within_the_observed_sets(
    all_match_payloads: list[dict[str, Any]],
) -> None:
    """`match_type` and `death_type` are stored as text, not DB enums.

    That is a deliberate choice (a new PUBG mode must not need a migration), so
    this test is an early-warning tripwire, not a constraint.
    """
    match_types: set[str] = set()
    death_types: set[str] = set()
    for payload in all_match_payloads:
        match = MatchResponse.model_validate(payload)
        match_types.add(match.attributes.match_type)
        death_types.update(p.stats.death_type for p in match.participants)

    assert match_types <= OBSERVED_MATCH_TYPES, f"new matchType: {match_types - OBSERVED_MATCH_TYPES}"
    assert death_types <= OBSERVED_DEATH_TYPES, f"new deathType: {death_types - OBSERVED_DEATH_TYPES}"
    # Only `official` counts toward career stats, so the split has to be real.
    assert "official" in match_types


def test_event_sample_types_are_self_consistent(event_samples: dict[str, dict[str, Any]]) -> None:
    """Cheap guard on the fixture the telemetry parser will be built against."""
    assert len(event_samples) >= 40
    for name, event in event_samples.items():
        assert event["_T"] == name
        assert event["_D"].endswith("Z")  # Zulu, sub-second precision


@pytest.mark.parametrize("bad", ["ai", "account.ai.123", "AI.7", ""])
def test_bot_prefix_is_not_a_substring_match(bad: str, real_match_payload: dict[str, Any]) -> None:
    """`is_bot` must be a prefix test on `ai.`, not `"ai" in account_id`.

    Real account ids are hex, but `"ai" in x` would still be a coin flip, and
    misclassifying a human as a bot removes them from every stat surface.
    """
    payload = copy.deepcopy(real_match_payload)
    participant = next(i for i in payload["included"] if i["type"] == "participant")
    participant["attributes"]["stats"]["playerId"] = bad

    match = MatchResponse.model_validate(payload)
    parsed = next(p for p in match.participants if p.id == participant["id"])
    assert parsed.is_bot is False
