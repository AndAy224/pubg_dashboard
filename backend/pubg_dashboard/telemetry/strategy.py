"""Per-participant strategy metrics: what each player actually did, as numbers.

This module consumes **no events**. It post-processes the trackers that already
ran — `FrameIndex`, `WorldTracker`, `CombatTracker`, `InventoryTracker` — into
one `strategy_metrics` row per participant, so the strategy page can ask
"what do we do differently in matches where we place high?" with SQL.

The measurement traps, all inherited from the position track:

* Position samples are ~10 s apart and enriched irregularly by combat events,
  so dwell time is *gap to the next sample, clamped* (`DWELL_CAP_S`). Unclamped,
  one quiet minute in the blue zone between samples books the whole minute to
  whatever the earlier sample said.
* Every positional metric is gated on the player's **first parachute landing**.
  `isInVehicle` includes the match-start aircraft, teammate distance during the
  flight is a meaningless zero, and the first circle is usually announced while
  half the lobby is still airborne — so the rotation clock starts at
  `max(announcement, landing)`.
* `FLAG_ALIVE` means *still in the match*, knocked included — correct here:
  a knocked player crawling to the circle edge is still spending time in blue.
* The white circle is a step function that only ever announces a **smaller**
  circle. Within one match its radius takes one discrete value per phase, so an
  announcement is "the (x, y, r) tuple changed to a real radius". Radii at or
  above `WHITE_R_PLACEHOLDER_CM` are the pre-game whole-map placeholder, not a
  circle anyone rotates to.
* A player can land twice (flare-gun redeploy); the drop is the **first**
  landing, which is what `FrameIndex.landing` records.
"""

from __future__ import annotations

import itertools
import math
from bisect import bisect_left
from collections.abc import Mapping
from typing import Any, Final

from pubg_dashboard.telemetry.combat import CombatTracker
from pubg_dashboard.telemetry.frames import (
    FLAG_ALIVE,
    FLAG_BLUE_ZONE,
    FLAG_PARACHUTING,
    FrameIndex,
    Sample,
)
from pubg_dashboard.telemetry.inventory import (
    OP_ADD_LOOSE,
    OP_EQUIP,
    SLOT_PRIMARY1,
    SLOT_PRIMARY2,
    SLOT_SIDEARM,
    InventoryTracker,
)
from pubg_dashboard.telemetry.world import WorldTracker

__all__ = ["compute_strategy"]

#: Longest gap one blue-zone sample may account for. The position cadence is
#: ~10 s while alive, so a larger gap means the track went quiet (spectating a
#: teammate's fight, lost events) rather than 40 s of standing in the zone.
DWELL_CAP_S: Final = 15.0

#: "Early game" boundary for the aggression metrics, seconds after t0. The
#: first circle closes around 8 minutes in; fights before that are drop fights.
EARLY_WINDOW_S: Final = 480.0

#: Looting window after landing for `early_pickups_n`.
LOOT_WINDOW_MS: Final = 300_000

#: A landing is "contested" by anyone off-team landing this close, this soon.
HOT_DROP_RADIUS_CM: Final = 20_000.0  # 200 m
HOT_DROP_WINDOW_MS: Final = 60_000

#: "Sticking together" threshold for `teammate_near_pct`.
NEAR_TEAMMATE_CM: Final = 10_000.0  # 100 m

#: A teammate position older/newer than this cannot be paired with a sample —
#: at driving speed the answer would be off by hundreds of metres.
TEAMMATE_PAIR_MS: Final = 15_000

#: White radii at or above this are the pre-game placeholder (observed 500 000),
#: not a real circle. The largest real first circle in the corpus is far below.
WHITE_R_PLACEHOLDER_CM: Final = 450_000.0

_WEAPON_SLOTS: Final = frozenset({SLOT_PRIMARY1, SLOT_PRIMARY2, SLOT_SIDEARM})


def compute_strategy(
    *,
    match_id: str,
    frames: FrameIndex,
    world: WorldTracker,
    combat: CombatTracker,
    inventory: InventoryTracker,
    teams: Mapping[str, int],
    t0_ms: int,
) -> list[dict[str, Any]]:
    """One `strategy_metrics` row per roster account.

    `teams` maps account_id -> team_id for the whole roster, bots included.
    Rows are computed for everyone — filtering bots is a query-time join, and
    an opponent baseline is free once the rows exist.
    """
    samples = {a: frames.samples_for(a) for a in teams}
    times = {a: [s.t_ms for s in ss] for a, ss in samples.items()}
    landings = {a: frames.landing(a) for a in teams}
    announcements = _announcements(world)

    first_engage: dict[str, float] = {}
    dealt_early: dict[str, float] = {}
    taken_early: dict[str, float] = {}
    _combat_timing(combat, first_engage, dealt_early, taken_early)

    first_equip_ms: dict[str, int] = {}
    early_pickups: dict[str, int] = {}
    for d in inventory.deltas:
        if d.op == OP_EQUIP and d.slot in _WEAPON_SLOTS:
            prev = first_equip_ms.get(d.account_id)
            if prev is None or d.t_ms < prev:
                first_equip_ms[d.account_id] = d.t_ms
        elif d.op == OP_ADD_LOOSE:
            landing = landings.get(d.account_id)
            if landing is not None and 0 <= d.t_ms - landing[0] <= LOOT_WINDOW_MS:
                early_pickups[d.account_id] = early_pickups.get(d.account_id, 0) + 1

    rows: list[dict[str, Any]] = []
    for account, team_id in teams.items():
        ss = samples[account]
        landing = landings[account]
        land_ms = landing[0] if landing else None

        mates = [
            (samples[b], times[b])
            for b, tid in teams.items()
            if b != account and tid == team_id
        ]
        dist_avg, near_pct = (
            _teammate_spread(ss, land_ms, mates) if mates else (None, None)
        )

        stats = combat.players.get(account)
        first_weapon_s = None
        if land_ms is not None and account in first_equip_ms:
            first_weapon_s = max(0.0, (first_equip_ms[account] - land_ms) / 1000.0)

        rows.append(
            {
                "match_id": match_id,
                "account_id": account,
                "blue_s": _blue_dwell(ss, land_ms),
                "blue_damage": stats.blue_zone_damage if stats else 0.0,
                "rotate_lag_s": _rotate_lag(
                    ss, times[account], land_ms, announcements, t0_ms
                ),
                "teammate_dist_avg_cm": dist_avg,
                "teammate_near_pct": near_pct,
                "hot_drop_n": _hot_drop(account, team_id, landings, teams),
                "first_engage_s": first_engage.get(account),
                "dmg_dealt_early": dealt_early.get(account, 0.0),
                "dmg_taken_early": taken_early.get(account, 0.0),
                "first_weapon_s": first_weapon_s,
                "early_pickups_n": early_pickups.get(account) if land_ms is not None else None,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# zone discipline
# ---------------------------------------------------------------------------
def _blue_dwell(ss: list[Sample], land_ms: int | None) -> float | None:
    """Seconds spent in the blue zone: flagged samples' clamped forward gaps."""
    if land_ms is None:
        return None
    total = 0.0
    for s0, s1 in itertools.pairwise(ss):
        if s0.t_ms < land_ms:
            continue
        if not (s0.flags & FLAG_ALIVE) or (s0.flags & FLAG_PARACHUTING):
            continue
        if s0.flags & FLAG_BLUE_ZONE:
            total += min((s1.t_ms - s0.t_ms) / 1000.0, DWELL_CAP_S)
    return total


def _announcements(world: WorldTracker) -> list[tuple[float, float, float, float]]:
    """`(t_s, x, y, r)` for each real white-circle announcement, in order."""
    out: list[tuple[float, float, float, float]] = []
    prev: tuple[float, float, float] | None = None
    for z in world.zones:
        cur = (z.white_x, z.white_y, z.white_r)
        if cur != prev:
            prev = cur
            if 0.0 < z.white_r < WHITE_R_PLACEHOLDER_CM:
                out.append((z.t_s, z.white_x, z.white_y, z.white_r))
    return out


def _rotate_lag(
    ss: list[Sample],
    ts: list[int],
    land_ms: int | None,
    announcements: list[tuple[float, float, float, float]],
    t0_ms: int,
) -> float | None:
    """Mean seconds from a circle announcement to first being inside it.

    The clock starts at `max(announcement, landing)` — nobody rotates from the
    aircraft. A phase the player never entered before elimination contributes
    nothing rather than a penalty: a death outside the circle is already
    visible in placement, and inventing a lag for it would double-count.
    """
    if land_ms is None or not announcements:
        return None
    land_rel_s = (land_ms - t0_ms) / 1000.0
    lags: list[float] = []
    for t_a, cx, cy, r in announcements:
        start_s = max(t_a, land_rel_s)
        i = bisect_left(ts, t0_ms + int(start_s * 1000.0))
        for s in ss[i:]:
            if not (s.flags & FLAG_ALIVE):
                break  # eliminated; later samples have the bit cleared
            if math.hypot(s.x - cx, s.y - cy) <= r:
                lags.append(max(0.0, (s.t_ms - t0_ms) / 1000.0 - start_s))
                break
    if not lags:
        return None
    return sum(lags) / len(lags)


# ---------------------------------------------------------------------------
# squad spread
# ---------------------------------------------------------------------------
def _teammate_spread(
    ss: list[Sample],
    land_ms: int | None,
    mates: list[tuple[list[Sample], list[int]]],
) -> tuple[float | None, float | None]:
    """(mean distance to nearest living teammate in cm, fraction within 100 m).

    Pairs each of the player's samples with every teammate's nearest-in-time
    sample; a teammate whose track has no sample within `TEAMMATE_PAIR_MS`
    (dead, disconnected, event gap) simply drops out of that instant.
    """
    if land_ms is None:
        return (None, None)
    dist_sum = 0.0
    n = 0
    near = 0
    for s in ss:
        if s.t_ms < land_ms:
            continue
        if not (s.flags & FLAG_ALIVE) or (s.flags & FLAG_PARACHUTING):
            continue
        best: float | None = None
        for mate_samples, mate_ts in mates:
            # The mate's nearest-in-time sample — by |Δt|, never by distance.
            # Choosing whichever bracketing sample is *closer in space* would
            # systematically understate the spread.
            j = bisect_left(mate_ts, s.t_ms)
            m = None
            for k in (j - 1, j):
                if 0 <= k < len(mate_samples):
                    cand = mate_samples[k]
                    if m is None or abs(cand.t_ms - s.t_ms) < abs(m.t_ms - s.t_ms):
                        m = cand
            if (
                m is not None
                and abs(m.t_ms - s.t_ms) <= TEAMMATE_PAIR_MS
                and (m.flags & FLAG_ALIVE)
            ):
                d = math.hypot(m.x - s.x, m.y - s.y)
                if best is None or d < best:
                    best = d
        if best is not None:
            dist_sum += best
            n += 1
            if best <= NEAR_TEAMMATE_CM:
                near += 1
    if n == 0:
        return (None, None)
    return (dist_sum / n, near / n)


# ---------------------------------------------------------------------------
# drop & combat timing
# ---------------------------------------------------------------------------
def _hot_drop(
    account: str,
    team_id: int,
    landings: Mapping[str, tuple[int, float, float] | None],
    teams: Mapping[str, int],
) -> int | None:
    """Off-team players landing within 200 m and ±60 s of this player."""
    landing = landings.get(account)
    if landing is None:
        return None
    lt, lx, ly = landing
    n = 0
    for other, other_landing in landings.items():
        if other == account or other_landing is None or teams.get(other) == team_id:
            continue
        ot, ox, oy = other_landing
        close = math.hypot(ox - lx, oy - ly) <= HOT_DROP_RADIUS_CM
        if close and abs(ot - lt) <= HOT_DROP_WINDOW_MS:
            n += 1
    return n


def _combat_timing(
    combat: CombatTracker,
    first_engage: dict[str, float],
    dealt_early: dict[str, float],
    taken_early: dict[str, float],
) -> None:
    """First engagement time and early-game damage, from attributed combat.

    "Engagement" is any attributed hit, knock or kill the player was on either
    end of. `LogPlayerAttack` (shots that missed) is deliberately not consulted:
    it has no victim, so it cannot distinguish sighting-in on a rock from a
    fight, and throwables double-report through it.
    """

    def note(account: str | None, t_s: float) -> None:
        if account and t_s >= 0.0 and t_s < first_engage.get(account, math.inf):
            first_engage[account] = t_s

    for h in combat.hits:
        note(h.attacker_account_id, h.t_s)
        note(h.victim_account_id, h.t_s)
        if 0.0 <= h.t_s <= EARLY_WINDOW_S:
            dealt_early[h.attacker_account_id] = (
                dealt_early.get(h.attacker_account_id, 0.0) + h.damage
            )
            taken_early[h.victim_account_id] = (
                taken_early.get(h.victim_account_id, 0.0) + h.damage
            )
    for knock in combat.knocks:
        note(knock.attacker_account_id, knock.t_s)
        note(knock.victim_account_id, knock.t_s)
    for kill in combat.kills:
        note(kill.killer_account_id, kill.t_s)
        note(kill.victim_account_id, kill.t_s)
