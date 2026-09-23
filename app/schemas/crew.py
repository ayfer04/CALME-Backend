"""Corps de requete pour l'identification et l'enrolement de l'equipage.

Les noms de champs sont en camelCase quand le contrat le demande (meme choix
que app/schemas/session.py) ; `empreinte` est le nom impose par la tache qui a
defini ces routes, partage avec le front. Aucun champ image nulle part : le
navigateur calcule l'empreinte et c'est tout ce qui voyage.
"""

from typing import Annotated

from pydantic import BaseModel, Field

# Descripteur produit par face-api.js : 128 flottants, deja L2-normalises
# cote navigateur. Une empreinte faciale est une donnee biometrique - la
# seule de tout le systeme dont on puisse re-deriver une identite - donc sa
# longueur est verifiee au caractere pres plutot que tronquee ou completee.
Empreinte = Annotated[list[float], Field(min_length=128, max_length=128)]


class IdentificationCorps(BaseModel):
    empreinte: Empreinte


class EnrolementCorps(BaseModel):
    displayName: str
    empreinte: Empreinte


class RemplacementEmpreinteCorps(BaseModel):
    """Corps de PUT /crew/{id}/empreinte : remplace l'empreinte d'un
    astronaute deja enrole (mauvais eclairage au premier enrolement, par
    exemple), sans creer de doublon. Meme validation que l'enrolement.
    """

    empreinte: Empreinte
