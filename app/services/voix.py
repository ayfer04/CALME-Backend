"""Indice vocal : la forme, jamais le contenu.

On ne transcrit rien. Hauteur, intensite, debit et silences suffisent, et ce
choix a une consequence directe : aucune transcription n'existe, donc aucune
ne peut fuiter. L'audio est traite en memoire et detruit dans la meme requete.
"""

import io

import numpy as np

# Les cinq features retenues du jeu eGeMAPSv02. Le jitter et le shimmer en
# sont volontairement absents : sur le micro d'une webcam a soixante
# centimetres, ce sont du bruit et non un signal.
FEATURES: dict[str, float] = {
    "F0semitoneFrom27.5Hz_sma3nz_amean": 0.25,        # hauteur moyenne
    "F0semitoneFrom27.5Hz_sma3nz_stddevNorm": 0.15,   # instabilite / monotonie
    "loudness_sma3_amean": 0.25,                      # intensite
    "VoicedSegmentsPerSec": 0.20,                     # debit de parole
    "MeanUnvoicedSegmentLength": 0.15,             # proportion de silences
}

# Ordres de grandeur pour de la parole adulte a 16 kHz. Ils ne servent qu'aux
# premieres seances d'une personne, avant que son historique existe, et la
# confiance est alors multipliee par 0,6. A reetalonner jeudi sur les
# enregistrements reels : ce sont des estimations de conception.
#
# Ne JAMAIS mettre (0.0, 1.0) ici : la hauteur moyenne vaut une trentaine de
# demi-tons, un ecart-type de 1 donnerait un z borne a +3, et l'indice vocal
# sortirait a 1,0 pour tout le monde — tout l'equipage en rouge.
BASELINE_VOCALE_GENERIQUE: dict[str, tuple[float, float]] = {
    "F0semitoneFrom27.5Hz_sma3nz_amean": (31.0, 5.0),
    "F0semitoneFrom27.5Hz_sma3nz_stddevNorm": (0.17, 0.05),
    "loudness_sma3_amean": (0.80, 0.40),
    "VoicedSegmentsPerSec": (2.20, 0.70),
    "MeanUnvoicedSegmentLength": (0.20, 0.08),
}

_smile = None


def extracteur():
    """Charge openSMILE une seule fois : l'initialisation coute ~1 s."""
    global _smile
    if _smile is None:
        import opensmile

        _smile = opensmile.Smile(
            feature_set=opensmile.FeatureSet.eGeMAPSv02,
            feature_level=opensmile.FeatureLevel.Functionals,
        )
    return _smile


def features_depuis_wav(octets: bytes) -> dict[str, float]:
    """Extrait les features d'un WAV en memoire. Rien n'est ecrit sur disque."""
    import soundfile

    pcm, fe = soundfile.read(io.BytesIO(octets), dtype="float32")
    if pcm.ndim > 1:
        pcm = pcm.mean(axis=1)
    ligne = extracteur().process_signal(pcm, fe).iloc[0]
    return {cle: float(ligne[cle]) for cle in FEATURES if cle in ligne.index}


def indice_vocal(features: dict[str, float],
                 baseline: dict[str, tuple[float, float]]) -> float:
    """Moyenne ponderee des ecarts a la voix habituelle de la personne,
    ramenee dans 0-1. Une feature absente voit son poids redistribue.
    """
    somme, poids_total = 0.0, 0.0
    for cle, poids in FEATURES.items():
        if cle not in features or cle not in baseline:
            continue
        moyenne, ecart_type = baseline[cle]
        if ecart_type <= 0:
            continue
        z = max(-3.0, min(3.0, (features[cle] - moyenne) / ecart_type))
        somme += poids * z
        poids_total += poids

    if poids_total <= 0:
        return 0.5
    return float(np.clip(0.5 + (somme / poids_total) / 6.0, 0.0, 1.0))
