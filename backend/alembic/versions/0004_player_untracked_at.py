"""players gains untracked_at

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-23

Settings can now add and remove tracked players, and an untracked player stays
listed so they can be re-tracked for free — the account id is already known, so
that costs no rate-limit token, unlike resolving a name.

That list needs to know who was *deliberately* untracked. `tracked = false`
cannot answer it: `players` holds a row for every human opponent as well (which
is what makes opponent lookup and aggregate heatmaps free), so at the time of
writing 4,338 of 4,341 rows are untracked and were never tracked at all.

Nullable, no backfill, no index. Existing untracked rows keep NULL, which is
correct — none of them were ever tracked. The three currently tracked players
are unaffected.

Deliberately not inferred from `last_polled_at IS NOT NULL`. That is exact
today — only the poller writes it and it only polls tracked players, verified
3 of 3 with no false positives — but it is inference that stops holding the
moment the poller changes, and it misses anyone untracked inside the 5-minute
window before their first poll.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "players",
        sa.Column("untracked_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("players", "untracked_at")
