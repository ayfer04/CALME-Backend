"""Cabine et equipage : occupant, derniere seance, consentement, capteurs,
identification faciale et enrolement.

Une seule cabine et un seul astronaute de test suffisent aujourd'hui (voir
tache-19-brief.md). Les routes ci-dessous l'assument explicitement plutot que
de le cacher derriere une fausse generalite : `cabin_id` est accepte pour
suivre le contrat du front, mais n'est pas utilise pour choisir entre
plusieurs cabines puisqu'il n'en existe qu'une.

L'identification et l'enrolement manipulent une empreinte faciale : une
donnee biometrique, la seule de tout le systeme dont on puisse re-deriver une
identite (voir app/models/tables.py::Astronaute.empreinte_faciale et
app/services/visage.py). Aucune image ne transite jamais par ces routes.
"""

from sqlalchemy.orm import Session as DbSession

from fastapi import APIRouter, Depends, HTTPException

from app.api.v1.calcul import mesures_de_la_seance
from app.deps import get_db
from app.models.tables import Astronaute, Mesure
from app.models.tables import Session as SessionModel
from app.schemas.crew import EnrolementCorps, IdentificationCorps, RemplacementEmpreinteCorps
from app.services import consentement, notation, visage

router = APIRouter()

# Modele et cadence sont ceux du materiel reellement branche sur la tour.
# La camera et le micro partagent le meme boitier USB (DJI Osmo Action 4) ;
# les capteurs de l'Arduino (coeur, sudation) sont abandonnes.
GABARIT_CAPTEURS = {
    "face": {"label": "Visage", "model": "DJI Osmo Action 4", "sampleRate": "10 im/s", "unit": "/100"},
    "voice": {"label": "Voix", "model": "DJI Osmo Action 4", "sampleRate": "16 kHz", "unit": "/100"},
    "mood": {"label": "Humeur", "model": "Whisper + llama3.2:3b", "sampleRate": "par réponse", "unit": "/100"},
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
        # Initiales deduites du nom quand l'enrolement ne les a pas saisies.
        "initials": astronaute.initiales or "".join(m[0] for m in astronaute.nom.split()[:2]).upper(),
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

    # Affiches comme des notes sur 100 (100 = le mieux), comme a l'ecran de la cabine.
    for cle, capteur, champ, raison_coupure in (("face", "visage", "tension", "camera"),
                                                 ("voice", "voix", "indice", "microphone"),
                                                 ("mood", "parole", "humeur", "microphone")):
        actif = getattr(consent, raison_coupure)
        serie: list[float] = []
        if derniere_session is not None and actif:
            lignes = (db.query(Mesure)
                      .filter(Mesure.session_id == derniere_session.id, Mesure.capteur == capteur)
                      .order_by(Mesure.ts.desc()).limit(30).all())
            serie = [
                notation.note_visage(float(l.valeurs[champ]), l.valeurs.get("sourire"))
                if capteur == "visage"
                else notation.note_voix(float(l.valeurs[champ])) if capteur == "voix"
                else round(float(l.valeurs[champ]), 1)
                for l in reversed(lignes) if l.valeurs.get(champ) is not None
            ]
        resultat.append({
            "key": cle,
            **GABARIT_CAPTEURS[cle],
            "value": serie[-1] if serie else None,
            "window": serie,
            "level": "green" if serie else "unreliable",
            "note": (
                "Coupé par consentement" if not actif
                else None if serie else "Aucune mesure reçue pendant la dernière séance"
            ),
        })

    return resultat


@router.get("/crew")
def liste_equipage(db: DbSession = Depends(get_db)):
    """Tout l'equipage, pour la liste de repli quand l'identification faciale
    ne reconnait personne (voir POST /cabins/{id}/identify).
    """
    astronautes = db.query(Astronaute).order_by(Astronaute.id).all()
    return [_crew_member(a) for a in astronautes]


@router.post("/crew/enroll")
def enroler(corps: EnrolementCorps, db: DbSession = Depends(get_db)):
    """Cree un nouvel astronaute avec son empreinte faciale.

    Un enrolement cree toujours une personne, il ne remplace jamais
    silencieusement l'empreinte d'un astronaute existant : cette route ne
    connait que displayName + empreinte, jamais un id a mettre a jour.
    """
    astronaute = Astronaute(nom=corps.displayName, empreinte_faciale=corps.empreinte)
    db.add(astronaute)
    db.commit()
    db.refresh(astronaute)
    return _crew_member(astronaute)


@router.put("/crew/{crew_id}/empreinte")
def remplacer_empreinte(
    crew_id: str, corps: RemplacementEmpreinteCorps, db: DbSession = Depends(get_db)
):
    """Remplace l'empreinte faciale d'un astronaute deja enrole.

    Sans cette route, la seule issue pour quelqu'un enrole sous un mauvais
    eclairage et qui n'est plus reconnu etait de creer un doublon (voir
    POST /crew/enroll). Meme validation (128 flottants) et meme schema de
    reponse que l'enrolement : c'est la meme donnee, seule la cible change.
    """
    try:
        astronaute_id = int(crew_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="astronaute introuvable")

    astronaute = db.get(Astronaute, astronaute_id)
    if astronaute is None:
        raise HTTPException(status_code=404, detail="astronaute introuvable")

    astronaute.empreinte_faciale = corps.empreinte
    db.commit()
    db.refresh(astronaute)
    return _crew_member(astronaute)


@router.post("/cabins/{cabin_id}/identify")
def identifier(cabin_id: str, corps: IdentificationCorps, db: DbSession = Depends(get_db)):
    """Compare l'empreinte recue a celles de l'equipage deja enrole.

    Ne considere que les astronautes qui ont deja une empreinte enregistree :
    ceux qui n'ont jamais ete enroles (empreinte_faciale nulle) sont
    simplement absents des candidats, jamais une cause de plantage.
    """
    candidats = [
        (a.id, a.empreinte_faciale)
        for a in db.query(Astronaute).filter(Astronaute.empreinte_faciale.isnot(None)).all()
    ]
    identifiant = visage.plus_proche_sous_seuil(corps.empreinte, candidats)
    if identifiant is None:
        return None
    return _crew_member(db.get(Astronaute, identifiant))
