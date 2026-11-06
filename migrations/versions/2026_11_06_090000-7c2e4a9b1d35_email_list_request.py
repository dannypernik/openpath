"""email_list_request

Revision ID: 7c2e4a9b1d35
Revises: 60f6b7b9911c
Create Date: 2026-11-06 09:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7c2e4a9b1d35'
down_revision = '60f6b7b9911c'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('email_list_request',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('action', sa.String(length=16), nullable=False),
    sa.Column('timestamp', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email')
    )


def downgrade():
    op.drop_table('email_list_request')
