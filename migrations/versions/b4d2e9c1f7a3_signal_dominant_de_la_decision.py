"""signal dominant de la decision

Revision ID: b4d2e9c1f7a3
Revises: 5f6851ca19a9
Create Date: 2026-09-24 12:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4d2e9c1f7a3'
down_revision: Union[str, Sequence[str], None] = '5f6851ca19a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Le signal qui a oriente le choix de l'exercice (voir
    # app/services/exercices.py::signal_dominant). Nullable : les decisions
    # deja prises l'ont ete sans lui, NULL est la seule valeur honnete.
    op.add_column('decisions', sa.Column('signal_dominant', sa.String(length=20), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('decisions', 'signal_dominant')
