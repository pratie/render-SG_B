"""add_reddit_mention_fields

Revision ID: 20cf8a382612
Revises: 030c42e02a6b
Create Date: 2024-12-18 00:23:18.676603

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20cf8a382612'
down_revision: Union[str, None] = '030c42e02a6b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('reddit_mentions', sa.Column('matching_keywords', sa.String(), nullable=True))
    op.add_column('reddit_mentions', sa.Column('num_comments', sa.Integer(), nullable=True))
    op.add_column('reddit_mentions', sa.Column('relevance_score', sa.Integer(), nullable=True))
    op.add_column('reddit_mentions', sa.Column('created_utc', sa.Integer(), nullable=True))
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('reddit_mentions', 'created_utc')
    op.drop_column('reddit_mentions', 'relevance_score')
    op.drop_column('reddit_mentions', 'num_comments')
    op.drop_column('reddit_mentions', 'matching_keywords')
    # ### end Alembic commands ###