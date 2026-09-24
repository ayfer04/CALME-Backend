#!/usr/bin/env python3
"""Passerelle de la cabine : port serie de l'Arduino -> POST /api/v1/ingest.

Tourne sur le Raspberry Pi. L'Arduino Mega n'a ni reseau ni memoire (8 Ko de
RAM) : il ecrit une ligne `D,<ir>,<gsr>,<courant_mA>` par echantillon, a
100 Hz (voir firmware/calme_capteurs/calme_capteurs.ino). La passerelle
regroupe une seconde, la signe exactement comme `verifier_signature` dans
app/api/v1/ingest.py, et la poste. Si la tour ne repond pas, les messages
attendent dans un tampon de dix minutes et repartent dans l'ordre au retour du
reseau - c'est le point de demonstration n°3 du dossier.

Aucune dependance au reste du Backend : ce fichier est copie seul sur le Pi.
pyserial n'est importe que dans `lire_en_continu`, pour que les fonctions de
construction du message restent testables sans materiel (tests/test_passerelle.py).
"""

import collections
import hashlib
import hmac
import os
import threading
import time
from datetime import datetime, timezone

import httpx

PORT = os.environ.get("CALME_PORT_SERIE", "/dev/ttyACM0")
URL = os.environ.get("CALME_URL_INGEST", "http://10.61.8.36:8001/api/v1/ingest")
DEVICE_ID = os.environ.get("CALME_DEVICE_ID", "cabine-01")
# Cle de demonstration declaree par la migration 7c9eee2ae359 pour cabine-01.
CLE = os.environ.get("CALME_CLE", "cle-demo-cabine-01")
CALIB_GSR = float(os.environ.get("CALME_CALIB_GSR", "512"))

FE = 100                 # frequence d'echantillonnage du firmware (Hz)
PAQUET_EDA = 10          # 100 Hz -> 10 Hz pour la sudation, comme GABARIT_CAPTEURS
SEUIL_DOIGT = 50_000     # en dessous, aucun doigt sur le MAX30102
TAMPON_MAX = 600         # 600 messages d'une seconde = dix minutes

# Bornes de la sudation brute exploitable : a 0 ou a la valeur d'etalonnage,
# les electrodes ne touchent personne ou le capteur sature.
GSR_MIN_EXPLOITABLE = 5


def signer(device_id: str, seq: int, ts: str, cle: str) -> str:
    """Meme calcul que verifier_signature cote serveur : HMAC-SHA256 sur
    device_id | seq | ts."""
    return hmac.new(cle.encode(), f"{device_id}|{seq}|{ts}".encode(), hashlib.sha256).hexdigest()


def gsr_vers_microsiemens(brut: float, calibration: float = CALIB_GSR) -> float:
    """Formule du fabricant (Seeed Grove GSR) avec le point d'etalonnage mesure
    a vide. Au-dela de ce point la resistance n'a plus de sens : on renvoie 0
    plutot qu'une conductance negative."""
    if brut >= calibration - 1:
        return 0.0
    resistance = ((1024 + 2 * brut) * 10_000) / (calibration - brut)
    return 1e6 / resistance


def lire_ligne(ligne: str) -> tuple[int, int, float] | None:
    """`D,ir,gsr,mA` -> (ir, gsr, mA). Toute autre ligne - message d'etat `#`,
    ligne tronquee a l'ouverture du port - renvoie None et est ignoree."""
    if not ligne.startswith("D,"):
        return None
    morceaux = ligne.split(",")
    if len(morceaux) != 4:
        return None
    try:
        return int(morceaux[1]), int(morceaux[2]), float(morceaux[3])
    except ValueError:
        return None


def construire(seq: int, ppg: list[int], gsr: list[int], ma: float | None,
               device_id: str = DEVICE_ID, cle: str = CLE,
               calibration: float = CALIB_GSR) -> dict:
    # isoformat() et rien d'autre : le serveur recalcule la signature sur
    # message.ts.isoformat(). Un suffixe "Z" a la place de "+00:00" changerait
    # la chaine signee, et toutes les signatures seraient refusees.
    ts = datetime.now(timezone.utc).isoformat()
    eda = []
    for i in range(0, len(gsr), PAQUET_EDA):
        paquet = gsr[i:i + PAQUET_EDA]
        eda.append(round(gsr_vers_microsiemens(sum(paquet) / len(paquet), calibration), 3))
    doigt = bool(ppg) and sum(ppg) / len(ppg) > SEUIL_DOIGT
    gsr_ok = bool(gsr) and all(GSR_MIN_EXPLOITABLE < g < calibration - 1 for g in gsr)
    return {
        "v": 1,
        "device_id": device_id,
        "ts": ts,
        "seq": seq,
        # Sans doigt (ou capteur absent, IR a 0), le signal n'est que du bruit
        # ou des zeros : on ne l'envoie pas, plutot que de laisser le serveur
        # chercher des battements dedans.
        "ppg_raw": ppg if doigt else [],
        "eda_us": eda,
        # Le firmware ecrit -1 tant que l'INA219 n'a pas repondu.
        "ma": ma if ma is not None and ma >= 0 else None,
        "qualite": {"cardiaque": 0.9 if doigt else 0.0, "eda": 0.9 if gsr_ok else 0.1},
        "sig": signer(device_id, seq, ts, cle),
    }


def envoyer_en_continu(tampon: collections.deque, url: str = URL) -> None:
    """Fil d'envoi separe : un POST bloque par une coupure reseau ne doit
    jamais retarder la lecture serie, sinon le tampon du port (quelques Ko,
    deux secondes de mesures) deborde et des echantillons se perdent."""
    with httpx.Client(timeout=3.0) as client:
        hors_ligne = False
        while True:
            if not tampon:
                time.sleep(0.05)
                continue
            message = tampon[0]
            try:
                reponse = client.post(url, json=message)
            except httpx.HTTPError as erreur:
                if not hors_ligne:
                    print(f"serveur injoignable ({erreur}), mise en tampon", flush=True)
                    hors_ligne = True
                time.sleep(1)
                continue
            if hors_ligne:
                print(f"serveur revenu, {len(tampon)} messages a rejouer", flush=True)
                hors_ligne = False
            if reponse.status_code >= 500:
                # Serveur en difficulte (migration, redeploiement) : on
                # reessaie le meme message plutot que de le perdre.
                time.sleep(1)
                continue
            if reponse.status_code != 202:
                # 401 (appareil ou cle) ou 422 (format) : reessayer ne
                # changera rien, on journalise et on passe au suivant.
                print(f"message {message['seq']} refuse : {reponse.status_code} "
                      f"{reponse.text[:200]}", flush=True)
            tampon.popleft()


def lire_en_continu(tampon: collections.deque, port: str = PORT) -> None:
    import serial  # paresseux : voir la docstring du module

    seq = 0
    while True:
        ppg: list[int] = []
        gsr: list[int] = []
        ma: float | None = None
        try:
            with serial.Serial(port, 115200, timeout=1) as liaison:
                print(f"port serie ouvert : {port}", flush=True)
                # L'ouverture du port redemarre le Mega : on laisse passer son
                # amorcage et les lignes a moitie ecrites qui le precedent.
                time.sleep(2)
                liaison.reset_input_buffer()
                while True:
                    ligne = liaison.readline().decode("ascii", "ignore").strip()
                    if ligne.startswith("#"):
                        print(f"arduino : {ligne}", flush=True)
                        continue
                    echantillon = lire_ligne(ligne)
                    if echantillon is None:
                        continue
                    ir, g, ma = echantillon
                    ppg.append(ir)
                    gsr.append(g)
                    if len(ppg) >= FE:
                        tampon.append(construire(seq, ppg, gsr, ma))
                        seq += 1
                        ppg, gsr = [], []
        except serial.SerialException as erreur:
            print(f"port serie indisponible ({erreur}), nouvel essai dans 2 s", flush=True)
            time.sleep(2)


def main() -> None:
    tampon: collections.deque = collections.deque(maxlen=TAMPON_MAX)
    print(f"passerelle {DEVICE_ID} : {PORT} -> {URL}", flush=True)
    threading.Thread(target=envoyer_en_continu, args=(tampon,), daemon=True).start()
    lire_en_continu(tampon)


if __name__ == "__main__":
    main()
