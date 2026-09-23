import hashlib
import hmac
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session as DbSession

from app.deps import get_db
from app.models.tables import Appareil, Astronaute, Mesure, Session as SessionModel
from app.schemas.ingest import IngestMessage

router = APIRouter()


def verifier_signature(message: IngestMessage, cle: str) -> bool:
    """HMAC-SHA256 sur device_id | seq | ts.

    Le numero de sequence est dans la signature : sans lui, un message capture
    pourrait etre modifie puis rejoue avec un autre seq et rester valide.

    Ce que cette fonction NE fait PAS, delibrement : rejeter le rejeu a
    l'identique (meme device_id, meme seq, meme ts, meme sig). Deux parades
    classiques existent et ont ete ecartees toutes les deux :
    - Un numero de sequence strictement croissant par appareil casserait le
      rejeu du tampon hors ligne de la passerelle : apres un redemarrage elle
      repart de seq=0 et ses messages legitimes en retard seraient tous
      rejetes. Ce tampon est le point de demonstration n°3 du projet.
    - Une fenetre de fraicheur sur `ts` casserait tout des que l'horloge du
      Raspberry Pi derive : pas d'horloge sauvegardee par pile, pas de NTP en
      fonctionnement hors ligne. Rejeter sur l'horodatage echangerait un
      risque de rejeu contre une panne totale et silencieuse.
    Le rejeu a l'identique reste donc possible : c'est un compromis assume,
    pas un oubli.
    """
    if not message.sig:
        return False
    ts = message.ts.isoformat()
    attendu = hmac.new(
        cle.encode(), f"{message.device_id}|{message.seq}|{ts}".encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(attendu, message.sig)


def get_or_create_session(db: DbSession) -> SessionModel:
    session = (
        db.query(SessionModel)
        .filter(SessionModel.fin.is_(None))
        .order_by(SessionModel.id.desc())
        .first()
    )
    if session:
        return session

    astronaute = db.query(Astronaute).first()
    if not astronaute:
        astronaute = Astronaute(nom="Astronaute de test")
        db.add(astronaute)
        db.flush()

    session = SessionModel(
        astronaute_id=astronaute.id,
        debut=datetime.now(timezone.utc),
        mode="normal",
    )
    db.add(session)
    db.flush()
    return session


@router.post("/ingest", status_code=status.HTTP_202_ACCEPTED)
def ingest(message: IngestMessage, db: DbSession = Depends(get_db)):
    appareil = db.query(Appareil).filter(Appareil.device_id == message.device_id).first()
    if not appareil or not verifier_signature(message, appareil.cle_signature):
        # Journalise et rejette. Un capteur qui parle mal n'est pas une urgence
        # medicale, c'est un capteur qui deconne - ou quelqu'un d'autre.
        # Un appareil absent de la table `appareils` est refuse au meme titre
        # qu'une signature invalide : la porte ouverte precedente (laisser
        # passer tout device_id inconnu) rendait le controle contournable par
        # sa propre entree. Desormais chaque appareil autorise, y compris le
        # simulateur, est declare avec sa cle (voir la migration de donnees).
        #
        # !r (repr) plutot qu'une interpolation brute : device_id vient du
        # reseau et n'est pas fiable. Sans cet echappement, un device_id
        # contenant un retour a la ligne pourrait fabriquer de fausses lignes
        # dans le journal qui sert precisement a prouver qu'on a rejete
        # quelque chose (injection de journal).
        print(f"signature refusee: {message.device_id!r} seq={message.seq}", flush=True)
        raise HTTPException(status_code=401, detail="signature invalide")

    session = get_or_create_session(db)

    if message.ppg_raw:
        db.add(
            Mesure(
                session_id=session.id,
                device_id=message.device_id,
                capteur="ppg",
                seq=message.seq,
                ts=message.ts,
                valeurs={"ppg_raw": message.ppg_raw},
                qualite={"cardiaque": message.qualite.cardiaque},
            )
        )

    if message.ibi_ms:
        db.add(
            Mesure(
                session_id=session.id,
                device_id=message.device_id,
                capteur="cardiaque",
                seq=message.seq,
                ts=message.ts,
                valeurs={"ibi_ms": message.ibi_ms},
                qualite={"cardiaque": message.qualite.cardiaque},
            )
        )

    if message.eda_us:
        db.add(
            Mesure(
                session_id=session.id,
                device_id=message.device_id,
                capteur="sudation",
                seq=message.seq,
                ts=message.ts,
                valeurs={"eda_us": message.eda_us},
                qualite={"eda": message.qualite.eda},
            )
        )

    if message.ma is not None:
        db.add(
            Mesure(
                session_id=session.id,
                device_id=message.device_id,
                capteur="courant",
                seq=message.seq,
                ts=message.ts,
                valeurs={"ma": message.ma},
                qualite={},
            )
        )

    db.commit()

    return {"recu": True, "seq": message.seq, "session_id": session.id}