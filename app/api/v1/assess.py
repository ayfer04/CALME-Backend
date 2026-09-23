"""Evaluation d'une seance : du calcul deterministe a la consigne redigee.

Deux etapes distinctes, et l'ordre compte. Du code ordinaire fixe l'indice, le
niveau et la liste des exercices autorises. Ensuite seulement, le modele
choisit dans cette liste et redige. S'il est indisponible, la premiere etape
reste entiere.
"""

import statistics
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DbSession

from app.deps import get_db
from app.models.tables import Decision, Indicateur, Session as SessionModel
from app.services.indice import POIDS, ecart_z, indice_charge, niveau_depuis
from app.ws.hub import hub

router = APIRouter()

SEANCES_POUR_BASELINE = 10
FACTEUR_BASELINE_GENERIQUE = 0.6

# Baseline de repli, tant que l'astronaute n'a pas assez de seances passees
# pour une baseline personnelle (voir historique_indicateurs ci-dessous).
# Module-level pour que sessions.py (clôture) la reutilise sans la
# redupliquer.
BASELINE_GENERIQUE = {
    "hrv_rmssd": (42.0, 15.0), "eda_reponses": (3.0, 2.0),
    "eda_fond": (5.0, 2.0), "fc_moyenne": (72.0, 9.0),
    "voix": (0.5, 0.15), "visage": (0.5, 0.15),
}

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


def historique_indicateurs(db: DbSession, astronaute_id: int, session_id_exclue: int) -> list[dict]:
    """Les indicateurs des seances precedentes de cet astronaute.

    Jamais ceux de la seance en cours (session_id_exclue) : comparer
    quelqu'un a lui-meme de la minute d'avant ne veut rien dire, seul un
    historique d'autres seances constitue une vraie baseline personnelle.
    """
    lignes = (
        db.query(Indicateur)
        .filter(
            Indicateur.astronaute_id == astronaute_id,
            Indicateur.session_id != session_id_exclue,
        )
        .all()
    )
    return [
        {
            "hrv_rmssd": ligne.hrv_rmssd,
            "eda_reponses": ligne.eda_reponses,
            "eda_fond": ligne.eda_fond,
            "fc_moyenne": ligne.fc_moyenne,
        }
        for ligne in lignes
    ]


def signaux_manquants(mesures: dict) -> list[dict]:
    """Les signaux que le calcul n'a pas pu exploiter, dedupliques.

    Pure fonction des mesures brutes : elle ne depend ni d'une baseline ni
    d'un historique, donc elle peut etre rejouee a l'identique plus tard
    (GET /sessions/{id}/assessment la rappelle sans recalculer l'indice).
    """
    manquants = []
    for cle in POIDS:
        if mesures.get(cle) is None:
            manquants.append({"signal": SIGNAL_DU_CHAMP[cle], "reason": "faulty"})

    # Un signal couvre deux champs (hr, eda) : on ne le liste qu'une fois.
    uniques, vus = [], set()
    for m in manquants:
        if m["signal"] not in vus:
            vus.add(m["signal"])
            uniques.append(m)
    return uniques


def construire_assessment(session_id: int, mesures: dict, baseline: dict,
                          facteur_confiance: float, indicateurs_bruts: dict) -> dict:
    zs = {}
    for cle in POIDS:
        valeur = mesures.get(cle)
        if valeur is None:
            continue
        moyenne, ecart_type = baseline[cle]
        zs[cle] = ecart_z(valeur, moyenne, ecart_type)

    indice, confiance = indice_charge(zs)
    confiance *= facteur_confiance

    return {
        "id": str(uuid4()),
        "sessionId": str(session_id),
        "index": round(indice, 1),
        "level": niveau_depuis(indice, confiance),
        "confidence": round(confiance, 3),
        "missingSignals": signaux_manquants(mesures),
        "indicators": indicateurs_bruts,
        "personalBaseline": round(baseline["hrv_rmssd"][0], 1) if "hrv_rmssd" in baseline else None,
        "computedAt": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/sessions/{session_id}/assess")
async def assess(session_id: int, db: DbSession = Depends(get_db)):
    from app.services.consigne import rediger
    from app.services.exercices import exercices_autorises
    from app.api.v1.calcul import mesures_de_la_seance, indicateurs_du_front

    # La baseline personnelle se construit sur les seances precedentes de cet
    # astronaute, jamais sur la seance en cours (voir historique_indicateurs).
    # Sans astronaute connu (session inexistante), pas d'historique possible :
    # on retombe sur la generique, comme avant.
    session = db.get(SessionModel, session_id)
    historique = (
        historique_indicateurs(db, session.astronaute_id, session_id)
        if session is not None else []
    )

    mesures = mesures_de_la_seance(db, session_id)
    baseline, facteur = baseline_ou_generique(historique, BASELINE_GENERIQUE)

    indicateurs_bruts = indicateurs_du_front(mesures)
    evaluation = construire_assessment(session_id, mesures, baseline, facteur, indicateurs_bruts)
    await hub.diffuser(session_id, {"type": "assessment", "payload": evaluation})

    autorises = exercices_autorises(evaluation["level"])
    exercice, message, source, modele = rediger(evaluation, autorises, historique=[])
    recommandation = {
        "id": f"reco-{evaluation['id']}",
        "assessmentId": evaluation["id"],
        "exercise": exercice,
        "message": message,
        "source": source,
        "modelName": modele,
    }
    await hub.diffuser(session_id, {"type": "recommendation", "payload": recommandation})

    # Persistance : sans elle, GET /sessions/{id}/assessment,
    # POST /assessments/{id}/recommend et POST /recommendations/{id}/feedback
    # n'ont aucun moyen de retrouver ce que ce calcul vient de produire — les
    # deux uuid4() ci-dessus seraient jetes des la fin de la requete.
    db.add(Decision(
        session_id=session_id,
        ts=datetime.now(timezone.utc),
        indice_charge=evaluation["index"],
        niveau=evaluation["level"],
        exercice_declenche=exercice is not None,
        consigne_ia=message,
        source=source,
        confiance=evaluation["confidence"],
        assessment_id=evaluation["id"],
        exercice_id=exercice["id"] if exercice else None,
    ))

    # Cliche "avant" des indicateurs bruts, pour que POST /sessions/{id}/close
    # puisse le relire tel quel plutot que de le deviner a partir de mesures
    # qui auront continue d'arriver pendant l'exercice, et pour que la
    # prochaine seance de cet astronaute ait un historique a comparer.
    if session is not None:
        db.add(Indicateur(
            session_id=session_id,
            astronaute_id=session.astronaute_id,
            ts=datetime.now(timezone.utc),
            fc_moyenne=mesures.get("fc_moyenne"),
            hrv_rmssd=mesures.get("hrv_rmssd"),
            eda_fond=mesures.get("eda_fond"),
            eda_reponses=mesures.get("eda_reponses"),
            frequence_respiratoire=mesures.get("respiration"),
        ))
    db.commit()

    return evaluation


class IndiceFacial(BaseModel):
    at: str
    tension: float = Field(ge=0, le=1)
    blinkRate: float = Field(ge=0)
    stillness: float = Field(ge=0, le=1)


@router.post("/sessions/{session_id}/face", status_code=202)
async def recevoir_indice_facial(session_id: int, corps: IndiceFacial):
    """Un flottant par seconde. Aucune image ne transite, jamais.

    L'analyse a lieu dans le navigateur du Pi : la promesse du dossier est
    donc vraie architecturalement, et pas seulement sur parole.
    """
    await hub.diffuser(session_id, {
        "type": "frame",
        "payload": {"at": corps.at, "heartRate": None, "skinConductance": None,
                    "faceTension": corps.tension, "voiceIndex": None, "suspect": []},
    })
    return {"recu": True}


@router.post("/sessions/{session_id}/audio")
async def recevoir_audio(session_id: int, fichier: UploadFile = File(...)):
    """L'audio est analyse en memoire et detruit dans la meme requete.

    Pas de fichier temporaire, pas de chemin sur disque : la seule chose qui
    survit a cet appel est un nombre entre 0 et 1.
    """
    from app.services.voix import (BASELINE_VOCALE_GENERIQUE,
                                   features_depuis_wav, indice_vocal)

    octets = await fichier.read()
    features = features_depuis_wav(octets)
    del octets

    indice = indice_vocal(features, BASELINE_VOCALE_GENERIQUE)

    await hub.diffuser(session_id, {
        "type": "frame",
        "payload": {"at": None, "heartRate": None, "skinConductance": None,
                    "faceTension": None, "voiceIndex": indice, "suspect": []},
    })
    return {"voiceIndex": round(indice, 3), **{k: round(v, 3) for k, v in features.items()}}
