"""Reconnaissance faciale par distance euclidienne entre empreintes.

Une empreinte faciale (128 flottants, L2-normalises, calcules par face-api.js
dans le navigateur) est une donnee biometrique : c'est la seule chose de tout
ce systeme dont on puisse re-deriver une identite. Ce module ne manipule
jamais d'image - il ne pourrait pas, il ne recoit que des vecteurs - et ne
fait jamais la difference entre "personne ne correspond" et "je ne suis pas
sur" : sous le seuil, il n'y a pas de reponse, il y a `None`.

L'equipage tient sur huit personnes : une boucle numpy suffit, pas besoin
d'un index vectoriel (pgvector ou autre).
"""

import os

import numpy as np

# Seuil documente par face-api.js pour la distance euclidienne entre deux
# descripteurs de la meme personne (en dessous, meme personne). Lisible
# depuis l'environnement pour pouvoir l'ajuster en demonstration sans
# recompiler ni redeployer.
SEUIL_RECONNAISSANCE = float(os.environ.get("SEUIL_RECONNAISSANCE_FACIALE", "0.6"))


def plus_proche_sous_seuil(
    empreinte: list[float], candidats: list[tuple[int, list[float]]]
) -> int | None:
    """Renvoie l'id du candidat le plus proche, seulement s'il est sous le seuil.

    Ne renvoie jamais "le moins pire" : au-dessus du seuil, personne n'est
    identifie. Se tromper de personne est pire que ne reconnaitre personne,
    parce que les mesures de stress de l'un iraient alors dans le dossier de
    l'autre.
    """
    if not candidats:
        return None

    cible = np.asarray(empreinte, dtype=float)
    meilleur_id: int | None = None
    meilleure_distance: float | None = None
    for candidat_id, vecteur in candidats:
        distance = float(np.linalg.norm(cible - np.asarray(vecteur, dtype=float)))
        if meilleure_distance is None or distance < meilleure_distance:
            meilleure_distance = distance
            meilleur_id = candidat_id

    if meilleure_distance is None or meilleure_distance >= SEUIL_RECONNAISSANCE:
        return None
    return meilleur_id
