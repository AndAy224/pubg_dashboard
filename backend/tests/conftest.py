"""Fixtures backed by the **real** archived PUBG corpus under `data/`.

Nothing in here is hand-written sample data. The corpus is 61 match responses
captured from the live API (5,584 participants spanning squad-fpp / duo-fpp /
solo / solo-fpp / squad and official / airoyale / tutorialatoz) plus the 61
matching gzipped telemetry streams. Synthetic payloads only ever prove that our
models agree with our own assumptions; these prove they agree with PUBG.

`data/` is gitignored, so a fresh clone has none of it. Every fixture therefore
skips with an actionable message instead of erroring, and the whole suite stays
green on a machine that has only the source tree.

No fixture here touches Postgres or the network — that is a hard requirement,
not an accident of the current implementation.
"""

from __future__ import annotations

import gzip
import json
import os
import pathlib
from typing import Any, Final

import pytest

# backend/tests/conftest.py -> repo root.
#
# Deliberately NOT `pubg_dashboard.config.REPO_ROOT`: importing Settings reads
# the repo `.env`, which would drag deployment configuration into pure unit
# tests and make the "data is missing" skip below depend on the environment
# being valid.
REPO_ROOT: Final = pathlib.Path(__file__).resolve().parents[2]
DATA_ROOT: Final = pathlib.Path(os.environ.get("PUBGD_TEST_DATA_DIR") or REPO_ROOT / "data")

MATCH_DIR: Final = DATA_ROOT / "matches"
TELEMETRY_DIR: Final = DATA_ROOT / "telemetry"
FIXTURE_DIR: Final = DATA_ROOT / "fixtures"

_SKIP_TMPL: Final = (
    "archived PUBG corpus not found at {path}. `data/` is gitignored, so a fresh "
    "clone has none of it: re-run scripts/panic_archive.py, or set "
    "PUBGD_TEST_DATA_DIR to an existing archive."
)


def _skip_missing(path: pathlib.Path) -> None:
    pytest.skip(_SKIP_TMPL.format(path=path), allow_module_level=False)


def _load_json(path: pathlib.Path) -> Any:
    # read_bytes + loads, not `json.load(open(...))`: the archive is UTF-8 and
    # Windows' default cp1252 text mode mangles non-ASCII player names.
    return json.loads(path.read_bytes())


def _match_paths() -> list[pathlib.Path]:
    """Collected at import time so `match_payload` can parametrise over it."""
    if not MATCH_DIR.is_dir():
        return []
    return sorted(MATCH_DIR.glob("*.json"))


# ---------------------------------------------------------------------------
# Match responses
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def all_match_payloads() -> list[dict[str, Any]]:
    """Every archived `GET /matches/{id}` response, ordered by match id.

    Session-scoped and shared by reference — treat the dicts as read-only. A
    test that needs to mutate one must `copy.deepcopy` first.
    """
    paths = _match_paths()
    if not paths:
        _skip_missing(MATCH_DIR)
    return [_load_json(p) for p in paths]


@pytest.fixture(scope="session")
def real_match_payload(all_match_payloads: list[dict[str, Any]]) -> dict[str, Any]:
    """One representative match: the lowest-id `official` match in the archive.

    Filtering on `official` matters — the four `tutorialatoz` matches in the
    corpus have a *single* participant and no rosters worth speaking of, so a
    naive "first file" pick would silently make most assertions vacuous.
    """
    for payload in all_match_payloads:
        if payload["data"]["attributes"]["matchType"] == "official":
            return payload
    pytest.skip("archive contains no `official` match")


@pytest.fixture(params=_match_paths() or [None], ids=lambda p: p.stem if p else "no-data")
def match_payload(request: pytest.FixtureRequest) -> dict[str, Any]:
    """One archived match per test invocation; the test id is the match uuid.

    Parametrised rather than looped so a schema regression names the exact match
    that broke instead of failing the whole corpus on the first bad row.
    """
    if request.param is None:
        _skip_missing(MATCH_DIR)
    return _load_json(request.param)


# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def telemetry_path(all_match_payloads: list[dict[str, Any]]) -> pathlib.Path:
    """The smallest archived telemetry file belonging to an `official` match.

    Smallest keeps the session fixture cheap; `official` keeps it meaningful.
    The genuinely smallest files in the archive are ~30 KB tutorial matches with
    one human and no combat, which would make every telemetry assertion pass for
    the wrong reason.
    """
    if not TELEMETRY_DIR.is_dir():
        _skip_missing(TELEMETRY_DIR)
    official = {
        p["data"]["id"]
        for p in all_match_payloads
        if p["data"]["attributes"]["matchType"] == "official"
    }
    candidates = [
        p for p in sorted(TELEMETRY_DIR.glob("*.json.gz")) if p.name[: -len(".json.gz")] in official
    ]
    if not candidates:
        pytest.skip(f"no telemetry for an `official` match under {TELEMETRY_DIR}")
    return min(candidates, key=lambda p: p.stat().st_size)


@pytest.fixture(scope="session")
def telemetry_match_id(telemetry_path: pathlib.Path) -> str:
    """Match id of `telemetry_events`, so a test can pair events with the payload.

    The archive names telemetry `{match_id}.json.gz`; that is a local convention
    of scripts/panic_archive.py, unrelated to the object-storage key layout.
    """
    return telemetry_path.name[: -len(".json.gz")]


@pytest.fixture(scope="session")
def telemetry_events(telemetry_path: pathlib.Path) -> list[dict[str, Any]]:
    """Decompressed event stream — a flat JSON array of `{_T, _D, ...}` objects."""
    with gzip.open(telemetry_path, "rb") as fh:
        return json.loads(fh.read())


@pytest.fixture(scope="session")
def event_samples() -> dict[str, dict[str, Any]]:
    """`data/fixtures/telemetry_event_samples.json`: one real event per `_T`.

    40 event types, keyed by `_T`. Cheap coverage of event shapes that the
    single archived match above happens not to contain.
    """
    path = FIXTURE_DIR / "telemetry_event_samples.json"
    if not path.is_file():
        _skip_missing(path)
    return _load_json(path)


# ---------------------------------------------------------------------------
# Other captured API responses
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def players_payload() -> dict[str, Any]:
    """A real `GET /players?filter[playerNames]=A,B,C` response (3 players)."""
    path = FIXTURE_DIR / "players_response.json"
    if not path.is_file():
        _skip_missing(path)
    return _load_json(path)
