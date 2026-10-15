"""baseline schema

Revision ID: 0001
Revises: 
"""

import sqlalchemy as sa
from alembic import op

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('ingest_files',
    sa.Column('path', sa.String(length=1024), nullable=False),
    sa.Column('source', sa.String(length=128), nullable=False),
    sa.Column('offset', sa.Integer(), nullable=False),
    sa.Column('size', sa.Integer(), nullable=False),
    sa.Column('mtime', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('path')
    )
    op.create_table('insights',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('type', sa.String(length=48), nullable=False),
    sa.Column('title', sa.String(length=512), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('severity', sa.String(length=16), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=True),
    sa.Column('occurrences', sa.Integer(), nullable=False),
    sa.Column('est_tokens', sa.Integer(), nullable=False),
    sa.Column('est_usd', sa.Float(), nullable=False),
    sa.Column('est_usd_month', sa.Float(), nullable=False),
    sa.Column('evidence', sa.Text(), nullable=False),
    sa.Column('artifact_kind', sa.String(length=32), nullable=True),
    sa.Column('artifact_path', sa.String(length=512), nullable=True),
    sa.Column('artifact_content', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('stale', sa.Boolean(), nullable=False),
    sa.Column('first_seen', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('insights', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_insights_project_id'), ['project_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_insights_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_insights_type'), ['type'], unique=False)

    op.create_table('meta',
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('value', sa.Text(), nullable=False),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('projects',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('slug', sa.String(length=512), nullable=False),
    sa.Column('path', sa.String(length=1024), nullable=True),
    sa.Column('name', sa.String(length=256), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('slug')
    )
    op.create_table('sessions',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(length=128), nullable=False),
    sa.Column('title', sa.String(length=512), nullable=True),
    sa.Column('cwd', sa.String(length=1024), nullable=True),
    sa.Column('git_branch', sa.String(length=256), nullable=True),
    sa.Column('entrypoint', sa.String(length=64), nullable=True),
    sa.Column('version', sa.String(length=64), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('sessions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_sessions_project_id'), ['project_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_sessions_started_at'), ['started_at'], unique=False)

    op.create_table('api_calls',
    sa.Column('id', sa.String(length=128), nullable=False),
    sa.Column('session_id', sa.String(length=64), nullable=False),
    sa.Column('turn_id', sa.String(length=64), nullable=True),
    sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
    sa.Column('model', sa.String(length=128), nullable=False),
    sa.Column('is_sidechain', sa.Boolean(), nullable=False),
    sa.Column('agent_id', sa.String(length=64), nullable=True),
    sa.Column('input_tokens', sa.Integer(), nullable=False),
    sa.Column('output_tokens', sa.Integer(), nullable=False),
    sa.Column('cache_write_5m', sa.Integer(), nullable=False),
    sa.Column('cache_write_1h', sa.Integer(), nullable=False),
    sa.Column('cache_read', sa.Integer(), nullable=False),
    sa.Column('web_search_requests', sa.Integer(), nullable=False),
    sa.Column('service_tier', sa.String(length=32), nullable=True),
    sa.Column('cost_usd', sa.Float(), nullable=True),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('api_calls', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_api_calls_model'), ['model'], unique=False)
        batch_op.create_index(batch_op.f('ix_api_calls_session_id'), ['session_id'], unique=False)
        batch_op.create_index('ix_api_calls_session_ts', ['session_id', 'ts'], unique=False)
        batch_op.create_index(batch_op.f('ix_api_calls_ts'), ['ts'], unique=False)
        batch_op.create_index(batch_op.f('ix_api_calls_turn_id'), ['turn_id'], unique=False)

    op.create_table('session_events',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('session_id', sa.String(length=64), nullable=False),
    sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('ref_id', sa.String(length=128), nullable=True),
    sa.Column('model', sa.String(length=128), nullable=True),
    sa.Column('cause', sa.String(length=64), nullable=True),
    sa.Column('tokens', sa.Integer(), nullable=False),
    sa.Column('wasted_usd', sa.Float(), nullable=False),
    sa.Column('gap_seconds', sa.Float(), nullable=True),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('session_events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_session_events_kind'), ['kind'], unique=False)
        batch_op.create_index(batch_op.f('ix_session_events_ref_id'), ['ref_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_session_events_session_id'), ['session_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_session_events_ts'), ['ts'], unique=False)

    op.create_table('tool_calls',
    sa.Column('id', sa.String(length=128), nullable=False),
    sa.Column('api_call_id', sa.String(length=128), nullable=False),
    sa.Column('session_id', sa.String(length=64), nullable=False),
    sa.Column('turn_id', sa.String(length=64), nullable=True),
    sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('target', sa.Text(), nullable=True),
    sa.Column('is_sidechain', sa.Boolean(), nullable=False),
    sa.Column('is_error', sa.Boolean(), nullable=False),
    sa.Column('result_chars', sa.Integer(), nullable=False),
    sa.Column('signature', sa.String(length=512), nullable=True),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('tool_calls', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_tool_calls_api_call_id'), ['api_call_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_tool_calls_name'), ['name'], unique=False)
        batch_op.create_index(batch_op.f('ix_tool_calls_session_id'), ['session_id'], unique=False)
        batch_op.create_index('ix_tool_calls_session_ts', ['session_id', 'ts'], unique=False)
        batch_op.create_index(batch_op.f('ix_tool_calls_signature'), ['signature'], unique=False)
        batch_op.create_index(batch_op.f('ix_tool_calls_turn_id'), ['turn_id'], unique=False)

    op.create_table('turns',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('session_id', sa.String(length=64), nullable=False),
    sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
    sa.Column('prompt', sa.Text(), nullable=True),
    sa.Column('prompt_chars', sa.Integer(), nullable=False),
    sa.Column('permission_mode', sa.String(length=32), nullable=True),
    sa.Column('category', sa.String(length=32), nullable=True),
    sa.Column('category_source', sa.String(length=16), nullable=True),
    sa.Column('category_confidence', sa.Float(), nullable=True),
    sa.Column('category_scores', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('turns', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_turns_category'), ['category'], unique=False)
        batch_op.create_index(batch_op.f('ix_turns_session_id'), ['session_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_turns_ts'), ['ts'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('turns', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_turns_ts'))
        batch_op.drop_index(batch_op.f('ix_turns_session_id'))
        batch_op.drop_index(batch_op.f('ix_turns_category'))

    op.drop_table('turns')
    with op.batch_alter_table('tool_calls', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_tool_calls_turn_id'))
        batch_op.drop_index(batch_op.f('ix_tool_calls_signature'))
        batch_op.drop_index('ix_tool_calls_session_ts')
        batch_op.drop_index(batch_op.f('ix_tool_calls_session_id'))
        batch_op.drop_index(batch_op.f('ix_tool_calls_name'))
        batch_op.drop_index(batch_op.f('ix_tool_calls_api_call_id'))

    op.drop_table('tool_calls')
    with op.batch_alter_table('session_events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_session_events_ts'))
        batch_op.drop_index(batch_op.f('ix_session_events_session_id'))
        batch_op.drop_index(batch_op.f('ix_session_events_ref_id'))
        batch_op.drop_index(batch_op.f('ix_session_events_kind'))

    op.drop_table('session_events')
    with op.batch_alter_table('api_calls', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_api_calls_turn_id'))
        batch_op.drop_index(batch_op.f('ix_api_calls_ts'))
        batch_op.drop_index('ix_api_calls_session_ts')
        batch_op.drop_index(batch_op.f('ix_api_calls_session_id'))
        batch_op.drop_index(batch_op.f('ix_api_calls_model'))

    op.drop_table('api_calls')
    with op.batch_alter_table('sessions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_sessions_started_at'))
        batch_op.drop_index(batch_op.f('ix_sessions_project_id'))

    op.drop_table('sessions')
    op.drop_table('projects')
    op.drop_table('meta')
    with op.batch_alter_table('insights', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_insights_type'))
        batch_op.drop_index(batch_op.f('ix_insights_status'))
        batch_op.drop_index(batch_op.f('ix_insights_project_id'))

    op.drop_table('insights')
    op.drop_table('ingest_files')
