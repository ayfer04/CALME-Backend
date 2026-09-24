"""La note de bien-etre de la cabine, sur 100 : 100 est la meilleure note
(serein, content), 0 la pire (detresse grave).

Elle remplace l'indice de charge (app/services/indice.py, ou un chiffre haut
voulait dire "stresse") : les capteurs de l'Arduino sont abandonnes, la
cabine ne s'appuie plus que sur ce qu'elle voit et entend.

Trois notes, chacune sur 100 :
- visage : tension des sourcils et de la bouche (MediaPipe, dans le
  navigateur), un sourire la releve ;
- voix : ecart a une voix posee (hauteur, intensite, debit, silences) ;
- humeur : ce que la personne raconte pendant la conversation, note par le
  modele local sur la transcription - qui n'est jamais conservee, seule la
  note l'est.

La note globale est leur moyenne ponderee, sur ce qui est disponible.
Deterministe pour le visage et la voix ; l'humeur vient du modele, mais un
filet de securite sur les mots de detresse ne depend pas de lui.
"""

import re

POIDS = {"parole": 0.45, "visage": 0.30, "voix": 0.25}

SEUIL_VERT = 60.0
SEUIL_ORANGE = 35.0
# En dessous, aucune note n'a vraiment ete mesuree (ni visage ni voix ni
# conversation) : on ne conclut rien.
CONFIANCE_MIN = 0.25
# Une humeur a ce niveau (idees noires, detresse) passe la seance au rouge,
# quoi que disent le visage et la voix.
HUMEUR_DETRESSE = 15.0

# Visage : au repos, la tension MediaPipe se situe autour de 0,08-0,12.
TENSION_REPOS = 0.08


def _borner(valeur: float) -> float:
    return max(0.0, min(100.0, valeur))


def note_visage(tension: float | None, sourire: float | None = None) -> float | None:
    if tension is None:
        return None
    note = 95.0 - 200.0 * max(0.0, tension - TENSION_REPOS) + 25.0 * (sourire or 0.0)
    return round(_borner(note), 1)


def note_voix(indice: float | None) -> float | None:
    """`indice` vaut 0,5 pour une voix a son habitude (app/services/voix.py) ;
    au-dessus, voix plus aigue, forte ou rapide (tension) ; en dessous, voix
    eteinte (fatigue, tristesse). La tension coute un peu plus cher."""
    if indice is None:
        return None
    note = 85.0 - 150.0 * max(0.0, indice - 0.5) - 100.0 * max(0.0, 0.5 - indice)
    return round(_borner(note), 1)


# Filet de securite : ces mots font tomber l'humeur au plus bas, que le
# modele les ait bien lus ou non.
MOTS_DETRESSE = re.compile(
    r"suicid|me tuer|me suicider|en finir|mettre fin a mes jours|mettre fin à mes jours|"
    r"plus envie de vivre|envie de mourir|je veux mourir|me faire du mal|me blesser",
    re.IGNORECASE,
)


# Le modele seul ne descend pas sous ce plancher : il lui arrivait de noter 0
# une phrase mal transcrite. Seuls les mots de detresse, ci-dessus, font
# tomber l'humeur au plus bas - et passer la seance au rouge.
PLANCHER_MODELE = 16.0
# Sous ce nombre de mots, la phrase est trop courte (ou du bruit mal
# transcrit) pour juger une humeur.
MOTS_MIN_HUMEUR = 4


def detresse_exprimee(texte: str) -> bool:
    return bool(texte) and bool(MOTS_DETRESSE.search(texte))


def humeur_securisee(humeur: float | None, texte: str) -> float | None:
    if detresse_exprimee(texte):
        return min(humeur if humeur is not None else 100.0, 5.0)
    if humeur is None or len((texte or "").split()) < MOTS_MIN_HUMEUR:
        return None
    return round(max(PLANCHER_MODELE, _borner(float(humeur))), 1)


def notes_de(mesures: dict) -> dict[str, float | None]:
    return {
        "visage": note_visage(mesures.get("visage"), mesures.get("sourire")),
        "voix": note_voix(mesures.get("voix")),
        "parole": mesures.get("parole"),
    }


def note_globale(notes: dict[str, float | None]) -> tuple[float, float]:
    """(note sur 100, confiance entre 0 et 1). La confiance est la part des
    poids reellement mesuree ; sans rien, 50 (neutre) a confiance nulle."""
    disponibles = {c: v for c, v in notes.items() if v is not None and c in POIDS}
    confiance = sum(POIDS[c] for c in disponibles)
    if confiance <= 0:
        return 50.0, 0.0
    note = sum(POIDS[c] * v for c, v in disponibles.items()) / confiance
    return round(_borner(note), 1), round(confiance, 3)


def niveau(note: float, confiance: float, humeur: float | None = None) -> str:
    if confiance < CONFIANCE_MIN:
        return "unreliable"
    if humeur is not None and humeur <= HUMEUR_DETRESSE:
        return "red"
    if note >= SEUIL_VERT:
        return "green"
    if note >= SEUIL_ORANGE:
        return "amber"
    return "red"


def signal_dominant(notes: dict[str, float | None]) -> str:
    """La note la plus basse sous le vert : c'est elle qui oriente
    l'exercice. Tout au vert : "diffus" (rien ne se detache)."""
    basses = {c: v for c, v in notes.items() if v is not None and v < SEUIL_VERT}
    if not basses:
        return "diffus"
    return min(basses, key=basses.get)


def verdict(note: float, niveau_: str) -> str:
    """La phrase que la cabine dit avant de proposer l'exercice."""
    arrondie = round(note)
    if niveau_ == "unreliable":
        return "Je n'ai pas assez d'éléments pour te donner une note aujourd'hui."
    if niveau_ == "green":
        return f"Tout va bien : {arrondie} sur 100."
    if niveau_ == "amber":
        return f"Je te sens un peu tendu : {arrondie} sur 100."
    return (f"Je te sens en difficulté : {arrondie} sur 100. "
            "Tu n'es pas seul, n'hésite pas à en parler au médecin de bord.")
