"""POST /sessions/{id}/dialogue : un tour de conversation avec la cabine.

Le navigateur envoie la reponse de l'astronaute (WAV) et l'historique de la
conversation, qu'il est le seul a conserver. Le serveur renvoie ce qu'il a
compris et la relance de Lila, puis oublie tout : pas de base, pas de
journal, pas de fichier (voir app/services/dialogue.py).
"""

import json
import os
import threading

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session as DbSession
from starlette.concurrency import run_in_threadpool

from app.deps import get_db
from app.models.tables import Mesure, Session as SessionModel
from app.services import dialogue
from app.ws.hub import hub

router = APIRouter()

# Whisper se charge en arriere-plan des le demarrage du serveur (voir
# dialogue.precharger). Desactive dans les tests : ils remplacent la
# transcription par une doublure et n'ont pas le modele.
if os.environ.get("PRECHARGER_WHISPER", "1") != "0":
    threading.Thread(target=dialogue.precharger, daemon=True).start()


def _historique(brut: str) -> list[dict]:
    try:
        valeur = json.loads(brut or "[]")
    except json.JSONDecodeError as erreur:
        raise HTTPException(status_code=422, detail="historique illisible") from erreur
    if not isinstance(valeur, list):
        raise HTTPException(status_code=422, detail="historique illisible")
    return [t for t in valeur if isinstance(t, dict)]


@router.post("/sessions/{session_id}/dialogue")
async def tour_de_dialogue(
    session_id: int,
    fichier: UploadFile = File(...),
    historique: str = Form("[]"),
    dernier_tour: bool = Form(False),
    db: DbSession = Depends(get_db),
):
    tours = _historique(historique)
    octets = await fichier.read()
    try:
        # Transcription et generation sont bloquantes (CPU, puis reseau) : hors
        # de la boucle asynchrone, pour ne pas figer le WebSocket de la mesure.
        entendu = await run_in_threadpool(dialogue.transcrire, octets)
    except dialogue.DialogueIndisponible as erreur:
        raise HTTPException(status_code=503, detail=f"dialogue indisponible : {erreur}") from erreur
    finally:
        del octets

    reponse, source, humeur = await run_in_threadpool(dialogue.repondre, tours, entendu, dernier_tour)
    if humeur is not None:
        # Seule la note est gardee : ni les mots, ni le son.
        if db.get(SessionModel, session_id) is not None:
            db.add(Mesure(session_id=session_id, device_id="cabine-front", capteur="parole", seq=0,
                          ts=datetime.now(timezone.utc), valeurs={"humeur": humeur}, qualite={}))
            db.commit()
        await hub.diffuser(session_id, {"type": "frame", "payload": {
            "at": None, "heartRate": None, "skinConductance": None, "faceTension": None,
            "voiceIndex": None, "suspect": [], "moodScore": humeur}})
    return {"entendu": entendu, "reponse": reponse, "source": source, "humeur": humeur}
