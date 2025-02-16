"""add_reddit_comments_table

Revision ID: e5b4ea30b7e5
Revises: 3dba36a59b04
Create Date: 2025-02-15 14:31:44.939738+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5b4ea30b7e5'
down_revision: Union[str, None] = '3dba36a59b04'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'reddit_comments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('brand_id', sa.Integer(), nullable=True),
        sa.Column('post_id', sa.String(), nullable=True),
        sa.Column('post_url', sa.String(), nullable=True),
        sa.Column('comment_text', sa.Text(), nullable=True),
        sa.Column('comment_url', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['brand_id'], ['brands.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_reddit_comments_id'), 'reddit_comments', ['id'], unique=False)
    op.create_index(op.f('ix_reddit_comments_post_id'), 'reddit_comments', ['post_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_reddit_comments_post_id'), table_name='reddit_comments')
    op.drop_index(op.f('ix_reddit_comments_id'), table_name='reddit_comments')
    op.drop_table('reddit_comments')
