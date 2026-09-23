"""Corps de requete de la cabine (consentement)."""

from pydantic import BaseModel


class ConsentBody(BaseModel):
    camera: bool
    microphone: bool
