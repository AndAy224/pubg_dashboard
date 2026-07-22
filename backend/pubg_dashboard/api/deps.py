"""Shared dependencies and query predicates.

`CAREER_MATCH_TYPES` is the single definition of "does this count". It lives
here rather than being repeated per-router because a stats surface that
disagrees with itself about which matches count is indistinguishable from a
stats bug.
"""

from __future__ import annotations

from typing import Annotated, Final

from fastapi import Depends, Query
from sqlalchemy import ColumnElement

from pubg_dashboard.db.models import Match, Participant
from pubg_dashboard.db.session import SessionDep

__all__ = ["CAREER_MATCH_TYPES", "IncludeBots", "SessionDep", "career_filter", "kills_column"]

#: Career stats count `official` only. `airoyale` and `tutorialatoz` are stored
#: and fully replayable but excluded from aggregates — a user decision, and it
#: supersedes BUILD-SPEC 7 Q3 which predates it. `Range_Main` (Camp Jackal)
#: only ever appears as `tutorialatoz`, so it falls out with it.
CAREER_MATCH_TYPES: Final[tuple[str, ...]] = ("official",)


def career_filter() -> ColumnElement[bool]:
    """Predicate selecting matches that count toward career stats."""
    return Match.match_type.in_(CAREER_MATCH_TYPES)


IncludeBots = Annotated[
    bool,
    Query(
        description=(
            "Count kills against bots. Default false: bots are ~19% of all "
            "kills and just over half of the tracked players' kills, so "
            "including them roughly doubles some K/Ds."
        )
    ),
]


def kills_column(include_bots: bool) -> ColumnElement[int]:
    """The kill count to aggregate.

    `kills_human` is NULL until a match is parsed, so it falls back to the raw
    API count rather than silently dropping unparsed matches from the total —
    an aggregate that quietly ignores rows is worse than one that is slightly
    generous, because nothing about it looks wrong.
    """
    if include_bots:
        return Participant.kills
    from sqlalchemy import func

    return func.coalesce(Participant.kills_human, Participant.kills)


def _session_marker(session: SessionDep) -> SessionDep:  # pragma: no cover
    return session


DbSession = Annotated[SessionDep, Depends(_session_marker)]
