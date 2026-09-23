import neurokit2 as nk

from app.services.sudation import indicateurs_eda


def test_compte_les_reponses_dun_eda_simule():
    eda = nk.eda_simulate(duration=120, sampling_rate=10, scr_number=6, random_state=2)
    fond, reponses = indicateurs_eda(eda.tolist(), fe=10)
    assert fond is not None
    # Six reponses sur deux minutes -> trois par minute, a deux pres.
    assert 1.0 <= reponses <= 5.0


def test_renvoie_none_sur_fenetre_trop_courte():
    assert indicateurs_eda([4.0, 4.1], fe=10) == (None, None)
