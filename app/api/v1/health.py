import httpx
from fastapi import APIRouter
from sqlalchemy import text

from app.db import SessionLocal, engine
from app.services.consigne import HOTE_OLLAMA, MODELE

router = APIRouter()


def _modele_pret() -> tuple[bool, str]:
    """Ollama repond-il, et le modele de la cabine y est-il installe ?"""
    try:
        reponse = httpx.get(f"{HOTE_OLLAMA}/api/tags", timeout=2.0)
        noms = {m.get("name") for m in reponse.json().get("models", [])}
        if MODELE in noms:
            return True, "Modèle chargé et joignable"
        return False, f"Ollama joignable, mais {MODELE} n'est pas installé"
    except Exception:
        return False, "Ollama injoignable : les consignes utilisent les règles"


@router.get("/health")
def health():
    try:
        with engine.connect() as connexion:
            connexion.execute(text("SELECT 1"))
        base = "ok"
    except Exception:
        base = "indisponible"

    modele_ok, detail_modele = _modele_pret()

    capteurs = {"hr": False, "eda": False, "face": False, "voice": False}
    if base == "ok":
        from app.api.v1.medecin import capteurs_recents

        db = SessionLocal()
        try:
            capteurs = capteurs_recents(db)
        finally:
            db.close()

    return {
        # Les deux champs historiques, lus par les scripts et les tests.
        "api": "ok",
        "base": base,
        # La forme attendue par le poste du medecin (HealthState cote front).
        "database": {"ok": base == "ok",
                     "detail": "PostgreSQL répond" if base == "ok" else "Base injoignable"},
        "model": {"ok": modele_ok, "detail": detail_modele, "name": MODELE if modele_ok else None},
        "sensors": {"ok": any(capteurs.values()), "online": sum(capteurs.values()),
                    "total": len(capteurs)},
        # Le tampon hors ligne vit dans la passerelle, pas ici : rien en attente
        # cote serveur.
        "buffer": {"pending": 0, "lastReplayAt": None},
    }
