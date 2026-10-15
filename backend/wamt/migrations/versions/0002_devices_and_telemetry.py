"""devices and telemetry

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('devices',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name'),
    sa.UniqueConstraint('token_hash')
    )
    op.create_table('otel_points',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
    sa.Column('source', sa.String(length=128), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('session_id', sa.String(length=64), nullable=True),
    sa.Column('model', sa.String(length=128), nullable=True),
    sa.Column('type', sa.String(length=32), nullable=True),
    sa.Column('value', sa.Float(), nullable=False),
    sa.Column('input_tokens', sa.Integer(), nullable=False),
    sa.Column('output_tokens', sa.Integer(), nullable=False),
    sa.Column('cache_read', sa.Integer(), nullable=False),
    sa.Column('cache_write', sa.Integer(), nullable=False),
    sa.Column('attrs', sa.Text(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('otel_points', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_otel_points_name'), ['name'], unique=False)
        batch_op.create_index(batch_op.f('ix_otel_points_session_id'), ['session_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_otel_points_ts'), ['ts'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('otel_points', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_otel_points_ts'))
        batch_op.drop_index(batch_op.f('ix_otel_points_session_id'))
        batch_op.drop_index(batch_op.f('ix_otel_points_name'))

    op.drop_table('otel_points')
    op.drop_table('devices')
