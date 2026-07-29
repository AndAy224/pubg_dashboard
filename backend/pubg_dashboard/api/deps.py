"""Shared dependencies and query predicates.

`CAREER_MATCH_TYPES` is the single definition of "does this count". It lives
here rather than being repeated per-router because a stats surface that
disagrees with itself about which matches count is indistinguishable from a
stats bug.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Final

from fastapi import Depends, Query
from sqlalchemy import ColumnElement

from pubg_dashboard.db.models import Match, Participant
from pubg_dashboard.db.session import SessionDep

__all__ = [
    "CAREER_MATCH_TYPES",
    "IncludeBots",
    "MatchScope",
    "MatchScopeDep",
    "SessionDep",
    "career_filter",
    "kills_column",
]

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


@dataclass(slots=True, frozen=True)
class MatchScope:
    """Which matches an aggregate should be computed over.

    Both fields are optional and both default to "all", so an endpoint that
    adopts this keeps its existing behaviour for callers that pass nothing.

    **Applies to `Match`, so every query using it must have `matches` in scope**
    — as a join, or as the `career_filter()` subquery it already builds. That
    is not a limitation so much as the point: filtering on the match is the only
    way three panels reading three different tables can agree about which
    matches they are describing.

    The Strategy page pooled Erangel and Miramar into one set of averages until
    this existed, and the numbers looked entirely reasonable while doing it.
    """

    map_name: str | None = None
    game_mode: str | None = None

    def predicates(self) -> list[ColumnElement[bool]]:
        """Spread into a `where()` beside `career_filter()`.

        An empty list is the common case and means "everything", which is why
        this returns predicates rather than a single `and_` — a caller cannot
        accidentally drop it and still compile.
        """
        out: list[ColumnElement[bool]] = []
        if self.map_name:
            out.append(Match.map_name == self.map_name)
        if self.game_mode:
            out.append(Match.game_mode == self.game_mode)
        return out


def match_scope(
    map_name: Annotated[
        str | None,
        Query(alias="map", description="Restrict to one map, e.g. Baltic_Main."),
    ] = None,
    game_mode: Annotated[
        str | None,
        Query(alias="gameMode", description="Restrict to one mode, e.g. squad-fpp."),
    ] = None,
) -> MatchScope:
    """`?map=` and `?gameMode=`, shared by every aggregate that accepts them.

    The aliases match `/strategy/drops`, which shipped them first, so a URL
    that filters one panel filters all of them.
    """
    return MatchScope(map_name=map_name, game_mode=game_mode)


MatchScopeDep = Annotated[MatchScope, Depends(match_scope)]


def _session_marker(session: SessionDep) -> SessionDep:  # pragma: no cover
    return session


DbSession = Annotated[SessionDep, Depends(_session_marker)]
