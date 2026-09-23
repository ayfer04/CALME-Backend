"""Du PPG brut aux indicateurs cardiaques.

La detection de battements se fait ici et non sur le microcontroleur : le
detecteur a seuil des bibliotheques Arduino rate des battements et en invente
sous artefact de mouvement, et la variabilite est notre indicateur le mieux
pondere. A 700 octets par seconde, transmettre le brut ne coute rien.
"""

import neurokit2 as nk
import numpy as np

IBI_MIN_MS = 273.0    # 220 bpm
IBI_MAX_MS = 2000.0   #  30 bpm


def rr_depuis_ppg(ppg: list[int], fe: int = 100) -> list[float]:
    if len(ppg) < fe * 5:
        return []
    signal = np.asarray(ppg, dtype=float)
    _, info = nk.ppg_process(signal, sampling_rate=fe)
    pics = np.asarray(info["PPG_Peaks"], dtype=float)
    if pics.size < 3:
        return []
    return (np.diff(pics) * (1000.0 / fe)).tolist()


def nettoyer_rr(rr: list[float]) -> list[float]:
    """Bornes physiologiques, puis rejet des sauts de plus de 20 %.

    Un intervalle qui double d'un battement a l'autre n'est pas une arythmie,
    c'est un battement rate par le detecteur.
    """
    valeurs = np.asarray([v for v in rr if IBI_MIN_MS <= v <= IBI_MAX_MS], dtype=float)
    if valeurs.size < 2:
        return valeurs.tolist()
    ecarts = np.abs(np.diff(valeurs))
    garde = ecarts < 0.2 * valeurs[:-1]
    return np.concatenate(([valeurs[0]], valeurs[1:][garde])).tolist()


def fc_moyenne(rr: list[float]) -> float | None:
    if not rr:
        return None
    return float(60000.0 / np.mean(rr))


def rmssd(rr: list[float]) -> float | None:
    if len(rr) < 2:
        return None
    return float(np.sqrt(np.mean(np.diff(np.asarray(rr, dtype=float)) ** 2)))
