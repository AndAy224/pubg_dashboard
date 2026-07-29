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

from typing import Annotated, Any, Final

from fastapi import APIRouter, Query
from sqlalchemy import case, exists, func, or_, select, true
from sqlalchemy.sql import ColumnElement

from pubg_dashboard.api.deps import career_filter
from pubg_dashboard.api.schemas import (
    CircleComparison,
    DeathCauseRow,
    DeathListRow,
    EngagementPlayerRow,
    EngagementRangeRow,
    EngagementResultRow,
    FirstDeathRow,
    KnockConversion,
    MatchEngagementRow,
    MatchEngagements,
    RangeBandRow,
    Rate,
    SessionRow,
    SquadDeaths,
    SquadEngagements,
    SquadReview,
)
from pubg_dashboard.db.models import (
    Engagement,
    EngagementParticipant,
    KillEvent,
    KnockEvent,
    Match,
    Participant,
    Player,
    ZonePlay,
)
from pubg_dashboard.db.session import SessionDep
from pubg_dashboard.telemetry.engagements import (
    ENGAGEMENT_GAP_S,
)
from pubg_dashboard.telemetry.engagements import (
    THIRD_PARTY_RADIUS_CM as ENGAGEMENT_THIRD_PARTY_RADIUS_CM,
)
from pubg_dashboard.telemetry.strategy import NEAR_TEAMMATE_CM

router = APIRouter(tags=["review"])

#: How close another team's kill must be to count as a third party on our
#: death. 200 m is the same radius `strategy_metrics.hot_drop_n` uses for a
#: contested drop, kept identical so the two numbers mean the same "nearby".
#:
#: `ENGAGEMENT_THIRD_PARTY_RADIUS_CM` above is the same 200 m answering a
#: different question — "another team's *fight* overlapping ours" rather than
#: "another team's kill near our death". It is imported rather than restated so
#: the page always reports the number the parser actually segmented with.
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


#: Bands for where a fight's **first landed blow** was, in metres. Wider at the
#: top than `_RANGE_BANDS` because an engagement is a whole exchange rather than
#: one shot, and the long tail is thinner.
_ENGAGEMENT_BANDS: Final[tuple[tuple[int, int | None], ...]] = (
    (0, 25),
    (25, 75),
    (75, 150),
    (150, None),
)


@router.get("/review/engagements", response_model=SquadEngagements)
async def squad_engagements(session: SessionDep) -> SquadEngagements:
    """The squad's fights.

    **The only endpoint here whose rows are a model rather than a reading.**
    `engagements` groups cross-team blows by a 20 s silence, and the sweep
    behind that constant found no knee — so `gap_seconds` goes out with the
    payload and the page prints it. Every count below inherits that choice;
    the per-side kill, knock and damage figures are facts *given* it.

    "Our side" is whichever of `team_a`/`team_b` a tracked account was on, so
    everything is expressed through `engagement_participants` first. That
    subquery is `DISTINCT` on `(match_id, seq)`: three tracked players in one
    fight is one fight, and a plain join would count it three times — the same
    trap `/strategy/drops` avoids by keying on `(match, team)`.
    """
    career = _career_matches()
    tracked = _tracked_ids()

    ours = (
        select(
            EngagementParticipant.match_id,
            EngagementParticipant.seq,
            EngagementParticipant.team_id.label("our_team"),
        )
        .where(
            EngagementParticipant.match_id.in_(career),
            EngagementParticipant.account_id.in_(tracked),
        )
        .distinct()
        .subquery()
    )

    e = Engagement.__table__
    we_are_a = ours.c.our_team == e.c.team_a
    our_kills = case((we_are_a, e.c.kills_a), else_=e.c.kills_b)
    their_kills = case((we_are_a, e.c.kills_b), else_=e.c.kills_a)
    decided = (e.c.kills_a + e.c.kills_b) > 0
    # NULL when no hit landed at all, which is why this is not `!=`. A fight
    # whose first blow is unattributable is not a fight the other side opened.
    we_first = e.c.first_hit_team_id == ours.c.our_team

    # Aggregated straight off the join, **not** off `select(...).subquery()`.
    # Wrapping it and then aggregating expressions that still reference `e` and
    # `ours` puts all three in the FROM clause: the subquery, `engagements`
    # again, and `ours` again. Postgres dutifully builds the cartesian product
    # — 506 x 11,158 x 506 rows here, which reads as the endpoint hanging and
    # would read as plausible-but-multiplied counts on a smaller archive.
    totals = (
        await session.execute(
            select(
                func.count(),
                func.count(func.distinct(e.c.match_id)),
                func.count().filter(decided),
                func.count().filter(decided, we_first),
                func.count().filter(decided, we_first, our_kills > their_kills),
                func.count().filter(decided, we_first),
                func.count().filter(decided, ~we_first, our_kills > their_kills),
                func.count().filter(decided, ~we_first),
                func.count().filter(e.c.third_party_team_id.is_not(None)),
                func.count().filter(our_kills > 0, their_kills == 0),
                func.count().filter(their_kills > 0, our_kills == 0),
                func.count().filter(our_kills > 0, their_kills > 0),
                func.count().filter(~decided),
            )
            .select_from(e)
            .join(ours, (e.c.match_id == ours.c.match_id) & (e.c.seq == ours.c.seq))
        )
    ).one()
    (
        fights,
        matches,
        n_decided,
        n_we_first,
        n_ahead_first,
        n_first_total,
        n_ahead_not_first,
        n_not_first_total,
        n_third,
        n_ours_only,
        n_theirs_only,
        n_both,
        n_neither,
    ) = (int(x or 0) for x in totals)

    return SquadEngagements(
        gap_seconds=int(ENGAGEMENT_GAP_S),
        third_party_radius_m=int(ENGAGEMENT_THIRD_PARTY_RADIUS_CM / 100),
        matches=matches,
        fights=fights,
        decided=n_decided,
        results=[
            # Labels describe the kill counts and stop there. "Won" and "lost"
            # are readings, and a fight where a third party cleaned up after us
            # is not obviously ours to have lost.
            EngagementResultRow(
                key="ours_only", label="only they lost someone", n=n_ours_only
            ),
            EngagementResultRow(
                key="theirs_only", label="only we lost someone", n=n_theirs_only
            ),
            EngagementResultRow(key="both", label="both sides lost someone", n=n_both),
            EngagementResultRow(key="neither", label="nobody died", n=n_neither),
        ],
        first_hit_ours=_rate(n_we_first, n_decided),
        ahead_when_first=_rate(n_ahead_first, n_first_total),
        ahead_when_not_first=_rate(n_ahead_not_first, n_not_first_total),
        third_party=_rate(n_third, fights),
        range_bands=await _engagement_bands(session, e, ours, our_kills, their_kills),
        players=await _engagement_players(session, career, tracked),
    )


async def _engagement_bands(
    session: SessionDep,
    e: Any,
    ours: Any,
    our_kills: ColumnElement,
    their_kills: ColumnElement,
) -> list[EngagementRangeRow]:
    """Fights bucketed by the range the first blow landed at.

    `first_hit_range_cm` is NULL when the exchange was knocks with no
    attributed hit, and those are dropped rather than bucketed at 0 m — the
    same reasoning that keeps `distance_cm = -1` out of the kill bands.
    """
    metres = e.c.first_hit_range_cm / 100.0
    band = case(
        *[(metres < hi, i) for i, (_lo, hi) in enumerate(_ENGAGEMENT_BANDS) if hi is not None],
        else_=len(_ENGAGEMENT_BANDS) - 1,
    )
    rows = (
        await session.execute(
            select(
                band.label("band"),
                func.count(),
                func.sum(our_kills),
                func.sum(their_kills),
            )
            .select_from(e)
            .join(ours, (e.c.match_id == ours.c.match_id) & (e.c.seq == ours.c.seq))
            .where(e.c.first_hit_range_cm.is_not(None))
            .group_by(band)
        )
    ).all()

    by_band = {int(b): (int(n or 0), int(k or 0), int(d or 0)) for b, n, k, d in rows}
    return [
        EngagementRangeRow(
            lo_m=lo,
            hi_m=hi,
            fights=by_band.get(i, (0, 0, 0))[0],
            we_killed=by_band.get(i, (0, 0, 0))[1],
            we_died=by_band.get(i, (0, 0, 0))[2],
        )
        for i, (lo, hi) in enumerate(_ENGAGEMENT_BANDS)
    ]


async def _engagement_players(
    session: SessionDep, career: ColumnElement, tracked: ColumnElement
) -> list[EngagementPlayerRow]:
    """Per tracked player: the average fight, and how it goes for them.

    `damage_taken` exists nowhere else in the schema. `participants` counts
    damage dealt and `kill_events` records who died, so until now the only
    measure of a fight going badly was somebody losing it.
    """
    ep = EngagementParticipant
    rows = (
        await session.execute(
            select(
                ep.account_id,
                func.min(Participant.name),
                func.count(),
                func.avg(ep.damage_dealt),
                func.avg(ep.damage_taken),
                func.count().filter(ep.was_knocked),
                func.count().filter(ep.died),
            )
            .join(
                Participant,
                (Participant.match_id == ep.match_id)
                & (Participant.account_id == ep.account_id),
            )
            .where(ep.match_id.in_(career), ep.account_id.in_(tracked))
            .group_by(ep.account_id)
            .order_by(func.count().desc())
        )
    ).all()

    return [
        EngagementPlayerRow(
            account_id=account,
            name=name or account,
            fights=int(n or 0),
            damage_dealt_avg=float(dealt or 0.0),
            damage_taken_avg=float(taken or 0.0),
            knocked=_rate(int(knocked or 0), int(n or 0)),
            died=_rate(int(died or 0), int(n or 0)),
        )
        for account, name, n, dealt, taken, knocked, died in rows
    ]


@router.get("/matches/{match_id}/engagements", response_model=MatchEngagements)
async def match_engagements(session: SessionDep, match_id: str) -> MatchEngagements:
    """Every exchange in one match, for the replay's fight list.

    Unfiltered — bots, opponents, everyone. The replay narrows to the followed
    player in the browser, because following someone has to feel instant and a
    round trip per click would not. ~116 rows per match.

    The alternative was deriving fights from `bundle.hits` client-side, which
    would have been a **second segmentation with its own threshold**, silently
    disagreeing with `/review/engagements` about how many fights a match had.
    One model, one constant, reported with the rows.
    """
    e = Engagement.__table__
    ep = EngagementParticipant.__table__

    rows = (await session.execute(select(e).where(e.c.match_id == match_id))).mappings().all()

    accounts: dict[int, list[str]] = {}
    for seq, account in (
        await session.execute(
            select(ep.c.seq, ep.c.account_id)
            .where(ep.c.match_id == match_id)
            .order_by(ep.c.seq, ep.c.account_id)
        )
    ).all():
        accounts.setdefault(int(seq), []).append(account)

    return MatchEngagements(
        gap_seconds=int(ENGAGEMENT_GAP_S),
        engagements=[
            MatchEngagementRow(
                seq=int(r["seq"]),
                t_start_s=float(r["t_start_s"]),
                t_end_s=float(r["t_end_s"]),
                team_a=int(r["team_a"]),
                team_b=int(r["team_b"]),
                x=r["x"],
                y=r["y"],
                kills_a=int(r["kills_a"]),
                kills_b=int(r["kills_b"]),
                knocks_a=int(r["knocks_a"]),
                knocks_b=int(r["knocks_b"]),
                third_party_team_id=r["third_party_team_id"],
                accounts=accounts.get(int(r["seq"]), []),
            )
            for r in sorted(rows, key=lambda r: r["t_start_s"])
        ],
    )


@router.get("/review/deaths", response_model=SquadDeaths)
async def squad_deaths(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 60,
) -> SquadDeaths:
    """One row per tracked death, plus the rates that survived measurement.

    Three of the plan's proposed buckets did not survive, and saying which is
    the point of this docstring:

    * **"died in the blue"** — 6 of 195. A footnote, never a category.
    * **"died in a vehicle"** — 1.0% of all deaths. Same call.
    * **"caught out of position"** — this one nearly shipped. 61% of tracked
      deaths that had a phase behind them came while the victim was outside
      the last circle to close, which reads as a finding until you measure how
      often they are outside it anyway: **56%**. So it is returned as
      `circle`, a pair of rates, and not as a flag on three fifths of every
      death list.

    What is left is genuinely additive: who was still alive, how far away, and
    whether a third team was in the fight.
    """
    career = _career_matches()
    tracked = _tracked_ids()

    k = KillEvent.__table__
    z = ZonePlay.__table__
    ep = EngagementParticipant.__table__

    ours = (
        select(k)
        .where(
            k.c.match_id.in_(career),
            k.c.victim_account_id.in_(tracked),
            # A suicide is a real death but not a thing an opponent did, and
            # every rate here is about opponents. Same exclusion as
            # `/review/squad`, so the two share a denominator.
            k.c.is_suicide.is_(False),
        )
        .subquery()
    )

    # The last circle to *close* before this death. Correlated and ordered by
    # phase rather than by time: `close_t_s` is NULL on a phase that only ever
    # announced, and ordering by a NULL would put it first.
    last_circle = (
        select(z.c.in_circle_at_close)
        .where(
            z.c.match_id == ours.c.match_id,
            z.c.account_id == ours.c.victim_account_id,
            z.c.close_t_s.is_not(None),
            z.c.close_t_s <= ours.c.t_s,
        )
        .order_by(z.c.phase.desc())
        .limit(1)
        .scalar_subquery()
    )

    # The exchange **this** death happened in. `died` is set by the parser
    # when a kill attached to an engagement, so this is a lookup rather than a
    # reconstruction — NULL for the 1.4% that attached to nothing.
    #
    # The `t_start_s <= t_s` predicate is not decoration. A player can die
    # twice (comeback modes; seven in the corpus died three times), so an
    # account can have `died` set on two engagements, and taking whichever has
    # the lower `seq` would describe the *earlier* death on both rows. Ordering
    # by start time descending picks the last exchange that had begun — which
    # is where a bleed-out belongs too, since the kill was attached to an
    # exchange that ended before it.
    eng = Engagement.__table__
    fight = (
        select(
            ep.c.seq,
            ep.c.damage_dealt,
            ep.c.damage_taken,
            eng.c.third_party_team_id,
        )
        .select_from(ep)
        .join(eng, (eng.c.match_id == ep.c.match_id) & (eng.c.seq == ep.c.seq))
        .where(
            ep.c.match_id == ours.c.match_id,
            ep.c.account_id == ours.c.victim_account_id,
            ep.c.died.is_(True),
            eng.c.t_start_s <= ours.c.t_s,
        )
        .order_by(eng.c.t_start_s.desc())
        .limit(1)
        .lateral("fight")
    )

    killer = Participant.__table__.alias("killer")
    victim = Participant.__table__.alias("victim")

    # Labelled, and read back through `.mappings()`. An earlier draft indexed
    # the tuple positionally and inserting one column silently shifted
    # `in_vehicle` onto `parachuting` — every value still the right *type*, so
    # nothing raised and the page rendered a plausible list.
    stmt = (
        select(
            ours.c.match_id.label("match_id"),
            ours.c.seq.label("seq"),
            Match.played_at.label("played_at"),
            Match.map_name.label("map_name"),
            ours.c.t_s.label("t_s"),
            ours.c.victim_account_id.label("account_id"),
            victim.c.name.label("name"),
            victim.c.win_place.label("win_place"),
            killer.c.name.label("killer_name"),
            ours.c.killer_is_bot.label("killer_is_bot"),
            ours.c.weapon.label("weapon"),
            ours.c.distance_cm.label("distance_cm"),
            ours.c.dbno_maker_account_id.label("dbno_maker"),
            ours.c.victim_nearest_teammate_cm.label("nearest_cm"),
            ours.c.victim_teammates_alive.label("teammates_alive"),
            ours.c.victim_in_vehicle.label("in_vehicle"),
            ours.c.victim_parachuting.label("parachuting"),
            last_circle.label("in_circle"),
            fight.c.third_party_team_id.label("third_party_team_id"),
            fight.c.seq.label("fight_seq"),
            fight.c.damage_dealt.label("damage_dealt"),
            fight.c.damage_taken.label("damage_taken"),
        )
        .select_from(ours)
        .join(Match, Match.match_id == ours.c.match_id)
        .join(
            victim,
            (victim.c.match_id == ours.c.match_id)
            & (victim.c.account_id == ours.c.victim_account_id),
        )
        .outerjoin(
            killer,
            (killer.c.match_id == ours.c.match_id)
            & (killer.c.account_id == ours.c.killer_account_id),
        )
        .outerjoin(fight, true())
        .order_by(Match.played_at.desc(), ours.c.t_s.desc())
    )

    all_rows = (await session.execute(stmt)).mappings().all()
    rows = [_death_row(r) for r in all_rows[:limit]]

    deaths = len(all_rows)

    # **`is None` everywhere, never truthiness.** `teammates_alive` is NULL on
    # a match parsed before v17, and `or 0` would turn every one of those into
    # "died alone" — 195 of 195, a confident, catastrophic, entirely plausible
    # answer. It rendered exactly that on the first run of this endpoint,
    # before the archive had been reparsed. Unmeasured rows are excluded from
    # the denominator instead, so the rate shrinks to nothing rather than
    # going to 100%.
    measured = [r for r in all_rows if r["teammates_alive"] is not None]
    with_company = [r for r in measured if r["teammates_alive"] > 0]
    alone = sum(1 for r in measured if r["teammates_alive"] == 0)
    isolated = sum(
        1
        for r in with_company
        if r["nearest_cm"] is not None and r["nearest_cm"] > NEAR_TEAMMATE_CM
    )
    # `is False` rather than `not`: `in_circle` is None on the 36% of deaths
    # with no phase behind them, and those belong in neither half.
    outside = sum(1 for r in all_rows if r["in_circle"] is False)
    measurable = sum(1 for r in all_rows if r["in_circle"] is not None)

    baseline = (
        await session.execute(
            select(
                func.count().filter(z.c.in_circle_at_close.is_(False)),
                func.count(),
            ).where(
                z.c.match_id.in_(career),
                z.c.account_id.in_(tracked),
                z.c.alive_at_close.is_(True),
                z.c.in_circle_at_close.is_not(None),
            )
        )
    ).one()

    return SquadDeaths(
        deaths=deaths,
        isolated_radius_m=int(NEAR_TEAMMATE_CM / 100),
        alone=_rate(alone, len(measured)),
        isolated=_rate(isolated, len(with_company)),
        third_partied=_rate(
            sum(1 for r in all_rows if r["third_party_team_id"] is not None), deaths
        ),
        knocked_first=_rate(sum(1 for r in all_rows if r["dbno_maker"] is not None), deaths),
        circle=CircleComparison(
            at_death=_rate(outside, measurable),
            baseline=_rate(int(baseline[0] or 0), int(baseline[1] or 0)),
        ),
        in_vehicle=sum(1 for r in all_rows if r["in_vehicle"] is True),
        parachuting=sum(1 for r in all_rows if r["parachuting"] is True),
        outside_any_fight=sum(1 for r in all_rows if r["fight_seq"] is None),
        rows=rows,
    )


def _death_row(r: Any) -> DeathListRow:
    """One labelled result row -> one `DeathListRow`."""
    nearest = r["nearest_cm"]
    alive = r["teammates_alive"]
    distance = r["distance_cm"]
    return DeathListRow(
        match_id=r["match_id"],
        seq=int(r["seq"]),
        played_at=r["played_at"],
        map_name=r["map_name"],
        t_s=float(r["t_s"]),
        account_id=r["account_id"],
        name=r["name"] or r["account_id"],
        win_place=int(r["win_place"] or 0),
        killer_name=r["killer_name"],
        killer_is_bot=r["killer_is_bot"],
        weapon=r["weapon"],
        # -1 is "not applicable" on 8.6% of kills. None, never 0.0, or every
        # melee kill renders as a point-blank shot.
        distance_m=(float(distance) / 100.0 if distance is not None and distance > 0 else None),
        knocked_first=r["dbno_maker"] is not None,
        third_partied=r["third_party_team_id"] is not None,
        # None means "not measured" — a match parsed before v17. False would
        # claim a teammate was up, which is a fact this row does not have.
        alone=None if alive is None else alive == 0,
        nearest_teammate_m=(float(nearest) / 100.0 if nearest is not None else None),
        in_vehicle=r["in_vehicle"],
        parachuting=r["parachuting"],
        in_circle=r["in_circle"],
        damage_dealt=(
            float(r["damage_dealt"]) if r["damage_dealt"] is not None else None
        ),
        damage_taken=(
            float(r["damage_taken"]) if r["damage_taken"] is not None else None
        ),
    )


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
