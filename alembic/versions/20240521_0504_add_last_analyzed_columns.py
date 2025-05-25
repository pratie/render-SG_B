"""add last_analyzed and subreddit_last_analyzed columns to brands

Revision ID: 20240521_0504
Revises: 82e7f2d91105
Create Date: 2024-05-21 10:34:40.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20240521_0504'
down_revision = '82e7f2d91105'
branch_labels = None
depends_on = None

def upgrade():
    # Add last_analyzed column if it doesn't exist
    op.add_column('brands', 
                 sa.Column('last_analyzed', 
                          sa.DateTime(), 
                          nullable=True))
    
    # Add subreddit_last_analyzed column if it doesn't exist
    op.add_column('brands',
                 sa.Column('subreddit_last_analyzed',
                          sa.String(),
                          server_default='{}',
                          nullable=True))

def downgrade():
    # Drop the columns if they exist
    op.drop_column('brands', 'last_analyzed')
    op.drop_column('brands', 'subreddit_last_analyzed')
