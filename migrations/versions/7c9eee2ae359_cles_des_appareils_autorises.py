"""cles des appareils autorises

Revision ID: 7c9eee2ae359
Revises: 1a1b57f78b6b
Create Date: 2026-09-23 11:03:03.434581

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7c9eee2ae359'
down_revision: Union[str, Sequence[str], None] = '1a1b57f78b6b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Migration de donnees : un appareil absent de cette table est desormais
# rejete par /ingest (voir app/api/v1/ingest.py), donc chaque appareil
# autorise a parler au serveur - y compris le simulateur - doit y avoir une
# ligne. Cles en clair, lisibles directement ici : ce prototype tourne sur un
# reseau isole pour une demonstration, pas en production, et une cle visible
# dans une migration est plus honnete qu'une porte laissee ouverte sans
# qu'on la voie.
#
# simulator/send_measures.py lit sa cle dans la variable d'environnement
# CALME_SIMULATEUR_CLE, avec CLE_SIMULATEUR ci-dessous comme valeur par
# defaut : les deux doivent rester synchronises.
CLE_CABINE_01 = "cle-demo-cabine-01"
CLE_SIMULATEUR = "cle-demo-calme-simulateur"

appareils = sa.table(
    "appareils",
    sa.column("device_id", sa.String),
    sa.column("cle_signature", sa.String),
)


def upgrade() -> None:
    """Declare les appareils autorises a parler a /ingest."""
    op.bulk_insert(
        appareils,
        [
            {"device_id": "cabine-01", "cle_signature": CLE_CABINE_01},
            {"device_id": "calme-simulateur", "cle_signature": CLE_SIMULATEUR},
        ],
    )


def downgrade() -> None:
    """Retire les deux appareils declares par cette migration."""
    op.execute(
        appareils.delete().where(
            appareils.c.device_id.in_(["cabine-01", "calme-simulateur"])
        )
    )
