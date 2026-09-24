"""Corps de requete de la synthese vocale."""

from pydantic import BaseModel, Field, field_validator

# Largement suffisant pour la question posee pendant la mesure et les
# consignes d'exercice (deux phrases, voir app/services/consigne.py,
# CONSIGNES_GENERIQUES) : refuse proprement un texte demesure avant qu'il
# n'atteigne Piper.
LONGUEUR_MAX_TEXTE = 500


class TexteCorps(BaseModel):
    texte: str = Field(min_length=1, max_length=LONGUEUR_MAX_TEXTE)

    @field_validator("texte")
    @classmethod
    def texte_non_vide(cls, valeur: str) -> str:
        # min_length=1 laisse passer un texte fait uniquement d'espaces.
        if not valeur.strip():
            raise ValueError("texte vide")
        return valeur
