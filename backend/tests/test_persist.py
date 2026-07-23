"""Persisting a parse is safe to repeat.

`parse_telemetry` is not a one-shot job — bumping `PARSER_VERSION` requeues the
whole archive so parser improvements apply retroactively without re-downloading
anything. Every write therefore has to survive being run again.

The heatmap is the one output that is not naturally idempotent: bins
accumulate, so a second parse of the same match would add its counts on top of
the first. A heatmap that is quietly 2x looks exactly like a popular drop spot.
"""

from __future__ import annotations

import datetime as dt
import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text as sql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from pubg_dashboard.config import get_settings
from pubg_dashboard.db.models import Base
from pubg_dashboard.ingest.persist import ReparseWithoutLedgerError, persist_parse_result
from pubg_dashboard.telemetry.parse import MatchMeta, ParseResult

DAY = dt.date(2026, 7, 22)
MAP = "Baltic_Main"
MATCH_TYPE = "official"


def _test_dsn() -> str:
    dsn = os.environ.get("PUBGD_TEST_DATABASE_URL")
    if dsn:
        return dsn
    base = get_settings().database_url
    head, _, tail = base.partition("?")
    return f"{head.rsplit('/', 1)[0]}/pubg_test" + (f"?{tail}" if tail else "")


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    eng = create_async_engine(_test_dsn())
    try:
        async with eng.begin() as conn:
            # drop *then* create: `create_all` skips tables that already exist,
            # so a scratch database built before a column was added keeps the
            # old shape and every test fails on the missing column instead of
            # on anything real.
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:
        await eng.dispose()
        pytest.skip(f"no Postgres at {_test_dsn()}: {exc}")

    maker = async_sessionmaker(eng, expire_on_commit=False)
    async with maker() as s:
        await s.execute(sql("TRUNCATE matches, heatmap_bins, kill_events CASCADE"))
        await s.execute(
            sql(
                "INSERT INTO matches (match_id, shard, map_name, game_mode, match_type,"
                " is_custom_match, duration_s, played_at, ingested_at)"
                " VALUES ('m1','steam',:map,'squad-fpp','official',false,1800,now(),now())"
            ),
            {"map": MAP},
        )
        await s.commit()
        yield s
    await eng.dispose()


def _result(*, kills: int = 2, bin_count: int = 5, strategy: int = 2) -> ParseResult:
    return ParseResult(
        match_id="m1",
        parser_version=1,
        meta=MatchMeta(t0_ms=1_784_000_000_000, map_name=MAP, team_size=4),
        players=[],
        bundle=b"bundle",
        heat_ledger=b"",
        kill_rows=[
            {
                "match_id": "m1", "seq": i, "t_s": float(i),
                "victim_account_id": f"account.v{i}", "victim_team_id": 1,
                "victim_is_bot": False, "victim_x": 1.0, "victim_y": 2.0,
                "killer_account_id": None, "killer_team_id": None,
                "killer_is_bot": None, "killer_x": None, "killer_y": None,
                "dbno_maker_account_id": None, "finisher_account_id": None,
                "weapon": None, "damage_type": None, "damage_reason": None,
                "distance_cm": None, "is_suicide": False, "is_team_kill": False,
                "through_wall": None, "assists": [],
            }
            for i in range(kills)
        ],
        heatmap_rows=[
            {
                "map_name": MAP, "kind": "movement", "account_id": "account.a",
                "game_mode": "squad-fpp", "day": DAY, "grid_x": i, "grid_y": 0,
                "count": bin_count,
            }
            for i in range(3)
        ],
        participant_updates=[],
        strategy_rows=[
            {
                "match_id": "m1", "account_id": f"account.v{i}",
                "blue_s": 10.0 * i, "blue_damage": 0.0, "rotate_lag_s": None,
                "teammate_dist_avg_cm": None, "teammate_near_pct": None,
                "hot_drop_n": i, "first_engage_s": None,
                "dmg_dealt_early": 0.0, "dmg_taken_early": 0.0,
                "first_weapon_s": None, "early_pickups_n": None,
            }
            for i in range(strategy)
        ],
    )


async def _totals(session: AsyncSession) -> tuple[int, int, int]:
    total = await session.scalar(sql("SELECT coalesce(sum(count),0) FROM heatmap_bins"))
    rows = await session.scalar(sql("SELECT count(*) FROM heatmap_bins"))
    kills = await session.scalar(sql("SELECT count(*) FROM kill_events"))
    return int(total or 0), int(rows or 0), int(kills or 0)


async def test_first_parse_writes_everything(session: AsyncSession) -> None:
    await persist_parse_result(
        session, _result(), replay_key="r", heat_ledger_key="h",
        previous_ledger=None, was_parsed=False, map_name=MAP, match_type=MATCH_TYPE, day=DAY,
    )
    await session.commit()
    assert await _totals(session) == (15, 3, 2)


async def test_reparse_does_not_inflate_the_heatmap(session: AsyncSession) -> None:
    """The whole reason `heat_ledger_key` exists.

    Without subtracting the previous contribution every bin doubles, and a
    heatmap that is quietly 2x is indistinguishable from a real hot spot.
    """
    first = _result()
    await persist_parse_result(
        session, first, replay_key="r", heat_ledger_key="h",
        previous_ledger=None, was_parsed=False, map_name=MAP, match_type=MATCH_TYPE, day=DAY,
    )
    await session.commit()
    before = await _totals(session)

    ledger = [
        (r["kind"], r["account_id"], r["game_mode"], r["grid_x"], r["grid_y"], r["count"])
        for r in first.heatmap_rows
    ]
    for _ in range(3):
        await persist_parse_result(
            session, _result(), replay_key="r", heat_ledger_key="h",
            previous_ledger=ledger, was_parsed=True, map_name=MAP, match_type=MATCH_TYPE, day=DAY,
        )
        await session.commit()

    assert await _totals(session) == before


async def test_reparse_without_a_ledger_is_refused(session: AsyncSession) -> None:
    """Refusing is the safe failure. Proceeding silently inflates the map."""
    with pytest.raises(ReparseWithoutLedgerError, match="cannot be subtracted"):
        await persist_parse_result(
            session, _result(), replay_key="r", heat_ledger_key="h",
            previous_ledger=None, was_parsed=True, map_name=MAP, match_type=MATCH_TYPE, day=DAY,
        )


async def test_a_shrinking_parse_leaves_no_phantom_kills(session: AsyncSession) -> None:
    """`seq` is only stable within a parser version.

    A changed parser can emit fewer kills than last time, so kill_events is
    delete-then-insert; upserting would strand the surplus rows forever.
    """
    await persist_parse_result(
        session, _result(kills=5), replay_key="r", heat_ledger_key="h",
        previous_ledger=None, was_parsed=False, map_name=MAP, match_type=MATCH_TYPE, day=DAY,
    )
    await session.commit()
    assert (await _totals(session))[2] == 5

    ledger = [("movement", "account.a", "squad-fpp", i, 0, 5) for i in range(3)]
    await persist_parse_result(
        session, _result(kills=2), replay_key="r", heat_ledger_key="h",
        previous_ledger=ledger, was_parsed=True, map_name=MAP, match_type=MATCH_TYPE, day=DAY,
    )
    await session.commit()
    assert (await _totals(session))[2] == 2


async def test_strategy_rows_are_replaced_not_accumulated(session: AsyncSession) -> None:
    """`strategy_metrics` follows the kill_events shape: absolute per-match
    values, delete-then-insert, so a reparse can shrink the set."""
    await persist_parse_result(
        session, _result(strategy=4), replay_key="r", heat_ledger_key="h",
        previous_ledger=None, was_parsed=False, map_name=MAP, match_type=MATCH_TYPE, day=DAY,
    )
    await session.commit()
    n = await session.scalar(sql("SELECT count(*) FROM strategy_metrics"))
    assert n == 4

    ledger = [("movement", "account.a", "squad-fpp", i, 0, 5) for i in range(3)]
    await persist_parse_result(
        session, _result(strategy=2), replay_key="r", heat_ledger_key="h",
        previous_ledger=ledger, was_parsed=True, map_name=MAP, match_type=MATCH_TYPE, day=DAY,
    )
    await session.commit()
    n = await session.scalar(sql("SELECT count(*) FROM strategy_metrics"))
    assert n == 2
    blue = await session.scalar(
        sql("SELECT blue_s FROM strategy_metrics WHERE account_id = 'account.v1'")
    )
    assert blue == 10.0


async def test_reversal_does_not_leave_dead_zero_rows(session: AsyncSession) -> None:
    """A subtraction can land a bin on exactly zero.

    They are not wrong, but they pile up across reparses and make every
    heatmap read scan rows that contribute nothing.
    """
    first = _result()
    await persist_parse_result(
        session, first, replay_key="r", heat_ledger_key="h",
        previous_ledger=None, was_parsed=False, map_name=MAP, match_type=MATCH_TYPE, day=DAY,
    )
    await session.commit()

    ledger = [
        (r["kind"], r["account_id"], r["game_mode"], r["grid_x"], r["grid_y"], r["count"])
        for r in first.heatmap_rows
    ]
    empty = _result()
    empty.heatmap_rows = []
    await persist_parse_result(
        session, empty, replay_key="r", heat_ledger_key="h",
        previous_ledger=ledger, was_parsed=True, map_name=MAP, match_type=MATCH_TYPE, day=DAY,
    )
    await session.commit()

    total, rows, _ = await _totals(session)
    assert total == 0
    assert rows == 0, "zeroed bins should be swept, not left behind"
