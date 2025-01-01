"""update_models

Revision ID: 030c42e02a6b
Revises: b73b8538fe26
Create Date: 2024-03-21 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '030c42e02a6b'
down_revision = 'b73b8538fe26'
branch_labels = None
depends_on = None


def upgrade():
    # Drop existing tables
    op.drop_table('reddit_mentions')
    op.drop_table('brands')
    op.drop_table('users')
    
    # Create new tables
    op.create_table('users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('last_login', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email')
    )
    
    op.create_table('brands',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_email', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('keywords', sa.JSON(), nullable=True),
        sa.Column('subreddits', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_email'], ['users.email'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    op.create_table('reddit_mentions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('brand_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('url', sa.String(), nullable=False),
        sa.Column('subreddit', sa.String(), nullable=False),
        sa.Column('keyword', sa.String(), nullable=False),
        sa.Column('score', sa.Integer(), nullable=True),
        sa.Column('suggested_comment', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['brand_id'], ['brands.id'], ),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('reddit_mentions')
    op.drop_table('brands')
    op.drop_table('users')
