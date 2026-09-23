"""Corps de requete du cycle de vie d'une seance.

Les noms de champs sont deliberement en camelCase, pas en snake_case : ce
sont ceux du contrat JSON avec le front (voir Frontend/src/api/live.ts), pas
une convention Python interne qu'il faudrait ensuite traduire.
"""

from typing import Literal

from pydantic import BaseModel


class OuvertureSeance(BaseModel):
    crewId: str
    # Une seule cabine aujourd'hui : le champ est valide mais pas exploite
    # (voir app/api/v1/cabine.py pour la meme simplification assumee).
    cabinId: str


class RetourConsigne(BaseModel):
    feedback: Literal["helped", "not-really"]
