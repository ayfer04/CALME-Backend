import math

from app.services.respiration import frequence_respiratoire


def serie_rr_modulee(cycles_min: float, n: int = 90,
                     rr_moyen: float = 857.0, amplitude: float = 40.0) -> list[float]:
    """Une serie d'intervalles RR modulee par la respiration.

    C'est l'arythmie sinusale respiratoire : le coeur accelere a l'inspiration
    et ralentit a l'expiration. C'est ce battement-la qu'on cherche a retrouver.
    """
    rr, t = [], 0.0
    f = cycles_min / 60.0
    for _ in range(n):
        valeur = rr_moyen + amplitude * math.sin(2 * math.pi * f * t)
        rr.append(valeur)
        t += valeur / 1000.0
    return rr


def test_retrouve_douze_cycles_par_minute():
    assert abs(frequence_respiratoire(serie_rr_modulee(12.0)) - 12.0) < 1.5


def test_retrouve_la_coherence_cardiaque_a_six():
    # Six cycles/minute est la cible des exercices : c'est la valeur qui doit
    # sortir a la fin d'une seance reussie.
    assert abs(frequence_respiratoire(serie_rr_modulee(6.0, n=140)) - 6.0) < 1.5


def test_refuse_une_fenetre_trop_courte():
    assert frequence_respiratoire(serie_rr_modulee(12.0, n=20)) is None
