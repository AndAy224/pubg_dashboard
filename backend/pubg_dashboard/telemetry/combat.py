"""Kills, knocks, revives and damage.

`LogPlayerKillV2` replaced `LogPlayerKill` in v21 and reshaped it: there is no
`assistant`, and no top-level `damageCauserName`/`distance`. Those moved inside
three separate damage blocks — `dBNODamageInfo` (the knock), `finishDamageInfo`
(the blow that finished them) and `killerDamageInfo` (what the credited killer
did). Reading the old field names off a V2 event yields `None` silently.

Measured presence across the corpus, all of which must be tolerated:

| block         | present |
|---------------|---------|
| `victim`      | 1.00    |
| `finisher`    | 0.97    |
| `killer`      | 0.96    |
| `dBNOMaker`   | 0.53    |

A zone death has `killer = null` and `damageTypeCategory = 'Damage_BlueZone'`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from pubg_dashboard.telemetry import events as E
from pubg_dashboard.telemetry.reader import norm, ts

__all__ = ["CombatTracker", "DeathInfo", "Hit", "KillEvent", "PlayerCombat"]

#: `distance` uses -1 to mean "not applicable", not "zero metres". Any
#: "longest kill" query must filter `> 0` or a melee kill wins it.
DISTANCE_NOT_APPLICABLE: Final = -1.0

_BLUE_ZONE: Final = "damage_bluezone"


@dataclass(slots=True)
class KillEvent:
    """One death. Maps 1:1 onto a `kill_events` row."""

    seq: int
    t_s: float
    victim_account_id: str
    victim_team_id: int
    victim_is_bot: bool
    victim_x: float
    victim_y: float
    killer_account_id: str | None = None
    killer_team_id: int | None = None
    killer_is_bot: bool | None = None
    killer_x: float | None = None
    killer_y: float | None = None
    dbno_maker_account_id: str | None = None
    finisher_account_id: str | None = None
    weapon: str | None = None
    damage_type: str | None = None
    damage_reason: str | None = None
    distance_cm: float | None = None
    is_suicide: bool = False
    is_team_kill: bool = False
    through_wall: bool | None = None
    assists: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DeathInfo:
    t_s: float
    x: float
    y: float
    killer_account_id: str | None
    weapon: str | None


@dataclass(slots=True)
class PlayerCombat:
    """Per-account telemetry-derived combat totals."""

    kills: int = 0
    kills_human: int = 0
    knocks: int = 0
    knocks_human: int = 0
    revives: int = 0
    damage_dealt: float = 0.0
    #: Damage *taken* from the blue zone. The only signal for zone discipline
    #: that costs health rather than time — attacker-less, so it lives outside
    #: the attributed `hits` path entirely.
    blue_zone_damage: float = 0.0
    shots_fired: int = 0
    shots_hit: int = 0
    #: The **last** death, not the first — see `CombatTracker.feed`.
    death: DeathInfo | None = None


@dataclass(slots=True)
class Knock:
    t_s: float
    victim_account_id: str
    attacker_account_id: str | None
    victim_x: float
    victim_y: float
    weapon: str | None
    distance_cm: float | None


@dataclass(slots=True)
class Revive:
    t_s: float
    victim_account_id: str
    reviver_account_id: str | None


@dataclass(slots=True)
class Hit:
    """One attributed hit on a player, for the replay's combat tracers.

    Drawn as a line from attacker to victim, so **both** positions matter —
    `LogPlayerTakeDamage` is the only event carrying them together.

    Zone damage is excluded at collection: it is 63% of all damage events and
    has no attacker, so it would be 37k lines from nowhere. Self-damage is
    excluded too, for the same reason `_damage` skips it in the totals.
    """

    t_s: float
    attacker_account_id: str
    victim_account_id: str
    attacker_x: float
    attacker_y: float
    victim_x: float
    victim_y: float
    damage: float
    #: HeadShot / TorsoShot / ArmShot / LegShot / PelvisShot / NonSpecific.
    damage_reason: str | None
    damage_type: str | None
    weapon: str | None


def _dmg(block: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalise one of the three damage-info blocks."""
    block = block or {}
    distance = block.get("distance")
    return {
        "weapon": (block.get("damageCauserName") or None),
        "damage_type": (block.get("damageTypeCategory") or None),
        "damage_reason": (block.get("damageReason") or None),
        # Keep -1 rather than coercing to None: it is a real, distinguishable
        # statement ("no meaningful distance"), and callers filter `> 0`.
        "distance_cm": None if distance is None else float(distance),
        "through_wall": block.get("isThroughPenetrableWall"),
    }


class CombatTracker:
    """Accumulates every combat outcome for one match."""

    __slots__ = ("_t0_s", "hits", "kills", "knocks", "players", "revives", "unattributed_damage")

    def __init__(self, t0_s: float) -> None:
        self._t0_s = t0_s
        self.kills: list[KillEvent] = []
        #: Attributed hits, for the replay's combat tracers.
        self.hits: list[Hit] = []
        self.knocks: list[Knock] = []
        self.revives: list[Revive] = []
        self.players: dict[str, PlayerCombat] = {}
        # Blue-zone ticks and other attacker-less damage. Counted so the
        # "most damage is not from players" claim stays measurable.
        self.unattributed_damage = 0.0

    def _player(self, account: str) -> PlayerCombat:
        got = self.players.get(account)
        if got is None:
            got = self.players[account] = PlayerCombat()
        return got

    def _rel(self, event: Mapping[str, Any]) -> float:
        return ts(event.get("_D")) - self._t0_s

    # -- ingest -------------------------------------------------------------
    def feed(self, event: Mapping[str, Any]) -> None:
        kind = norm(event.get("_T", ""))
        if kind == norm(E.PLAYER_KILL_V2):
            self._kill_v2(event)
        elif kind == norm(E.PLAYER_KILL_V1):
            self._kill_v1(event)
        elif kind == norm(E.PLAYER_MAKE_GROGGY):
            self._groggy(event)
        elif kind == norm(E.PLAYER_REVIVE):
            self._revive(event)
        elif kind == norm(E.PLAYER_TAKE_DAMAGE):
            self._damage(event)
        elif kind == norm(E.MATCH_END):
            self._match_end(event)

    def _kill_v2(self, event: Mapping[str, Any]) -> None:
        victim = event.get("victim") or {}
        victim_account = str(victim.get("accountId") or "")
        if not victim_account:
            return

        killer = event.get("killer") if isinstance(event.get("killer"), Mapping) else None
        finisher = event.get("finisher") if isinstance(event.get("finisher"), Mapping) else None
        dbno_maker = (
            event.get("dBNOMaker") if isinstance(event.get("dBNOMaker"), Mapping) else None
        )

        info = _dmg(event.get("killerDamageInfo") or event.get("finishDamageInfo"))
        vx, vy, _ = E.location(victim)
        killer_account = str(killer.get("accountId")) if killer else None
        victim_team = int(victim.get("teamId") or 0)
        killer_team = int(killer.get("teamId") or 0) if killer else None

        # A blue-zone/fall/drown death has no killer at all. A suicide has the
        # victim as their own killer.
        is_suicide = killer_account is not None and killer_account == victim_account
        is_team_kill = (
            killer_account is not None
            and not is_suicide
            and killer_team is not None
            and killer_team == victim_team
        )

        kx = ky = None
        if killer:
            kx, ky, _ = E.location(killer)

        assists = [str(a) for a in (event.get("assists_AccountId") or []) if a]

        self.kills.append(
            KillEvent(
                seq=len(self.kills),
                t_s=self._rel(event),
                victim_account_id=victim_account,
                victim_team_id=victim_team,
                victim_is_bot=E.is_bot(victim),
                victim_x=vx,
                victim_y=vy,
                killer_account_id=killer_account,
                killer_team_id=killer_team,
                killer_is_bot=E.is_bot(killer) if killer else None,
                killer_x=kx,
                killer_y=ky,
                dbno_maker_account_id=str(dbno_maker.get("accountId")) if dbno_maker else None,
                finisher_account_id=str(finisher.get("accountId")) if finisher else None,
                is_suicide=is_suicide,
                is_team_kill=is_team_kill,
                assists=assists,
                **info,
            )
        )

        # Credit the kill. Self-kills and team kills are excluded from the
        # headline counters — they are not achievements.
        if killer_account and not is_suicide and not is_team_kill:
            stats = self._player(killer_account)
            stats.kills += 1
            if not E.is_bot(victim):
                stats.kills_human += 1

        # **Overwrite, never `setdefault`.** A player can die twice in comeback
        # modes; keying on the first death discards their entire second life
        # and freezes the replay's inventory 20 minutes early.
        self._player(victim_account).death = DeathInfo(
            t_s=self._rel(event),
            x=vx,
            y=vy,
            killer_account_id=killer_account,
            weapon=info["weapon"],
        )

    def _kill_v1(self, event: Mapping[str, Any]) -> None:
        """Pre-v21 shape, kept as a fallback branch.

        The archived corpus contains none of these — every match is V2 — so this
        exists for older archives rather than for current ingest.
        """
        victim = event.get("victim") or {}
        victim_account = str(victim.get("accountId") or "")
        if not victim_account:
            return
        killer = event.get("killer") if isinstance(event.get("killer"), Mapping) else None
        vx, vy, _ = E.location(victim)
        killer_account = str(killer.get("accountId")) if killer else None
        victim_team = int(victim.get("teamId") or 0)
        killer_team = int(killer.get("teamId") or 0) if killer else None
        is_suicide = killer_account is not None and killer_account == victim_account
        is_team_kill = (
            killer_account is not None
            and not is_suicide
            and killer_team is not None
            and killer_team == victim_team
        )
        kx = ky = None
        if killer:
            kx, ky, _ = E.location(killer)
        distance = event.get("distance")

        self.kills.append(
            KillEvent(
                seq=len(self.kills),
                t_s=self._rel(event),
                victim_account_id=victim_account,
                victim_team_id=victim_team,
                victim_is_bot=E.is_bot(victim),
                victim_x=vx,
                victim_y=vy,
                killer_account_id=killer_account,
                killer_team_id=killer_team,
                killer_is_bot=E.is_bot(killer) if killer else None,
                killer_x=kx,
                killer_y=ky,
                weapon=event.get("damageCauserName") or None,
                damage_type=event.get("damageTypeCategory") or None,
                damage_reason=event.get("damageReason") or None,
                distance_cm=None if distance is None else float(distance),
                is_suicide=is_suicide,
                is_team_kill=is_team_kill,
            )
        )
        if killer_account and not is_suicide and not is_team_kill:
            stats = self._player(killer_account)
            stats.kills += 1
            if not E.is_bot(victim):
                stats.kills_human += 1
        self._player(victim_account).death = DeathInfo(
            t_s=self._rel(event),
            x=vx,
            y=vy,
            killer_account_id=killer_account,
            weapon=event.get("damageCauserName") or None,
        )

    def _groggy(self, event: Mapping[str, Any]) -> None:
        """`LogPlayerMakeGroggy` — absent from solo entirely (55/61 matches).

        Any parser that assumes it is present breaks on every solo match.
        """
        victim = event.get("victim") or {}
        victim_account = str(victim.get("accountId") or "")
        if not victim_account:
            return
        attacker = event.get("attacker") if isinstance(event.get("attacker"), Mapping) else None
        attacker_account = str(attacker.get("accountId")) if attacker else None
        vx, vy, _ = E.location(victim)
        distance = event.get("distance")

        self.knocks.append(
            Knock(
                t_s=self._rel(event),
                victim_account_id=victim_account,
                attacker_account_id=attacker_account,
                victim_x=vx,
                victim_y=vy,
                weapon=event.get("damageCauserName") or None,
                distance_cm=None if distance is None else float(distance),
            )
        )
        if attacker_account and attacker_account != victim_account:
            stats = self._player(attacker_account)
            stats.knocks += 1
            if not E.is_bot(victim):
                stats.knocks_human += 1

    def _revive(self, event: Mapping[str, Any]) -> None:
        victim = event.get("victim") or {}
        reviver = event.get("reviver") if isinstance(event.get("reviver"), Mapping) else None
        victim_account = str(victim.get("accountId") or "")
        reviver_account = str(reviver.get("accountId")) if reviver else None
        if not victim_account:
            return
        self.revives.append(
            Revive(
                t_s=self._rel(event),
                victim_account_id=victim_account,
                reviver_account_id=reviver_account,
            )
        )
        if reviver_account:
            self._player(reviver_account).revives += 1

    def _damage(self, event: Mapping[str, Any]) -> None:
        """Damage, **attacker-attributed only**.

        The large majority of `LogPlayerTakeDamage` events are blue-zone ticks
        with `attacker = null` and `attackId = -1`. Summing them all inflates
        every player's damage with the zone's contribution.
        """
        amount = float(event.get("damage") or 0.0)
        attacker = event.get("attacker") if isinstance(event.get("attacker"), Mapping) else None
        if attacker is None:
            self.unattributed_damage += amount
            # Blue-zone ticks are the exception worth keeping per-victim: they
            # measure zone discipline. Matched on the lowercased category —
            # the enum is open and casing has moved between patches.
            if norm(str(event.get("damageTypeCategory") or "")) == _BLUE_ZONE:
                victim_account = str((event.get("victim") or {}).get("accountId") or "")
                if victim_account:
                    self._player(victim_account).blue_zone_damage += amount
            return
        attacker_account = str(attacker.get("accountId") or "")
        victim = event.get("victim") or {}
        # Self-damage is already netted out of the API's damageDealt; counting
        # it here would disagree with the scoreboard.
        if not attacker_account or attacker_account == str(victim.get("accountId") or ""):
            return
        self._player(attacker_account).damage_dealt += amount

        # Record the geometry for the replay's combat tracers. Zero-damage
        # events are dropped: 27% of attributed damage events land 0 (armour
        # absorption, already-dead targets), and a tracer for a hit that did
        # nothing is noise.
        if amount <= 0.0:
            return
        victim_account = str(victim.get("accountId") or "")
        if not victim_account:
            return
        ax, ay, _ = E.location(attacker)
        vx, vy, _ = E.location(victim)
        self.hits.append(
            Hit(
                t_s=self._rel(event),
                attacker_account_id=attacker_account,
                victim_account_id=victim_account,
                attacker_x=ax,
                attacker_y=ay,
                victim_x=vx,
                victim_y=vy,
                damage=amount,
                damage_reason=(event.get("damageReason") or None),
                damage_type=(event.get("damageTypeCategory") or None),
                weapon=(event.get("damageCauserName") or None),
            )
        )

    def _match_end(self, event: Mapping[str, Any]) -> None:
        """Take accuracy from `allWeaponStats` rather than re-deriving it.

        **The field names are `shots` and `hits`.** They were previously read
        as `shotsFired` / `hitCount` / `shotsHit`, none of which exist, so both
        counters summed to a silent zero on every one of the 5,978 archived
        participants — non-NULL, so `count(shots_fired)` reported the column
        as fully populated. Measured against the corpus: `shots`, `hits`,
        `dBNOHits`, `damage`, `dBNODamage`, `holdingTime`, `hitDetails` are
        the only keys ever present.

        `hits` counts shots that connected with a standing target and
        `dBNOHits` those that connected with a knocked one; accuracy wants
        both, so they are summed.

        Re-deriving this from events is **not** an option, which is why the
        misnamed fields went unnoticed for so long:

        * `LogWeaponFireCount.fireCount` is a periodic ping quantised to
          multiples of 10 — measured against this same `allWeaponStats`, 99
          real shots report as 120, 63 as 60, 276 as 270, and any weapon
          fired fewer than 10 times is never reported at all.
        * counting `LogPlayerAttack` double-counts throwables, which emit both
          it and `LogPlayerUseThrowable` under one `attackId`.

        **Coverage is the real limit, and it is severe**: PUBG populates
        `allWeaponStats` for a median of 2 accounts per match (max 4 in the
        archive), and for a *tracked* player in only 3 of 65 matches. Anything
        reading these columns must treat `shots_fired == 0` as "not reported"
        rather than "fired nothing", or it will show three headline 0%
        accuracies that look like a rendering bug and are in fact missing data.
        """
        for entry in event.get("allWeaponStats") or []:
            if not isinstance(entry, Mapping):
                continue
            account = str(entry.get("accountId") or "")
            if not account:
                continue
            stats = self._player(account)
            for weapon in entry.get("stats") or []:
                if not isinstance(weapon, Mapping):
                    continue
                stats.shots_fired += int(weapon.get("shots") or 0)
                stats.shots_hit += int(weapon.get("hits") or 0) + int(
                    weapon.get("dBNOHits") or 0
                )

    # -- output -------------------------------------------------------------
    def longest_kill_cm(self, account: str) -> float:
        """Longest *real* kill distance. `-1` sentinels are excluded."""
        return max(
            (
                k.distance_cm
                for k in self.kills
                if k.killer_account_id == account
                and k.distance_cm is not None
                and k.distance_cm > 0
            ),
            default=0.0,
        )
