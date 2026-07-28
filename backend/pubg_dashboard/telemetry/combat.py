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

__all__ = [
    "CombatTracker",
    "DeathInfo",
    "Hit",
    "KillEvent",
    "PlayerCombat",
    "WeaponAccuracy",
    "normalise_weapon_id",
]

#: Weapons where PUBG counts **pellets**, not trigger pulls.
#:
#: `allWeaponStats` reports 90 shots for 10 attack events with a Berreta686 —
#: nine pellets each. Measured across the corpus, these are every causer whose
#: attack count is under half its reported shot count; every other gun is 1:1.
#: Launchers are here for the mirror-image reason (one attack, several
#: reported rounds), which is the same arithmetic from the other side.
#:
#: Nothing in the parser branches on this. It exists so the corpus test can
#: assert that **no weapon outside this set** behaves like a pellet weapon —
#: a shotgun shipped next patch then fails the test instead of quietly
#: reporting several hundred percent accuracy.
PELLET_WEAPONS: Final = frozenset(
    {
        "weapberreta686_c",
        "weapcrossbow_1_c",
        "weapm79_c",
        "weappanzerfaust100m1_c",
        "weapsaiga12_c",
        "weapsawnoff_c",
        "weapwinchester_c",
    }
)


def normalise_weapon_id(item_id: str | None) -> str:
    """`LogPlayerAttack`'s item id -> the spelling every other source uses.

    Three sources name the same gun three ways: the attack event carries
    `Item_Weapon_M16A4_C`, `allWeaponStats` says `WeapM16A4_C`, and
    `damageCauserName` (which `kill_events.weapon` already stores) also says
    `WeapM16A4_C`. Lowercased, because every PUBG enum is open and casing has
    moved between patches for all of them.

    Verified against the corpus: all 55 distinct attack weapon ids normalise
    onto the `allWeaponStats` vocabulary. The 11 `allWeaponStats` names that
    have no attack counterpart are not guns at all — fists
    (`PlayerMale_A_C`), grenades, molotovs, the blue zone and vehicles — and
    none of them ever reports a non-zero shot count.

    Returns `''` for a missing id, which is a real case: 1.7% of attack events
    carry an empty `weapon.itemId`. Those are bucketed as unknown rather than
    dropped, so the shot totals stay right even where the weapon is not.
    """
    s = item_id or ""
    if s.startswith("Item_Weapon_"):
        s = "Weap" + s[len("Item_Weapon_") :]
    return s.lower()

#: `distance` uses -1 to mean "not applicable", not "zero metres". Any
#: "longest kill" query must filter `> 0` or a melee kill wins it.
DISTANCE_NOT_APPLICABLE: Final = -1.0

_BLUE_ZONE: Final = "damage_bluezone"
_HEAD_SHOT: Final = "headshot"


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
    #: Trigger pulls, from `LogPlayerAttack`, throwables excluded.
    shots_fired: int = 0
    #: Trigger pulls that produced at least one attributed damage event.
    shots_hit: int = 0
    #: Pellet-level hits — one per attributed damage event, so a shotgun blast
    #: that lands six pellets counts six here and one in `shots_hit`.
    hit_events: int = 0
    #: Attacks whose `weapon.itemId` was empty (1.7% of the corpus). Counted
    #: rather than dropped, and persisted, so "the field moved" shows up as
    #: this going to zero instead of as a per-weapon table quietly going short.
    shots_unknown_weapon: int = 0
    #: What PUBG itself reported, kept beside the derivation rather than
    #: replaced by it. Populated for ~3% of participants — see `_match_end`.
    aws_shots: int = 0
    aws_hits: int = 0
    #: The **last** death, not the first — see `CombatTracker.feed`.
    death: DeathInfo | None = None


@dataclass(slots=True)
class WeaponAccuracy:
    """One `(account, weapon)` row of `participant_weapons`."""

    shots: int = 0
    shots_landed: int = 0
    hit_events: int = 0
    dbno_hit_events: int = 0
    headshot_events: int = 0
    damage: float = 0.0


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

    __slots__ = (
        "_attacks",
        "_landed",
        "_t0_s",
        "_thrown",
        "hits",
        "kills",
        "knocks",
        "players",
        "revives",
        "unattributed_damage",
        "weapons",
    )

    def __init__(self, t0_s: float) -> None:
        self._t0_s = t0_s
        # attackId -> (attacker account, normalised weapon id).
        #
        # Collected rather than counted on sight, for two reasons that both
        # come out of the wire's ordering. A throwable emits **both**
        # `LogPlayerAttack` and `LogPlayerUseThrowable` under one attackId,
        # same millisecond, in either order — so "is this attack a throw" is
        # not answerable when the attack arrives. And a damage event has to
        # find its attack, which means the attack has to still be around.
        # ~6,000 entries per match; the memory is not worth optimising.
        self._attacks: dict[int, tuple[str, str]] = {}
        self._thrown: set[int] = set()
        # attackId -> (hit events, dbno hits, headshots, damage). One attack
        # can produce several damage events: a shotgun blast lands per pellet.
        self._landed: dict[int, tuple[int, int, int, float]] = {}
        #: `(account, weapon)` -> counters. Filled by `resolve_accuracy`.
        self.weapons: dict[tuple[str, str], WeaponAccuracy] = {}
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
        elif kind == norm(E.PLAYER_ATTACK):
            self._attack(event)
        elif kind == norm(E.PLAYER_USE_THROWABLE):
            attack_id = event.get("attackId")
            if isinstance(attack_id, int):
                self._thrown.add(attack_id)
        elif kind == norm(E.MATCH_END):
            self._match_end(event)

    def _attack(self, event: Mapping[str, Any]) -> None:
        """One trigger pull.

        `attackId` is **match-unique** — measured at 30,148 attacks to 30,148
        distinct ids across eight matches, and asserted by a corpus test,
        because the whole hit join hangs off it.
        """
        attack_id = event.get("attackId")
        if not isinstance(attack_id, int):
            return
        attacker = event.get("attacker") if isinstance(event.get("attacker"), Mapping) else None
        account = str((attacker or {}).get("accountId") or "")
        if not account:
            return
        weapon = event.get("weapon") if isinstance(event.get("weapon"), Mapping) else None
        self._attacks[attack_id] = (account, normalise_weapon_id((weapon or {}).get("itemId")))

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

        # -- accuracy ---------------------------------------------------------
        # **Recorded here, above the zero-damage guard below.** 27% of
        # attributed damage events land 0 — armour absorption, and shots on an
        # already-knocked victim — and a shot that did no damage is still a
        # shot that hit. Dropping them here would understate accuracy by about
        # a quarter and look entirely reasonable doing it.
        #
        # The join requires the attacker to match, not just the id to exist.
        # attackIds are match-unique today, so this cannot currently fire — but
        # PUBG has changed id semantics before, and if they ever became
        # per-player counters an id-only join would cross-attribute silently.
        attack_id = event.get("attackId")
        record = self._attacks.get(attack_id) if isinstance(attack_id, int) else None
        if record is not None and record[0] == attacker_account:
            events_n, dbno_n, head_n, dmg = self._landed.get(attack_id, (0, 0, 0, 0.0))
            self._landed[attack_id] = (
                events_n + 1,
                dbno_n + (1 if victim.get("isDBNO") else 0),
                head_n + (1 if norm(str(event.get("damageReason") or "")) == _HEAD_SHOT else 0),
                dmg + amount,
            )

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

        **`dBNOHits` is a subset of `hits`, not an addend.** This code used to
        sum the two, on the reading that `hits` counted shots landing on a
        standing target and `dBNOHits` those landing on a knocked one. The
        corpus says otherwise: `dBNOHits <= hits` on **547 of 547** weapon rows
        with no exception, and a per-weapon check against derived hit events
        matches `hits` alone (median ratio 1.00) while matching `hits +
        dBNOHits` at 0.78. Worked example, `WeapBerreta686_C` in
        `008a45cb…`: `shots 90, hits 44, dBNOHits 35`, against 44 attributed
        damage events of which 35 had a DBNO victim.

        Summing inflated every accuracy figure the dashboard showed by **31%**
        — corpus totals `shots 32,821, hits 5,592, dBNOHits 1,757`, so 17.0%
        was displayed as 22.4%. Nothing caught it because nothing could:
        `shots_hit` never exceeded `shots_fired` (0 rows of 9,041), so the
        number stayed a plausible percentage, and the unit test below was
        written from the same assumption as the code. Fixed in parser v9.

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
                stats.aws_shots += int(weapon.get("shots") or 0)
                # `hits` already includes `dBNOHits`. Do not add them.
                stats.aws_hits += int(weapon.get("hits") or 0)

    def resolve_accuracy(self) -> None:
        """Turn the collected attacks and hits into per-player and per-weapon rows.

        Deferred to the end of the pass rather than accumulated on sight,
        because a throwable's `LogPlayerAttack` and `LogPlayerUseThrowable`
        arrive in the same millisecond in either order — so an attack cannot
        know at arrival whether it is a throw.

        **This is what makes accuracy a real stat.** PUBG reports
        `allWeaponStats` for a median of two accounts per match and for a
        *tracked* player in three of 65, so `shots_fired` was populated for
        3.3% of human participants and every UI treated 0 as "not reported".
        Derived this way it is populated for **89.9%** — and the remaining 10%
        are players who genuinely never fired, which is the first time the two
        have been distinguishable.

        Validated per weapon against the 531 `allWeaponStats` rows in the
        corpus that report a shot: median derived/reported is **1.000** for
        shots (402 of 531 exact) and **1.000** for hit events (444 of 453).
        """
        for attack_id, (account, weapon) in self._attacks.items():
            if attack_id in self._thrown:
                continue
            stats = self._player(account)
            stats.shots_fired += 1
            if not weapon:
                stats.shots_unknown_weapon += 1

            row = self.weapons.get((account, weapon))
            if row is None:
                row = self.weapons[(account, weapon)] = WeaponAccuracy()
            row.shots += 1

            landed = self._landed.get(attack_id)
            if landed is None:
                continue
            events_n, dbno_n, head_n, dmg = landed
            # One trigger pull that connected, however many pellets landed.
            # This is the pellet-independent measure and the one the UI shows:
            # PUBG counts nine "shots" for one Berreta686 trigger pull, so a
            # ratio of damage events to attacks reads as several hundred
            # percent accuracy on a shotgun.
            stats.shots_hit += 1
            stats.hit_events += events_n
            row.shots_landed += 1
            row.hit_events += events_n
            row.dbno_hit_events += dbno_n
            row.headshot_events += head_n
            row.damage += dmg

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
