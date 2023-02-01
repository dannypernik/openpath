"""user.grad_year

Revision ID: 937ac216ffac
Revises: 98e49c56e446
Create Date: 2023-02-01 14:45:36.625369

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '937ac216ffac'
down_revision = '98e49c56e446'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('grad_year', sa.String(length=4), nullable=True))

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('grad_year')

    # ### end Alembic commands ###
