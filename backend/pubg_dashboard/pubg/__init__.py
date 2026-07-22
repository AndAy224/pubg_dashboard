"""PUBG API client layer.

Everything that talks to `api.pubg.com` or the telemetry CDN lives here, and
nothing else in the project should construct an HTTP request to PUBG.

The one fact worth carrying out of this package: **only keyed endpoints cost
quota.** `/players`, `/seasons`, season stats and weapon mastery are limited
(10/min by default); `/matches/{id}` and the telemetry CDN are free and
unauthenticated. :class:`PubgClient` enforces that split — see
`client.py` and `ratelimit.py` for the reasoning.
"""

from __future__ import annotations

from pubg_dashboard.pubg.client import BASE_URL, PLAYER_BATCH_SIZE, PubgClient
from pubg_dashboard.pubg.errors import (
    PlayerNotFound,
    PubgApiError,
    PubgServerError,
    RateLimited,
    TelemetryUnavailable,
)
from pubg_dashboard.pubg.ratelimit import TokenBucket, key_fingerprint, shared_bucket
from pubg_dashboard.pubg.schemas import (
    Asset,
    ErrorResponse,
    GameModeStats,
    MatchResponse,
    Participant,
    ParticipantStats,
    Player,
    PlayerSeasonResponse,
    PlayersResponse,
    Roster,
    Season,
    SeasonsResponse,
    WeaponMasteryResponse,
    WeaponSummary,
)

__all__ = [
    "BASE_URL",
    "PLAYER_BATCH_SIZE",
    "Asset",
    "ErrorResponse",
    "GameModeStats",
    "MatchResponse",
    "Participant",
    "ParticipantStats",
    "Player",
    "PlayerNotFound",
    "PlayerSeasonResponse",
    "PlayersResponse",
    "PubgApiError",
    "PubgClient",
    "PubgServerError",
    "RateLimited",
    "Roster",
    "Season",
    "SeasonsResponse",
    "TelemetryUnavailable",
    "TokenBucket",
    "WeaponMasteryResponse",
    "WeaponSummary",
    "key_fingerprint",
    "shared_bucket",
]
