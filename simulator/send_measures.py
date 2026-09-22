import time
from datetime import datetime, timezone

import httpx

URL = "http://127.0.0.1:8000/api/v1/ingest"


def message(seq: int, ibi: int, eda: float) -> dict:
    return {
        "v": 1,
        "device_id": "calme-simulateur",
        "ts": datetime.now(timezone.utc).isoformat(),
        "seq": seq,
        "ibi_ms": [ibi],
        "eda_us": [eda],
        "qualite": {"cardiaque": 0.95, "eda": 0.95},
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