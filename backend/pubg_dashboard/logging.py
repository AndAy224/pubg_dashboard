"""structlog configuration.

Specced in BUILD-SPEC and never written, which is why every module already does
`structlog.get_logger(__name__)` against the library default.

Two output modes, chosen by whether stderr is a terminal: a console renderer
for a human running `pubgd` by hand, and JSON for the systemd units, where the
journal is the only record of what happened and grepping it is the debugging
interface.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

__all__ = ["configure_logging"]

_configured = False


def configure_logging(*, level: str = "INFO", force_json: bool | None = None) -> None:
    """Idempotent. Safe to call from every entry point.

    Idempotent on purpose: the CLI, the API and the worker all want logging set
    up, and the worker is started by the CLI — configuring twice would stack
    processors and double every line.
    """
    global _configured
    if _configured:
        return

    as_json = not sys.stderr.isatty() if force_json is None else force_json

    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        # Exceptions become a field rather than a separate traceback, so a
        # failed job's cause survives in the journal next to its job id.
        structlog.processors.format_exc_info,
    ]
    renderer: Any = (
        structlog.processors.JSONRenderer()
        if as_json
        else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    )

    logging.basicConfig(format="%(message)s", stream=sys.stderr, level=level.upper())
    structlog.configure(
        processors=[*shared, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping()[level.upper()]
        ),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )
    _configured = True
