"""Evaluation d'une seance : du calcul deterministe a la consigne redigee.

Deux etapes distinctes, et l'ordre compte. Du code ordinaire fixe l'indice, le
niveau et la liste des exercices autorises. Ensuite seulement, le modele
choisit dans cette liste et redige. S'il est indisponible, la premiere etape
reste entiere.
"""

import statistics
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DbSession

from app.deps import get_db
from app.services.indice import POIDS, ecart_z, indice_charge, niveau_depuis
from app.ws.hub import hub

router = APIRouter()

SEANCES_POUR_BASELINE = 10
FACTEUR_BASELINE_GENERIQUE = 0.6

# Les cles du front, pour missingSignals. Le contrat parle de quatre signaux.
SIGNAL_DU_CHAMP = {
    "hrv_rmssd": "hr",
    "fc_moyenne": "hr",
    "eda_fond": "eda",
    "eda_reponses": "eda",
    "visage": "face",
    "voix": "voice",
}


def baseline_ou_generique(historique: list[dict], generique: dict) -> tuple[dict, float]:
    """La comparaison a l'historique personnel demande plusieurs dizaines de
    seances pour etre stable. En dessous, on l'annonce au lieu de faire semblant.
    """
    if len(historique) < SEANCES_POUR_BASELINE:
        return generique, FACTEUR_BASELINE_GENERIQUE

    base = {}
    for cle in POIDS:
        valeurs = [h[cle] for h in historique if h.get(cle) is not None]
        if len(valeurs) < 2:
            base[cle] = generique[cle]
            continue
        base[cle] = (statistics.fmean(valeurs), statistics.stdev(valeurs))
    return base, 1.0


def construire_assessment(session_id: int, mesures: dict, baseline: dict,
                          facteur_confiance: float, indicateurs_bruts: dict) -> dict:
    zs = {}
    manquants = []
    for cle in POIDS:
        valeur = mesures.get(cle)
        if valeur is None:
            manquants.append({"signal": SIGNAL_DU_CHAMP[cle], "reason": "faulty"})
            continue
        moyenne, ecart_type = baseline[cle]
        zs[cle] = ecart_z(valeur, moyenne, ecart_type)

    indice, confiance = indice_charge(zs)
    confiance *= facteur_confiance

    # Un signal couvre deux champs (hr, eda) : on ne le liste qu'une fois.
    uniques, vus = [], set()
    for m in manquants:
        if m["signal"] not in vus:
            vus.add(m["signal"])
            uniques.append(m)

    return {
        "id": str(uuid4()),
        "sessionId": str(session_id),
        "index": round(indice, 1),
        "level": niveau_depuis(indice, confiance),
        "confidence": round(confiance, 3),
        "missingSignals": uniques,
        "indicators": indicateurs_bruts,
        "personalBaseline": round(baseline["hrv_rmssd"][0], 1) if "hrv_rmssd" in baseline else None,
        "computedAt": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/sessions/{session_id}/assess")
async def assess(session_id: int, db: DbSession = Depends(get_db)):
    from app.services.consigne import rediger
    from app.services.exercices import exercices_autorises
    from app.api.v1.calcul import mesures_de_la_seance, indicateurs_du_front

    mesures = mesures_de_la_seance(db, session_id)
    generique = {
        "hrv_rmssd": (42.0, 15.0), "eda_reponses": (3.0, 2.0),
        "eda_fond": (5.0, 2.0), "fc_moyenne": (72.0, 9.0),
        "voix": (0.5, 0.15), "visage": (0.5, 0.15),
    }
    baseline, facteur = baseline_ou_generique([], generique)

    evaluation = construire_assessment(
        session_id, mesures, baseline, facteur, indicateurs_du_front(mesures)
    )
    await hub.diffuser(session_id, {"type": "assessment", "payload": evaluation})

    autorises = exercices_autorises(evaluation["level"])
    exercice, message, source, modele = rediger(evaluation, autorises, historique=[])
    recommandation = {
        "id": str(uuid4()),
        "assessmentId": evaluation["id"],
        "exercise": exercice,
        "message": message,
        "source": source,
        "modelName": modele,
    }
    await hub.diffuser(session_id, {"type": "recommendation", "payload": recommandation})

    return evaluation
