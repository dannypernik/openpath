"""email_list_request.confirmed_at

Revision ID: b41f6d0e8a27
Revises: 7c2e4a9b1d35
Create Date: 2026-11-07 09:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b41f6d0e8a27'
down_revision = '7c2e4a9b1d35'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('email_list_request', schema=None) as batch_op:
        batch_op.add_column(sa.Column('confirmed_at', sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table('email_list_request', schema=None) as batch_op:
        batch_op.drop_column('confirmed_at')
