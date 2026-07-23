"""Telemetry parsing: raw PUBG event stream -> replay bundle, kills, heatmaps.

Read `docs/reference/telemetry-observed-schema.md` before touching anything in
here. It is machine-generated from the archived corpus and outranks every other
document, including PUBG's own.
"""

from __future__ import annotations
