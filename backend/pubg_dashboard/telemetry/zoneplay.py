"""Circle discipline: where each player stood when each zone phase moved.

Consumes **no events** — post-processes `FrameIndex` and `WorldTracker`, the
same shape as `strategy.py`, and is hooked in beside it.

`strategy_metrics.rotate_lag_s` answers "how long after a circle appeared were
we inside it" with a heuristic built from position samples. This module answers
the sharper question with **PUBG's own roster**: `LogPhaseChange` carries
`playersInWhiteCircle`, so "were we inside" needs no geometry at all.

### The two instants per phase

`LogPhaseChange` fires twice for every phase, and `common.isGame` separates
them exactly (see `events.phase_kind`):

* **announce** (`isGame == phase - 0.5`, or `0.1` for phase 1) — the white
  circle has appeared. The blue is still at the previous phase's radius.
* **close** (`isGame == phase`) — the blue has *started* shrinking toward it.

Confirmed from the radii rather than inferred from the gaps: at phase 2's
announce the blue reads 1921 m and the new white 1056 m; eighty seconds later
at the close the blue reads 1835 m — it has begun to move, not finished. The
gap is 240 s for phase 1 and 80/80/80/80/60 s after, PUBG's published timings.

**The close is the rotation deadline.** Being outside the next circle when the
blue starts moving is the thing that costs a squad the game; being outside when
it is first announced is normal and is how most of the lobby starts every
phase. Both are recorded because they are different questions.

### Why the geometry is kept anyway

`in_circle_*` is exact. `dist_to_white_edge_cm` is derived from the position
track, which samples at ~10 s, so it can disagree — and `sample_lag_ms` says by
how much. The disagreement is the test: two independent streams agreeing is
evidence the coordinate transform is right, and a wrong transform still draws a
perfectly plausible circle.
"""

from __future__ import annotations

import math
from bisect import bisect_left
from collections.abc import Mapping
from typing import Any, Final

from pubg_dashboard.telemetry import events as E
from pubg_dashboard.telemetry.frames import (
    FLAG_ALIVE,
    FLAG_IN_VEHICLE,
    FrameIndex,
    Sample,
)
from pubg_dashboard.telemetry.strategy import WHITE_R_PLACEHOLDER_CM
from pubg_dashboard.telemetry.world import WorldTracker

__all__ = ["compute_zone_play"]

#: A position sample further than this from a phase instant cannot describe
#: where the player was standing. The cadence is ~10 s, so this admits the
#: normal case and rejects a track that went quiet.
MAX_SAMPLE_LAG_MS: Final = 15_000


def compute_zone_play(
    *,
    match_id: str,
    frames: FrameIndex,
    world: WorldTracker,
    teams: Mapping[str, int],
    t0_ms: int,
) -> list[dict[str, Any]]:
    """One row per (account, phase) that had at least one usable instant.

    Rows are written for **every** participant, bots included — filtering is a
    query-time join on `participants.is_bot`, and a lobby baseline ("were the
    teams that beat us inside the circle at phase 4?") is free once the rows
    exist. That is the same reasoning `strategy_metrics` uses.

    `t0_ms` is required and is not optional bookkeeping: **`Sample.t_ms` is
    absolute epoch milliseconds while `PhaseChange.t_s` is seconds relative to
    t0.** Comparing them directly finds no sample within any sane window, and
    the failure is silent — rows still appear, `in_circle_*` is still correct
    because it comes from the roster, and every geometry column is quietly
    NULL. It looked like working output on the first run.

    A phase the player never saw produces **no row at all**, rather than a row
    of nulls: "dead before phase 6" and "alive outside the circle at phase 6"
    are different facts and must not collapse into the same shape.
    """
    by_phase: dict[int, dict[str, Any]] = {}
    for change in world.phases:
        if change.phase <= 0:
            continue
        slot = by_phase.setdefault(change.phase, {})
        # Two events per phase, and the later one wins per kind — a duplicate
        # would otherwise depend on file order, which is not time order.
        key = change.kind
        prev = slot.get(key)
        if prev is None or change.t_s >= prev.t_s:
            slot[key] = change

    if not by_phase:
        return []

    samples = {a: frames.samples_for(a) for a in teams}
    times = {a: [s.t_ms for s in ss] for a, ss in samples.items()}

    rows: list[dict[str, Any]] = []
    for phase in sorted(by_phase):
        announce = by_phase[phase].get(E.PHASE_ANNOUNCE)
        close = by_phase[phase].get(E.PHASE_CLOSE)
        # A match can end on an announcement that never closes — measured, 6
        # of 184 phases across 23 matches — so neither side may be assumed.
        if announce is None and close is None:
            continue

        in_at_announce = set(announce.in_circle) if announce is not None else None
        in_at_close = set(close.in_circle) if close is not None else None

        # The instant the geometry is measured at is the deadline, not the
        # announcement — "where were we when the blue started moving".
        geom_t = close.t_s if close is not None else announce.t_s  # type: ignore[union-attr]

        # Read the circle at that same instant, **not at the announce**.
        # `white_circle_at` snaps to the last periodic sample at or before the
        # time asked for, and the announcement fires in the same second the
        # white circle updates — so asking at the announce returns the
        # *previous* phase's circle about half the time. That produced rows
        # where `in_circle_at_close` and the distance disagreed on 48% of
        # rows, with the disagreements at *lower* sample lag than the
        # agreements, which is how it was caught: staleness cannot explain a
        # pattern that runs the wrong way. Between a close and the next
        # phase's announce the white circle is constant, so this instant is
        # unambiguous.
        circle = world.white_circle_at(geom_t)
        if circle is not None and not (0.0 < circle[2] < WHITE_R_PLACEHOLDER_CM):
            # The pre-game whole-map placeholder is not a circle anyone
            # rotates to.
            circle = None

        for account in teams:
            row = _row(
                match_id=match_id,
                account=account,
                phase=phase,
                announce_t_s=None if announce is None else announce.t_s,
                close_t_s=None if close is None else close.t_s,
                in_at_announce=in_at_announce,
                in_at_close=in_at_close,
                circle=circle,
                geom_t_ms=t0_ms + int(geom_t * 1000),
                ss=samples[account],
                ts=times[account],
            )
            if row is not None:
                rows.append(row)
    return rows


def _row(
    *,
    match_id: str,
    account: str,
    phase: int,
    announce_t_s: float | None,
    close_t_s: float | None,
    in_at_announce: set[str] | None,
    in_at_close: set[str] | None,
    circle: tuple[float, float, float] | None,
    geom_t_ms: int,
    ss: list[Sample],
    ts: list[int],
) -> dict[str, Any] | None:
    sample = _nearest(ss, ts, geom_t_ms)
    alive = bool(sample is not None and sample[0].flags & FLAG_ALIVE)

    # No track anywhere near this phase and not named in either roster: the
    # player was not in the match at this point. Emitting a row of nulls would
    # make "eliminated in phase 2" indistinguishable from "outside the circle".
    named = (in_at_announce is not None and account in in_at_announce) or (
        in_at_close is not None and account in in_at_close
    )
    if sample is None and not named:
        return None

    dist_centre: float | None = None
    dist_edge: float | None = None
    if sample is not None and circle is not None:
        cx, cy, r = circle
        dist_centre = math.dist((sample[0].x, sample[0].y), (cx, cy))
        # Signed: negative is inside, so a single column orders naturally from
        # "deep in the circle" to "far outside it".
        dist_edge = dist_centre - r

    return {
        "match_id": match_id,
        "account_id": account,
        "phase": phase,
        "announce_t_s": announce_t_s,
        "close_t_s": close_t_s,
        # None, not False, when that half of the pair never fired — "we were
        # outside" and "the match ended first" are different answers.
        "in_circle_at_announce": None if in_at_announce is None else account in in_at_announce,
        "in_circle_at_close": None if in_at_close is None else account in in_at_close,
        "dist_to_white_centre_cm": dist_centre,
        "dist_to_white_edge_cm": dist_edge,
        "white_r_cm": None if circle is None else circle[2],
        "alive_at_close": alive,
        "in_vehicle_at_close": (
            None if sample is None else bool(sample[0].flags & FLAG_IN_VEHICLE)
        ),
        #: How stale the position was. The cadence is ~10 s, so a phase read
        #: against a 9-second-old sample is a different quality of fact from
        #: one read against a 0.5-second-old sample, and the corpus test uses
        #: this to explain disagreements rather than tolerate them blindly.
        "sample_lag_ms": None if sample is None else sample[1],
    }


def _nearest(ss: list[Sample], ts: list[int], t_ms: int) -> tuple[Sample, int] | None:
    """The position sample nearest in time to `t_ms`, with its lag in ms.

    **`t_ms` is absolute epoch milliseconds**, matching `Sample.t_ms`. Callers
    holding a phase time must add `t0_ms` first; passing relative seconds here
    silently matches nothing at all.

    **Nearest in time, not the last one before.** `strategy.py` learned this
    the hard way for teammate pairing: picking whichever bracketing sample
    suits systematically biases the answer, and here taking the earlier sample
    would report where a player was up to ten seconds before the deadline —
    which at driving speed is most of a kilometre.
    """
    if not ts:
        return None
    target = t_ms
    i = bisect_left(ts, target)
    best: tuple[Sample, int] | None = None
    for j in (i - 1, i):
        if 0 <= j < len(ss):
            lag = abs(ts[j] - target)
            if best is None or lag < best[1]:
                best = (ss[j], lag)
    if best is None or best[1] > MAX_SAMPLE_LAG_MS:
        return None
    return best
