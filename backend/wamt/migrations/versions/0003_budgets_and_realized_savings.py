"""budgets and realized savings

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('budgets',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('period', sa.String(length=8), nullable=False),
    sa.Column('limit_usd', sa.Float(), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('budgets', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_budgets_project_id'), ['project_id'], unique=False)

    # Pre-Alembic databases get `insights` from the current model in db._complete_legacy_schema(),
    # so these columns can already exist when this revision runs.
    existing = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('insights')}
    columns = [
        sa.Column('done_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('baseline_usd_month', sa.Float(), nullable=True),
        sa.Column('residual_usd_month', sa.Float(), nullable=True),
        sa.Column('realized_usd_month', sa.Float(), nullable=True),
        sa.Column('measured_at', sa.DateTime(timezone=True), nullable=True),
    ]
    with op.batch_alter_table('insights', schema=None) as batch_op:
        for column in columns:
            if column.name not in existing:
                batch_op.add_column(column)



def downgrade() -> None:
    with op.batch_alter_table('insights', schema=None) as batch_op:
        batch_op.drop_column('measured_at')
        batch_op.drop_column('realized_usd_month')
        batch_op.drop_column('residual_usd_month')
        batch_op.drop_column('baseline_usd_month')
        batch_op.drop_column('done_at')

    with op.batch_alter_table('budgets', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_budgets_project_id'))

    op.drop_table('budgets')
