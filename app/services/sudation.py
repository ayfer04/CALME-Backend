"""Activite electrodermale : niveau de fond et reponses rapides.

Le niveau de fond derive lentement, les reponses phasiques reagissent en
quelques secondes. Ce sont deux indicateurs distincts et on les pondere
differemment : les reponses rapides sont notre meilleur signal d'alerte.
"""

import neurokit2 as nk
import numpy as np

DUREE_MIN_S = 10.0


def indicateurs_eda(eda: list[float], fe: int = 10) -> tuple[float | None, float | None]:
    duree = len(eda) / fe
    if duree < DUREE_MIN_S:
        return None, None

    signal = np.asarray(eda, dtype=float)
    try:
        # Attention : le parametre `method` d'eda_process pilote le NETTOYAGE et
        # n'accepte que 'neurokit' ou 'biosppy'. La decomposition tonique /
        # phasique se choisit avec `method_phasic`. Verifie sur NeuroKit2 0.2.13.
        signaux, info = nk.eda_process(signal, sampling_rate=fe, method_phasic="highpass")
    except Exception:
        # Un signal plat ou sature fait echouer la decomposition. Ce n'est pas
        # une erreur du systeme, c'est un capteur qui ne dit rien : on le dit.
        return None, None

    fond = float(np.mean(signaux["EDA_Tonic"]))
    pics = info.get("SCR_Peaks", [])
    reponses = float(len(pics) * 60.0 / duree)
    return fond, reponses
