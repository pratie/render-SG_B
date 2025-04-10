"""add_reddit_tokens_and_preferences

Revision ID: 82e7f2d91105
Revises: e5b4ea30b7e5
Create Date: 2025-04-10 18:11:23.123456

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '82e7f2d91105'
down_revision: Union[str, None] = 'e5b4ea30b7e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create reddit_tokens table
    op.create_table('reddit_tokens',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_email', sa.String(), nullable=True),
        sa.Column('access_token', sa.String(), nullable=False),
        sa.Column('refresh_token', sa.String(), nullable=False),
        sa.Column('token_type', sa.String(), nullable=False),
        sa.Column('scope', sa.String(), nullable=False),
        sa.Column('expires_at', sa.Integer(), nullable=False),
        sa.Column('reddit_username', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_email'], ['users.email'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_reddit_tokens_user_email'), 'reddit_tokens', ['user_email'], unique=True)

    # Create user_preferences table
    op.create_table('user_preferences',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_email', sa.String(), nullable=True),
        sa.Column('tone', sa.String(), nullable=True),
        sa.Column('response_style', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_email'], ['users.email'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_user_preferences_id'), 'user_preferences', ['id'], unique=False)
    op.create_index(op.f('ix_user_preferences_user_email'), 'user_preferences', ['user_email'], unique=True)


def downgrade() -> None:
    # Drop user_preferences table
    op.drop_index(op.f('ix_user_preferences_user_email'), table_name='user_preferences')
    op.drop_index(op.f('ix_user_preferences_id'), table_name='user_preferences')
    op.drop_table('user_preferences')

    # Drop reddit_tokens table
    op.drop_index(op.f('ix_reddit_tokens_user_email'), table_name='reddit_tokens')
    op.drop_table('reddit_tokens')
