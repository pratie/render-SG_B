"""Add payment fields to User model."""
from sqlalchemy import Boolean, Column, DateTime, String
from alembic import op
import sqlalchemy as sa

def upgrade():
    # Add payment fields to users table
    with op.batch_alter_table('users') as batch_op:
        batch_op.add_column(sa.Column('has_paid', sa.Boolean(), nullable=False, server_default='false'))
        batch_op.add_column(sa.Column('payment_date', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('stripe_payment_id', sa.String(), nullable=True))

def downgrade():
    # Remove payment fields from users table
    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_column('stripe_payment_id')
        batch_op.drop_column('payment_date')
        batch_op.drop_column('has_paid')
