"""add payment fields

Revision ID: 75ebfc75be57
Revises: 20cf8a382612
Create Date: 2024-12-28 21:11:56.841764

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '75ebfc75be57'
down_revision: Union[str, None] = '20cf8a382612'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('users') as batch_op:
        batch_op.add_column(sa.Column('has_paid', sa.Boolean(), nullable=False, server_default='false'))
        batch_op.add_column(sa.Column('payment_date', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('stripe_payment_id', sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_column('stripe_payment_id')
        batch_op.drop_column('payment_date')
        batch_op.drop_column('has_paid')
