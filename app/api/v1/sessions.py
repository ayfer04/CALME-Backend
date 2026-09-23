"""Cycle de vie d'une seance : ouverture, lecture, cloture, consentement.

Le calcul lui-meme (indice, niveau, indicateurs) reste dans assess.py, qui le
fait deja et le diffuse sur le WebSocket. Ce module ne recalcule jamais une
decision deja prise : il ouvre la seance, relit ce qui a ete persiste, et ne
recalcule que ce qui n'a pas de sens a etre fige (les indicateurs "apres" a
la cloture, qui sont par definition mesures a cet instant-la).
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DbSession

from app.api.v1.assess import (
    BASELINE_GENERIQUE,
    baseline_ou_generique,
    construire_assessment,
    historique_indicateurs,
    signaux_manquants,
)
from app.api.v1.calcul import indicateurs_du_front, mesures_de_la_seance
from app.deps import get_db
from app.models.tables import Astronaute, Decision, Indicateur
from app.models.tables import Session as SessionModel
from app.schemas.cabine import ConsentBody
from app.schemas.session import OuvertureSeance
from app.services import consentement

router = APIRouter()

# Les seuls modes que le front sait afficher (contrat CabinMode). Les
# seances ouvertes par l'ancien chemin de secours d'/ingest (avant que cette
# route n'existe) portent encore "normal" : on les ramene a une valeur
# valide plutot que de laisser fuiter une chaine que le front ne connait pas.
MODES_VALIDES = {"standby", "measuring", "session", "degraded"}


def _derniere_decision(db: DbSession, session_id: int) -> Decision | None:
    return (
        db.query(Decision)
        .filter(Decision.session_id == session_id)
        .order_by(Decision.id.desc())
        .first()
    )


def _session_publique(db: DbSession, session: SessionModel) -> dict:
    decision = _derniere_decision(db, session.id)
    mode = session.mode if session.mode in MODES_VALIDES else "measuring"
    return {
        "id": str(session.id),
        "crewId": str(session.astronaute_id),
        "startedAt": session.debut.isoformat(),
        "closedAt": session.fin.isoformat() if session.fin else None,
        "mode": mode,
        "exerciseId": decision.exercice_id if decision else None,
    }


@router.post("/sessions")
def ouvrir_session(corps: OuvertureSeance, db: DbSession = Depends(get_db)):
    try:
        astronaute_id = int(corps.crewId)
    except ValueError:
        astronaute_id = -1
    astronaute = db.get(Astronaute, astronaute_id)
    if astronaute is None:
        raise HTTPException(status_code=404, detail="equipier introuvable")

    session = SessionModel(
        astronaute_id=astronaute.id,
        debut=datetime.now(timezone.utc),
        fin=None,
        # La cabine commence a mesurer des l'ouverture : c'est le sens meme
        # d'ouvrir une seance, pas un etat intermediaire a confirmer.
        mode="measuring",
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return _session_publique(db, session)


@router.get("/sessions/{session_id}")
def lire_session(session_id: int, db: DbSession = Depends(get_db)):
    session = db.get(SessionModel, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="seance introuvable")
    return _session_publique(db, session)


@router.get("/sessions/{session_id}/assessment")
def lire_evaluation(session_id: int, db: DbSession = Depends(get_db)):
    """Relit la derniere evaluation persistee. Ne relance jamais le calcul :
    sinon l'id renvoye changerait a chaque appel (construire_assessment tire
    un uuid4() neuf a chaque execution) et casserait tout ce qui reference
    deja l'ancien - la recommandation en cours, le feedback a venir.
    """
    session = db.get(SessionModel, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="seance introuvable")

    decision = _derniere_decision(db, session_id)
    if decision is None:
        raise HTTPException(status_code=404, detail="aucune evaluation pour cette seance")

    # missingSignals, indicators et personalBaseline ne sont pas dans
    # `decisions` : ce sont des projections pures des mesures brutes (et,
    # pour la baseline, de l'historique de l'astronaute), pas la decision
    # elle-meme - les relire à l'identique n'a pas d'interet, les rederiver
    # est sans risque.
    mesures = mesures_de_la_seance(db, session_id)
    historique = historique_indicateurs(db, session.astronaute_id, session_id)
    baseline, _ = baseline_ou_generique(historique, BASELINE_GENERIQUE)

    return {
        "id": decision.assessment_id,
        "sessionId": str(session_id),
        "index": decision.indice_charge,
        "level": decision.niveau,
        "confidence": decision.confiance,
        "missingSignals": signaux_manquants(mesures),
        "indicators": indicateurs_du_front(mesures),
        "personalBaseline": (
            round(baseline["hrv_rmssd"][0], 1) if "hrv_rmssd" in baseline else None
        ),
        "computedAt": decision.ts.isoformat(),
    }


@router.post("/sessions/{session_id}/close")
def clore_session(session_id: int, db: DbSession = Depends(get_db)):
    session = db.get(SessionModel, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="seance introuvable")

    decision = _derniere_decision(db, session_id)
    if decision is None:
        # Sans indice de depart, il n'y a rien de honnete a renvoyer comme
        # indexBefore (non-nullable dans le contrat) : on refuse plutot que
        # d'en inventer un.
        raise HTTPException(
            status_code=409, detail="aucune evaluation pour cette seance, cloture impossible"
        )

    avant = (
        db.query(Indicateur)
        .filter(Indicateur.session_id == session_id)
        .order_by(Indicateur.ts.asc())
        .first()
    )

    # "indexAfter est celui calcule a la cloture" : ici, et seulement ici, un
    # nouveau calcul est le bon geste - ce n'est pas une relecture de la
    # decision prise a l'assessment, c'est une decision neuve prise maintenant.
    mesures_cloture = mesures_de_la_seance(db, session_id)
    indicateurs_cloture = indicateurs_du_front(mesures_cloture)

    db.add(Indicateur(
        session_id=session_id,
        astronaute_id=session.astronaute_id,
        ts=datetime.now(timezone.utc),
        fc_moyenne=mesures_cloture.get("fc_moyenne"),
        hrv_rmssd=mesures_cloture.get("hrv_rmssd"),
        eda_fond=mesures_cloture.get("eda_fond"),
        eda_reponses=mesures_cloture.get("eda_reponses"),
        frequence_respiratoire=mesures_cloture.get("respiration"),
    ))

    # Sans aucun signal biologique, indice_charge() renverrait quand meme
    # 30.0 a confiance nulle (son repli neutre) : ce n'est pas "l'indice a la
    # cloture", c'est l'absence de mesure. On le dit avec null plutot que de
    # laisser passer ce repli pour un vrai chiffre.
    index_apres = None
    niveau_apres = None
    a_du_biologique = (
        mesures_cloture.get("fc_moyenne") is not None
        or mesures_cloture.get("hrv_rmssd") is not None
    )
    if a_du_biologique:
        historique = historique_indicateurs(db, session.astronaute_id, session_id)
        baseline, facteur = baseline_ou_generique(historique, BASELINE_GENERIQUE)
        evaluation_cloture = construire_assessment(
            session_id, mesures_cloture, baseline, facteur, indicateurs_cloture
        )
        index_apres = evaluation_cloture["index"]
        niveau_apres = evaluation_cloture["level"]

    session.fin = datetime.now(timezone.utc)
    session.mode = "standby"
    db.commit()

    return {
        "sessionId": str(session_id),
        "indexBefore": decision.indice_charge,
        "indexAfter": index_apres,
        "breathingRateBefore": avant.frequence_respiratoire if avant else None,
        "breathingRateAfter": mesures_cloture.get("respiration"),
        "heartRateBefore": avant.fc_moyenne if avant else None,
        "heartRateAfter": mesures_cloture.get("fc_moyenne"),
        "alertRaised": decision.niveau == "red" or niveau_apres == "red",
    }


@router.post("/sessions/{session_id}/consent")
def couper_consentement_seance(
    session_id: int, corps: ConsentBody, db: DbSession = Depends(get_db)
):
    """Route nichee sous /sessions pour suivre le contrat du front, mais
    l'effet est cabine-wide : une seule cabine aujourd'hui, le consentement
    n'est pas attache a une seance precise (voir GET /cabins/{id}/consent).
    """
    session = db.get(SessionModel, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="seance introuvable")
    ligne = consentement.mettre_a_jour(db, corps.camera, corps.microphone)
    return {"camera": ligne.camera, "microphone": ligne.microphone}
