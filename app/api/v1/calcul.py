"""Assemble les mesures d'une seance en indicateurs, depuis la base."""

from datetime import datetime
from statistics import mean

from sqlalchemy.orm import Session as DbSession

from app.models.tables import Mesure
from app.services.cardiaque import fc_moyenne, nettoyer_rr, rmssd, rr_depuis_ppg
from app.services.respiration import frequence_respiratoire
from app.services.sudation import indicateurs_eda


def mesures_de_la_seance(db: DbSession, session_id: int, depuis: datetime | None = None) -> dict:
    """Les indicateurs de la seance ; avec `depuis`, seulement ce qui a ete
    mesure a partir de cet instant (la periode d'exercice, a la cloture)."""
    requete = db.query(Mesure).filter(Mesure.session_id == session_id)
    if depuis is not None:
        requete = requete.filter(Mesure.ts >= depuis)
    lignes = requete.order_by(Mesure.ts, Mesure.seq).all()

    ppg: list[int] = []
    eda: list[float] = []
    tensions: list[float] = []
    sourires: list[float] = []
    voix: list[float] = []
    humeurs: list[float] = []
    for ligne in lignes:
        if ligne.capteur == "ppg":
            ppg.extend(ligne.valeurs.get("ppg_raw", []))
        elif ligne.capteur == "sudation":
            eda.extend(ligne.valeurs.get("eda_us", []))
        elif ligne.capteur == "visage" and ligne.valeurs.get("tension") is not None:
            tensions.append(float(ligne.valeurs["tension"]))
            if ligne.valeurs.get("sourire") is not None:
                sourires.append(float(ligne.valeurs["sourire"]))
        elif ligne.capteur == "parole" and ligne.valeurs.get("humeur") is not None:
            humeurs.append(float(ligne.valeurs["humeur"]))
        elif ligne.capteur == "voix" and ligne.valeurs.get("indice") is not None:
            voix.append(float(ligne.valeurs["indice"]))

    rr = nettoyer_rr(rr_depuis_ppg(ppg))
    fond, reponses = indicateurs_eda(eda)

    return {
        "hrv_rmssd": rmssd(rr),
        "fc_moyenne": fc_moyenne(rr),
        "eda_fond": fond,
        "eda_reponses": reponses,
        "respiration": frequence_respiratoire(rr),
        # Moyennes des indices calcules dans le navigateur (visage, une fois par
        # seconde) et sur le serveur (voix, par reponse enregistree).
        "voix": mean(voix) if voix else None,
        "visage": mean(tensions) if tensions else None,
        "sourire": mean(sourires) if sourires else None,
        # L'humeur la plus basse de la conversation : une seule phrase de
        # detresse suffit, une moyenne la noierait.
        "parole": min(humeurs) if humeurs else None,
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
