"""Dialogue de la cabine pendant la minute de mesure.

La cabine pose sa question, l'astronaute repond, la cabine rebondit. Pour
rebondir il faut comprendre les mots : la reponse est donc transcrite, sur la
tour, par Whisper (faster-whisper, hors ligne), puis confiee au modele local
qui redige une relance de deux phrases au plus.

Ce que ce module garantit, et qui remplace l'ancien "on ne transcrit rien" :
la transcription n'existe qu'en memoire, le temps de la requete. Elle n'est
jamais ecrite en base, jamais journalisee, jamais conservee cote serveur -
comme l'audio dans app/services/voix.py. Le seul historique de la
conversation vit dans le navigateur de la cabine, et disparait avec la seance.

Comme pour la synthese vocale (app/services/synthese.py), les deux briques
sont optionnelles : Whisper absent leve `DialogueIndisponible`, un modele
Ollama muet ou trop lent donne une relance generique. La mesure, elle,
continue dans tous les cas.
"""

import io
import os
import random
import threading

import httpx
import numpy as np

from app.services.consigne import DELAI_CONNEXION_S, HOTE_OLLAMA, MODELE

MODELE_WHISPER = os.environ.get("MODELE_WHISPER", "small")
# Ou chercher (et, en developpement seulement, telecharger) le modele Whisper.
# Dans l'image Docker il y est deja, telecharge au build : la cabine tourne
# hors ligne, rien ne doit partir sur le reseau au moment de la requete.
DOSSIER_WHISPER = os.environ.get("DOSSIER_WHISPER") or None
TAUX_WHISPER = 16_000

# Une relance doit tomber pendant que l'astronaute est encore la : au-dela, la
# minute de mesure est finie et la phrase arriverait sur l'ecran suivant.
# Sur le CPU de la tour, le modele 3b redige une relance courte en 5 a 8 s.
DELAI_REPONSE_S = 15.0
TOURS_MAX_HISTORIQUE = 6
LONGUEUR_MAX_ENTENDU = 400

# Les chaines prononcees gardent leurs accents : elles sont affichees et lues
# par Piper, qui prononcerait "ete" comme il est ecrit.
SYSTEME = (
    "Tu es Lila, la voix de la cabine de récupération d'un vaisseau spatial. "
    "Pendant qu'elle mesure le stress de l'astronaute, la cabine discute avec lui "
    "pour l'aider à se poser. Tu réponds en français, en tutoyant, en 30 mots au "
    "maximum : une phrase courte qui reformule ce qu'il vient de dire, puis UNE "
    "question ouverte et douce sur ce qu'il ressent ou sur sa journée. Tu accueilles "
    "toutes les émotions sans jamais conseiller de les repousser. Tu ne parles jamais "
    "de symptômes, de santé ni de médicaments : aucun conseil médical, aucun "
    "diagnostic, aucun jugement. Pas d'emoji, pas de liste. Si c'est le dernier "
    "tour, pas de question : tu le remercies et tu l'invites à respirer calmement. "
    "S'il parle de se faire du mal ou d'un danger, tu lui dis avec douceur de "
    "prévenir tout de suite le médecin de bord.\n\n"
    # Un exemple suffit a un petit modele pour tenir le ton et la longueur ;
    # sans lui, le 3b partait en questions sur les symptomes physiques.
    "Exemple.\n"
    "Astronaute : J'ai passé la journée à recalibrer les capteurs, rien ne marchait.\n"
    "Lila : Une journée où rien ne répond, c'est usant. Qu'est-ce qui t'a le plus agacé ?"
)

RELANCES_SANS_MODELE = [
    "Merci de me le raconter. Qu'est-ce qui a été le plus lourd pour toi aujourd'hui ?",
    "Je t'entends. Et là, maintenant, comment te sens-tu ?",
    "D'accord. Qu'est-ce qui t'aiderait à souffler un peu ce soir ?",
]
CLOTURE_SANS_MODELE = "Merci de m'avoir parlé. Respire calmement, je termine la mesure."
RELANCE_SILENCE = "Prends ton temps. Tu peux me raconter ta journée en quelques mots."

_modele_whisper = None
# Le prechargement (au demarrage) et une premiere requete peuvent arriver en
# meme temps : un seul des deux charge le modele.
_verrou_whisper = threading.Lock()


class DialogueIndisponible(Exception):
    """La transcription est impossible (bibliotheque ou modele absents, audio
    illisible). La route la traduit en 503 ; le front continue la mesure sans
    dialogue, comme avant."""


def _charger_whisper():
    global _modele_whisper
    with _verrou_whisper:
        return _charger_whisper_sans_verrou()


def _charger_whisper_sans_verrou():
    global _modele_whisper
    if _modele_whisper is None:
        try:
            from faster_whisper import WhisperModel
        except ImportError as erreur:
            raise DialogueIndisponible("bibliotheque faster-whisper non installee") from erreur
        try:
            # int8 sur CPU : la tour n'a pas de carte graphique, et c'est le
            # format qui garde la transcription sous deux secondes.
            _modele_whisper = WhisperModel(MODELE_WHISPER, device="cpu", compute_type="int8",
                                           download_root=DOSSIER_WHISPER)
        except Exception as erreur:
            raise DialogueIndisponible(f"modele Whisper indisponible : {erreur}") from erreur
    return _modele_whisper


def precharger() -> None:
    """Charge Whisper en avance, pour que le premier tour de la premiere
    seance ne paie pas les quelques secondes de chargement. Silencieux en cas
    d'echec : la route redira pourquoi au moment ou on s'en sert."""
    try:
        _charger_whisper()
    except DialogueIndisponible:
        pass


def _audio_16k(octets: bytes) -> np.ndarray:
    """WAV (ou FLAC, OGG) -> float32 mono a 16 kHz, en memoire."""
    import soundfile

    try:
        signal, taux = soundfile.read(io.BytesIO(octets), dtype="float32", always_2d=True)
    except Exception as erreur:
        raise DialogueIndisponible(f"audio illisible : {erreur}") from erreur
    mono = signal.mean(axis=1)
    if taux != TAUX_WHISPER and len(mono):
        from scipy.signal import resample_poly

        mono = resample_poly(mono, TAUX_WHISPER, taux).astype("float32")
    return mono


def transcrire(octets: bytes) -> str:
    """Renvoie ce qui a ete dit, ou une chaine vide si personne n'a parle."""
    audio = _audio_16k(octets)
    if len(audio) < TAUX_WHISPER // 4:          # moins d'un quart de seconde
        return ""
    modele = _charger_whisper()
    try:
        segments, _ = modele.transcribe(audio, language="fr", beam_size=1, vad_filter=True,
                                        condition_on_previous_text=False)
        texte = " ".join(s.text.strip() for s in segments).strip()
    except Exception as erreur:
        raise DialogueIndisponible(f"echec de transcription : {erreur}") from erreur
    return texte[:LONGUEUR_MAX_ENTENDU]


def _messages(historique: list[dict], entendu: str, dernier_tour: bool) -> list[dict]:
    messages = [{"role": "system", "content": SYSTEME}]
    for tour in historique[-TOURS_MAX_HISTORIQUE:]:
        role = "assistant" if tour.get("role") == "lila" else "user"
        texte = str(tour.get("texte", ""))[:LONGUEUR_MAX_ENTENDU]
        if texte:
            messages.append({"role": role, "content": texte})
    consigne = " (C'est le dernier tour : pas de question.)" if dernier_tour else ""
    messages.append({"role": "user", "content": entendu + consigne})
    return messages


SCHEMA_REPONSE = {
    "type": "object",
    "properties": {
        "reponse": {"type": "string"},
        "humeur": {"type": "integer", "minimum": 0, "maximum": 100},
    },
    "required": ["reponse", "humeur"],
}

CONSIGNE_HUMEUR = (
    ' Reponds en JSON : {"reponse": ta phrase pour lui, "humeur": une note de 0 '
    "a 100 de l'etat emotionnel exprime par l'astronaute dans ses mots (100 : "
    "tres bien, content ; 50 : neutre ; 20 : triste, angoisse ; 0 : detresse "
    'grave, idees suicidaires)}.'
)


def detresse_exprimee(texte: str) -> bool:
    from app.services.notation import detresse_exprimee as _detresse

    return _detresse(texte)


def repondre(historique: list[dict], entendu: str,
             dernier_tour: bool) -> tuple[str, str, float | None]:
    """Renvoie (relance, source, humeur). Source "model" ou "rules" ; humeur
    sur 100, ou None si rien n'a ete dit ou si le modele n'a pas repondu."""
    from app.services.notation import humeur_securisee

    if not entendu:
        return (CLOTURE_SANS_MODELE if dernier_tour else RELANCE_SILENCE), "rules", None
    try:
        import ollama

        client = ollama.Client(host=HOTE_OLLAMA,
                               timeout=httpx.Timeout(DELAI_REPONSE_S, connect=DELAI_CONNEXION_S))
        messages = _messages(historique, entendu, dernier_tour)
        messages[0] = {"role": "system", "content": SYSTEME + CONSIGNE_HUMEUR}
        reponse = client.chat(model=MODELE, messages=messages, format=SCHEMA_REPONSE,
                              options={"num_predict": 110, "temperature": 0.6})
        import json

        contenu = json.loads(reponse["message"]["content"])
        texte = " ".join(str(contenu.get("reponse", "")).split())
        if texte:
            return texte, "model", humeur_securisee(contenu.get("humeur"), entendu)
    except Exception:
        pass
    # Sans modele, pas de note d'humeur - sauf le filet de securite sur les
    # mots de detresse, qui ne depend pas de lui.
    humeur = humeur_securisee(None, entendu)
    if dernier_tour:
        return CLOTURE_SANS_MODELE, "rules", humeur
    return random.choice(RELANCES_SANS_MODELE), "rules", humeur
