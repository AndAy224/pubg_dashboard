"""Squad retrospective: how we actually lose, in counts.

Every figure here comes from `kill_events`, `knock_events` and `participants` —
tables that have been populated since parser v11. **Nothing in this router
needs a reparse**, which is why it ships first.

Like `strategy.py`, the endpoints return **rows, not conclusions**. The
sentences the Review page prints are built in `frontend/src/lib/findings.ts`,
where a pure function can be tested without a server, and where the rule that
every claim carries its `n` is enforced in one place.

Three constants below are judgement calls rather than wire facts —
`THIRD_PARTY_RADIUS_CM`, `THIRD_PARTY_WINDOW_S` and `EARLY_DEATH_S`. They are
returned to the client rather than left implicit, so the page can name them
instead of presenting a tuned number as a discovered one.

There was almost a fourth. Knock-to-kill conversion was first written as "the
victim's next death within N seconds", and the answer moved from 50% to 68% as
N swept 30-180 s with no knee anywhere in between — because a revived player
who dies again ten minutes later is indistinguishable, in that join, from a
slow bleed-out. `kill_events.dbno_maker_account_id` is the same question
already answered by the parser, with no threshold at all. Where a column like
that exists, use it; a tunable constant in a rate is a place for a plausible
wrong number to live.
"""

from __future__ import annotations

from typing import Annotated, Final

from fastapi import APIRouter, Query
from sqlalchemy import case, exists, func, or_, select
from sqlalchemy.sql import ColumnElement

from pubg_dashboard.api.deps import career_filter
from pubg_dashboard.api.schemas import (
    DeathCauseRow,
    FirstDeathRow,
    KnockConversion,
    RangeBandRow,
    Rate,
    SessionRow,
    SquadReview,
)
from pubg_dashboard.db.models import KillEvent, KnockEvent, Match, Participant, Player
from pubg_dashboard.db.session import SessionDep

router = APIRouter(tags=["review"])

#: How close another team's kill must be to count as a third party on our
#: death. 200 m is the same radius `strategy_metrics.hot_drop_n` uses for a
#: contested drop, kept identical so the two numbers mean the same "nearby".
THIRD_PARTY_RADIUS_CM: Final = 20_000.0

#: ...and how long before our death. Beyond half a minute the other fight is a
#: separate event that happened to be close by.
THIRD_PARTY_WINDOW_S: Final = 30.0

#: "Died early". The first circle finishes closing around 5.5 minutes in
#: (measured: phase 1 announces at ~91 s and the blue starts moving at ~330 s),
#: so a death inside 5 minutes is a drop fight, not a rotation.
EARLY_DEATH_S: Final = 300.0

#: Kill-distance bands, in metres. Open-ended at the top: the longest kill in
#: the corpus is far beyond any band worth drawing.
_RANGE_BANDS: Final[tuple[tuple[int, int | None], ...]] = (
    (0, 10),
    (10, 50),
    (50, 100),
    (100, 200),
    (200, None),
)

#: Matches further apart than this start a new session — the same three hours
#: `players.py` uses, so the two surfaces cannot disagree about what an evening
#: is.
SESSION_GAP_S: Final = 3 * 3600


def _tracked_ids() -> ColumnElement:
    """Account ids of tracked players.

    `players.tracked`, never "has a `players` row": the table holds a row per
    human **opponent** too — 4,338 of 4,341 rows are untracked and never were —
    so membership in `players` is a different question entirely.
    """
    return select(Player.account_id).where(Player.tracked).scalar_subquery()


def _career_matches() -> ColumnElement:
    return select(Match.match_id).where(career_filter()).scalar_subquery()


def _rate(n: int, total: int) -> Rate:
    """`pct` is None on an empty denominator, never 0.0."""
    return Rate(n=n, total=total, pct=(n / total if total else None))


@router.get("/review/squad", response_model=SquadReview)
async def squad_review(session: SessionDep) -> SquadReview:
    """How the squad dies, and what it does with a knock.

    Career matches only, so this and the career stats are drawn from the same
    population.
    """
    career = _career_matches()
    tracked = _tracked_ids()

    # --- denominators -----------------------------------------------------
    matches = (
        await session.execute(
            select(func.count(func.distinct(Participant.match_id)))
            .where(Participant.match_id.in_(career), Participant.account_id.in_(tracked))
        )
    ).scalar_one()

    # A death is a `kill_events` row where we are the victim. Suicides are
    # excluded: they are a real death but not a thing an opponent did, and
    # every rate below is about opponents.
    ours = (
        select(KillEvent)
        .where(
            KillEvent.match_id.in_(career),
            KillEvent.victim_account_id.in_(tracked),
            KillEvent.is_suicide.is_(False),
        )
        .subquery()
    )

    deaths = (await session.execute(select(func.count()).select_from(ours))).scalar_one()

    # --- third party ------------------------------------------------------
    # Another team's kill, near us, just before ours. "Another team" excludes
    # both the team that killed us and our own, or a squad wiping us in
    # sequence would count itself as a third party on every member after the
    # first.
    other = KillEvent.__table__.alias("other")
    third_party_pred = exists(
        select(1)
        .select_from(other)
        .where(
            other.c.match_id == ours.c.match_id,
            other.c.seq != ours.c.seq,
            other.c.t_s.between(ours.c.t_s - THIRD_PARTY_WINDOW_S, ours.c.t_s),
            other.c.killer_team_id.is_not(None),
            other.c.killer_team_id != ours.c.killer_team_id,
            other.c.killer_team_id != ours.c.victim_team_id,
            func.sqrt(
                func.power(other.c.victim_x - ours.c.victim_x, 2)
                + func.power(other.c.victim_y - ours.c.victim_y, 2)
            )
            < THIRD_PARTY_RADIUS_CM,
        )
    )

    # "Knocked, then finished" versus "killed outright". `dbno_maker` is
    # exactly this distinction already resolved by the parser — it is NULL when
    # nobody had knocked the victim first. Re-deriving it by looking for a
    # nearby `knock_events` row would need a time window, and a window here is
    # wrong in both directions: too tight and a slow bleed-out reads as an
    # outright kill, too loose and a revived player's later death gets
    # attributed to a knock they survived.
    knocked_pred = ours.c.dbno_maker_account_id.is_not(None)

    causes = (
        await session.execute(
            select(
                func.count().filter(third_party_pred),
                func.count().filter(knocked_pred),
                func.count().filter(~knocked_pred),
                func.count().filter(ours.c.t_s < EARLY_DEATH_S),
                func.count().filter(ours.c.killer_is_bot.is_(True)),
            ).select_from(ours)
        )
    ).one()
    n_third, n_knocked, n_outright, n_early, n_bot = (int(x or 0) for x in causes)

    # --- knock conversion, both directions --------------------------------
    knocks = await _knock_conversion(session, career, tracked)

    # --- who goes down first ----------------------------------------------
    first_deaths = await _first_deaths(session, career)

    # --- kill distance bands ----------------------------------------------
    range_bands = await _range_bands(session, career, tracked)

    # --- zone deaths, reported as a footnote, not a bucket ----------------
    zone_deaths = (
        await session.execute(
            select(func.count())
            .select_from(Participant)
            .where(
                Participant.match_id.in_(career),
                Participant.account_id.in_(tracked),
                Participant.death_type == "byzone",
            )
        )
    ).scalar_one()

    return SquadReview(
        matches=int(matches or 0),
        deaths=int(deaths or 0),
        third_party=_rate(n_third, int(deaths or 0)),
        third_party_radius_m=int(THIRD_PARTY_RADIUS_CM / 100),
        third_party_window_s=int(THIRD_PARTY_WINDOW_S),
        knocks=knocks,
        first_deaths=first_deaths,
        range_bands=range_bands,
        # Non-exclusive on purpose, and the labels say so: a death can be
        # third-partied *and* early *and* preceded by a knock. Forcing them
        # into a partition would need a precedence order nothing in the data
        # justifies.
        death_causes=[
            DeathCauseRow(cause="knocked_first", n=n_knocked, label="knocked, then finished"),
            DeathCauseRow(cause="outright", n=n_outright, label="killed outright"),
            DeathCauseRow(cause="third_partied", n=n_third, label="third-partied"),
            DeathCauseRow(
                cause="early", n=n_early, label=f"in the first {int(EARLY_DEATH_S / 60)} minutes"
            ),
            DeathCauseRow(cause="to_bot", n=n_bot, label="to a bot"),
        ],
        zone_deaths=int(zone_deaths or 0),
    )


async def _knock_conversion(
    session: SessionDep, career: ColumnElement, tracked: ColumnElement
) -> KnockConversion:
    """Knocks we made and knocks we took, each with its conversion to a kill.

    **The numerator is `kill_events.dbno_maker_account_id`, not a time window.**
    The parser already resolves which knock led to which kill, so "did that
    knock become a kill" needs no threshold at all. That matters: pairing a
    knock to the victim's next death instead swings the answer from 50% to 68%
    depending on where the window is drawn (measured across 30-180 s, no knee),
    because a revived player can die again fifteen minutes later and the naive
    join credits it to the original knock. `dbno_maker` is populated on 4,716
    of 8,289 career kills, which is the same ~51-57% of victims that die still
    flagged `isDBNO`.

    Bots are excluded from *our* knocks. On the taking side there is nothing to
    exclude — the victim is us.
    """
    made = (
        await session.execute(
            select(func.count()).where(
                KnockEvent.match_id.in_(career),
                KnockEvent.attacker_account_id.in_(tracked),
                KnockEvent.victim_is_bot.is_(False),
            )
        )
    ).scalar_one()
    made_converted = (
        await session.execute(
            select(func.count()).where(
                KillEvent.match_id.in_(career),
                KillEvent.dbno_maker_account_id.in_(tracked),
                KillEvent.victim_is_bot.is_(False),
            )
        )
    ).scalar_one()

    taken = (
        await session.execute(
            select(func.count()).where(
                KnockEvent.match_id.in_(career),
                KnockEvent.victim_account_id.in_(tracked),
            )
        )
    ).scalar_one()
    taken_converted = (
        await session.execute(
            select(func.count()).where(
                KillEvent.match_id.in_(career),
                KillEvent.victim_account_id.in_(tracked),
                KillEvent.dbno_maker_account_id.is_not(None),
            )
        )
    ).scalar_one()

    return KnockConversion(
        made=_rate(int(made_converted or 0), int(made or 0)),
        taken=_rate(int(taken_converted or 0), int(taken or 0)),
    )


async def _first_deaths(session: SessionDep, career: ColumnElement) -> list[FirstDeathRow]:
    """Who goes down first, among matches with at least two of us on the team.

    Restricted to shared rosters because "first to die" is meaningless when
    only one tracked player is in the lobby. The three tracked players are
    always on the same roster when they play together — 0 counterexamples in
    the archive — so a match-level grouping is enough and no team predicate is
    needed.

    `died_at_s` is NULL for a survivor, and `NULLS LAST` keeps them out of
    first place rather than sorting them to the front as SQL would by default
    on a descending order.
    """
    ranked = (
        select(
            Participant.account_id,
            Participant.name,
            func.row_number()
            .over(
                partition_by=Participant.match_id,
                order_by=Participant.died_at_s.asc().nulls_last(),
            )
            .label("rn"),
            func.count().over(partition_by=Participant.match_id).label("n_tracked"),
        )
        .join(Player, Player.account_id == Participant.account_id)
        .where(Participant.match_id.in_(career), Player.tracked)
        .subquery()
    )

    rows = (
        await session.execute(
            select(
                ranked.c.account_id,
                ranked.c.name,
                func.count().filter(ranked.c.rn == 1),
                func.count(),
            )
            .where(ranked.c.n_tracked >= 2)
            .group_by(ranked.c.account_id, ranked.c.name)
            .order_by(func.count().filter(ranked.c.rn == 1).desc())
        )
    ).all()

    return [
        FirstDeathRow(account_id=a, name=n, died_first=int(d or 0), squad_matches=int(m or 0))
        for a, n, d, m in rows
    ]


async def _range_bands(
    session: SessionDep, career: ColumnElement, tracked: ColumnElement
) -> list[RangeBandRow]:
    """Kills for and against, bucketed by distance.

    **`distance_cm > 0` is not cosmetic**: -1 is a "not applicable" sentinel on
    8.6% of kills, and left in it would pile them all into the 0-10 m band as
    if every one were a point-blank fight.
    """
    band = case(
        *[
            (
                KillEvent.distance_cm / 100.0 < hi,
                i,
            )
            for i, (_lo, hi) in enumerate(_RANGE_BANDS)
            if hi is not None
        ],
        else_=len(_RANGE_BANDS) - 1,
    )

    rows = (
        await session.execute(
            select(
                band.label("band"),
                func.count().filter(KillEvent.killer_account_id.in_(tracked)),
                func.count().filter(KillEvent.victim_account_id.in_(tracked)),
            )
            .where(
                KillEvent.match_id.in_(career),
                KillEvent.distance_cm > 0,
                or_(
                    KillEvent.killer_account_id.in_(tracked),
                    KillEvent.victim_account_id.in_(tracked),
                ),
            )
            .group_by(band)
        )
    ).all()

    by_band = {int(b): (int(k or 0), int(d or 0)) for b, k, d in rows}
    return [
        RangeBandRow(
            lo_m=lo, hi_m=hi, we_killed=by_band.get(i, (0, 0))[0], we_died=by_band.get(i, (0, 0))[1]
        )
        for i, (lo, hi) in enumerate(_RANGE_BANDS)
    ]


@router.get("/review/sessions", response_model=list[SessionRow])
async def squad_sessions(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> list[SessionRow]:
    """Evenings of play, squad-wide.

    `players/{id}/sessions` answers this per player; a squad that plays
    together needs one row per evening, not three near-identical ones.
    A match counts once no matter how many tracked players were in it, and
    `best_place` is the roster's placement — they share it.

    A calendar day is the wrong unit: an evening starting at 22:00 and ending
    at 01:30 is one session, and grouping by date splits it in two.
    """
    rows = (
        await session.execute(
            select(
                Match.match_id,
                Match.played_at,
                func.min(Participant.win_place),
                func.sum(func.coalesce(Participant.kills_human, Participant.kills)),
                func.count().filter(Participant.died_at_s.is_not(None)),
                func.sum(Participant.damage_dealt),
            )
            .select_from(Participant)
            .join(Match, Match.match_id == Participant.match_id)
            .join(Player, Player.account_id == Participant.account_id)
            .where(Player.tracked, career_filter())
            .group_by(Match.match_id, Match.played_at)
            .order_by(Match.played_at.desc())
            .limit(300)
        )
    ).all()

    out: list[SessionRow] = []
    current: list[tuple] = []
    for row in rows:
        if current and (current[-1][1] - row[1]).total_seconds() > SESSION_GAP_S:
            out.append(_session_row(current))
            current = []
            if len(out) >= limit:
                return out
        current.append(row)
    if current:
        out.append(_session_row(current))
    return out[:limit]


def _session_row(rows: list[tuple]) -> SessionRow:
    """Rows are newest-first within a session, so the start is the last one."""
    places = [int(r[2] or 0) for r in rows]
    return SessionRow(
        started_at=rows[-1][1],
        ended_at=rows[0][1],
        matches=len(rows),
        best_place=min(places),
        wins=sum(1 for p in places if p == 1),
        top10=sum(1 for p in places if 1 <= p <= 10),
        kills=sum(int(r[3] or 0) for r in rows),
        deaths=sum(int(r[4] or 0) for r in rows),
        damage=float(sum(float(r[5] or 0.0) for r in rows)),
        places=places,
    )


__all__ = [
    "EARLY_DEATH_S",
    "SESSION_GAP_S",
    "THIRD_PARTY_RADIUS_CM",
    "THIRD_PARTY_WINDOW_S",
    "router",
]
