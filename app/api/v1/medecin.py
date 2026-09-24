"""Le poste du medecin de bord : vue de l'equipage, historique, alertes,
tendances, energie.

Tout est calcule depuis ce que la cabine a reellement enregistre (decisions,
mesures, seances). Le principe du dossier tient : le medecin voit des
tendances et des alertes, pas des mesures seconde par seconde, et une alerte
ne transporte que qui et quand.
"""

from datetime import date, datetime, timedelta, timezone
from statistics import mean

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DbSession

from app.api.v1.cabine import _crew_member
from app.deps import get_db
from app.models.tables import Astronaute, Decision, Indicateur, Mesure
from app.models.tables import Session as SessionModel
from app.services.exercices import CATALOGUE
from app.services import notation

router = APIRouter()

# Le jour de bord : le sol courant de la mission, recale sur la date du jour.
SOL_AUJOURDHUI = 4212
# Note de bien-etre neutre (echelle sur 100, 100 = le mieux), pour les jours
# sans seance.
INDICE_NEUTRE = 50.0
NOMS_EXERCICES = {e["id"]: e["name"] for e in CATALOGUE}


def _sol(jour: date) -> int:
    return SOL_AUJOURDHUI - (datetime.now(timezone.utc).date() - jour).days


def _utc(ts: datetime) -> datetime:
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _decisions_de(db: DbSession, astronaute_id: int, depuis: datetime | None = None) -> list[Decision]:
    requete = (db.query(Decision)
               .join(SessionModel, Decision.session_id == SessionModel.id)
               .filter(SessionModel.astronaute_id == astronaute_id))
    if depuis is not None:
        requete = requete.filter(Decision.ts >= depuis)
    return requete.order_by(Decision.ts).all()


def _par_jour(decisions: list[Decision], jours: int) -> list[float]:
    """Un point par jour (le plus ancien d'abord). Un jour sans seance reprend
    la valeur de la veille : une courbe qui retombe a zero les jours sans
    mesure dirait quelque chose de faux."""
    aujourdhui = datetime.now(timezone.utc).date()
    valeurs: dict[date, list[float]] = {}
    for d in decisions:
        valeurs.setdefault(_utc(d.ts).date(), []).append(d.indice_charge)
    points, precedent = [], INDICE_NEUTRE
    for i in range(jours - 1, -1, -1):
        jour = aujourdhui - timedelta(days=i)
        if jour in valeurs:
            precedent = round(mean(valeurs[jour]), 1)
        points.append(precedent)
    return points


@router.get("/crew/overview")
def vue_equipage(db: DbSession = Depends(get_db)):
    depuis = datetime.now(timezone.utc) - timedelta(days=7)
    resultat = []
    for astronaute in db.query(Astronaute).order_by(Astronaute.id).all():
        decisions = _decisions_de(db, astronaute.id, depuis)
        spark = _par_jour(decisions, 7)
        moyenne = round(mean(d.indice_charge for d in decisions), 1) if decisions else INDICE_NEUTRE
        derniere = (db.query(SessionModel).filter(SessionModel.astronaute_id == astronaute.id)
                    .order_by(SessionModel.debut.desc()).first())
        resultat.append({
            "member": _crew_member(astronaute),
            "meanIndex": moyenne,
            "level": notation.niveau(moyenne, 1.0),
            "delta": round(spark[-1] - spark[0], 1),
            "lastSessionAt": derniere.debut.isoformat() if derniere else None,
            "spark": spark,
        })
    return resultat


@router.get("/crew/{crew_id}/history")
def historique(crew_id: str, db: DbSession = Depends(get_db)):
    try:
        astronaute = db.get(Astronaute, int(crew_id))
    except ValueError:
        astronaute = None
    if astronaute is None:
        raise HTTPException(status_code=404, detail="membre d'equipage introuvable")

    decisions = _decisions_de(db, astronaute.id, datetime.now(timezone.utc) - timedelta(days=30))
    points = [{"sol": _sol(datetime.now(timezone.utc).date()) - 29 + i, "index": v}
              for i, v in enumerate(_par_jour(decisions, 30))]
    seances = [{
        "id": str(d.session_id),
        "at": _utc(d.ts).isoformat(),
        "indexBefore": d.indice_charge,
        "indexAfter": d.indice_apres,
        "exerciseName": NOMS_EXERCICES.get(d.exercice_id or "", "Aucun exercice"),
        "feedback": d.feedback,
    } for d in reversed(decisions)][:20]
    return {
        "member": _crew_member(astronaute),
        "points": points,
        "sessions": seances,
        "accessGrant": {
            "reason": "explicit-consent",
            "alertId": None,
            "acknowledgedBy": None,
            "grantedAt": datetime.now(timezone.utc).isoformat(),
        },
    }


def _alerte(d: Decision, astronaute: Astronaute) -> dict:
    return {
        "id": f"alerte-{d.id}",
        "crewId": str(astronaute.id),
        "crewName": astronaute.nom,
        "raisedAt": _utc(d.ts).isoformat(),
        "kind": "threshold-crossed",
        "acknowledgedAt": d.alerte_acquittee_le.isoformat() if d.alerte_acquittee_le else None,
        "acknowledgedBy": d.alerte_acquittee_par,
        "note": None,
    }


@router.get("/alerts")
def alertes(db: DbSession = Depends(get_db)):
    """Une alerte par seance passee au rouge : qui et quand, jamais la mesure."""
    lignes = (db.query(Decision, Astronaute)
              .join(SessionModel, Decision.session_id == SessionModel.id)
              .join(Astronaute, SessionModel.astronaute_id == Astronaute.id)
              .filter(Decision.niveau == "red")
              .order_by(Decision.ts.desc()).limit(50).all())
    return [_alerte(d, a) for d, a in lignes]


@router.post("/alerts/{alert_id}/acknowledge")
def acquitter(alert_id: str, db: DbSession = Depends(get_db)):
    try:
        decision = db.get(Decision, int(alert_id.removeprefix("alerte-")))
    except ValueError:
        decision = None
    if decision is None or decision.niveau != "red":
        raise HTTPException(status_code=404, detail="alerte introuvable")
    if decision.alerte_acquittee_le is None:
        decision.alerte_acquittee_le = datetime.now(timezone.utc)
        decision.alerte_acquittee_par = "Médecin de bord"
        db.commit()
    astronaute = db.get(Astronaute, db.get(SessionModel, decision.session_id).astronaute_id)
    return _alerte(decision, astronaute)


@router.get("/trends")
def tendances(db: DbSession = Depends(get_db)):
    """Agrege sur tout l'equipage, sans nom : ce que le medecin peut voir
    sans justifier un acces individuel."""
    depuis = datetime.now(timezone.utc) - timedelta(days=30)
    decisions = db.query(Decision).filter(Decision.ts >= depuis).order_by(Decision.ts).all()
    courbe = _par_jour(decisions, 30)
    aujourdhui = datetime.now(timezone.utc).date()
    jours_actifs = {_utc(d.ts).date() for d in decisions}

    avant, apres = [], []
    for session_id in {d.session_id for d in decisions}:
        releves = (db.query(Indicateur).filter(Indicateur.session_id == session_id,
                                               Indicateur.frequence_respiratoire.isnot(None))
                   .order_by(Indicateur.ts).all())
        if len(releves) >= 2:
            avant.append(releves[0].frequence_respiratoire)
            apres.append(releves[-1].frequence_respiratoire)

    return {
        "meanIndex": [{"sol": _sol(aujourdhui) - 29 + i, "value": v} for i, v in enumerate(courbe)],
        "sessionsPerDay": round(len(decisions) / max(1, len(jours_actifs)), 1),
        # 0 quand aucune frequence respiratoire n'a pu etre mesuree (pas de
        # capteur cardiaque) : le front l'affiche comme une absence.
        "breathingRateBefore": round(mean(avant), 1) if avant else 0,
        "breathingRateAfter": round(mean(apres), 1) if apres else 0,
        "amberShare": round(sum(d.niveau in ("amber", "red") for d in decisions)
                            / len(decisions), 2) if decisions else 0,
    }


# --- Energie ----------------------------------------------------------------
#
# Le budget du dossier (partie Fabrication), par mode : veille, mesure, seance,
# degrade. Sans INA219 monte, la puissance affichee est celle du budget du
# mode courant - une estimation, que le front presente comme telle.

BUDGET = [
    ("Capteurs et Arduino", (1.2, 2.4, 2.4, 2.0)),
    ("Caméra", (0.0, 1.8, 1.8, 0.0)),
    ("Serveur", (8.0, 22.0, 28.0, 14.0)),
    ("Écran", (0.0, 12.0, 12.0, 0.0)),
    ("Éclairage", (2.0, 4.0, 18.0, 4.0)),
    ("Son", (0.0, 0.0, 10.0, 6.0)),
]
MODES = ("standby", "measuring", "session", "degraded")
BUDGET_NOMINAL_W = 72.0
# Consigne du reseau du vaisseau : en memoire, elle revient a 100 % au
# redemarrage du serveur, comme un disjoncteur qu'on rearme.
_consigne = {"percent": 100}


class Consigne(BaseModel):
    percent: int = Field(ge=10, le=100)


def _etat_energie(db: DbSession) -> dict:
    ouverte = db.query(SessionModel).filter(SessionModel.fin.is_(None)).first()
    mode = "degraded" if _consigne["percent"] < 50 else ("session" if ouverte else "standby")
    total = {m: round(sum(l[1][i] for l in BUDGET), 1) for i, m in enumerate(MODES)}
    debut_jour = datetime.combine(datetime.now(timezone.utc).date(), datetime.min.time(), timezone.utc)
    seances = db.query(SessionModel).filter(SessionModel.debut >= debut_jour).count()
    # Une seance type : une minute de mesure et cinq d'exercice ; le reste en veille.
    cout = total["standby"] * 24 + seances * (total["measuring"] / 60 + total["session"] * 5 / 60)
    economie = seances * (total["session"] - total["degraded"]) * 5 / 60
    return {
        "mode": mode,
        "watts": total[mode],
        "setpointPercent": _consigne["percent"],
        "budgetWatts": round(BUDGET_NOMINAL_W * _consigne["percent"] / 100, 1),
        "lines": [{"label": nom, "byMode": dict(zip(MODES, valeurs))} for nom, valeurs in BUDGET],
        "dailyCostWh": round(cout, 1),
        "dailySavingWh": round(economie, 1),
    }


@router.get("/power")
def energie(db: DbSession = Depends(get_db)):
    return _etat_energie(db)


@router.post("/power/setpoint")
def consigne_energie(corps: Consigne, db: DbSession = Depends(get_db)):
    _consigne["percent"] = corps.percent
    return _etat_energie(db)


def capteurs_recents(db: DbSession, secondes: int = 30) -> dict[str, bool]:
    """Quels capteurs ont envoye quelque chose recemment : pour l'etat de sante."""
    limite = datetime.now(timezone.utc) - timedelta(seconds=secondes)
    capteurs = {c for (c,) in db.query(Mesure.capteur).filter(Mesure.ts >= limite).distinct()}
    return {"hr": "ppg" in capteurs, "eda": "sudation" in capteurs,
            "face": "visage" in capteurs, "voice": "voix" in capteurs}
