"""zone play

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-29 01:56:59.632636+00:00

Circle discipline, in SQL: one row per (match, account, phase) recording
whether the player was inside the next white circle when it was announced and
again when the blue started closing on it.

`in_circle_*` comes straight from `LogPhaseChange.playersInWhiteCircle`, so it
is exact rather than derived from position. The distances alongside it come
from the ~10 s position track and carry `sample_lag_ms`, which is how a
disagreement between the two gets explained instead of tolerated.

Rows exist for **every** participant, bots included, exactly as
`strategy_metrics` does — that makes the lobby baseline ("were the teams that
beat us inside at phase 4?") free, and filtering is a query-time join on
`participants.is_bot`.

Delete-then-insert on `match_id`, like `kill_events`, `knock_events`,
`strategy_metrics` and `participant_weapons`. Nothing here writes to
`heatmap_bins`, so **the heat ledger is untouched** and this migration needs no
truncate: a reparse replaces each match's rows wholesale.

`ix_zone_play_account` is a plain B-tree, so unlike `ix_knock_attacker` it is
**not** hand-written and **not** in `HAND_MANAGED_INDEXES` — autogenerate
handles it correctly because there is no WHERE predicate to compare.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0009'
down_revision: str | None = '0008'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('zone_play',
    sa.Column('match_id', sa.String(length=36), nullable=False),
    sa.Column('account_id', sa.String(length=64), nullable=False),
    sa.Column('phase', sa.Integer(), nullable=False),
    sa.Column('announce_t_s', sa.Float(), nullable=True),
    sa.Column('close_t_s', sa.Float(), nullable=True),
    sa.Column('in_circle_at_announce', sa.Boolean(), nullable=True),
    sa.Column('in_circle_at_close', sa.Boolean(), nullable=True),
    sa.Column('dist_to_white_centre_cm', sa.Float(), nullable=True),
    sa.Column('dist_to_white_edge_cm', sa.Float(), nullable=True),
    sa.Column('white_r_cm', sa.Float(), nullable=True),
    sa.Column('alive_at_close', sa.Boolean(), nullable=True),
    sa.Column('in_vehicle_at_close', sa.Boolean(), nullable=True),
    sa.Column('sample_lag_ms', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['match_id'], ['matches.match_id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('match_id', 'account_id', 'phase')
    )
    op.create_index('ix_zone_play_account', 'zone_play', ['account_id', 'match_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_zone_play_account', table_name='zone_play')
    op.drop_table('zone_play')
