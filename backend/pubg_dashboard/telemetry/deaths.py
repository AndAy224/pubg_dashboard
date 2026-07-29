"""Where the victim stood, and who was left, at the instant of each death.

Consumes **no events** — post-processes `FrameIndex` against `CombatTracker`'s
kills, the same shape as `strategy.py` and `zoneplay.py`.

Everything else about a death is already in SQL. `kill_events` says who did it,
with what, from how far; `dbno_maker_account_id` says whether it started as a
knock; `zone_play` says whether the victim was inside the last circle;
`engagements` says whether a third team was there. **Two facts are not, and
cannot be**, because they live in the position track and nothing persists it:
how far the nearest living teammate was, and how many were still up.

So this module computes exactly those, and nothing that SQL can already answer.
A death classification derived here would be a copy of one derivable from a
join, and copies go stale on the next parser version while the join does not.

### The position at death is exact, not sampled

`zone_play` has to carry `sample_lag_ms` because a phase instant falls wherever
it falls in a ~10 s position cadence. A death does not: `LogPlayerKillV2`
carries the victim's own `Character` block, `FrameIndex` feeds off it, and the
sample lands on the death millisecond. Measured over 1,918 deaths the lag is a
**median of 1 ms and a p90 of 32 ms**, and not one death lacked a sample.

The lag is still recorded, because the number that needs watching is the
*teammate's*, not the victim's — a teammate 15 s stale is most of a kilometre
away at driving speed, and `TEAMMATE_PAIR_MS` drops those rather than pretend.
"""

from __future__ import annotations

import math
from bisect import bisect_left
from collections.abc import Mapping
from typing import Any

from pubg_dashboard.telemetry.combat import CombatTracker
from pubg_dashboard.telemetry.frames import (
    FLAG_IN_VEHICLE,
    FrameIndex,
    Sample,
)
from pubg_dashboard.telemetry.strategy import TEAMMATE_PAIR_MS

__all__ = ["compute_death_context"]


def compute_death_context(
    *,
    combat: CombatTracker,
    frames: FrameIndex,
    teams: Mapping[str, int],
    t0_ms: int,
) -> dict[int, dict[str, Any]]:
    """`kill_events.seq` -> the victim's context, for every kill in the match.

    Keyed on `seq` so `_kill_rows` can merge it straight in: this is extra
    columns on the kill, not a table of its own. A kill whose victim has no
    usable track yields no entry at all, and the columns stay NULL — measured,
    that never happened in 1,918 deaths, which is exactly why it must not be
    written as a zero.

    Computed for **every** death, bots included. Same reasoning as
    `strategy_metrics` and `zone_play`: the lobby baseline is what makes a
    squad number mean anything, and it costs nothing once the rows exist.
    """
    by_team: dict[int, list[str]] = {}
    for account, team in teams.items():
        by_team.setdefault(team, []).append(account)

    samples = {a: frames.samples_for(a) for a in teams}
    times = {a: [s.t_ms for s in ss] for a, ss in samples.items()}

    out: dict[int, dict[str, Any]] = {}
    for kill in combat.kills:
        victim = kill.victim_account_id
        t_ms = t0_ms + int(kill.t_s * 1000)
        got = _nearest(samples.get(victim, ()), times.get(victim, ()), t_ms)
        if got is None:
            continue
        sample, lag = got

        nearest_cm: float | None = None
        alive = 0
        for mate in by_team.get(teams.get(victim, -1), ()):
            if mate == victim:
                continue
            # **Aliveness from the death time, position from the track.** Two
            # different questions, and only the second one is sampled.
            #
            # Reading `FLAG_ALIVE` off the nearest sample looks equivalent and
            # is not. `FrameIndex._resolve` clears the flag on every sample at
            # or after the account's final death, and a teammate who dies in
            # the same burst emits their death frame milliseconds later — so
            # `_nearest` returns that frame and reports them already gone.
            # Measured: 65 of 139 "died alone" deaths had a teammate whose own
            # death was **2 to 128 milliseconds** afterwards. Every one read as
            # dying alone, and the squad's duo rate came out at 92%, which is
            # what made it worth looking at.
            #
            # `death_ms` is the *final* death, so a player who died, redeployed
            # and is back in the match counts as alive in between — which is
            # the answer this question wants.
            mate_death = frames.death_ms(mate)
            if mate_death is not None and mate_death <= t_ms:
                continue
            alive += 1
            mate_got = _nearest(samples.get(mate, ()), times.get(mate, ()), t_ms)
            # A living teammate with no sample near this instant is counted
            # among the living but contributes no distance — they are
            # unmeasured, not far away, exactly as `_teammate_spread` treats
            # them. This is why `teammates_alive` can be non-zero while
            # `nearest_teammate_cm` is NULL.
            if mate_got is None:
                continue
            distance = math.hypot(mate_got[0].x - sample.x, mate_got[0].y - sample.y)
            if nearest_cm is None or distance < nearest_cm:
                nearest_cm = distance

        out[kill.seq] = {
            #: None means "nobody was left to be near", which is a different
            #: answer from "they were a long way off" and the reason
            #: `teammates_alive` travels beside it. The common case by a wide margin
            #: — solo modes, and the last member of every squad.
            "victim_nearest_teammate_cm": nearest_cm,
            "victim_teammates_alive": alive,
            #: **Exact, and rare: 1.0% of deaths.** Too thin to carry a
            #: category — the same call "died in the blue" got at 3.1%. It is
            #: one bit off a sample already loaded, so it is recorded and
            #: footnoted rather than turned into a bucket.
            "victim_in_vehicle": bool(sample.flags & FLAG_IN_VEHICLE),
            #: There is no `victim_parachuting`, and its absence is deliberate.
            #: v17 recorded one from `FLAG_PARACHUTING`, which means **the
            #: match is in its plane phase** rather than "this player is under
            #: a canopy" — so it was set for anyone who dropped early and was
            #: already fighting. 42 of the 62 deaths it marked had landed.
            #: Measured properly, against each player's own
            #: `LogParachuteLanding`, exactly **one death in 1,918** was
            #: airborne, and that one was a flare-gun redeploy at 364 s. Far
            #: below the bar that made "in a vehicle" a footnote at 1.0%.
            "victim_sample_lag_ms": lag,
        }
    return out


def _nearest(
    ss: list[Sample] | tuple[()], ts: list[int] | tuple[()], t_ms: int
) -> tuple[Sample, int] | None:
    """Nearest sample in time, or None past `TEAMMATE_PAIR_MS`.

    **Nearest in time, never nearest in space.** Picking whichever bracketing
    teammate sample happens to be closer would systematically understate every
    distance here — the same trap `strategy._teammate_spread` documents, and
    the reason both do it the same way.
    """
    if not ts:
        return None
    i = bisect_left(ts, t_ms)
    best: tuple[Sample, int] | None = None
    for j in (i - 1, i):
        if 0 <= j < len(ss):
            lag = abs(ts[j] - t_ms)
            if best is None or lag < best[1]:
                best = (ss[j], lag)
    if best is None or best[1] > TEAMMATE_PAIR_MS:
        return None
    return best
