"""Assemble les mesures d'une seance en indicateurs, depuis la base."""

from sqlalchemy.orm import Session as DbSession

from app.models.tables import Mesure
from app.services.cardiaque import fc_moyenne, nettoyer_rr, rmssd, rr_depuis_ppg
from app.services.respiration import frequence_respiratoire
from app.services.sudation import indicateurs_eda


def mesures_de_la_seance(db: DbSession, session_id: int) -> dict:
    lignes = db.query(Mesure).filter(Mesure.session_id == session_id).order_by(Mesure.seq).all()

    ppg: list[int] = []
    eda: list[float] = []
    for ligne in lignes:
        if ligne.capteur == "ppg":
            ppg.extend(ligne.valeurs.get("ppg_raw", []))
        elif ligne.capteur == "sudation":
            eda.extend(ligne.valeurs.get("eda_us", []))

    rr = nettoyer_rr(rr_depuis_ppg(ppg))
    fond, reponses = indicateurs_eda(eda)

    return {
        "hrv_rmssd": rmssd(rr),
        "fc_moyenne": fc_moyenne(rr),
        "eda_fond": fond,
        "eda_reponses": reponses,
        "respiration": frequence_respiratoire(rr),
        "voix": None,      # renseigne par POST /media/audio
        "visage": None,    # renseigne par POST /media/face
    }


def indicateurs_du_front(mesures: dict) -> dict:
    """Les noms du contrat TypeScript, pas les notres."""
    return {
        "heartRateMean": mesures.get("fc_moyenne"),
        "heartRateVariability": mesures.get("hrv_rmssd"),
        "edaTonic": mesures.get("eda_fond"),
        "edaPhasic": mesures.get("eda_reponses"),
        "faceTension": mesures.get("visage"),
        "voiceIndex": mesures.get("voix"),
        "breathingRate": mesures.get("respiration"),
    }
