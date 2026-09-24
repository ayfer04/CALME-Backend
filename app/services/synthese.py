"""Synthese vocale de la cabine : Piper transforme un texte en WAV.

Piper est entierement optionnel. Si sa bibliotheque n'est pas installee, si
le modele de voix embarque est absent, ou si la synthese echoue pour une
autre raison, ce module leve `VoixIndisponible` et rien d'autre : le reste
du serveur continue de fonctionner, seule la route /tts est affectee (voir
app/api/v1/tts.py). L'import de `piper` est volontairement paresseux, a
l'interieur de la fonction, jamais en tete de module - un import en tete
ferait planter TOUT le serveur au demarrage si le paquet manque, exactement
ce qu'on veut eviter a la veille d'une soutenance.
"""

import hashlib
import io
import os
import wave
from pathlib import Path

# Voix francaise embarquee dans l'image (voir app/resources/tts/), jamais
# telechargee au moment de la requete : la cabine tourne hors ligne. Chemin
# calcule depuis ce fichier, comme DEFAUT_DOSSIER_STATIQUE dans app/main.py,
# pour ne pas dependre du repertoire courant au lancement du serveur.
DOSSIER_MODELE = Path(__file__).resolve().parent.parent / "resources" / "tts"

# La voix de la cabine, reglable sans toucher au code : "Pierre", voix
# masculine du modele fr_FR-upmc-medium (qui porte deux locuteurs, jessica et
# pierre), un peu ralentie pour rester posee. Le modele est telecharge au
# build de l'image dans DOSSIER_VOIX (voir le Dockerfile) ; s'il manque (poste
# de developpement), on retombe sur Siwis, embarquee dans le depot.
VOIX = os.environ.get("VOIX_PIPER", "fr_FR-upmc-medium")
LOCUTEUR = os.environ.get("LOCUTEUR_PIPER", "pierre")
VITESSE = float(os.environ.get("VITESSE_VOIX", "1.08"))   # >1 = plus lent
DOSSIER_VOIX = Path(os.environ.get("DOSSIER_VOIX", "/app/modeles/piper"))
VOIX_DE_SECOURS = DOSSIER_MODELE / "fr_FR-siwis-medium.onnx"


def _chemin_modele() -> Path:
    for dossier in (DOSSIER_VOIX, DOSSIER_MODELE):
        candidat = dossier / f"{VOIX}.onnx"
        if candidat.is_file() and candidat.with_suffix(".onnx.json").is_file():
            return candidat
    return VOIX_DE_SECOURS


MODELE = _chemin_modele()
CONFIG_MODELE = MODELE.with_suffix(".onnx.json")

# Les memes textes reviennent a chaque seance : la question posee pendant la
# minute de mesure, et les huit consignes generiques (voir
# app/services/consigne.py, CONSIGNES_GENERIQUES). Inutile de les
# resynthetiser a chaque fois - un dictionnaire en memoire suffit, indexe sur
# un hachage plutot que sur le texte lui-meme.
_cache: dict[str, bytes] = {}

_voix = None
_reglages = None


class VoixIndisponible(Exception):
    """Piper n'a pas pu produire d'audio : bibliotheque absente, modele
    manquant, ou echec de synthese. L'appelant (la route /tts) la traduit en
    503, jamais en exception qui remonte jusqu'au client.
    """


def _charger_voix():
    """Charge le modele Piper une seule fois : l'initialisation d'ONNX
    Runtime coute quelques centaines de millisecondes, inutile de la payer a
    chaque requete.
    """
    global _voix
    if _voix is None:
        if not MODELE.is_file() or not CONFIG_MODELE.is_file():
            raise VoixIndisponible(f"modele de voix absent : {MODELE}")
        try:
            from piper import PiperVoice
        except ImportError as erreur:
            raise VoixIndisponible("bibliotheque piper non installee") from erreur
        try:
            _voix = PiperVoice.load(str(MODELE), str(CONFIG_MODELE))
        except Exception as erreur:
            raise VoixIndisponible(
                f"echec de chargement du modele de voix : {erreur}"
            ) from erreur
    return _voix


def _reglages_synthese(voix):
    """Locuteur et debit. Le locuteur n'existe que pour les modeles qui en
    portent plusieurs (speaker_id_map) : Siwis, en secours, n'en a qu'un."""
    global _reglages
    if _reglages is None:
        from piper import SynthesisConfig

        carte = getattr(getattr(voix, "config", None), "speaker_id_map", None) or {}
        _reglages = SynthesisConfig(speaker_id=carte.get(LOCUTEUR), length_scale=VITESSE)
    return _reglages


def synthetiser(texte: str) -> bytes:
    """Renvoie un WAV (octets) prononcant `texte`, en francais.

    Rien n'est ecrit sur disque : le WAV est assemble en memoire, comme
    app/services/voix.py le fait deja pour l'audio entrant. Le modele de
    voix embarque est la seule exception a cette regle - c'est une
    ressource, pas une donnee de mesure.
    """
    cle = hashlib.sha256(f"{MODELE.name}|{LOCUTEUR}|{VITESSE}|{texte}".encode("utf-8")).hexdigest()
    if cle in _cache:
        return _cache[cle]

    voix = _charger_voix()
    tampon = io.BytesIO()
    try:
        with wave.open(tampon, "wb") as fichier_wav:
            voix.synthesize_wav(texte, fichier_wav, syn_config=_reglages_synthese(voix))
    except Exception as erreur:
        raise VoixIndisponible(f"echec de synthese : {erreur}") from erreur

    octets = tampon.getvalue()
    _cache[cle] = octets
    return octets
