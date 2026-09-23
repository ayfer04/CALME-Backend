import neurokit2 as nk

from app.services.cardiaque import fc_moyenne, nettoyer_rr, rmssd, rr_depuis_ppg


def test_retrouve_la_frequence_dun_ppg_simule():
    ppg = nk.ppg_simulate(duration=30, sampling_rate=100, heart_rate=70, random_state=1)
    rr = nettoyer_rr(rr_depuis_ppg([int(v * 10000) for v in ppg], fe=100))
    assert 65 <= fc_moyenne(rr) <= 75


def test_rmssd_dune_serie_connue():
    # Ecarts successifs : +10, -10, +10 -> RMSSD = 10
    rr = [800.0, 810.0, 800.0, 810.0]
    assert abs(rmssd(rr) - 10.0) < 0.01


def test_nettoyer_ecarte_les_sauts_et_les_hors_bornes():
    rr = [800.0, 810.0, 2500.0, 805.0, 100.0, 795.0]
    propre = nettoyer_rr(rr)
    assert 2500.0 not in propre
    assert 100.0 not in propre


def test_renvoie_none_sur_serie_trop_courte():
    assert fc_moyenne([]) is None
    assert rmssd([800.0]) is None
