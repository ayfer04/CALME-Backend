import hashlib
import hmac
import os
import time
from datetime import datetime, timezone

import httpx

URL = "http://127.0.0.1:8000/api/v1/ingest"
DEVICE_ID = "calme-simulateur"

# Doit correspondre a CLE_SIMULATEUR dans
# migrations/versions/7c9eee2ae359_cles_des_appareils_autorises.py : /ingest
# rejette desormais tout appareil absent de la table `appareils`, y compris
# le simulateur.
CLE = os.environ.get("CALME_SIMULATEUR_CLE", "cle-demo-calme-simulateur")


def signer(device_id: str, seq: int, ts: str, cle: str) -> str:
    """Meme calcul que verifier_signature cote serveur : HMAC-SHA256 sur
    device_id | seq | ts."""
    return hmac.new(cle.encode(), f"{device_id}|{seq}|{ts}".encode(), hashlib.sha256).hexdigest()


def message(seq: int, ibi: int, eda: float) -> dict:
    ts = datetime.now(timezone.utc).isoformat()
    return {
        "v": 1,
        "device_id": DEVICE_ID,
        "ts": ts,
        "seq": seq,
        "ibi_ms": [ibi],
        "eda_us": [eda],
        "qualite": {"cardiaque": 0.95, "eda": 0.95},
        "sig": signer(DEVICE_ID, seq, ts, CLE),
    }


def main():
    seq = 0
    with httpx.Client() as client:
        while True:
            # FC autour de 70 bpm : ~857 ms entre battements
            ibi = 857
            eda = 4.0
            reponse = client.post(URL, json=message(seq, ibi, eda))
            print(seq, reponse.status_code, reponse.json())
            seq += 1
            time.sleep(1)


if __name__ == "__main__":
    main()