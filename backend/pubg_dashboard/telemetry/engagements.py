"""Fights: cross-team exchanges of fire, grouped.

Consumes **no events** — post-processes `CombatTracker`, whose `hits`, `knocks`
and `kills` already carry both endpoints, both teams and the damage. Hooked in
beside `strategy.py` and `zoneplay.py`.

### This module is the one modelled quantity in the parser

Everything else derived here is a wire fact with a name: `in_circle_at_close`
is PUBG's own roster, `dbno_maker` is PUBG's own knock-to-kill link, a kill is
a kill. **"An engagement" is not a thing PUBG records.** It is a grouping this
module invents, and the grouping has a free parameter.

That parameter was swept before this was written, over 2,992 engagements in 25
archived matches, and **there is no knee**:

```
gap   5s -> 4559        gap  30s -> 2589
gap  10s -> 3791        gap  45s -> 2249
gap  15s -> 3311        gap  60s -> 2058
gap  20s -> 2992        gap  90s -> 1890
gap  25s -> 2762        gap 120s -> 1797
```

A smooth decay, so 20 s versus 30 s is a **13% swing in the engagement count
from a ten-second choice**. `ENGAGEMENT_GAP_S` is therefore returned to the
client by the API and printed on the page, rather than left implicit: a reader
who knows the fights were cut at a 20 s silence can discount accordingly, and
one who does not will read a modelled count as a measured one.

Nothing downstream stores a `won`/`lost` verdict. The per-side kill, knock,
damage and hit counts are facts *given* the grouping; "we lost that fight" is
an interpretation, and it is left to the query that wants it.

### Why kills are attached rather than segmented

The exchange is built from **hits and knocks only**, and kills are attached to
it afterwards. A death does not have to land inside the exchange that caused
it: `Damage_DBNO` bleed-out ticks are self-attributed (`attackId: -1`,
attacker == victim), so `CombatTracker` drops them as self-damage and they
produce no `Hit` at all. Measured, the killing blow's own damage event is 20 s
or more before the death on **16% of cross-team kills** — those are the players
who were knocked, crawled, and ran out.

Segmenting on kills as well would open a fresh one-event engagement for every
bleed-out, reading as "team A killed team B with no exchange" a minute after
the fight that actually did it. So kills are attached by three rules, in order,
and only the last is a threshold:

1. the kill falls inside the exchange's span — exact;
2. `dbno_maker`'s knock is in the exchange — PUBG's own link, **no threshold**;
3. the pair's most recent exchange, if it ended within `ENGAGEMENT_GAP_S`.

Measured at gap 20 s: 47.3% / 29.3% / 22.1%, with **1.3% left unattached** —
kills where the credited killer never landed an attributed hit on the victim at
all. Those are counted in `unattached_kills` rather than dropped silently, and
rule 3's reach is sub-second in the median (it exists because the fatal damage
event and the `LogPlayerKillV2` that follows it are a few milliseconds apart,
not because fights need a lookback).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from pubg_dashboard.telemetry.combat import CombatTracker, Hit, KillEvent, Knock

__all__ = ["ENGAGEMENT_GAP_S", "THIRD_PARTY_RADIUS_CM", "compute_engagements"]

#: A silence longer than this between two teams ends the fight.
#:
#: **A judgement call, not a wire fact** — see the module docstring for the
#: sweep. Changing it changes the engagement count by roughly 4% per second
#: around here, so it is a `PARSER_VERSION` concern and the API reports it.
ENGAGEMENT_GAP_S: Final = 20.0

#: How close a second fight has to be to count as a third party on this one.
#:
#: Deliberately the same 200 m as `strategy.HOT_DROP_RADIUS_CM` and the review
#: router's `THIRD_PARTY_RADIUS_CM`, so the three places in this codebase that
#: say "nearby" all mean the same distance. A time-overlap test alone would
#: flag a four-player squad whose members are fighting different teams 800 m
#: apart, which is two fights, not a third party.
THIRD_PARTY_RADIUS_CM: Final = 20_000.0


@dataclass(slots=True)
class _Side:
    """One team's contribution to one engagement."""

    hits: int = 0
    damage: float = 0.0
    knocks: int = 0
    kills: int = 0


@dataclass(slots=True)
class _Actor:
    """One account's contribution to one engagement."""

    team_id: int = 0
    hits_dealt: int = 0
    hits_taken: int = 0
    damage_dealt: float = 0.0
    damage_taken: float = 0.0
    knocks: int = 0
    kills: int = 0
    was_knocked: bool = False
    died: bool = False


@dataclass(slots=True)
class _Segment:
    """An exchange between two teams, `team_a < team_b` by construction."""

    team_a: int
    team_b: int
    t_start_s: float
    t_end_s: float
    hits: list[Hit] = field(default_factory=list)
    knocks: list[Knock] = field(default_factory=list)
    kills: list[KillEvent] = field(default_factory=list)


def compute_engagements(
    *,
    match_id: str,
    combat: CombatTracker,
    teams: Mapping[str, int],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    """`(engagement rows, participant rows, kills that attached to nothing)`.

    Rows are written for **every** team pair, bots included, on the same
    reasoning as `strategy_metrics` and `zone_play`: filtering is a query-time
    join on `participants.is_bot`, and a lobby baseline costs nothing once the
    rows exist. Bots are roughly 14% of participants and they do fight, so a
    parse-time filter would also make the totals disagree with `kill_events`.

    `seq` is assigned in start-time order and is stable for a given parser
    version and telemetry file — the same requirement `kill_events.seq` has,
    and for the same reason: it is half of a primary key that a reparse
    rewrites.
    """
    pairs: dict[tuple[int, int], list[_Segment]] = {}

    for t_s, _rank, _i, kind, obj in _stream(combat, teams):
        pair = _pair(teams, obj)
        if pair is None:
            continue
        bucket = pairs.setdefault(pair, [])
        if not bucket or t_s - bucket[-1].t_end_s > ENGAGEMENT_GAP_S:
            bucket.append(_Segment(pair[0], pair[1], t_s, t_s))
        seg = bucket[-1]
        seg.t_end_s = t_s
        if kind == "hit":
            seg.hits.append(obj)
        else:
            seg.knocks.append(obj)

    unattached = _attach_kills(pairs, combat, teams)

    # Start time, then the team pair, so two engagements opening in the same
    # millisecond still order identically on every reparse.
    segments = sorted(
        (s for bucket in pairs.values() for s in bucket),
        key=lambda s: (s.t_start_s, s.team_a, s.team_b),
    )
    third = _third_parties(segments)

    engagement_rows: list[dict[str, Any]] = []
    participant_rows: list[dict[str, Any]] = []
    for seq, seg in enumerate(segments):
        engagement_rows.append(_engagement_row(match_id, seq, seg, third.get(seq), teams))
        participant_rows.extend(_participant_rows(match_id, seq, seg, teams))
    return engagement_rows, participant_rows, unattached


def _stream(
    combat: CombatTracker, teams: Mapping[str, int]
) -> list[tuple[float, int, int, str, Any]]:
    """Every cross-team blow that landed, in a total order.

    Sorted by `(t_s, kind, source index)` rather than by `t_s` alone. Hits and
    knocks share timestamps constantly — a knock *is* a hit that took the
    victim to zero — and Python's sort is stable only with respect to the list
    it is given, which here is two concatenated lists. Without the tiebreak the
    order would depend on how many hits happened to precede the knock, and a
    segment boundary could land differently between two parses of the same
    file.
    """
    out: list[tuple[float, int, int, str, Any]] = []
    for i, hit in enumerate(combat.hits):
        out.append((hit.t_s, 0, i, "hit", hit))
    for i, knock in enumerate(combat.knocks):
        if knock.attacker_account_id:
            out.append((knock.t_s, 1, i, "knock", knock))
    out.sort(key=lambda r: (r[0], r[1], r[2]))
    return out


def _pair(teams: Mapping[str, int], obj: Any) -> tuple[int, int] | None:
    """The two teams involved, low first — or None if this is not a fight.

    Rejects same-team damage (friendly fire and self-damage) and anyone missing
    from the roster. A missing account is real: `LogPlayerCreate` does not fire
    for every id that appears in a damage event.
    """
    attacker = getattr(obj, "attacker_account_id", None)
    victim = obj.victim_account_id
    ta, tb = teams.get(attacker or ""), teams.get(victim)
    if ta is None or tb is None or ta == tb:
        return None
    return (ta, tb) if ta < tb else (tb, ta)


def _attach_kills(
    pairs: dict[tuple[int, int], list[_Segment]],
    combat: CombatTracker,
    teams: Mapping[str, int],
) -> int:
    """Put every cross-team kill onto an exchange. Returns how many did not fit.

    See the module docstring for why this is a separate step from segmentation
    and what the three rules measured at.
    """
    # (dbno maker, victim) -> [(knock time, segment)], newest last.
    by_knock: dict[tuple[str, str], list[tuple[float, _Segment]]] = {}
    for bucket in pairs.values():
        for seg in bucket:
            for knock in seg.knocks:
                key = (knock.attacker_account_id or "", knock.victim_account_id)
                by_knock.setdefault(key, []).append((knock.t_s, seg))
    for entries in by_knock.values():
        entries.sort(key=lambda e: e[0])

    unattached = 0
    for kill in combat.kills:
        if not kill.killer_account_id or kill.is_suicide or kill.is_team_kill:
            continue
        ta = teams.get(kill.killer_account_id)
        tb = teams.get(kill.victim_account_id)
        if ta is None or tb is None or ta == tb:
            continue
        pair = (ta, tb) if ta < tb else (tb, ta)
        bucket = pairs.get(pair, ())

        # 1. Inside the exchange. The tolerance is two milliseconds, not a
        #    window: it absorbs float round-trips through `t_s`, nothing more.
        found = next(
            (s for s in bucket if s.t_start_s - 0.002 <= kill.t_s <= s.t_end_s + 0.002),
            None,
        )

        # 2. The knock PUBG itself linked to this death. No threshold — this is
        #    the rule that puts a bleed-out back onto the fight that caused it,
        #    which at a median lag of 8 s past the exchange nothing else would.
        #    The knock's segment must be this same pair: a squad can knock
        #    someone another squad then finishes, and PUBG credits the kill to
        #    the finisher's side.
        if found is None and kill.dbno_maker_account_id:
            key = (kill.dbno_maker_account_id, kill.victim_account_id)
            found = next(
                (
                    seg
                    for t_s, seg in reversed(by_knock.get(key, ()))
                    if t_s <= kill.t_s + 0.002 and (seg.team_a, seg.team_b) == pair
                ),
                None,
            )

        # 3. The pair's last exchange, bounded by the same gap that segmented
        #    it. In practice this is a millisecond fixer, not a lookback: the
        #    fatal `LogPlayerTakeDamage` and the `LogPlayerKillV2` after it are
        #    separate events with separate timestamps.
        if found is None:
            reachable = [
                s
                for s in bucket
                if s.t_end_s <= kill.t_s and kill.t_s - s.t_end_s <= ENGAGEMENT_GAP_S
            ]
            found = max(reachable, key=lambda s: s.t_end_s, default=None)

        if found is None:
            unattached += 1
        else:
            found.kills.append(kill)
    return unattached


def _third_parties(segments: list[_Segment]) -> dict[int, int]:
    """`seq -> the team that turned up while this fight was happening`.

    A third party is another exchange that **shares exactly one team** with
    this one, **overlaps it in time**, and whose centre is within
    `THIRD_PARTY_RADIUS_CM`. Sharing a team is what makes it a third party
    rather than an unrelated fight nearby: someone here is being shot at from
    two directions.

    Quadratic in the number of engagements, which is ~120 per match, so ~14k
    comparisons — not worth an interval tree.

    Ties break on the earliest start, so the answer does not depend on
    iteration order.
    """
    centres = [_centre(s) for s in segments]
    out: dict[int, int] = {}
    for i, seg in enumerate(segments):
        here = centres[i]
        mine = {seg.team_a, seg.team_b}
        best: tuple[float, int] | None = None
        for j, other in enumerate(segments):
            if i == j:
                continue
            theirs = {other.team_a, other.team_b}
            shared = mine & theirs
            if len(shared) != 1:
                continue
            if other.t_end_s < seg.t_start_s or other.t_start_s > seg.t_end_s:
                continue
            there = centres[j]
            if here is None or there is None:
                continue
            if math.dist(here, there) > THIRD_PARTY_RADIUS_CM:
                continue
            outsider = next(iter(theirs - shared))
            if best is None or other.t_start_s < best[0]:
                best = (other.t_start_s, outsider)
        if best is not None:
            out[i] = best[1]
    return out


def _centre(seg: _Segment) -> tuple[float, float] | None:
    """Midpoint of every endpoint of every hit — shooters included.

    Not the victims' centroid. At 300 m one side stands still and the other
    does the dying, so a victim-only centroid puts the fight on top of the team
    that lost it. Both ends together is the only symmetric answer available.

    None when the exchange has no hit at all, which happens when the only
    events are knocks — `Knock` carries the victim's position but not the
    attacker's, so it cannot contribute a symmetric point.
    """
    if not seg.hits:
        return None
    xs = [h.attacker_x for h in seg.hits] + [h.victim_x for h in seg.hits]
    ys = [h.attacker_y for h in seg.hits] + [h.victim_y for h in seg.hits]
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def _range_cm(hit: Hit) -> float:
    return math.dist((hit.attacker_x, hit.attacker_y), (hit.victim_x, hit.victim_y))


def _engagement_row(
    match_id: str,
    seq: int,
    seg: _Segment,
    third_party: int | None,
    teams: Mapping[str, int],
) -> dict[str, Any]:
    a, b = _Side(), _Side()

    def side(account: str) -> _Side:
        return a if teams.get(account) == seg.team_a else b

    for hit in seg.hits:
        s = side(hit.attacker_account_id)
        s.hits += 1
        s.damage += hit.damage
    for knock in seg.knocks:
        side(knock.attacker_account_id or "").knocks += 1
    for kill in seg.kills:
        side(kill.killer_account_id or "").kills += 1

    centre = _centre(seg)
    first = seg.hits[0] if seg.hits else None
    ranges = [_range_cm(h) for h in seg.hits]

    return {
        "match_id": match_id,
        "seq": seq,
        "t_start_s": seg.t_start_s,
        "t_end_s": seg.t_end_s,
        "team_a": seg.team_a,
        "team_b": seg.team_b,
        "x": None if centre is None else centre[0],
        "y": None if centre is None else centre[1],
        # **"Who landed the first blow", never "who started it."**
        # `LogPlayerAttack` has no victim, so the shot that opened a fight and
        # missed is not attributable to anyone — the first *hit* is the
        # earliest thing that is. A team that fired first and missed reads here
        # as the team that got shot at, and no column in this table can fix
        # that. Naming it accurately is the whole mitigation.
        "first_hit_account_id": None if first is None else first.attacker_account_id,
        "first_hit_team_id": (
            None if first is None else teams.get(first.attacker_account_id)
        ),
        "first_hit_range_cm": None if first is None else _range_cm(first),
        #: The closest the two sides got, over the exchange's hits. Says
        #: whether a long-range trade ever turned into a fight.
        "min_range_cm": min(ranges) if ranges else None,
        "hits_a": a.hits,
        "hits_b": b.hits,
        "dmg_a_to_b": a.damage,
        "dmg_b_to_a": b.damage,
        "knocks_a": a.knocks,
        "knocks_b": b.knocks,
        "kills_a": a.kills,
        "kills_b": b.kills,
        "third_party_team_id": third_party,
    }


def _participant_rows(
    match_id: str, seq: int, seg: _Segment, teams: Mapping[str, int]
) -> list[dict[str, Any]]:
    """One row per account that dealt or took a blow in this engagement.

    This is the table "why did we lose that fight" is answered from: it is the
    only place that says a specific player took 180 damage and dealt 12.
    """
    actors: dict[str, _Actor] = {}

    def actor(account: str) -> _Actor:
        got = actors.get(account)
        if got is None:
            got = actors[account] = _Actor(team_id=teams.get(account, 0))
        return got

    for hit in seg.hits:
        dealt = actor(hit.attacker_account_id)
        dealt.hits_dealt += 1
        dealt.damage_dealt += hit.damage
        taken = actor(hit.victim_account_id)
        taken.hits_taken += 1
        taken.damage_taken += hit.damage
    for knock in seg.knocks:
        if knock.attacker_account_id:
            actor(knock.attacker_account_id).knocks += 1
        actor(knock.victim_account_id).was_knocked = True
    for kill in seg.kills:
        if kill.killer_account_id:
            actor(kill.killer_account_id).kills += 1
        actor(kill.victim_account_id).died = True

    return [
        {
            "match_id": match_id,
            "seq": seq,
            "account_id": account,
            "team_id": act.team_id,
            "hits_dealt": act.hits_dealt,
            "hits_taken": act.hits_taken,
            "damage_dealt": act.damage_dealt,
            "damage_taken": act.damage_taken,
            "knocks": act.knocks,
            "kills": act.kills,
            "was_knocked": act.was_knocked,
            "died": act.died,
        }
        # Sorted so a reparse writes the same rows in the same order.
        for account, act in sorted(actors.items())
    ]
