"""Synthese vocale de la cabine : POST /tts transforme un texte en WAV.

La cabine doit parler : dire sa question pendant la minute de mesure, puis
lire la consigne d'exercice choisie (voir app/services/consigne.py). Piper
est entierement optionnel (voir app/services/synthese.py) - si sa
bibliotheque ou son modele de voix manquent, ou si la synthese echoue pour
toute autre raison, cette route renvoie un 503 explicite. Elle ne fait
jamais planter le reste du serveur : c'est le seul but de cette isolation.
"""

from fastapi import APIRouter, HTTPException
from starlette.responses import Response

from app.schemas.tts import TexteCorps
from app.services import synthese

router = APIRouter()


@router.post("/tts")
def synthetiser_texte(corps: TexteCorps):
    try:
        wav = synthese.synthetiser(corps.texte)
    except synthese.VoixIndisponible as erreur:
        raise HTTPException(
            status_code=503,
            detail=f"synthese vocale indisponible : {erreur}",
        ) from erreur
    return Response(content=wav, media_type="audio/wav")
