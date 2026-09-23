"""Redaction de la consigne, a la demande, et retour de l'astronaute dessus.

POST /assessments/{id}/recommend est un verbe : il declenche une nouvelle
redaction (exercices_autorises + rediger), il ne relit pas une consigne deja
ecrite. C'est deliberement different de GET /sessions/{id}/assessment, qui
lui ne fait que relire une decision déjà prise.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DbSession

from app.deps import get_db
from app.models.tables import Decision
from app.schemas.session import RetourConsigne
from app.services.consigne import rediger
from app.services.exercices import exercices_autorises

router = APIRouter()

# L'id public d'une recommandation derive de celui de l'evaluation dont elle
# procede : la relation est 1-vers-1 (une seule redaction active par
# evaluation), donc une colonne dediee rien que pour ce lien serait
# redondante avec assessment_id, deja sur la ligne `decisions`.
PREFIXE_RECOMMANDATION = "reco-"


def _decision_par_assessment(db: DbSession, assessment_id: str) -> Decision:
    decision = db.query(Decision).filter(Decision.assessment_id == assessment_id).first()
    if decision is None:
        raise HTTPException(status_code=404, detail="evaluation introuvable")
    return decision


@router.post("/assessments/{assessment_id}/recommend")
def recommander(assessment_id: str, db: DbSession = Depends(get_db)):
    decision = _decision_par_assessment(db, assessment_id)

    autorises = exercices_autorises(decision.niveau)
    # rediger() ne lit que index/level de l'evaluation dans son prompt : pas
    # besoin de reconstruire l'objet Assessment complet pour l'appeler.
    evaluation = {"index": decision.indice_charge, "level": decision.niveau}
    exercice, message, source, modele = rediger(evaluation, autorises, historique=[])

    # On ecrase la redaction precedente : rejouer cette route, c'est
    # explicitement demander une nouvelle redaction pour la meme evaluation.
    decision.exercice_id = exercice["id"] if exercice else None
    decision.exercice_declenche = exercice is not None
    decision.consigne_ia = message
    decision.source = source
    db.commit()

    return {
        "id": f"{PREFIXE_RECOMMANDATION}{decision.assessment_id}",
        "assessmentId": decision.assessment_id,
        "exercise": exercice,
        "message": message,
        "source": source,
        "modelName": modele,
    }


@router.post("/recommendations/{recommendation_id}/feedback", status_code=204)
def deposer_feedback(
    recommendation_id: str, corps: RetourConsigne, db: DbSession = Depends(get_db)
):
    if not recommendation_id.startswith(PREFIXE_RECOMMANDATION):
        raise HTTPException(status_code=404, detail="recommandation introuvable")
    assessment_id = recommendation_id[len(PREFIXE_RECOMMANDATION):]

    decision = _decision_par_assessment(db, assessment_id)
    decision.feedback = corps.feedback
    db.commit()
    return None
