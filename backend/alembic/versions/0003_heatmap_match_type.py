"""heatmap_bins gains a match_type dimension

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-22

Heatmaps counted every match type while career stats counted `official` only,
so the two disagreed on the same screen — one tracked player showed 28 career
kills against 48 binned. Neither number was wrong; they answered different
questions.

`match_type` joins the primary key. Unlike `account_id` and `game_mode` it
carries the **real** value with no `''` "all" sentinel: there are only three
distinct types, so "all types" is a query that omits the predicate and lets
the existing SUM/GROUP BY do the work. An "" aggregate row would double the
table to save summing three rows.

**Existing bins cannot be migrated in place.** Backfilling them to a single
literal would mislabel the 12 non-`official` matches in the archive, and the
stored heat ledgers record contributions under the *old* key — replaying one
against the new key would subtract from rows that do not exist and drive bins
negative. So this truncates the bins and resets the parse markers; the worker
then rebuilds everything from raw telemetry, which costs no API calls and is
the entire reason raw telemetry is archived.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Truncate before touching the key: rebuilding the primary key over ~490k
    # rows that are about to be deleted is wasted work.
    op.execute("TRUNCATE TABLE heatmap_bins")

    op.add_column(
        "heatmap_bins",
        sa.Column(
            "match_type",
            sa.String(length=24),
            nullable=False,
            server_default=sa.text("'official'"),
        ),
    )
    op.drop_constraint("heatmap_bins_pkey", "heatmap_bins", type_="primary")
    op.create_primary_key(
        "heatmap_bins_pkey",
        "heatmap_bins",
        ["map_name", "kind", "account_id", "game_mode", "match_type", "day", "grid_x", "grid_y"],
    )

    # Hand-written, like every index in HAND_MANAGED_INDEXES: autogenerate
    # does not compare index definitions closely enough to be trusted with
    # them. See alembic/env.py.
    op.drop_index("ix_heatmap_lookup", table_name="heatmap_bins")
    op.create_index(
        "ix_heatmap_lookup",
        "heatmap_bins",
        ["map_name", "kind", "account_id", "match_type"],
    )

    # Clear the parse markers so the reparse is treated as a first parse.
    # `persist_parse_result` refuses to reparse a match that is flagged parsed
    # but has no ledger — that guard is what stops a heatmap silently
    # doubling, and it must not be tripped by this migration's own cleanup.
    op.execute(
        "UPDATE matches SET telemetry_parsed_at = NULL, heat_ledger_key = NULL, "
        "parser_version = NULL WHERE telemetry_key IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("TRUNCATE TABLE heatmap_bins")
    op.drop_index("ix_heatmap_lookup", table_name="heatmap_bins")
    op.drop_constraint("heatmap_bins_pkey", "heatmap_bins", type_="primary")
    op.drop_column("heatmap_bins", "match_type")
    op.create_primary_key(
        "heatmap_bins_pkey",
        "heatmap_bins",
        ["map_name", "kind", "account_id", "game_mode", "day", "grid_x", "grid_y"],
    )
    op.create_index(
        "ix_heatmap_lookup", "heatmap_bins", ["map_name", "kind", "account_id"]
    )
    op.execute(
        "UPDATE matches SET telemetry_parsed_at = NULL, heat_ledger_key = NULL, "
        "parser_version = NULL WHERE telemetry_key IS NOT NULL"
    )
