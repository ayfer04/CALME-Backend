"""Cabine et equipage : occupant, derniere seance, consentement, capteurs.

Une seule cabine et un seul astronaute de test suffisent aujourd'hui (voir
tache-19-brief.md). Les routes ci-dessous l'assument explicitement plutot que
de le cacher derriere une fausse generalite : `cabin_id` est accepte pour
suivre le contrat du front, mais n'est pas utilise pour choisir entre
plusieurs cabines puisqu'il n'en existe qu'une.
"""

from sqlalchemy.orm import Session as DbSession

from fastapi import APIRouter, Depends

from app.api.v1.calcul import mesures_de_la_seance
from app.deps import get_db
from app.models.tables import Astronaute, Mesure
from app.models.tables import Session as SessionModel
from app.services import consentement

router = APIRouter()

# Bornes physiologiques plausibles du capteur cardiaque (voir
# app/services/cardiaque.py, IBI_MIN_MS/IBI_MAX_MS : 30 a 220 bpm). Un
# resultat hors de ces bornes n'est pas une urgence medicale, c'est un
# capteur qui deconne - exactement l'esprit du champ `note`.
FC_MIN, FC_MAX = 30, 220

# Modele et cadence sont ceux graves sur le composant reellement cable dans
# la cabine, pas des valeurs de demonstration : voir tache-19-brief.md.
# La camera et le micro partagent le meme boitier USB (Logitech C270).
GABARIT_CAPTEURS = {
    "hr": {"label": "Cardiaque", "model": "MAX30102", "sampleRate": "100 Hz", "unit": "bpm"},
    "eda": {"label": "Sudation", "model": "Grove GSR", "sampleRate": "10 Hz", "unit": "µS"},
    "face": {"label": "Visage", "model": "Logitech C270", "sampleRate": "5 im/s", "unit": ""},
    "voice": {"label": "Voix", "model": "Logitech C270", "sampleRate": "16 kHz", "unit": ""},
}


def _premier_astronaute(db: DbSession) -> Astronaute:
    """Une seule cabine, un seul astronaute de test aujourd'hui : on renvoie
    le premier de la table plutot que d'exiger un crewId qui n'existe nulle
    part encore (meme simplification, et la meme raison, que dans
    app/api/v1/ingest.py::get_or_create_session).
    """
    astronaute = db.query(Astronaute).order_by(Astronaute.id).first()
    if astronaute is None:
        astronaute = Astronaute(nom="Astronaute de test")
        db.add(astronaute)
        db.commit()
        db.refresh(astronaute)
    return astronaute


def _crew_member(astronaute: Astronaute) -> dict:
    return {
        "id": str(astronaute.id),
        "displayName": astronaute.nom,
        "role": astronaute.role,
        "initials": astronaute.initiales,
        "joinedSol": astronaute.sol_embarquement,
    }


@router.get("/cabins/{cabin_id}/occupant")
def occupant(cabin_id: str, db: DbSession = Depends(get_db)):
    return _crew_member(_premier_astronaute(db))


@router.get("/crew/{crew_id}/last-session")
def derniere_seance(crew_id: str, db: DbSession = Depends(get_db)):
    try:
        astronaute_id = int(crew_id)
    except ValueError:
        return {"lastSessionAt": None}

    derniere = (
        db.query(SessionModel)
        .filter(SessionModel.astronaute_id == astronaute_id)
        .order_by(SessionModel.debut.desc())
        .first()
    )
    return {"lastSessionAt": derniere.debut.isoformat() if derniere else None}


@router.get("/cabins/{cabin_id}/consent")
def lire_consentement(cabin_id: str, db: DbSession = Depends(get_db)):
    ligne = consentement.obtenir_ou_creer(db)
    return {"camera": ligne.camera, "microphone": ligne.microphone}


@router.get("/cabins/{cabin_id}/sensors")
def capteurs(cabin_id: str, db: DbSession = Depends(get_db)):
    consent = consentement.obtenir_ou_creer(db)

    # Instantane de la derniere seance connue, ouverte ou non : les capteurs
    # n'ont pas d'existence hors d'une seance dans ce systeme, donc "l'etat
    # des capteurs maintenant" est celui de la derniere mesure recue.
    derniere_session = db.query(SessionModel).order_by(SessionModel.id.desc()).first()
    mesures = mesures_de_la_seance(db, derniere_session.id) if derniere_session else {}

    resultat = []

    valeur_hr = mesures.get("fc_moyenne")
    if valeur_hr is None:
        niveau_hr, note_hr = "unreliable", "Aucune mesure recue"
    elif not (FC_MIN <= valeur_hr <= FC_MAX):
        niveau_hr, note_hr = "red", f"Hors bornes {FC_MIN}-{FC_MAX} bpm, mesure suspecte"
    else:
        niveau_hr, note_hr = "green", None
    resultat.append({
        "key": "hr",
        **GABARIT_CAPTEURS["hr"],
        "value": round(valeur_hr, 1) if valeur_hr is not None else None,
        # Pas de serie de battements par minute persistee seconde par
        # seconde : la fenetre ne serait qu'un decor. On ne l'invente pas.
        "window": [],
        "level": niveau_hr,
        "note": note_hr,
    })

    valeur_eda = mesures.get("eda_fond")
    fenetre_eda: list[float] = []
    if derniere_session is not None:
        ligne_sudation = (
            db.query(Mesure)
            .filter(Mesure.session_id == derniere_session.id, Mesure.capteur == "sudation")
            .order_by(Mesure.seq.desc())
            .first()
        )
        if ligne_sudation is not None:
            fenetre_eda = list(ligne_sudation.valeurs.get("eda_us", []))[-30:]
    resultat.append({
        "key": "eda",
        **GABARIT_CAPTEURS["eda"],
        "value": round(valeur_eda, 2) if valeur_eda is not None else None,
        "window": fenetre_eda,
        "level": "green" if valeur_eda is not None else "unreliable",
        "note": None if valeur_eda is not None else "Aucune mesure recue",
    })

    # Visage et voix ne transitent que par le WebSocket au moment ou ils
    # sont produits (voir POST /sessions/{id}/face et /audio) : rien n'est
    # ecrit en base pour eux, donc rien de reel a relire ici. On le dit
    # plutot que d'inventer une valeur qui n'a jamais existe.
    for cle, raison_coupure in (("face", "camera"), ("voice", "microphone")):
        actif = getattr(consent, raison_coupure)
        resultat.append({
            "key": cle,
            **GABARIT_CAPTEURS[cle],
            "value": None,
            "window": [],
            "level": "unreliable",
            "note": (
                "Coupe par consentement" if not actif
                else "Non journalise en base (flux WebSocket uniquement)"
            ),
        })

    return resultat
