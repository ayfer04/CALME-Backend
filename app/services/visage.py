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


# Deux personnes trop proches l'une de l'autre : on ne tranche pas. Le meilleur
# candidat doit devancer le second d'au moins cette distance.
MARGE_ENTRE_CANDIDATS = float(os.environ.get("MARGE_RECONNAISSANCE_FACIALE", "0.05"))
# Reconnu avec certitude sous ce seuil : l'empreinte du jour s'ajoute aux
# references de la personne (lumiere, lunettes, barbe : la cabine apprend).
SEUIL_APPRENTISSAGE = 0.45
REFERENCES_MAX = 10


def references(empreinte_faciale) -> list[list[float]]:
    """Les empreintes de reference d'un astronaute. Les anciennes lignes n'en
    gardaient qu'une (un vecteur plat) ; elles en gardent maintenant une liste."""
    if not empreinte_faciale:
        return []
    if isinstance(empreinte_faciale[0], (int, float)):
        return [list(empreinte_faciale)]
    return [list(v) for v in empreinte_faciale]


def ajouter_reference(empreinte_faciale, nouvelle: list[float]) -> list[list[float]]:
    """Ajoute une reference, en gardant les plus recentes."""
    return (references(empreinte_faciale) + [list(nouvelle)])[-REFERENCES_MAX:]


def meilleure_correspondance(
    empreinte: list[float], candidats: list[tuple[int, list[list[float]]]]
) -> tuple[int | None, float | None]:
    """(id, distance) du candidat retenu, ou (None, distance) si personne ne
    correspond assez, ou si deux candidats sont trop proches pour trancher.

    Distance d'un candidat = la plus petite distance a l'une de ses
    references. Ne renvoie jamais "le moins pire" : se tromper de personne est
    pire que ne reconnaitre personne, parce que les mesures de l'un iraient
    alors dans le dossier de l'autre.
    """
    cible = np.asarray(empreinte, dtype=float)
    distances = []
    for candidat_id, refs in candidats:
        if refs:
            distances.append((min(float(np.linalg.norm(cible - np.asarray(r, dtype=float)))
                                  for r in refs), candidat_id))
    if not distances:
        return None, None
    distances.sort()
    meilleure, meilleur_id = distances[0]
    if meilleure >= SEUIL_RECONNAISSANCE:
        return None, meilleure
    if len(distances) > 1 and distances[1][0] - meilleure < MARGE_ENTRE_CANDIDATS:
        return None, meilleure
    return meilleur_id, meilleure


def plus_proche_sous_seuil(
    empreinte: list[float], candidats: list[tuple[int, list[float]]]
) -> int | None:
    """Forme historique : un seul vecteur par candidat."""
    return meilleure_correspondance(empreinte, [(i, references(v)) for i, v in candidats])[0]
