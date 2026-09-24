"""note de fin et acquittement des alertes

Revision ID: c7e3a1d9b2f4
Revises: b4d2e9c1f7a3
Create Date: 2026-09-24 14:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7e3a1d9b2f4'
down_revision: Union[str, Sequence[str], None] = 'b4d2e9c1f7a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # L'indice calcule a la cloture (apres l'exercice), pour que l'historique
    # du medecin montre l'avant et l'apres ; et l'acquittement des alertes.
    # Tout est nullable : les decisions deja prises n'ont rien de tout cela.
    op.add_column('decisions', sa.Column('indice_apres', sa.Float(), nullable=True))
    op.add_column('decisions', sa.Column('alerte_acquittee_le', sa.DateTime(timezone=True), nullable=True))
    op.add_column('decisions', sa.Column('alerte_acquittee_par', sa.String(length=100), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('decisions', 'alerte_acquittee_par')
    op.drop_column('decisions', 'alerte_acquittee_le')
    op.drop_column('decisions', 'indice_apres')
