"""Frequence respiratoire deduite du rythme cardiaque, sans capteur dedie.

Le coeur accelere a l'inspiration et ralentit a l'expiration : la serie des
intervalles RR porte donc la respiration. On la ramene a une cadence fixe, on
isole la bande 0,1-0,4 Hz (6 a 24 cycles/min) et on prend la frequence
dominante.
"""

import neurokit2 as nk
import numpy as np

FE_INTERP = 4.0        # Hz, tres au-dessus de la bande d'interet
DUREE_MIN_S = 55.0     # il faut ~60 s pour resoudre 0,1 Hz


def frequence_respiratoire(rr_ms: list[float]) -> float | None:
    if len(rr_ms) < 30:
        return None

    rr = np.asarray(rr_ms, dtype=float)
    t = np.cumsum(rr) / 1000.0
    if t[-1] - t[0] < DUREE_MIN_S:
        return None

    ti = np.arange(t[0], t[-1], 1.0 / FE_INTERP)
    tachogramme = np.interp(ti, t, rr)
    tachogramme = tachogramme - tachogramme.mean()

    filtre = nk.signal_filter(
        tachogramme, sampling_rate=FE_INTERP,
        lowcut=0.1, highcut=0.4, method="butterworth", order=3,
    )
    dsp = nk.signal_psd(filtre, sampling_rate=FE_INTERP, method="welch")
    dominante = float(dsp.loc[dsp["Power"].idxmax(), "Frequency"])
    return dominante * 60.0
