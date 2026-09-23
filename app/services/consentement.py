"""Consentement camera/micro de la cabine.

Persiste en base pour survivre a un redemarrage : le serveur tourne sous
systemd et redemarre seul apres une coupure de courant, donc une variable de
module (reinitialisee a chaque process) ne suffit pas a tenir la promesse
« coupure durable » que l'astronaute attend.
"""

from datetime import datetime, timezone

from sqlalchemy.orm import Session as DbSession

from app.models.tables import ConsentementCabine

# Une seule cabine aujourd'hui, sous le meme identifiant que celui par
# defaut du front (Frontend/src/api/config.ts, CABIN_ID). Les fonctions
# ci-dessous prennent quand meme cabine_id en parametre pour ne pas avoir a
# retoucher ce module le jour ou une deuxieme cabine sera cablee.
CABINE_PAR_DEFAUT = "cabine-01"


def obtenir_ou_creer(db: DbSession, cabine_id: str = CABINE_PAR_DEFAUT) -> ConsentementCabine:
    ligne = (
        db.query(ConsentementCabine)
        .filter(ConsentementCabine.cabine_id == cabine_id)
        .first()
    )
    if ligne is not None:
        return ligne
    # Par defaut, camera et micro actifs : le consentement se coupe depuis la
    # cabine, il ne se retire pas silencieusement des la premiere requete.
    ligne = ConsentementCabine(
        cabine_id=cabine_id, camera=True, microphone=True, maj=datetime.now(timezone.utc)
    )
    db.add(ligne)
    db.commit()
    db.refresh(ligne)
    return ligne


def mettre_a_jour(
    db: DbSession, camera: bool, microphone: bool, cabine_id: str = CABINE_PAR_DEFAUT
) -> ConsentementCabine:
    ligne = obtenir_ou_creer(db, cabine_id)
    ligne.camera = camera
    ligne.microphone = microphone
    ligne.maj = datetime.now(timezone.utc)
    db.commit()
    db.refresh(ligne)
    return ligne
