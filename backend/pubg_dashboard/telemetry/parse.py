"""Parse orchestrator: one raw telemetry file in, every derived output out.

Two passes over the event array, never more — a match is ~37k events and
several parse concurrently.

    pass 0 (prescan)  LogMatchStart      -> t0, mapName, teamSize, weather
                      LogPlayerCreate    -> roster (name, teamId, isBot)
                      LogItemPickup      -> pickup index (inventory rule 1)
                      LogPlayerKillV2    -> final death per account (rule 4)
    pass 1 (main)     frames | world | combat | inventory | heatmap
    finalise          LogMatchEnd        -> rankings, allWeaponStats
                      -> replay bundle, kill_events, heatmap bins,
                         participant telemetry columns

Both passes are required: the inventory state machine needs to know each
account's *final* death and whether a crate pickup has a plain twin before it
can process the first event, and neither is knowable in a single forward pass.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

import structlog

from pubg_dashboard.telemetry import events as E
from pubg_dashboard.telemetry.bundle import (
    PARSER_VERSION,
    Dictionary,
    ReplayBundle,
    choose_tick_ms,
    pack_u8,
    pack_u16,
    quantise,
    write_bundle,
    write_heat_ledger,
)
from pubg_dashboard.telemetry.combat import CombatTracker
from pubg_dashboard.telemetry.frames import FrameIndex
from pubg_dashboard.telemetry.heatmap import (
    KIND_DEATH,
    KIND_KILL,
    KIND_KNOCK,
    HeatmapAccumulator,
)
from pubg_dashboard.telemetry.inventory import InventoryTracker, PlayerInventory
from pubg_dashboard.telemetry.maps import world_size
from pubg_dashboard.telemetry.reader import load, norm, ts_ms
from pubg_dashboard.telemetry.strategy import compute_strategy
from pubg_dashboard.telemetry.world import WorldTracker

log = structlog.get_logger(__name__)

__all__ = ["ParseResult", "parse_telemetry"]


@dataclass(slots=True)
class MatchMeta:
    t0_ms: int = 0
    map_name: str = ""
    team_size: int = 0
    weather_id: str = ""
    camera_view: str = ""
    is_custom: bool = False


@dataclass(slots=True)
class PlayerRow:
    account_id: str
    name: str
    team_id: int
    is_bot: bool
    ranking: int = 0
    individual_ranking: int = 0


@dataclass(slots=True)
class ParseResult:
    """Everything one parse produces."""

    match_id: str
    parser_version: int
    meta: MatchMeta
    players: list[PlayerRow]
    bundle: bytes
    #: Server-side only — never shipped to the browser. See `write_heat_ledger`.
    heat_ledger: bytes
    kill_rows: list[dict[str, Any]]
    heatmap_rows: list[dict[str, Any]]
    participant_updates: list[dict[str, Any]]
    strategy_rows: list[dict[str, Any]]
    unknown_events: dict[str, int] = field(default_factory=dict)
    duration_ms: int = 0


def parse_telemetry(
    raw: bytes,
    *,
    match_id: str,
    shard: str = "steam",
    game_mode: str = "",
    match_type: str = "official",
    played_at: dt.datetime | None = None,
) -> ParseResult:
    """Parse one raw telemetry file into every derived output."""
    events = load(raw)
    meta, roster, unknown = _prescan(events)
    ws = world_size(meta.map_name)

    t0_s = meta.t0_ms / 1000.0
    frames = FrameIndex(meta.t0_ms, ws)
    world = WorldTracker(t0_s, ws)
    combat = CombatTracker(t0_s)
    inventory = InventoryTracker(meta.t0_ms)
    day = (played_at or dt.datetime.now(dt.UTC)).astimezone(dt.UTC).date()
    heat = HeatmapAccumulator(
        map_name=meta.map_name,
        game_mode=game_mode,
        match_type=match_type,
        day=day,
        world_size=ws,
    )

    for event in events:
        inventory.prescan(event)

    inv_state: dict[str, PlayerInventory] = {}
    last_ms = meta.t0_ms
    for event in events:
        frames.feed(event)
        world.feed(event)
        combat.feed(event)
        heat.feed(event)
        inventory.feed(event, inv_state)
        t = ts_ms(event.get("_D"))
        if t > last_ms:
            last_ms = t

    # Kill/death/knock bins come from the combat tracker rather than the raw
    # stream, so `kill_events` and the heatmap can never disagree about where
    # a kill happened.
    for k in combat.kills:
        heat.add(KIND_DEATH, k.victim_x, k.victim_y, k.victim_account_id)
        if k.killer_account_id and k.killer_x is not None and k.killer_y is not None:
            heat.add(KIND_KILL, k.killer_x, k.killer_y, k.killer_account_id)
    for knock in combat.knocks:
        heat.add(KIND_KNOCK, knock.victim_x, knock.victim_y,
                 knock.attacker_account_id or "")

    _apply_match_end(events, roster)

    # Deterministic across reparses: index `p` must mean the same player every
    # time, or a cached client bundle and a fresh one disagree.
    players = sorted(roster.values(), key=lambda p: (p.team_id, p.account_id))
    order = [p.account_id for p in players]
    index = {account: i for i, account in enumerate(order)}

    duration_ms = max(0, last_ms - meta.t0_ms)
    tick_ms = choose_tick_ms(duration_ms)

    dicts = {
        "items": Dictionary(),
        "weapons": Dictionary(),
        "dmgType": Dictionary(),
        "dmgReason": Dictionary(),
        "vehicles": Dictionary(),
    }

    bundle = ReplayBundle(
        match_id=match_id,
        shard=shard,
        map_name=meta.map_name,
        world_size=ws,
        t0_ms=meta.t0_ms,
        duration_ms=duration_ms,
        tick_ms=tick_ms,
        team_size=meta.team_size,
        weather_id=meta.weather_id,
        camera_view=meta.camera_view,
        players=[
            {
                "a": p.account_id,
                "n": p.name,
                "t": p.team_id,
                "b": p.is_bot,
                "r": p.ranking,
                "ir": p.individual_ranking,
                "c": p.team_id % 24,
            }
            for p in players
        ],
        pos=frames.build(order, tick_ms),
        events=_event_track(combat, world, index, dicts, ws, tick_ms),
        zones=_zone_track(world, ws, tick_ms),
        plane=_plane(world, ws),
        inv=_inventory_track(inventory, index, dicts["items"], meta.t0_ms, tick_ms),
        hits=_hit_track(combat, index, dicts, ws, tick_ms),
        dicts={name: d.values for name, d in dicts.items()},
    )

    result = ParseResult(
        match_id=match_id,
        parser_version=PARSER_VERSION,
        meta=meta,
        players=players,
        bundle=write_bundle(bundle),
        heat_ledger=write_heat_ledger(heat.deltas()),
        kill_rows=_kill_rows(match_id, combat),
        heatmap_rows=heat.rows(),
        participant_updates=_participant_updates(combat, frames, roster, meta.t0_ms),
        strategy_rows=compute_strategy(
            match_id=match_id,
            frames=frames,
            world=world,
            combat=combat,
            inventory=inventory,
            teams={a: r.team_id for a, r in roster.items()},
            t0_ms=meta.t0_ms,
        ),
        unknown_events=unknown,
        duration_ms=duration_ms,
    )
    log.info(
        "telemetry.parsed",
        match_id=match_id,
        events=len(events),
        players=len(players),
        kills=len(combat.kills),
        bundle_bytes=len(result.bundle),
        unknown_events=sum(unknown.values()),
    )
    return result


# ---------------------------------------------------------------------------
# pass 0
# ---------------------------------------------------------------------------
def _prescan(
    events: Sequence[Mapping[str, Any]],
) -> tuple[MatchMeta, dict[str, PlayerRow], dict[str, int]]:
    meta = MatchMeta()
    roster: dict[str, PlayerRow] = {}
    unknown: dict[str, int] = {}
    seen_start = False

    for event in events:
        kind = norm(event.get("_T", ""))
        if kind not in E.KNOWN_EVENTS:
            # Counted and reported, never raised: LogSpecialZoneInCharacters
            # has 13,167 occurrences and appears in no documentation at all.
            name = str(event.get("_T", "?"))
            unknown[name] = unknown.get(name, 0) + 1
            continue

        if kind == norm(E.MATCH_START) and not seen_start:
            seen_start = True
            meta.t0_ms = ts_ms(event.get("_D"))
            meta.map_name = str(event.get("mapName") or "")
            meta.team_size = int(event.get("teamSize") or 0)
            meta.weather_id = str(event.get("weatherId") or "")
            meta.camera_view = str(event.get("cameraViewBehaviour") or "")
            meta.is_custom = bool(event.get("isCustomGame"))
            for wrapper in event.get("characters") or []:
                _add_player(roster, E.unwrap_character(wrapper))

        elif kind == norm(E.PLAYER_CREATE):
            _add_player(roster, event.get("character"))

    if not meta.map_name:
        # LogMatchStart is present in 65/65 archived matches, but a truncated
        # download would leave the whole parse silently scaled to the wrong map.
        log.warning("telemetry.no_match_start", note="falling back to defaults")
    return meta, roster, unknown


def _add_player(roster: dict[str, PlayerRow], character: Mapping[str, Any] | None) -> None:
    if not character:
        return
    account = str(character.get("accountId") or "")
    if not account or account in roster:
        return
    roster[account] = PlayerRow(
        account_id=account,
        name=str(character.get("name") or account),
        team_id=int(character.get("teamId") or 0),
        is_bot=E.is_bot(character),
    )


def _apply_match_end(
    events: Sequence[Mapping[str, Any]], roster: dict[str, PlayerRow]
) -> None:
    """Final rankings from `LogMatchEnd.characters[]`.

    **Not** `gameResultOnFinished.results[]` — that holds the winning team
    only (~4 of 98 players), so using it as a scoreboard silently drops 96% of
    the lobby. And each entry is a `CharacterWrapper`: reading
    `characters[i].ranking` raises KeyError on modern telemetry.
    """
    for event in events:
        if norm(event.get("_T", "")) != norm(E.MATCH_END):
            continue
        for wrapper in event.get("characters") or []:
            character = E.unwrap_character(wrapper)
            if not character:
                continue
            account = str(character.get("accountId") or "")
            row = roster.get(account)
            if row is None:
                _add_player(roster, character)
                row = roster.get(account)
            if row is not None:
                row.ranking = int(character.get("ranking") or 0)
                row.individual_ranking = int(character.get("individualRanking") or 0)


# ---------------------------------------------------------------------------
# bundle sections
# ---------------------------------------------------------------------------
def _tick(t_s: float, tick_ms: int) -> int:
    v = int(t_s * 1000.0 / tick_ms)
    return 0 if v < 0 else min(v, 65_535)


def _event_track(
    combat: CombatTracker,
    world: WorldTracker,
    index: Mapping[str, int],
    dicts: Mapping[str, Dictionary],
    ws: int,
    tick_ms: int,
) -> list[dict[str, Any]]:
    """A few hundred entries, so plain maps — readability beats 4 KB here."""
    from pubg_dashboard.telemetry.bundle import NULL_PLAYER

    def p(account: str | None) -> int:
        return NULL_PLAYER if not account else index.get(account, NULL_PLAYER)

    out: list[dict[str, Any]] = []
    for k in combat.kills:
        out.append({
            "t": _tick(k.t_s, tick_ms), "k": "kill",
            "v": p(k.victim_account_id), "p": p(k.killer_account_id),
            "f": p(k.finisher_account_id), "d": p(k.dbno_maker_account_id),
            "w": dicts["weapons"].intern(k.weapon),
            "dt": dicts["dmgType"].intern(k.damage_type),
            "dr": dicts["dmgReason"].intern(k.damage_reason),
            "dist": int(k.distance_cm or 0),
            "sui": k.is_suicide, "tk": k.is_team_kill,
            "vx": quantise(k.victim_x, ws), "vy": quantise(k.victim_y, ws),
            "kx": quantise(k.killer_x, ws) if k.killer_x is not None else 0,
            "ky": quantise(k.killer_y, ws) if k.killer_y is not None else 0,
        })
    for knock in combat.knocks:
        out.append({
            "t": _tick(knock.t_s, tick_ms), "k": "knock",
            "v": p(knock.victim_account_id), "p": p(knock.attacker_account_id),
            "w": dicts["weapons"].intern(knock.weapon),
            "dist": int(knock.distance_cm or 0),
            "vx": quantise(knock.victim_x, ws), "vy": quantise(knock.victim_y, ws),
        })
    for revive in combat.revives:
        out.append({
            "t": _tick(revive.t_s, tick_ms), "k": "revive",
            "v": p(revive.victim_account_id), "p": p(revive.reviver_account_id),
        })
    for cp in world.landed:
        out.append({
            "t": _tick(cp.spawn_t_s if cp.spawn_t_s is not None else (cp.land_t_s or 0.0), tick_ms),
            "k": "cp",
            "x": quantise(cp.x, ws), "y": quantise(cp.y, ws),
            "land": _tick(cp.land_t_s or 0.0, tick_ms),
            "items": [dicts["items"].intern(i) for i in cp.items],
        })
    for ride in world.rides:
        out.append({
            "t": _tick(ride.t_s, tick_ms), "k": "ride", "p": p(ride.account_id),
            "veh": dicts["vehicles"].intern(ride.vehicle_id),
            "x": quantise(ride.x, ws), "y": quantise(ride.y, ws),
        })
        if ride.left_t_s is not None:
            out.append({
                "t": _tick(ride.left_t_s, tick_ms), "k": "leave", "p": p(ride.account_id),
                "veh": dicts["vehicles"].intern(ride.vehicle_id),
                "x": quantise(ride.left_x or 0.0, ws), "y": quantise(ride.left_y or 0.0, ws),
                "dist": int(ride.ride_distance or 0),
            })
    for t_s, phase in world.phases:
        out.append({"t": _tick(t_s, tick_ms), "k": "phase", "ph": phase})

    out.sort(key=lambda e: e["t"])
    return out


def _zone_track(world: WorldTracker, ws: int, tick_ms: int) -> dict[str, Any]:
    z = world.zones
    return {
        "n": len(z),
        "t": pack_u16([_tick(s.t_s, tick_ms) for s in z]),
        # blue == safetyZone*, INTERPOLATE
        "bx": pack_u16([quantise(s.blue_x, ws) for s in z]),
        "by": pack_u16([quantise(s.blue_y, ws) for s in z]),
        "br": pack_u16([quantise(s.blue_r, ws) for s in z]),
        # white == poisonGasWarning*, SNAP (step function)
        "wx": pack_u16([quantise(s.white_x, ws) for s in z]),
        "wy": pack_u16([quantise(s.white_y, ws) for s in z]),
        "wr": pack_u16([quantise(s.white_r, ws) for s in z]),
        # all-zero on the current patch; the renderer must guard r > 0
        "rx": pack_u16([quantise(s.red_x, ws) for s in z]),
        "ry": pack_u16([quantise(s.red_y, ws) for s in z]),
        "rr": pack_u16([quantise(s.red_r, ws) for s in z]),
        "alive": pack_u8([s.alive_players for s in z]),
        "teams": pack_u8([s.alive_teams for s in z]),
    }


#: Hit categories worth drawing a tracer for, lowercased. Blue-zone damage is
#: excluded upstream (no attacker); this drops the remaining non-combat
#: sources so a tracer always means "someone shot someone".
_TRACER_TYPES: Final = frozenset(
    {
        "damage_gun",
        "damage_dbno",
        "damage_explosion_grenade",
        "damage_molotov",
        "damage_punch",
        "damage_melee",
        "damage_explosion_vehicle",
        "damage_vehiclecrashhit",
        "damage_explosion_redzone",
        "damage_explosion_c4",
        "damage_crossbow",
        "damage_explosion_stickybomb",
    }
)


def _hit_track(
    combat: CombatTracker,
    index: Mapping[str, int],
    dicts: Mapping[str, Dictionary],
    ws: int,
    tick_ms: int,
) -> dict[str, Any]:
    """Attributed hits, as parallel arrays — the replay's combat tracers.

    Measured at ~550 per match, so at 15 bytes each this is ~8 KB raw and
    around 4 KB gzipped against a 126 KB bundle. Arrays rather than the maps
    `_event_track` uses, because this is an order of magnitude more entries.

    Both endpoints are stored: a tracer is a line from shooter to victim, and
    `LogPlayerTakeDamage` is the only event carrying both positions together.

    Damage is clamped into a byte. It is capped at 100 in practice (a full
    health bar) and the renderer only uses it to weight line thickness, so the
    clamp cannot mislead.
    """
    hits = [
        h
        for h in combat.hits
        if norm(h.damage_type or "") in _TRACER_TYPES
        and h.attacker_account_id in index
        and h.victim_account_id in index
    ]
    return {
        "n": len(hits),
        "t": pack_u16([_tick(h.t_s, tick_ms) for h in hits]),
        "a": pack_u8([index[h.attacker_account_id] for h in hits]),
        "v": pack_u8([index[h.victim_account_id] for h in hits]),
        "ax": pack_u16([quantise(h.attacker_x, ws) for h in hits]),
        "ay": pack_u16([quantise(h.attacker_y, ws) for h in hits]),
        "vx": pack_u16([quantise(h.victim_x, ws) for h in hits]),
        "vy": pack_u16([quantise(h.victim_y, ws) for h in hits]),
        "dmg": pack_u8([min(255, max(0, round(h.damage))) for h in hits]),
        "dr": pack_u8([dicts["dmgReason"].intern(h.damage_reason) & 0xFF for h in hits]),
        "w": pack_u16([dicts["weapons"].intern(h.weapon) for h in hits]),
    }


def _plane(world: WorldTracker, ws: int) -> dict[str, float] | None:
    path = world.plane_path()
    if path is None:
        return None
    return {
        "x0": quantise(path.x0, ws), "y0": quantise(path.y0, ws),
        "x1": quantise(path.x1, ws), "y1": quantise(path.y1, ws),
    }


def _inventory_track(
    inventory: InventoryTracker,
    index: Mapping[str, int],
    items: Dictionary,
    t0_ms: int,
    tick_ms: int,
) -> dict[str, Any]:
    from pubg_dashboard.telemetry.bundle import NULL_PLAYER
    from pubg_dashboard.telemetry.inventory import SLOT_LOOSE

    deltas = [d for d in inventory.deltas if d.account_id in index]
    deltas.sort(key=lambda d: d.t_ms)
    return {
        "kfEveryMs": 60_000,
        "n": len(deltas),
        "t": pack_u16([_tick((d.t_ms - t0_ms) / 1000.0, tick_ms) for d in deltas]),
        "p": pack_u8([index.get(d.account_id, NULL_PLAYER) for d in deltas]),
        "op": pack_u8([d.op for d in deltas]),
        "a": pack_u16([items.intern(d.item) for d in deltas]),
        "b": pack_u16([items.intern(d.other) if d.other else 0xFFFF for d in deltas]),
        "q": pack_u16([d.quantity for d in deltas]),
        "slot": pack_u8([d.slot if d.slot != SLOT_LOOSE else 0xFF for d in deltas]),
    }


# ---------------------------------------------------------------------------
# SQL-bound outputs
# ---------------------------------------------------------------------------
def _kill_rows(match_id: str, combat: CombatTracker) -> list[dict[str, Any]]:
    return [
        {
            "match_id": match_id,
            "seq": k.seq,
            "t_s": k.t_s,
            "victim_account_id": k.victim_account_id,
            "victim_team_id": k.victim_team_id,
            "victim_is_bot": k.victim_is_bot,
            "victim_x": k.victim_x,
            "victim_y": k.victim_y,
            "killer_account_id": k.killer_account_id,
            "killer_team_id": k.killer_team_id,
            "killer_is_bot": k.killer_is_bot,
            "killer_x": k.killer_x,
            "killer_y": k.killer_y,
            "dbno_maker_account_id": k.dbno_maker_account_id,
            "finisher_account_id": k.finisher_account_id,
            "weapon": k.weapon,
            "damage_type": k.damage_type,
            "damage_reason": k.damage_reason,
            "distance_cm": k.distance_cm,
            "is_suicide": k.is_suicide,
            "is_team_kill": k.is_team_kill,
            "through_wall": k.through_wall,
            "assists": k.assists,
        }
        for k in combat.kills
    ]


def _participant_updates(
    combat: CombatTracker,
    frames: FrameIndex,
    roster: Mapping[str, PlayerRow],
    t0_ms: int,
) -> list[dict[str, Any]]:
    """Telemetry-derived `participants` columns, one row per account."""
    out: list[dict[str, Any]] = []
    for account, row in roster.items():
        stats = combat.players.get(account)
        death = stats.death if stats else None
        # LogParachuteLanding is authoritative for the drop. The first frame
        # sample is only a fallback for a player who never landed — it can sit
        # on the aircraft's path, which is why it is not the primary source.
        landing = frames.landing(account)
        if landing is not None:
            land_ms, land_x, land_y = landing
            landing_x, landing_y = land_x, land_y
            landed_at_s: float | None = (land_ms - t0_ms) / 1000.0
        else:
            samples = frames.samples_for(account)
            landing_x = samples[0].x if samples else None
            landing_y = samples[0].y if samples else None
            landed_at_s = None
        out.append(
            {
                "account_id": account,
                "kills_human": stats.kills_human if stats else 0,
                "knocks_human": stats.knocks_human if stats else 0,
                "death_x": death.x if death else None,
                "death_y": death.y if death else None,
                "died_at_s": death.t_s if death else None,
                "killer_account_id": death.killer_account_id if death else None,
                "death_weapon": death.weapon if death else None,
                "shots_fired": stats.shots_fired if stats else 0,
                "shots_hit": stats.shots_hit if stats else 0,
                "landing_x": landing_x,
                "landing_y": landing_y,
                "landed_at_s": landed_at_s,
                "is_bot": row.is_bot,
            }
        )
    return out
