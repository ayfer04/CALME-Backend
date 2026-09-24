"""Indice de charge : la seule decision du systeme, et elle est deterministe.

Un modele de langage ne fixe jamais de niveau ici. Meme entree, meme sortie,
toujours. C'est ce qui rend la decision testable et explicable apres coup.
"""

# Le poids le plus fort va aux indicateurs les mieux etablis et les moins
# controlables volontairement ; le plus faible a l'indice facial, le plus bruite.
POIDS: dict[str, float] = {
    "hrv_rmssd": 0.30,      # inverse : une variabilite basse signe le stress
    "eda_reponses": 0.25,
    "voix": 0.15,
    "eda_fond": 0.10,
    "fc_moyenne": 0.10,
    "visage": 0.10,
}

INVERSES = {"hrv_rmssd"}

# En dessous de cette couverture (somme des poids des signaux presents), la
# part manquante compte comme "a sa normale" : un seul signal ne peut plus
# porter l'indice a lui seul jusqu'aux extremes. Sans ce plancher, la
# sudation seule (0,35 des poids) poussait l'indice a 90 sur un capteur bruite.
COUVERTURE_MIN = 0.6

SEUIL_ORANGE = 40.0
SEUIL_ROUGE = 70.0
CONFIANCE_MIN = 0.4


def ecart_z(valeur: float, moyenne: float, ecart_type: float) -> float:
    """Ecart a l'historique de la personne, borne a trois sigmas.

    Le bornage n'est pas cosmetique : un capteur qui deraille produirait sinon
    un z de 40 qui saturerait l'indice a lui seul.
    """
    if ecart_type <= 0:
        return 0.0
    return max(-3.0, min(3.0, (valeur - moyenne) / ecart_type))


def indice_charge(zs: dict[str, float]) -> tuple[float, float]:
    """Moyenne ponderee des ecarts, ramenee sur 100.

    Un signal absent voit son poids retire et les autres renormalises : le
    systeme perd de la certitude, pas sa fonction. Sous COUVERTURE_MIN, la
    renormalisation s'arrete : ce qui manque compte comme neutre. La confiance renvoyee est
    la somme des poids disponibles, et elle est affichee, jamais cachee.
    """
    disponibles = {cle: z for cle, z in zs.items() if z is not None and cle in POIDS}
    confiance = sum(POIDS[cle] for cle in disponibles)
    if confiance <= 0:
        return 30.0, 0.0

    somme = sum(
        POIDS[cle] * (-z if cle in INVERSES else z)
        for cle, z in disponibles.items()
    )
    indice = 30.0 + 20.0 * (somme / max(confiance, COUVERTURE_MIN))
    return max(0.0, min(100.0, indice)), confiance


def niveau_depuis(indice: float, confiance: float) -> str:
    if confiance < CONFIANCE_MIN:
        return "unreliable"
    if indice >= SEUIL_ROUGE:
        return "red"
    if indice >= SEUIL_ORANGE:
        return "amber"
    return "green"
