"""Event-name constants and the accessors for PUBG's inconsistent shapes.

Every name here is spelled as it appears **on the wire**, taken from the 47
event types in `docs/reference/telemetry-observed-schema.md`, not from PUBG's
documentation. Where the two differ the wire wins and the difference is noted.

Dispatch through `norm()` (lowercase) rather than comparing these constants
directly, so a casing change in a future patch degrades to "unknown event
counted at INFO" instead of "feature silently stopped working".
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from pubg_dashboard.telemetry.reader import norm

# --- match lifecycle -------------------------------------------------------
MATCH_DEFINITION: Final = "LogMatchDefinition"
MATCH_START: Final = "LogMatchStart"
MATCH_END: Final = "LogMatchEnd"

# --- player ----------------------------------------------------------------
PLAYER_CREATE: Final = "LogPlayerCreate"
PLAYER_POSITION: Final = "LogPlayerPosition"
PLAYER_LOGIN: Final = "LogPlayerLogin"
PLAYER_LOGOUT: Final = "LogPlayerLogout"
PLAYER_ATTACK: Final = "LogPlayerAttack"
PLAYER_TAKE_DAMAGE: Final = "LogPlayerTakeDamage"
PLAYER_KILL_V2: Final = "LogPlayerKillV2"
PLAYER_KILL_V1: Final = "LogPlayerKill"  # pre-v21; kept as a fallback branch
PLAYER_MAKE_GROGGY: Final = "LogPlayerMakeGroggy"
PLAYER_REVIVE: Final = "LogPlayerRevive"
PLAYER_USE_THROWABLE: Final = "LogPlayerUseThrowable"
PLAYER_USE_FLARE_GUN: Final = "LogPlayerUseFlareGun"
PLAYER_DESTROY_PROP: Final = "LogPlayerDestroyProp"
PARACHUTE_LANDING: Final = "LogParachuteLanding"
ARMOR_DESTROY: Final = "LogArmorDestroy"
HEAL: Final = "LogHeal"
SWIM_START: Final = "LogSwimStart"
SWIM_END: Final = "LogSwimEnd"
VAULT_START: Final = "LogVaultStart"
CHARACTER_CARRY: Final = "LogCharacterCarry"
WEAPON_FIRE_COUNT: Final = "LogWeaponFireCount"

# --- items -----------------------------------------------------------------
ITEM_PICKUP: Final = "LogItemPickup"
# Capital B. PUBG's docs say `...Lootbox`; the wire says `...LootBox`, 26k times.
ITEM_PICKUP_FROM_LOOTBOX: Final = "LogItemPickupFromLootBox"
# "Carepackage", one word, lowercase p — not "CarePackage".
ITEM_PICKUP_FROM_CAREPACKAGE: Final = "LogItemPickupFromCarepackage"
ITEM_PICKUP_FROM_VEHICLE_TRUNK: Final = "LogItemPickupFromVehicleTrunk"
ITEM_PUT_TO_VEHICLE_TRUNK: Final = "LogItemPutToVehicleTrunk"
ITEM_DROP: Final = "LogItemDrop"
ITEM_EQUIP: Final = "LogItemEquip"
ITEM_UNEQUIP: Final = "LogItemUnequip"
ITEM_ATTACH: Final = "LogItemAttach"
ITEM_DETACH: Final = "LogItemDetach"
ITEM_USE: Final = "LogItemUse"

# --- world -----------------------------------------------------------------
GAME_STATE_PERIODIC: Final = "LogGameStatePeriodic"
PHASE_CHANGE: Final = "LogPhaseChange"
CARE_PACKAGE_SPAWN: Final = "LogCarePackageSpawn"
CARE_PACKAGE_LAND: Final = "LogCarePackageLand"
VEHICLE_RIDE: Final = "LogVehicleRide"
VEHICLE_LEAVE: Final = "LogVehicleLeave"
VEHICLE_DAMAGE: Final = "LogVehicleDamage"
VEHICLE_DESTROY: Final = "LogVehicleDestroy"
WHEEL_DESTROY: Final = "LogWheelDestroy"
OBJECT_DESTROY: Final = "LogObjectDestroy"
OBJECT_INTERACTION: Final = "LogObjectInteraction"
EM_PICKUP_LIFT_OFF: Final = "LogEmPickupLiftOff"
RED_ZONE_ENDED: Final = "LogRedZoneEnded"
# 13,167 events in the corpus and in no official documentation whatsoever. An
# exhaustive `_T` switch that raises on unknown names dies on the first match.
SPECIAL_ZONE_IN_CHARACTERS: Final = "LogSpecialZoneInCharacters"

#: Every `_T` observed across the 65-match corpus, lowercased for dispatch.
KNOWN_EVENTS: Final[frozenset[str]] = frozenset(
    norm(name)
    for name in (
        MATCH_DEFINITION, MATCH_START, MATCH_END,
        PLAYER_CREATE, PLAYER_POSITION, PLAYER_LOGIN, PLAYER_LOGOUT,
        PLAYER_ATTACK, PLAYER_TAKE_DAMAGE, PLAYER_KILL_V2, PLAYER_KILL_V1,
        PLAYER_MAKE_GROGGY, PLAYER_REVIVE, PLAYER_USE_THROWABLE,
        PLAYER_USE_FLARE_GUN, PLAYER_DESTROY_PROP, PARACHUTE_LANDING,
        ARMOR_DESTROY, HEAL, SWIM_START, SWIM_END, VAULT_START,
        CHARACTER_CARRY, WEAPON_FIRE_COUNT,
        ITEM_PICKUP, ITEM_PICKUP_FROM_LOOTBOX, ITEM_PICKUP_FROM_CAREPACKAGE,
        ITEM_PICKUP_FROM_VEHICLE_TRUNK, ITEM_PUT_TO_VEHICLE_TRUNK, ITEM_DROP,
        ITEM_EQUIP, ITEM_UNEQUIP, ITEM_ATTACH, ITEM_DETACH, ITEM_USE,
        GAME_STATE_PERIODIC, PHASE_CHANGE, CARE_PACKAGE_SPAWN,
        CARE_PACKAGE_LAND, VEHICLE_RIDE, VEHICLE_LEAVE, VEHICLE_DAMAGE,
        VEHICLE_DESTROY, WHEEL_DESTROY, OBJECT_DESTROY, OBJECT_INTERACTION,
        EM_PICKUP_LIFT_OFF, RED_ZONE_ENDED, SPECIAL_ZONE_IN_CHARACTERS,
    )
)

# --- semantic constants ----------------------------------------------------

BOT_CHARACTER_TYPE: Final = "user_ai"
BOT_ACCOUNT_PREFIX: Final = "ai."

#: `common.isGame` while the aircraft is in the air.
#:
#: The wire value is 0.10000000149011612 — a 32-bit float widened to a double —
#: so `isGame == 0.1` is **never** true. This gates plane-phase detection and
#: the movement heatmap's flight-path filter, both of which fail silently and
#: plausibly when the comparison is exact.
PLANE_PHASE_IS_GAME: Final = 0.1
IS_GAME_TOLERANCE: Final = 1e-6

#: `isGame >= 1` means the match proper has begun.
IN_PLAY_IS_GAME: Final = 1.0


def is_plane_phase(is_game: float | int | None) -> bool:
    """True while players are still on the aircraft. Tolerance-compared."""
    if is_game is None:
        return False
    return abs(float(is_game) - PLANE_PHASE_IS_GAME) < IS_GAME_TOLERANCE


def is_in_play(is_game: float | int | None) -> bool:
    """True once the match proper is under way (excludes the plane phase)."""
    return is_game is not None and float(is_game) >= IN_PLAY_IS_GAME


def unwrap_character(obj: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    """Return the `Character` inside a possible `CharacterWrapper`.

    `LogMatchEnd.characters[]` wraps each character one level deeper on modern
    telemetry: reading `characters[i].ranking` raises `KeyError`, the value
    lives at `characters[i].character.ranking`. Older data is unwrapped. Both
    shapes reach here.
    """
    if not obj:
        return None
    inner = obj.get("character")
    return inner if isinstance(inner, Mapping) else obj


def is_bot(character: Mapping[str, Any] | None) -> bool:
    """Bot test, telemetry-first with an id-prefix fallback.

    `character.type == 'user_ai'` is authoritative and also catches a bot that
    PUBG hands a real-looking account id. The `ai.` prefix is the fallback for
    payloads with no character block.
    """
    if not character:
        return False
    if norm(str(character.get("type") or "")) == BOT_CHARACTER_TYPE:
        return True
    return str(character.get("accountId") or "").startswith(BOT_ACCOUNT_PREFIX)


def location(obj: Mapping[str, Any] | None) -> tuple[float, float, float]:
    """`(x, y, z)` in centimetres from anything carrying a `location`.

    Missing coordinates become 0.0 rather than raising: a single malformed
    event must not abort the match, and out-of-range values are clamped later
    at bin/quantise time anyway.
    """
    if not obj:
        return (0.0, 0.0, 0.0)
    loc = obj.get("location") or obj
    return (
        float(loc.get("x") or 0.0),
        float(loc.get("y") or 0.0),
        float(loc.get("z") or 0.0),
    )


def has_vehicle(vehicle: Mapping[str, Any] | None) -> bool:
    """True when a vehicle block describes a real vehicle.

    `victimVehicle` / `killerVehicle` are **zeroed sentinel objects** when the
    player is on foot, not `null`. Testing `is not None` marks every on-foot
    kill as a vehicle kill.
    """
    return bool(vehicle) and bool(str(vehicle.get("vehicleType") or ""))
