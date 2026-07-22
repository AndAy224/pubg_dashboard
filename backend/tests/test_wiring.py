"""The composition root actually composes.

Every bug this file guards against was real and none of them were visible to
`import pubg_dashboard`: the ingest layer talks to Protocols, the concrete
client and storage classes satisfied neither, and nothing in the tree ever
constructed an `IngestContext` to find out. A Protocol that nobody instantiates
is a comment.

These are cheap structural checks, deliberately not mocks of behaviour — the
question is only "do the two halves still fit together".
"""

from __future__ import annotations

import datetime as dt
import inspect

import pytest

from pubg_dashboard.ingest import handlers
from pubg_dashboard.ingest.ports import PubgApi
from pubg_dashboard.ingest.wiring import PubgApiAdapter, TelemetryStoreAdapter, build_context
from pubg_dashboard.pubg.client import PubgClient
from pubg_dashboard.storage.filesystem import FilesystemStorage


def test_adapter_satisfies_the_pubg_port() -> None:
    assert isinstance(PubgApiAdapter(PubgClient(api_key="x")), PubgApi)


def test_adapter_covers_every_port_method_with_a_matching_signature() -> None:
    """`runtime_checkable` only checks that the *names* exist.

    It says nothing about parameters, which is exactly how
    `get_players_by_names` / `get_players` drifted apart unnoticed.
    """
    adapter = PubgApiAdapter(PubgClient(api_key="x"))
    for name in ("get_players_by_names", "get_players_by_ids", "get_match", "download_telemetry"):
        port_sig = inspect.signature(getattr(PubgApi, name))
        impl_sig = inspect.signature(getattr(adapter, name))
        assert list(impl_sig.parameters) == [
            p for p in port_sig.parameters if p != "self"
        ], f"{name} does not match the port"


def test_storage_adapter_satisfies_the_store_port(tmp_path: object) -> None:
    store = TelemetryStoreAdapter(FilesystemStorage())
    for name in ("key_for", "exists", "put"):
        assert hasattr(store, name), f"TelemetryStore.{name} missing"


def test_storage_key_is_date_partitioned() -> None:
    """The retention and backfill scans narrow on this prefix.

    A key built from `match_id` alone would flatten the hierarchy they walk.
    """
    store = TelemetryStoreAdapter(FilesystemStorage())
    key = store.key_for("steam", "abc-123", dt.datetime(2026, 7, 22, tzinfo=dt.UTC))
    assert key == "telemetry/steam/2026/07/abc-123.json.gz"


def test_handler_registry_covers_every_job_kind_the_pipeline_enqueues() -> None:
    """A kind with no handler is claimed, fails, and dead-letters after 5 tries.

    The worker logs it, but nothing else does — so an unregistered handler looks
    exactly like a queue that is quietly falling behind.
    """
    ctx = build_context(with_storage=False)
    registry: dict[str, object] = {}
    handlers.register_handlers(registry, ctx)

    enqueued_kinds = {
        handlers.JOB_FETCH_MATCH,
        handlers.JOB_FETCH_TELEMETRY,
        handlers.JOB_PARSE_TELEMETRY,
        handlers.JOB_BACKFILL_PLAYER,
    }
    assert enqueued_kinds <= set(registry), f"unhandled: {enqueued_kinds - set(registry)}"


def test_poller_context_has_no_storage() -> None:
    """The poller reads /players and enqueues; it never touches the bucket.

    Building storage for it would make a MinIO deployment refuse to poll
    whenever the bucket was down.
    """
    assert build_context(with_storage=False).storage is None


@pytest.mark.parametrize("with_storage", [True, False])
def test_build_context_is_wired(with_storage: bool) -> None:
    ctx = build_context(with_storage=with_storage)
    assert isinstance(ctx.api, PubgApi)
    assert ctx.sessionmaker is not None
    assert ctx.settings is not None
