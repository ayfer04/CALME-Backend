# Chaîne C.A.L.M.E. — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Faire tourner la chaîne complète — capteurs → Arduino → passerelle Pi → serveur → indicateurs → indice → consigne → écran de la cabine — avant ce soir.

**Architecture:** L'Arduino Mega ADK n'a pas de réseau : il émet des lignes CSV en série USB vers le Raspberry Pi, qui sert de passerelle (tampon 10 min, signature HMAC) et poste sur le FastAPI. Tout le traitement de signal vit sur le serveur i5 avec NeuroKit2 ; du code déterministe fixe l'indice et le niveau, et Ollama ne fait que choisir un exercice dans une liste imposée et rédiger la consigne. Le Pi porte aussi Chromium en kiosque, la webcam et MediaPipe — l'image ne quitte jamais le Pi.

**Tech Stack:** Arduino (C++), Python 3.12 / FastAPI / SQLAlchemy / Alembic / NeuroKit2 / opensmile / Ollama, PostgreSQL, React 19 / TypeScript / Vite / Tailwind 4, MediaPipe Tasks Vision, Coolify.

**Spec:** `docs/superpowers/specs/2026-09-23-stack-calme-design.md`

## Global Constraints

- **Langue du code** : identifiants, commentaires et messages de commit en français, comme le dépôt existant.
- **Le contrat du front est la référence.** Les noms d'événements WebSocket et les champs JSON exposés doivent correspondre **au caractère près** à `Frontend/src/api/types.ts`. Le front est déjà écrit contre eux.
- **Bornes cardiaques** : 273 ≤ IBI ≤ 2000 ms (30–220 bpm), déjà validées par Pydantic dans `app/schemas/ingest.py`.
- **Seuils de l'indice** : vert < 40, orange 40–70, rouge ≥ 70. Formule `indice = clip(30 + 20 · Σ(wᵢ·zᵢ), 0, 100)`.
- **Poids** : `hrv_rmssd` 0,30 (inversé) · `eda_reponses` 0,25 · `voix` 0,15 · `eda_fond` 0,10 · `fc_moyenne` 0,10 · `visage` 0,10.
- **Pas de PyTorch.** Dépendances Python ajoutées : `neurokit2`, `opensmile`, `ollama`. Rien d'autre.
- **Aucun média brut persisté.** L'audio est traité en mémoire (`io.BytesIO`), jamais écrit sur disque. Aucune image ne transite.
- **Fréquences** : PPG 100 Hz, EDA 10 Hz (échantillonné 50, moyenné par 5), courant 1 Hz.
- **Boucle de développement** : `uvicorn --reload` en direct. Coolify est la cible de déploiement du soir, pas la boucle d'itération.

## Répartition par pôle — à lancer en parallèle

| Pôle | Tâches | Bloque |
|---|---|---|
| **Embarqué** | 0 → 14 → 15 | La tâche 0 bloque tout le pôle |
| **Serveur** | 1 → 2 → 3 → 4 → 5 → 6 → 7 | La tâche 1 débloque le pôle Client |
| **IA** | 8 → 9, puis 10 | Indépendant jusqu'à la tâche 7 |
| **Client** | 11 ∥ 12 → 13 | 13 attend la tâche 1 |
| **Serveur (dette)** | 16, puis 17 le soir | 17 après la tâche 13 |
| **Rendu** | 18 | Peut se faire en parallèle toute la journée |

**Règle d'ordre :** faire la tâche 1 (WebSocket) avant la 3 (indicateurs). Un WebSocket qui pousse des valeurs fausses est démontrable ; des indicateurs justes sans WebSocket ne se voient pas.

## File Structure

**Backend — à créer**

| Fichier | Responsabilité |
|---|---|
| `app/ws/hub.py` | Registre des connexions WebSocket par session, diffusion |
| `app/api/v1/stream.py` | Route `WS /sessions/{id}/stream` |
| `app/services/cardiaque.py` | PPG → RR → RMSSD, FC moyenne |
| `app/services/sudation.py` | EDA → niveau de fond, réponses/min |
| `app/services/respiration.py` | RR → fréquence respiratoire (EDR) |
| `app/services/indice.py` | Écarts z, indice de charge, confiance, niveau |
| `app/services/exercices.py` | Catalogue des 8 exercices, filtrage par palier |
| `app/services/consigne.py` | Ollama sous JSON Schema, repli déterministe |
| `app/services/voix.py` | eGeMAPS → indice vocal |
| `app/api/v1/assess.py` | `POST /sessions/{id}/assess`, `POST /media/face`, `POST /media/audio` |
| `tests/` | Tests unitaires des fonctions pures |

**Backend — à modifier**

| Fichier | Changement |
|---|---|
| `app/schemas/ingest.py` | Champs `ppg_raw` et `ma`, optionnels |
| `app/api/v1/ingest.py` | Stocker `ppg_raw`, déclencher le calcul, diffuser sur le WS |
| `app/main.py` | Monter les routeurs `stream` et `assess` |
| `requirements.txt` | Réduire aux dépendances directes, ajouter les trois nouvelles |

**Embarqué — à créer**

| Fichier | Responsabilité |
|---|---|
| `firmware/scan_i2c/scan_i2c.ino` | Scanner I²C de diagnostic (tâche 0) |
| `firmware/calme/calme.ino` | Acquisition et émission série |
| `passerelle/passerelle.py` | Série → agrégation 1 s → HMAC → POST, tampon 10 min |
| `passerelle/calme-passerelle.service` | Unité systemd |

**Frontend — à modifier**

| Fichier | Changement |
|---|---|
| `src/styles/index.css` | Variables de la grille cabine 800×480 |
| `src/api/transport.ts` | Méthodes `sendFaceIndex` et `sendVoiceSample` |
| `src/api/live.ts` | Leur implémentation réelle |
| `src/api/mock/transport.ts` | Leur implémentation simulée |
| `src/features/cabin/hooks/use-face-index.ts` | **Créer** — MediaPipe, webcam, agrégation |
| `.env` | `VITE_USE_MOCK=false` |

---

# PÔLE EMBARQUÉ

### Tâche 0 : Scanner I²C — bloquante, à faire en premier

**Files:**
- Create: `firmware/scan_i2c/scan_i2c.ino`

**Interfaces:**
- Consomme : rien.
- Produit : la certitude que 0x57 (MAX30102) et 0x40 (INA219) répondent. Sans elle, les tâches 14 et 15 n'ont pas d'objet.

- [ ] **Étape 1 : Écrire le sketch**

```cpp
#include <Wire.h>

void setup() {
  Serial.begin(115200);
  while (!Serial) {}
  Wire.begin();
  Serial.println(F("--- scan I2C ---"));
}

void loop() {
  byte trouves = 0;
  for (byte adresse = 1; adresse < 127; adresse++) {
    Wire.beginTransmission(adresse);
    if (Wire.endTransmission() == 0) {
      Serial.print(F("trouve 0x"));
      if (adresse < 16) Serial.print('0');
      Serial.println(adresse, HEX);
      trouves++;
    }
  }
  if (trouves == 0) Serial.println(F("aucun peripherique"));
  Serial.println(F("---"));
  delay(3000);
}
```

- [ ] **Étape 2 : Câbler et téléverser**

MAX30102 : `VIN`→5 V, `GND`→GND, `SDA`→pin 20, `SCL`→pin 21.
INA219 : mêmes broches I²C.

- [ ] **Étape 3 : Lire le moniteur série à 115200**

Attendu : `trouve 0x40` **et** `trouve 0x57`.

- [ ] **Étape 4 : Si 0x57 manque — adapter les niveaux**

C'est le problème des rappels I²C tirés sur le 1,8 V interne du capteur : le Mega, en logique 5 V, ne voit jamais un état haut.

Correctif à essayer **en premier car réversible** : insérer un adaptateur de niveau bidirectionnel (type BSS138) entre le Mega et le capteur — côté haute tension sur le Mega, côté basse tension sur le capteur.

Relancer l'étape 3. Ne pas dessouder les rappels de la carte tant que l'adaptateur n'a pas été essayé.

- [ ] **Étape 5 : Commit**

```bash
git add firmware/scan_i2c/scan_i2c.ino
git commit -m "embarque: scanner I2C de diagnostic"
```

---

### Tâche 14 : Sketch d'acquisition Arduino

**Files:**
- Create: `firmware/calme/calme.ino`

**Interfaces:**
- Consomme : le câblage validé en tâche 0.
- Produit : un flux série 115200 de quatre types de lignes, consommé par la tâche 15.

```
P,<ir>              PPG brut canal IR, 100 Hz
E,<raw>             GSR moyenné, 10 Hz
T,<millis>,<n_ppg>  ancre temporelle, 1 Hz — n_ppg = nb de lignes P de la seconde
I,<ma>              courant INA219, 1 Hz
```

- [ ] **Étape 1 : Installer les bibliothèques**

Dans l'IDE Arduino, gestionnaire de bibliothèques : `SparkFun MAX3010x Pulse and Proximity Sensor Library` et `Adafruit INA219`.

- [ ] **Étape 2 : Écrire le sketch**

```cpp
#include <Wire.h>
#include <MAX30105.h>
#include <Adafruit_INA219.h>

MAX30105 ppg;
Adafruit_INA219 ina;

const uint8_t BROCHE_GSR = A0;

unsigned long prochain_ppg = 0;   // 100 Hz -> 10 ms
unsigned long prochain_eda = 0;   //  10 Hz -> 100 ms
unsigned long prochaine_seconde = 0;

uint16_t compteur_ppg = 0;
uint32_t somme_gsr = 0;
uint8_t  n_gsr = 0;

void setup() {
  Serial.begin(115200);
  Wire.begin();

  if (!ppg.begin(Wire, I2C_SPEED_FAST)) {
    Serial.println(F("X,max30102 absent"));
    while (1) { delay(1000); }
  }
  // 100 Hz, LED IR seule : on ne fait pas de SpO2, on fait de la variabilite.
  ppg.setup(0x1F, 4, 2, 100, 411, 4096);

  if (!ina.begin()) Serial.println(F("X,ina219 absent"));

  unsigned long maintenant = millis();
  prochain_ppg = prochain_eda = prochaine_seconde = maintenant;
}

void loop() {
  unsigned long maintenant = millis();

  if ((long)(maintenant - prochain_ppg) >= 0) {
    prochain_ppg += 10;
    Serial.print(F("P,"));
    Serial.println(ppg.getIR());
    compteur_ppg++;
  }

  // On echantillonne le GSR a 50 Hz et on n'emet que la moyenne par 5.
  // Moins de bruit et cinq fois moins de debit, pour un signal dont les
  // reponses phasiques montent en une a trois secondes.
  static unsigned long prochain_brut = 0;
  if ((long)(maintenant - prochain_brut) >= 0) {
    prochain_brut += 20;
    somme_gsr += analogRead(BROCHE_GSR);
    n_gsr++;
  }
  if ((long)(maintenant - prochain_eda) >= 0 && n_gsr > 0) {
    prochain_eda += 100;
    Serial.print(F("E,"));
    Serial.println(somme_gsr / n_gsr);
    somme_gsr = 0;
    n_gsr = 0;
  }

  if ((long)(maintenant - prochaine_seconde) >= 0) {
    prochaine_seconde += 1000;
    Serial.print(F("I,"));
    Serial.println(ina.getCurrent_mA(), 1);
    Serial.print(F("T,"));
    Serial.print(maintenant);
    Serial.print(',');
    Serial.println(compteur_ppg);
    compteur_ppg = 0;
  }
}
```

- [ ] **Étape 3 : Vérifier le flux**

Moniteur série à 115200, doigt posé sur le capteur. Attendu :
- des lignes `P,` avec des valeurs IR **> 50000** (en dessous, aucun doigt détecté) et qui **ondulent** au rythme du pouls ;
- une ligne `T,<millis>,100` par seconde — si `n_ppg` s'écarte de 100 de plus de 5 %, la boucle est trop lente, réduire le débit du GSR.

- [ ] **Étape 4 : Commit**

```bash
git add firmware/calme/calme.ino
git commit -m "embarque: acquisition PPG, GSR et courant en serie"
```

---

### Tâche 15 : Passerelle série → HTTP sur le Pi

**Files:**
- Create: `passerelle/passerelle.py`
- Create: `passerelle/calme-passerelle.service`

**Interfaces:**
- Consomme : le flux série de la tâche 14.
- Produit : un `POST /api/v1/ingest` par seconde, conforme au schéma étendu de la tâche 2.

- [ ] **Étape 1 : Écrire la passerelle**

```python
"""Passerelle serie -> HTTP de la cabine C.A.L.M.E.

L'Arduino Mega ADK n'a pas de reseau et n'a que 8 Ko de SRAM : il ne peut ni
poster, ni tamponner. Ce service fait les deux a sa place. Le tampon vit ici,
en Python, ou dix minutes de mesures ne coutent rien.
"""

import hashlib
import hmac
import os
import time
from collections import deque
from datetime import datetime, timezone

import httpx
import serial

PORT = os.environ.get("PORT_SERIE", "/dev/ttyACM0")
URL = os.environ.get("URL_INGEST", "http://192.168.1.10:8000/api/v1/ingest")
DEVICE_ID = os.environ.get("DEVICE_ID", "cabine-01")
CLE = os.environ["CLE_SIGNATURE"].encode()

TAMPON = deque(maxlen=600)   # dix minutes a un message par seconde


def signer(charge: dict) -> str:
    brut = f"{charge['device_id']}|{charge['seq']}|{charge['ts']}".encode()
    return hmac.new(CLE, brut, hashlib.sha256).hexdigest()


def construire(seq: int, ppg: list[int], eda: list[float],
               ma: float | None, n_attendu: int) -> dict:
    # La qualite n'est pas decorative : elle pilote la confiance affichee a
    # l'ecran. Un echantillon manquant ou hors bornes la fait descendre.
    q_card = min(1.0, len(ppg) / n_attendu) if n_attendu else 0.0
    plausibles = [v for v in ppg if 10000 < v < 300000]
    q_card *= (len(plausibles) / len(ppg)) if ppg else 0.0
    q_eda = min(1.0, len(eda) / 10.0)

    charge = {
        "v": 1,
        "device_id": DEVICE_ID,
        "ts": datetime.now(timezone.utc).isoformat(),
        "seq": seq,
        "ibi_ms": [],
        "eda_us": eda,
        "ppg_raw": ppg,
        "ma": ma,
        "qualite": {"cardiaque": round(q_card, 3), "eda": round(q_eda, 3)},
    }
    charge["sig"] = signer(charge)
    return charge


def vider(client: httpx.Client) -> None:
    """Rejoue le tampon par paquets de soixante avant de reprendre le rythme."""
    envoyes = 0
    while TAMPON and envoyes < 60:
        message = TAMPON[0]
        try:
            client.post(URL, json=message, timeout=2.0).raise_for_status()
        except Exception:
            return
        TAMPON.popleft()
        envoyes += 1


def main() -> None:
    lien = serial.Serial(PORT, 115200, timeout=1)
    client = httpx.Client()
    seq = 0
    ppg: list[int] = []
    eda: list[float] = []
    ma: float | None = None
    n_attendu = 100

    while True:
        ligne = lien.readline().decode(errors="ignore").strip()
        if not ligne:
            continue
        genre, _, reste = ligne.partition(",")

        if genre == "P":
            ppg.append(int(reste))
        elif genre == "E":
            eda.append(float(reste))
        elif genre == "I":
            ma = float(reste)
        elif genre == "T":
            _, _, attendu = reste.partition(",")
            n_attendu = int(attendu) or 100

            message = construire(seq, ppg, eda, ma, n_attendu)
            seq += 1
            ppg, eda, ma = [], [], None

            try:
                client.post(URL, json=message, timeout=2.0).raise_for_status()
                vider(client)
            except Exception:
                TAMPON.append(message)
                print(f"hors ligne, {len(TAMPON)} en tampon", flush=True)


if __name__ == "__main__":
    main()
```

- [ ] **Étape 2 : Installer les dépendances sur le Pi**

```bash
sudo apt install -y python3-serial
pip3 install --break-system-packages httpx pyserial
```

- [ ] **Étape 3 : Écrire l'unité systemd**

```ini
[Unit]
Description=Passerelle serie C.A.L.M.E.
After=network.target

[Service]
Type=simple
User=pi
Environment=PORT_SERIE=/dev/ttyACM0
Environment=URL_INGEST=http://192.168.1.10:8000/api/v1/ingest
Environment=DEVICE_ID=cabine-01
Environment=CLE_SIGNATURE=a-remplacer-par-la-cle-de-l-appareil
ExecStart=/usr/bin/python3 /home/pi/passerelle/passerelle.py
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
```

- [ ] **Étape 4 : Vérifier le tampon en direct**

Lancer la passerelle, débrancher l'Ethernet du Pi 20 secondes, le rebrancher.
Attendu : les messages `hors ligne, N en tampon` montent, puis le tampon se vide et `seq` reprend sans trou côté serveur.

**C'est le point de démonstration n°3. Le vérifier maintenant, pas vendredi.**

- [ ] **Étape 5 : Commit**

```bash
git add passerelle/
git commit -m "embarque: passerelle serie vers HTTP avec tampon hors ligne"
```

---

# PÔLE SERVEUR

### Tâche 1 : WebSocket de séance — débloque le front

**Files:**
- Create: `app/ws/__init__.py`, `app/ws/hub.py`
- Create: `app/api/v1/stream.py`
- Modify: `app/main.py`
- Test: `tests/test_hub.py`

**Interfaces:**
- Consomme : rien.
- Produit : `hub.diffuser(session_id: int, evenement: dict) -> None` (coroutine), utilisé par les tâches 7 et 10. Les `evenement` ont la forme `{"type": str, "payload": dict}` avec `type` ∈ `frame · indicators · assessment · recommendation · mode · progress · notice`, exactement comme `StreamEvent` dans `Frontend/src/api/types.ts`.

- [ ] **Étape 1 : Écrire le test qui échoue**

```python
# tests/test_hub.py
import pytest

from app.ws.hub import Hub


class FauxSocket:
    def __init__(self):
        self.recus = []

    async def send_json(self, donnees):
        self.recus.append(donnees)


@pytest.mark.asyncio
async def test_diffuse_aux_abonnes_de_la_session():
    hub = Hub()
    a, b, autre = FauxSocket(), FauxSocket(), FauxSocket()
    hub.rejoindre(1, a)
    hub.rejoindre(1, b)
    hub.rejoindre(2, autre)

    await hub.diffuser(1, {"type": "notice", "payload": {"level": "info", "message": "ok"}})

    assert len(a.recus) == 1
    assert len(b.recus) == 1
    assert autre.recus == []


@pytest.mark.asyncio
async def test_un_socket_mort_ne_bloque_pas_les_autres():
    class SocketMort(FauxSocket):
        async def send_json(self, donnees):
            raise RuntimeError("ferme")

    hub = Hub()
    mort, vivant = SocketMort(), FauxSocket()
    hub.rejoindre(1, mort)
    hub.rejoindre(1, vivant)

    await hub.diffuser(1, {"type": "notice", "payload": {}})

    assert len(vivant.recus) == 1
    assert mort not in hub._salles[1]
```

- [ ] **Étape 2 : Configurer pytest et lancer le test**

```bash
pip install pytest-asyncio
cat > pytest.ini <<'INI'
[pytest]
asyncio_mode = auto
testpaths = tests
INI
touch tests/__init__.py
pytest tests/test_hub.py -v
```
Attendu : ÉCHEC, `ModuleNotFoundError: No module named 'app.ws'`.

Sans `asyncio_mode = auto`, pytest-asyncio ignore silencieusement les tests
`async def` et les compte comme réussis — un test vert qui n'a rien exécuté est
pire qu'un test rouge.

- [ ] **Étape 3 : Écrire le hub**

```python
# app/ws/hub.py
"""Registre des connexions temps reel, une salle par seance.

Un socket qui tombe ne doit jamais empecher les autres de recevoir : c'est
tout l'interet d'avoir une diffusion tolerante plutot qu'une boucle naive.
"""

from collections import defaultdict


class Hub:
    def __init__(self) -> None:
        self._salles: dict[int, set] = defaultdict(set)

    def rejoindre(self, session_id: int, socket) -> None:
        self._salles[session_id].add(socket)

    def quitter(self, session_id: int, socket) -> None:
        self._salles[session_id].discard(socket)

    async def diffuser(self, session_id: int, evenement: dict) -> None:
        morts = []
        for socket in list(self._salles.get(session_id, ())):
            try:
                await socket.send_json(evenement)
            except Exception:
                morts.append(socket)
        for socket in morts:
            self._salles[session_id].discard(socket)


hub = Hub()
```

```python
# app/ws/__init__.py
from app.ws.hub import Hub, hub

__all__ = ["Hub", "hub"]
```

- [ ] **Étape 4 : Lancer le test, vérifier qu'il passe**

```bash
pytest tests/test_hub.py -v
```
Attendu : 2 passed.

- [ ] **Étape 5 : Écrire la route**

```python
# app/api/v1/stream.py
import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.ws.hub import hub

router = APIRouter()


@router.websocket("/sessions/{session_id}/stream")
async def stream(websocket: WebSocket, session_id: int):
    await websocket.accept()
    hub.rejoindre(session_id, websocket)
    try:
        while True:
            # Le client ne pousse rien d'autre qu'un ping : on attend
            # simplement qu'il se taise pour detecter la deconnexion.
            await asyncio.wait_for(websocket.receive_text(), timeout=60)
    except (WebSocketDisconnect, asyncio.TimeoutError, Exception):
        pass
    finally:
        hub.quitter(session_id, websocket)
```

- [ ] **Étape 6 : Monter le routeur**

Dans `app/main.py`, remplacer le contenu par :

```python
from fastapi import FastAPI

from app.api.v1 import health, ingest, stream

app = FastAPI(title="C.A.L.M.E. - API serveur de bord")

app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(ingest.router, prefix="/api/v1", tags=["ingest"])
app.include_router(stream.router, prefix="/api/v1", tags=["stream"])
```

- [ ] **Étape 7 : Vérifier à la main**

```bash
uvicorn app.main:app --reload --host 0.0.0.0 &
python3 -c "
from websockets.sync.client import connect
with connect('ws://localhost:8000/api/v1/sessions/1/stream') as c:
    print('connecte')
"
```
Attendu : `connecte`, sans exception.

- [ ] **Étape 8 : Commit**

```bash
git add app/ws app/api/v1/stream.py app/main.py tests/test_hub.py
git commit -m "serveur: WebSocket de seance et hub de diffusion"
```

---

### Tâche 2 : Étendre le contrat d'ingestion

**Files:**
- Modify: `app/schemas/ingest.py`
- Modify: `app/api/v1/ingest.py`
- Test: `tests/test_schema_ingest.py`

**Interfaces:**
- Consomme : rien.
- Produit : `IngestMessage.ppg_raw: list[int]` et `IngestMessage.ma: float | None`, lus par les tâches 3 et 7.

- [ ] **Étape 1 : Écrire le test qui échoue**

```python
# tests/test_schema_ingest.py
import pytest
from pydantic import ValidationError

from app.schemas.ingest import IngestMessage

BASE = {
    "v": 1,
    "device_id": "cabine-01",
    "ts": "2026-09-23T10:00:00Z",
    "seq": 0,
    "qualite": {"cardiaque": 0.9, "eda": 0.9},
}


def test_accepte_le_ppg_brut_et_le_courant():
    m = IngestMessage(**BASE, ppg_raw=[120000, 120500], ma=212.0)
    assert m.ppg_raw == [120000, 120500]
    assert m.ma == 212.0


def test_reste_compatible_avec_le_simulateur():
    """Le simulateur existant n'envoie ni ppg_raw ni ma : il doit continuer."""
    m = IngestMessage(**BASE, ibi_ms=[857], eda_us=[4.0])
    assert m.ppg_raw == []
    assert m.ma is None


def test_rejette_un_intervalle_hors_bornes():
    with pytest.raises(ValidationError):
        IngestMessage(**BASE, ibi_ms=[120])
```

- [ ] **Étape 2 : Lancer le test, vérifier qu'il échoue**

```bash
pytest tests/test_schema_ingest.py -v
```
Attendu : ÉCHEC sur `test_accepte_le_ppg_brut_et_le_courant`, champ inconnu.

- [ ] **Étape 3 : Étendre le schéma**

Dans `app/schemas/ingest.py`, ajouter deux champs à `IngestMessage`, après `eda_us` :

```python
    ppg_raw: list[int] = Field(default_factory=list)
    ma: float | None = None
```

- [ ] **Étape 4 : Lancer le test, vérifier qu'il passe**

```bash
pytest tests/test_schema_ingest.py -v
```
Attendu : 3 passed.

- [ ] **Étape 5 : Stocker le PPG brut**

Dans `app/api/v1/ingest.py`, à l'intérieur de `ingest()`, **avant** le bloc `if message.ibi_ms:` :

```python
    if message.ppg_raw:
        db.add(
            Mesure(
                session_id=session.id,
                device_id=message.device_id,
                capteur="ppg",
                seq=message.seq,
                ts=message.ts,
                valeurs={"ppg_raw": message.ppg_raw},
                qualite={"cardiaque": message.qualite.cardiaque},
            )
        )
```

- [ ] **Étape 6 : Vérifier bout en bout**

```bash
python simulator/send_measures.py   # doit continuer a afficher 202
```

- [ ] **Étape 7 : Commit**

```bash
git add app/schemas/ingest.py app/api/v1/ingest.py tests/test_schema_ingest.py
git commit -m "serveur: ingestion du PPG brut et du courant, retro-compatible"
```

---

### Tâche 3 : Indicateurs cardiaques

**Files:**
- Create: `app/services/__init__.py`, `app/services/cardiaque.py`
- Test: `tests/test_cardiaque.py`

**Interfaces:**
- Consomme : `IngestMessage.ppg_raw` (tâche 2).
- Produit :
  - `rr_depuis_ppg(ppg: list[int], fe: int = 100) -> list[float]` — RR en ms
  - `nettoyer_rr(rr: list[float]) -> list[float]`
  - `fc_moyenne(rr: list[float]) -> float | None`
  - `rmssd(rr: list[float]) -> float | None`

- [ ] **Étape 1 : Écrire le test qui échoue**

```python
# tests/test_cardiaque.py
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
```

- [ ] **Étape 2 : Lancer le test, vérifier qu'il échoue**

```bash
pip install neurokit2
pytest tests/test_cardiaque.py -v
```
Attendu : ÉCHEC, `ModuleNotFoundError: No module named 'app.services'`.

- [ ] **Étape 3 : Écrire le service**

```python
# app/services/cardiaque.py
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
```

```python
# app/services/__init__.py
```

- [ ] **Étape 4 : Lancer le test, vérifier qu'il passe**

```bash
pytest tests/test_cardiaque.py -v
```
Attendu : 4 passed.

- [ ] **Étape 5 : Commit**

```bash
git add app/services/ tests/test_cardiaque.py
git commit -m "serveur: detection de battements et variabilite cardiaque"
```

---

### Tâche 4 : Indicateurs de sudation

**Files:**
- Create: `app/services/sudation.py`
- Test: `tests/test_sudation.py`

**Interfaces:**
- Consomme : `IngestMessage.eda_us`.
- Produit : `indicateurs_eda(eda: list[float], fe: int = 10) -> tuple[float | None, float | None]` → `(eda_fond, eda_reponses)` où `eda_reponses` est un nombre de réponses par minute.

- [ ] **Étape 1 : Écrire le test qui échoue**

```python
# tests/test_sudation.py
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
```

- [ ] **Étape 2 : Lancer le test, vérifier qu'il échoue**

```bash
pytest tests/test_sudation.py -v
```
Attendu : ÉCHEC, module absent.

- [ ] **Étape 3 : Écrire le service**

```python
# app/services/sudation.py
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
```

- [ ] **Étape 4 : Lancer le test, vérifier qu'il passe**

```bash
pytest tests/test_sudation.py -v
```
Attendu : 2 passed.

- [ ] **Étape 5 : Commit**

```bash
git add app/services/sudation.py tests/test_sudation.py
git commit -m "serveur: niveau de fond et reponses rapides de la sudation"
```

---

### Tâche 5 : Fréquence respiratoire dérivée du rythme cardiaque

**Files:**
- Create: `app/services/respiration.py`
- Test: `tests/test_respiration.py`

**Interfaces:**
- Consomme : la sortie de `nettoyer_rr` (tâche 3).
- Produit : `frequence_respiratoire(rr_ms: list[float]) -> float | None` — cycles par minute.

C'est l'indicateur qui porte l'argument énergétique du dossier. Il ne se calcule qu'une fois par phase (avant / après), jamais en fenêtre glissante : il faut au moins 60 s de RR pour résoudre 0,1 Hz.

- [ ] **Étape 1 : Écrire le test qui échoue**

```python
# tests/test_respiration.py
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
```

- [ ] **Étape 2 : Lancer le test, vérifier qu'il échoue**

```bash
pytest tests/test_respiration.py -v
```
Attendu : ÉCHEC, module absent.

- [ ] **Étape 3 : Écrire le service**

```python
# app/services/respiration.py
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
```

- [ ] **Étape 4 : Lancer le test, vérifier qu'il passe**

```bash
pytest tests/test_respiration.py -v
```
Attendu : 3 passed.

Si le premier test échoue de peu, élargir la tolérance à 2,0 plutôt que de toucher au filtre : la résolution fréquentielle d'un Welch sur 75 s est intrinsèquement limitée.

- [ ] **Étape 5 : Commit**

```bash
git add app/services/respiration.py tests/test_respiration.py
git commit -m "serveur: frequence respiratoire par arythmie sinusale"
```

---

### Tâche 6 : Indice de charge, confiance et niveau

**Files:**
- Create: `app/services/indice.py`
- Test: `tests/test_indice.py`

**Interfaces:**
- Consomme : les sorties des tâches 3, 4, 5 et 10.
- Produit :
  - `POIDS: dict[str, float]`
  - `ecart_z(valeur, moyenne, ecart_type) -> float`
  - `indice_charge(zs: dict[str, float]) -> tuple[float, float]` → `(indice, confiance)`
  - `niveau_depuis(indice: float, confiance: float) -> str` → `"green" | "amber" | "red" | "unreliable"`

Les libellés de niveau sont ceux du type `Level` du front. Ne pas les traduire.

- [ ] **Étape 1 : Écrire le test qui échoue**

```python
# tests/test_indice.py
from app.services.indice import POIDS, ecart_z, indice_charge, niveau_depuis


def test_les_poids_somment_a_un():
    assert abs(sum(POIDS.values()) - 1.0) < 1e-9


def test_a_sa_propre_normale_lindice_vaut_trente():
    zs = {cle: 0.0 for cle in POIDS}
    indice, confiance = indice_charge(zs)
    assert abs(indice - 30.0) < 0.01
    assert abs(confiance - 1.0) < 1e-9


def test_reproduit_le_scenario_du_dossier():
    """Mei sort a 58, en orange, alors qu'elle est d'ordinaire autour de 30.

    Attention au signe : le stress fait BAISSER la variabilite cardiaque. Un z
    positif sur hrv_rmssd veut dire « mieux que d'habitude », pas « plus
    stressee ». C'est pour ca que le service l'inverse, et c'est pour ca que ce
    test doit le modeliser correctement sous peine de ne rien verifier.
    """
    zs = {cle: 1.4 for cle in POIDS}
    zs["hrv_rmssd"] = -1.4
    indice, _ = indice_charge(zs)
    assert abs(indice - 58.0) < 0.5
    assert niveau_depuis(indice, 1.0) == "amber"


def test_un_signal_manquant_renormalise_et_baisse_la_confiance():
    zs = {cle: 1.0 for cle in POIDS if cle != "visage"}
    zs["hrv_rmssd"] = -1.0
    indice, confiance = indice_charge(zs)
    assert abs(confiance - 0.90) < 1e-9
    # Les poids restants sont renormalises : l'indice ne bouge pas.
    assert abs(indice - 50.0) < 0.01


def test_les_seuils_sont_quarante_et_soixante_dix():
    assert niveau_depuis(39.9, 1.0) == "green"
    assert niveau_depuis(40.0, 1.0) == "amber"
    assert niveau_depuis(69.9, 1.0) == "amber"
    assert niveau_depuis(70.0, 1.0) == "red"


def test_une_confiance_trop_basse_rend_la_mesure_inexploitable():
    assert niveau_depuis(80.0, 0.3) == "unreliable"


def test_lecart_z_est_borne():
    assert ecart_z(1000.0, 0.0, 1.0) == 3.0
    assert ecart_z(-1000.0, 0.0, 1.0) == -3.0
    assert ecart_z(5.0, 5.0, 0.0) == 0.0
```

- [ ] **Étape 2 : Lancer le test, vérifier qu'il échoue**

```bash
pytest tests/test_indice.py -v
```
Attendu : ÉCHEC, module absent.

- [ ] **Étape 3 : Écrire le service**

```python
# app/services/indice.py
"""Indice de charge : la seule decision du systeme, et elle est deterministe.

Un modele de langage ne fixe jamais de niveau ici. Meme entree, meme sortie,
toujours. C'est ce qui rend la decision testable et explicable apres coup.
"""

# Le poids le plus fort va aux indicateurs les mieux etablis et les moins
# controlables volontairement ; le plus faible a l'indice facial, le plus bruite.
POIDS: dict[str, float] = {
    "hrv_rmssd": 0.30,      # inverse : une variabilite basse signe le stress
    "eda_reponses": 0.25,
    "voix": 0.15,
    "eda_fond": 0.10,
    "fc_moyenne": 0.10,
    "visage": 0.10,
}

INVERSES = {"hrv_rmssd"}

SEUIL_ORANGE = 40.0
SEUIL_ROUGE = 70.0
CONFIANCE_MIN = 0.4


def ecart_z(valeur: float, moyenne: float, ecart_type: float) -> float:
    """Ecart a l'historique de la personne, borne a trois sigmas.

    Le bornage n'est pas cosmetique : un capteur qui deraille produirait sinon
    un z de 40 qui saturerait l'indice a lui seul.
    """
    if ecart_type <= 0:
        return 0.0
    return max(-3.0, min(3.0, (valeur - moyenne) / ecart_type))


def indice_charge(zs: dict[str, float]) -> tuple[float, float]:
    """Moyenne ponderee des ecarts, ramenee sur 100.

    Un signal absent voit son poids retire et les autres renormalises : le
    systeme perd de la certitude, pas sa fonction. La confiance renvoyee est
    la somme des poids disponibles, et elle est affichee, jamais cachee.
    """
    disponibles = {cle: z for cle, z in zs.items() if z is not None and cle in POIDS}
    confiance = sum(POIDS[cle] for cle in disponibles)
    if confiance <= 0:
        return 30.0, 0.0

    somme = sum(
        POIDS[cle] * (-z if cle in INVERSES else z)
        for cle, z in disponibles.items()
    )
    indice = 30.0 + 20.0 * (somme / confiance)
    return max(0.0, min(100.0, indice)), confiance


def niveau_depuis(indice: float, confiance: float) -> str:
    if confiance < CONFIANCE_MIN:
        return "unreliable"
    if indice >= SEUIL_ROUGE:
        return "red"
    if indice >= SEUIL_ORANGE:
        return "amber"
    return "green"
```

- [ ] **Étape 4 : Lancer le test, vérifier qu'il passe**

```bash
pytest tests/test_indice.py -v
```
Attendu : 7 passed.

- [ ] **Étape 5 : Commit**

```bash
git add app/services/indice.py tests/test_indice.py
git commit -m "serveur: indice de charge, confiance et paliers"
```

---

### Tâche 7 : Évaluation d'une séance et diffusion

**Files:**
- Create: `app/api/v1/assess.py`
- Modify: `app/main.py`
- Test: `tests/test_assess.py`

**Interfaces:**
- Consomme : tâches 1 à 6, plus `exercices_autorises` et `rediger` (tâches 8 et 9).
- Produit : `POST /api/v1/sessions/{id}/assess` → un JSON conforme au type `Assessment` du front, et deux événements diffusés sur le WebSocket : `assessment` puis `recommendation`.

**Baseline personnelle :** moyenne et écart-type des `Indicateur` de l'astronaute sur ses séances précédentes. Sous 10 séances, on compare à une baseline générique et on multiplie la confiance par 0,6 — à dire à l'écran, pas à cacher.

- [ ] **Étape 1 : Écrire le test qui échoue**

```python
# tests/test_assess.py
from app.api.v1.assess import baseline_ou_generique, construire_assessment

GENERIQUE = {
    "hrv_rmssd": (42.0, 15.0),
    "eda_reponses": (3.0, 2.0),
    "eda_fond": (5.0, 2.0),
    "fc_moyenne": (72.0, 9.0),
    "voix": (0.5, 0.15),
    "visage": (0.5, 0.15),
}


def test_sous_dix_seances_la_baseline_est_generique_et_la_confiance_baisse():
    base, facteur = baseline_ou_generique(historique=[], generique=GENERIQUE)
    assert base == GENERIQUE
    assert abs(facteur - 0.6) < 1e-9


def test_au_dela_de_dix_seances_la_baseline_est_personnelle():
    historique = [{"hrv_rmssd": 50.0 + i} for i in range(12)]
    base, facteur = baseline_ou_generique(historique=historique, generique=GENERIQUE)
    assert abs(facteur - 1.0) < 1e-9
    moyenne, ecart_type = base["hrv_rmssd"]
    assert abs(moyenne - 55.5) < 0.01
    assert ecart_type > 0


def test_lassessment_a_la_forme_attendue_par_le_front():
    a = construire_assessment(
        session_id=1,
        mesures={"hrv_rmssd": 30.0, "eda_reponses": 6.0, "fc_moyenne": 78.0,
                 "eda_fond": 7.0, "voix": None, "visage": None},
        baseline=GENERIQUE,
        facteur_confiance=1.0,
        indicateurs_bruts={"heartRateMean": 78.0, "heartRateVariability": 30.0,
                           "edaTonic": 7.0, "edaPhasic": 6.0,
                           "faceTension": None, "voiceIndex": None,
                           "breathingRate": 14.0},
    )
    assert set(a) >= {"id", "sessionId", "index", "level", "confidence",
                      "missingSignals", "indicators", "personalBaseline", "computedAt"}
    assert a["level"] in {"green", "amber", "red", "unreliable"}
    # Voix et visage absents : leurs poids sont retires, 1 - 0,15 - 0,10 = 0,75
    assert abs(a["confidence"] - 0.75) < 1e-9
    signaux = {m["signal"] for m in a["missingSignals"]}
    assert signaux == {"voice", "face"}
```

- [ ] **Étape 2 : Lancer le test, vérifier qu'il échoue**

```bash
pytest tests/test_assess.py -v
```
Attendu : ÉCHEC, module absent.

- [ ] **Étape 3 : Écrire le module**

```python
# app/api/v1/assess.py
"""Evaluation d'une seance : du calcul deterministe a la consigne redigee.

Deux etapes distinctes, et l'ordre compte. Du code ordinaire fixe l'indice, le
niveau et la liste des exercices autorises. Ensuite seulement, le modele
choisit dans cette liste et redige. S'il est indisponible, la premiere etape
reste entiere.
"""

import statistics
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DbSession

from app.deps import get_db
from app.services.indice import POIDS, ecart_z, indice_charge, niveau_depuis
from app.ws.hub import hub

router = APIRouter()

SEANCES_POUR_BASELINE = 10
FACTEUR_BASELINE_GENERIQUE = 0.6

# Les cles du front, pour missingSignals. Le contrat parle de quatre signaux.
SIGNAL_DU_CHAMP = {
    "hrv_rmssd": "hr",
    "fc_moyenne": "hr",
    "eda_fond": "eda",
    "eda_reponses": "eda",
    "visage": "face",
    "voix": "voice",
}


def baseline_ou_generique(historique: list[dict], generique: dict) -> tuple[dict, float]:
    """La comparaison a l'historique personnel demande plusieurs dizaines de
    seances pour etre stable. En dessous, on l'annonce au lieu de faire semblant.
    """
    if len(historique) < SEANCES_POUR_BASELINE:
        return generique, FACTEUR_BASELINE_GENERIQUE

    base = {}
    for cle in POIDS:
        valeurs = [h[cle] for h in historique if h.get(cle) is not None]
        if len(valeurs) < 2:
            base[cle] = generique[cle]
            continue
        base[cle] = (statistics.fmean(valeurs), statistics.stdev(valeurs))
    return base, 1.0


def construire_assessment(session_id: int, mesures: dict, baseline: dict,
                          facteur_confiance: float, indicateurs_bruts: dict) -> dict:
    zs = {}
    manquants = []
    for cle in POIDS:
        valeur = mesures.get(cle)
        if valeur is None:
            manquants.append({"signal": SIGNAL_DU_CHAMP[cle], "reason": "faulty"})
            continue
        moyenne, ecart_type = baseline[cle]
        zs[cle] = ecart_z(valeur, moyenne, ecart_type)

    indice, confiance = indice_charge(zs)
    confiance *= facteur_confiance

    # Un signal couvre deux champs (hr, eda) : on ne le liste qu'une fois.
    uniques, vus = [], set()
    for m in manquants:
        if m["signal"] not in vus:
            vus.add(m["signal"])
            uniques.append(m)

    return {
        "id": str(uuid4()),
        "sessionId": str(session_id),
        "index": round(indice, 1),
        "level": niveau_depuis(indice, confiance),
        "confidence": round(confiance, 3),
        "missingSignals": uniques,
        "indicators": indicateurs_bruts,
        "personalBaseline": round(baseline["hrv_rmssd"][0], 1) if "hrv_rmssd" in baseline else None,
        "computedAt": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/sessions/{session_id}/assess")
async def assess(session_id: int, db: DbSession = Depends(get_db)):
    from app.services.consigne import rediger
    from app.services.exercices import exercices_autorises
    from app.api.v1.calcul import mesures_de_la_seance, indicateurs_du_front

    mesures = mesures_de_la_seance(db, session_id)
    generique = {
        "hrv_rmssd": (42.0, 15.0), "eda_reponses": (3.0, 2.0),
        "eda_fond": (5.0, 2.0), "fc_moyenne": (72.0, 9.0),
        "voix": (0.5, 0.15), "visage": (0.5, 0.15),
    }
    baseline, facteur = baseline_ou_generique([], generique)

    evaluation = construire_assessment(
        session_id, mesures, baseline, facteur, indicateurs_du_front(mesures)
    )
    await hub.diffuser(session_id, {"type": "assessment", "payload": evaluation})

    autorises = exercices_autorises(evaluation["level"])
    exercice, message, source, modele = rediger(evaluation, autorises, historique=[])
    recommandation = {
        "id": str(uuid4()),
        "assessmentId": evaluation["id"],
        "exercise": exercice,
        "message": message,
        "source": source,
        "modelName": modele,
    }
    await hub.diffuser(session_id, {"type": "recommendation", "payload": recommandation})

    return evaluation
```

- [ ] **Étape 4 : Écrire le module de calcul d'appoint**

```python
# app/api/v1/calcul.py
"""Assemble les mesures d'une seance en indicateurs, depuis la base."""

from sqlalchemy.orm import Session as DbSession

from app.models.tables import Mesure
from app.services.cardiaque import fc_moyenne, nettoyer_rr, rmssd, rr_depuis_ppg
from app.services.respiration import frequence_respiratoire
from app.services.sudation import indicateurs_eda


def mesures_de_la_seance(db: DbSession, session_id: int) -> dict:
    lignes = db.query(Mesure).filter(Mesure.session_id == session_id).order_by(Mesure.seq).all()

    ppg: list[int] = []
    eda: list[float] = []
    for ligne in lignes:
        if ligne.capteur == "ppg":
            ppg.extend(ligne.valeurs.get("ppg_raw", []))
        elif ligne.capteur == "sudation":
            eda.extend(ligne.valeurs.get("eda_us", []))

    rr = nettoyer_rr(rr_depuis_ppg(ppg))
    fond, reponses = indicateurs_eda(eda)

    return {
        "hrv_rmssd": rmssd(rr),
        "fc_moyenne": fc_moyenne(rr),
        "eda_fond": fond,
        "eda_reponses": reponses,
        "respiration": frequence_respiratoire(rr),
        "voix": None,      # renseigne par POST /media/audio
        "visage": None,    # renseigne par POST /media/face
    }


def indicateurs_du_front(mesures: dict) -> dict:
    """Les noms du contrat TypeScript, pas les notres."""
    return {
        "heartRateMean": mesures.get("fc_moyenne"),
        "heartRateVariability": mesures.get("hrv_rmssd"),
        "edaTonic": mesures.get("eda_fond"),
        "edaPhasic": mesures.get("eda_reponses"),
        "faceTension": mesures.get("visage"),
        "voiceIndex": mesures.get("voix"),
        "breathingRate": mesures.get("respiration"),
    }
```

- [ ] **Étape 5 : Monter le routeur**

Dans `app/main.py`, ajouter `assess` à l'import et :

```python
app.include_router(assess.router, prefix="/api/v1", tags=["assess"])
```

- [ ] **Étape 6 : Lancer le test, vérifier qu'il passe**

```bash
pytest tests/test_assess.py -v
```
Attendu : 3 passed.

- [ ] **Étape 7 : Commit**

```bash
git add app/api/v1/assess.py app/api/v1/calcul.py app/main.py tests/test_assess.py
git commit -m "serveur: evaluation d'une seance et diffusion temps reel"
```

---

# PÔLE IA

### Tâche 8 : Catalogue d'exercices et filtrage par palier

**Files:**
- Create: `app/services/exercices.py`
- Test: `tests/test_exercices.py`

**Interfaces:**
- Consomme : le `level` produit par la tâche 6.
- Produit : `CATALOGUE: list[dict]` et `exercices_autorises(niveau: str) -> list[dict]`. Chaque exercice a la forme du type `Exercise` du front : `{id, name, duration, indication, minLevel, kind}`.

- [ ] **Étape 1 : Écrire le test qui échoue**

```python
# tests/test_exercices.py
from app.services.exercices import CATALOGUE, exercices_autorises


def test_le_catalogue_a_huit_exercices():
    assert len(CATALOGUE) == 8


def test_chaque_exercice_a_la_forme_du_contrat_front():
    for exercice in CATALOGUE:
        assert set(exercice) == {"id", "name", "duration", "indication", "minLevel", "kind"}
        assert exercice["minLevel"] in {"green", "amber", "red"}
        assert exercice["kind"] in {"breathing", "grounding", "audio", "light", "nap", "journal"}


def test_en_vert_les_exercices_sont_courts_et_legers():
    ids = {e["id"] for e in exercices_autorises("green")}
    assert "journal" in ids
    assert "playlist" in ids


def test_en_rouge_la_coherence_cardiaque_est_disponible():
    assert "cc365" in {e["id"] for e in exercices_autorises("red")}


def test_une_mesure_inexploitable_ne_propose_rien():
    assert exercices_autorises("unreliable") == []
```

- [ ] **Étape 2 : Lancer le test, vérifier qu'il échoue**

```bash
pytest tests/test_exercices.py -v
```
Attendu : ÉCHEC, module absent.

- [ ] **Étape 3 : Écrire le catalogue**

```python
# app/services/exercices.py
"""Les huit interventions de la cabine. Toutes non medicamenteuses, toutes
realisables avec le son et la lumiere d'une piece.

Les trois premieres sont celles qui font le plus baisser la frequence
respiratoire : c'est sur elles que repose l'argument energetique du dossier.
"""

RANG = {"green": 0, "amber": 1, "red": 2}

CATALOGUE: list[dict] = [
    {"id": "cc365", "name": "Coherence cardiaque 365", "duration": 5,
     "indication": "Activation forte, variabilite cardiaque basse",
     "minLevel": "green", "kind": "breathing"},
    {"id": "carre", "name": "Carre de respiration", "duration": 4,
     "indication": "Anxiete ponctuelle, avant une tache delicate",
     "minLevel": "green", "kind": "breathing"},
    {"id": "478", "name": "Respiration 4-7-8", "duration": 3,
     "indication": "Difficulte d'endormissement",
     "minLevel": "green", "kind": "breathing"},
    {"id": "ancrage5432", "name": "Ancrage sensoriel 5-4-3-2-1", "duration": 5,
     "indication": "Rumination, perte de reperes",
     "minLevel": "amber", "kind": "grounding"},
    {"id": "playlist", "name": "Playlist a tempo decroissant", "duration": 10,
     "indication": "Charge moderee, descente progressive",
     "minLevel": "green", "kind": "audio"},
    {"id": "circadien", "name": "Sequence lumineuse circadienne", "duration": 15,
     "indication": "Desynchronisation, baisse de vigilance",
     "minLevel": "green", "kind": "light"},
    {"id": "sieste", "name": "Micro-sieste guidee", "duration": 20,
     "indication": "Fatigue accumulee",
     "minLevel": "amber", "kind": "nap"},
    {"id": "journal", "name": "Journal vocal differe", "duration": 8,
     "indication": "Repli, isolement social",
     "minLevel": "green", "kind": "journal"},
]


def exercices_autorises(niveau: str) -> list[dict]:
    """En rouge, c'est systematiquement une coherence cardiaque prolongee.

    Une mesure aberrante ne declenche aucun exercice : proposer une respiration
    sur un faux contact, c'est apprendre aux gens a ignorer la machine.
    """
    if niveau == "unreliable":
        return []
    if niveau == "red":
        return [e for e in CATALOGUE if e["kind"] == "breathing"]
    plafond = RANG[niveau]
    return [e for e in CATALOGUE if RANG[e["minLevel"]] <= plafond]
```

- [ ] **Étape 4 : Lancer le test, vérifier qu'il passe**

```bash
pytest tests/test_exercices.py -v
```
Attendu : 5 passed.

- [ ] **Étape 5 : Commit**

```bash
git add app/services/exercices.py tests/test_exercices.py
git commit -m "ia: catalogue des huit exercices et filtrage par palier"
```

---

### Tâche 9 : Rédaction de la consigne par Ollama, avec repli

**Files:**
- Create: `app/services/consigne.py`
- Test: `tests/test_consigne.py`

**Interfaces:**
- Consomme : `exercices_autorises` (tâche 8), l'évaluation (tâche 7).
- Produit : `rediger(evaluation: dict, autorises: list[dict], historique: list[dict]) -> tuple[dict | None, str, str, str | None]` → `(exercice, message, source, nom_du_modele)` où `source` ∈ `"model" | "rules"`.

- [ ] **Étape 1 : Écrire le test qui échoue**

```python
# tests/test_consigne.py
from app.services.consigne import CONSIGNES_GENERIQUES, rediger
from app.services.exercices import exercices_autorises


def test_sans_modele_le_systeme_retombe_sur_les_regles(monkeypatch):
    monkeypatch.setattr("app.services.consigne.interroger_modele",
                        lambda *a, **k: None)
    autorises = exercices_autorises("amber")
    exercice, message, source, modele = rediger(
        {"level": "amber", "index": 55.0}, autorises, historique=[])
    assert source == "rules"
    assert modele is None
    assert exercice in autorises
    assert message == CONSIGNES_GENERIQUES[exercice["id"]]


def test_un_exercice_hors_liste_est_refuse(monkeypatch):
    """Le modele n'a acces a aucun autre levier que la liste qu'on lui donne."""
    monkeypatch.setattr("app.services.consigne.interroger_modele",
                        lambda *a, **k: {"exercice_id": "sieste", "message": "Dormez."})
    autorises = exercices_autorises("red")   # respiration uniquement
    exercice, message, source, _ = rediger(
        {"level": "red", "index": 78.0}, autorises, historique=[])
    assert exercice["id"] != "sieste"
    assert source == "rules"


def test_une_reponse_valide_du_modele_est_retenue(monkeypatch):
    monkeypatch.setattr("app.services.consigne.interroger_modele",
                        lambda *a, **k: {"exercice_id": "cc365",
                                         "message": "Cinq minutes, on respire ensemble."})
    autorises = exercices_autorises("red")
    exercice, message, source, modele = rediger(
        {"level": "red", "index": 78.0}, autorises, historique=[])
    assert exercice["id"] == "cc365"
    assert message == "Cinq minutes, on respire ensemble."
    assert source == "model"
    assert modele is not None


def test_aucun_exercice_autorise_ne_fait_pas_planter():
    exercice, message, source, _ = rediger(
        {"level": "unreliable", "index": 0.0}, [], historique=[])
    assert exercice is None
    assert source == "rules"
    assert "maintenance" in message.lower()
```

- [ ] **Étape 2 : Lancer le test, vérifier qu'il échoue**

```bash
pytest tests/test_consigne.py -v
```
Attendu : ÉCHEC, module absent.

- [ ] **Étape 3 : Écrire le service**

```python
# app/services/consigne.py
"""Le modele redige, il ne decide pas.

Il choisit un exercice DANS la liste qu'on lui donne et ecrit la consigne. Il
n'a acces a aucun autre levier. Sa reponse est contrainte en JSON au decodage
et verifiee avant affichage : si l'exercice n'est pas dans la liste, ou si le
format ne tient pas, le serveur prend un choix par defaut.

Consequence : si le modele est indisponible, trop lent, ou coupe pour
economiser l'energie, le systeme continue. Il perd sa capacite a personnaliser,
pas sa fonction.
"""

import os

MODELE = os.environ.get("MODELE_OLLAMA", "llama3.2:3b")
HOTE_OLLAMA = os.environ.get("HOTE_OLLAMA", "http://localhost:11434")
DELAI_MAX_S = 12.0

CONSIGNES_GENERIQUES: dict[str, str] = {
    "cc365": "Cinq minutes de respiration guidee. Suivez le cercle : il se dilate a l'inspiration, il se contracte a l'expiration.",
    "carre": "Quatre minutes. Inspirez sur quatre temps, retenez quatre, expirez quatre, attendez quatre.",
    "478": "Trois minutes. Inspirez sur quatre temps, retenez sept, expirez sur huit.",
    "ancrage5432": "Cinq minutes. Nommez cinq choses que vous voyez, quatre que vous entendez, trois que vous touchez.",
    "playlist": "Dix minutes de son, dont le tempo descendra progressivement. Vous n'avez rien a faire.",
    "circadien": "Quinze minutes de lumiere descendante, calee sur l'heure de bord.",
    "sieste": "Vingt minutes. Fermez les yeux, la cabine vous reveillera.",
    "journal": "Huit minutes. Racontez votre journee a voix haute. Personne ne l'ecoutera.",
}

MESSAGE_MAINTENANCE = (
    "Les mesures ne sont pas exploitables pour l'instant. "
    "Aucun exercice n'est propose. Signalez-le en maintenance."
)

SYSTEME = (
    "Tu es l'assistant d'une cabine de recuperation a bord d'un vaisseau. "
    "Tu choisis UN exercice dans la liste fournie et tu rediges une consigne "
    "de deux phrases maximum, calme, tutoiement exclu, sans emoji, sans "
    "diagnostic medical. Tu ne proposes rien qui ne soit pas dans la liste."
)


def interroger_modele(evaluation: dict, autorises: list[dict], historique: list[dict]) -> dict | None:
    """Renvoie None en cas d'indisponibilite : l'appelant gere le repli."""
    try:
        import ollama

        client = ollama.Client(host=HOTE_OLLAMA, timeout=DELAI_MAX_S)
        liste = "\n".join(f"- {e['id']} : {e['name']} ({e['duration']} min, {e['indication']})"
                          for e in autorises)
        schema = {
            "type": "object",
            "properties": {
                "exercice_id": {"type": "string", "enum": [e["id"] for e in autorises]},
                "message": {"type": "string"},
            },
            "required": ["exercice_id", "message"],
        }
        reponse = client.chat(
            model=MODELE,
            messages=[
                {"role": "system", "content": SYSTEME},
                {"role": "user", "content":
                    f"Indice de charge : {evaluation['index']} sur 100, palier "
                    f"{evaluation['level']}.\nExercices disponibles :\n{liste}"},
            ],
            format=schema,   # contrainte appliquee au decodage, pas verifiee apres coup
        )
        import json
        return json.loads(reponse["message"]["content"])
    except Exception:
        return None


def rediger(evaluation: dict, autorises: list[dict],
            historique: list[dict]) -> tuple[dict | None, str, str, str | None]:
    if not autorises:
        return None, MESSAGE_MAINTENANCE, "rules", None

    defaut = autorises[0]
    propose = interroger_modele(evaluation, autorises, historique)

    if propose:
        choisi = next((e for e in autorises if e["id"] == propose.get("exercice_id")), None)
        message = (propose.get("message") or "").strip()
        if choisi and message:
            return choisi, message, "model", MODELE

    return defaut, CONSIGNES_GENERIQUES[defaut["id"]], "rules", None
```

- [ ] **Étape 4 : Lancer le test, vérifier qu'il passe**

```bash
pytest tests/test_consigne.py -v
```
Attendu : 4 passed.

- [ ] **Étape 5 : Tirer les modèles et vérifier en vrai**

```bash
ollama pull llama3.2:3b
ollama pull llama3.2:1b     # le repli du mode degrade
python3 -c "
from app.services.consigne import rediger
from app.services.exercices import exercices_autorises
print(rediger({'level':'amber','index':55.0}, exercices_autorises('amber'), []))
"
```
Attendu : `source == 'model'` et une consigne en français. Chronométrer : si c'est au-dessus de 12 s, basculer `MODELE_OLLAMA=llama3.2:1b`.

- [ ] **Étape 6 : Commit**

```bash
git add app/services/consigne.py tests/test_consigne.py
git commit -m "ia: redaction de la consigne sous JSON Schema, avec repli deterministe"
```

---

### Tâche 10 : Indice vocal et endpoints média

**Files:**
- Create: `app/services/voix.py`
- Modify: `app/api/v1/assess.py`
- Test: `tests/test_voix.py`

**Interfaces:**
- Consomme : un WAV 16 kHz mono envoyé par le Pi.
- Produit :
  - `FEATURES: dict[str, float]` — les cinq features eGeMAPS retenues et leur poids
  - `indice_vocal(features: dict[str, float], baseline: dict[str, tuple[float, float]]) -> float`
  - `POST /api/v1/sessions/{id}/audio` et `POST /api/v1/sessions/{id}/face`

**Le micro du C270 conditionne le choix des features.** Jitter et shimmer sont trop sensibles à la qualité du micro et à la distance pour être exploitables sur une webcam : ils sont exclus. eGeMAPS fournissant déjà le débit et les silences, ni `parselmouth` ni `silero-vad` ne sont nécessaires.

- [ ] **Étape 1 : Écrire le test qui échoue**

```python
# tests/test_voix.py
from app.services.voix import FEATURES, indice_vocal

BASELINE = {cle: (10.0, 2.0) for cle in FEATURES}


def test_les_poids_somment_a_un():
    assert abs(sum(FEATURES.values()) - 1.0) < 1e-9


def test_ni_jitter_ni_shimmer():
    """Trop sensibles au micro d'une webcam pour porter un indice."""
    noms = " ".join(FEATURES).lower()
    assert "jitter" not in noms
    assert "shimmer" not in noms


def test_a_la_baseline_lindice_vaut_un_demi():
    features = {cle: 10.0 for cle in FEATURES}
    assert abs(indice_vocal(features, BASELINE) - 0.5) < 0.01


def test_tout_au_dessus_de_la_baseline_monte_lindice():
    features = {cle: 16.0 for cle in FEATURES}   # +3 sigma
    assert indice_vocal(features, BASELINE) > 0.8


def test_lindice_reste_borne():
    enorme = {cle: 1e6 for cle in FEATURES}
    minuscule = {cle: -1e6 for cle in FEATURES}
    assert 0.0 <= indice_vocal(enorme, BASELINE) <= 1.0
    assert 0.0 <= indice_vocal(minuscule, BASELINE) <= 1.0


def test_une_feature_absente_ne_fait_pas_planter():
    partiel = {cle: 10.0 for cle in list(FEATURES)[:2]}
    assert 0.0 <= indice_vocal(partiel, BASELINE) <= 1.0
```

- [ ] **Étape 2 : Lancer le test, vérifier qu'il échoue**

```bash
pytest tests/test_voix.py -v
```
Attendu : ÉCHEC, module absent.

- [ ] **Étape 3 : Écrire le service**

```python
# app/services/voix.py
"""Indice vocal : la forme, jamais le contenu.

On ne transcrit rien. Hauteur, intensite, debit et silences suffisent, et ce
choix a une consequence directe : aucune transcription n'existe, donc aucune
ne peut fuiter. L'audio est traite en memoire et detruit dans la meme requete.
"""

import io

import numpy as np

# Les cinq features retenues du jeu eGeMAPSv02. Le jitter et le shimmer en
# sont volontairement absents : sur le micro d'une webcam a soixante
# centimetres, ce sont du bruit et non un signal.
FEATURES: dict[str, float] = {
    "F0semitoneFrom27.5Hz_sma3nz_amean": 0.25,        # hauteur moyenne
    "F0semitoneFrom27.5Hz_sma3nz_stddevNorm": 0.15,   # instabilite / monotonie
    "loudness_sma3_amean": 0.25,                      # intensite
    "VoicedSegmentsPerSec": 0.20,                     # debit de parole
    "MeanUnvoicedSegmentLength": 0.15,             # proportion de silences
}

# Ordres de grandeur pour de la parole adulte a 16 kHz. Ils ne servent qu'aux
# premieres seances d'une personne, avant que son historique existe, et la
# confiance est alors multipliee par 0,6. A reetalonner jeudi sur les
# enregistrements reels : ce sont des estimations de conception.
#
# Ne JAMAIS mettre (0.0, 1.0) ici : la hauteur moyenne vaut une trentaine de
# demi-tons, un ecart-type de 1 donnerait un z borne a +3, et l'indice vocal
# sortirait a 1,0 pour tout le monde — tout l'equipage en rouge.
BASELINE_VOCALE_GENERIQUE: dict[str, tuple[float, float]] = {
    "F0semitoneFrom27.5Hz_sma3nz_amean": (31.0, 5.0),
    "F0semitoneFrom27.5Hz_sma3nz_stddevNorm": (0.17, 0.05),
    "loudness_sma3_amean": (0.80, 0.40),
    "VoicedSegmentsPerSec": (2.20, 0.70),
    "MeanUnvoicedSegmentLength": (0.20, 0.08),
}

_smile = None


def extracteur():
    """Charge openSMILE une seule fois : l'initialisation coute ~1 s."""
    global _smile
    if _smile is None:
        import opensmile

        _smile = opensmile.Smile(
            feature_set=opensmile.FeatureSet.eGeMAPSv02,
            feature_level=opensmile.FeatureLevel.Functionals,
        )
    return _smile


def features_depuis_wav(octets: bytes) -> dict[str, float]:
    """Extrait les features d'un WAV en memoire. Rien n'est ecrit sur disque."""
    import soundfile

    pcm, fe = soundfile.read(io.BytesIO(octets), dtype="float32")
    if pcm.ndim > 1:
        pcm = pcm.mean(axis=1)
    ligne = extracteur().process_signal(pcm, fe).iloc[0]
    return {cle: float(ligne[cle]) for cle in FEATURES if cle in ligne.index}


def indice_vocal(features: dict[str, float],
                 baseline: dict[str, tuple[float, float]]) -> float:
    """Moyenne ponderee des ecarts a la voix habituelle de la personne,
    ramenee dans 0-1. Une feature absente voit son poids redistribue.
    """
    somme, poids_total = 0.0, 0.0
    for cle, poids in FEATURES.items():
        if cle not in features or cle not in baseline:
            continue
        moyenne, ecart_type = baseline[cle]
        if ecart_type <= 0:
            continue
        z = max(-3.0, min(3.0, (features[cle] - moyenne) / ecart_type))
        somme += poids * z
        poids_total += poids

    if poids_total <= 0:
        return 0.5
    return float(np.clip(0.5 + (somme / poids_total) / 6.0, 0.0, 1.0))
```

- [ ] **Étape 4 : Lancer le test, vérifier qu'il passe**

```bash
pip install opensmile soundfile
pytest tests/test_voix.py -v
```
Attendu : 6 passed.

- [ ] **Étape 5 : Ajouter les deux endpoints média**

À la fin de `app/api/v1/assess.py` :

```python
from fastapi import File, UploadFile
from pydantic import BaseModel, Field


class IndiceFacial(BaseModel):
    at: str
    tension: float = Field(ge=0, le=1)
    blinkRate: float = Field(ge=0)
    stillness: float = Field(ge=0, le=1)


@router.post("/sessions/{session_id}/face", status_code=202)
async def recevoir_indice_facial(session_id: int, corps: IndiceFacial):
    """Un flottant par seconde. Aucune image ne transite, jamais.

    L'analyse a lieu dans le navigateur du Pi : la promesse du dossier est
    donc vraie architecturalement, et pas seulement sur parole.
    """
    await hub.diffuser(session_id, {
        "type": "frame",
        "payload": {"at": corps.at, "heartRate": None, "skinConductance": None,
                    "faceTension": corps.tension, "voiceIndex": None, "suspect": []},
    })
    return {"recu": True}


@router.post("/sessions/{session_id}/audio")
async def recevoir_audio(session_id: int, fichier: UploadFile = File(...)):
    """L'audio est analyse en memoire et detruit dans la meme requete.

    Pas de fichier temporaire, pas de chemin sur disque : la seule chose qui
    survit a cet appel est un nombre entre 0 et 1.
    """
    from app.services.voix import (BASELINE_VOCALE_GENERIQUE,
                                   features_depuis_wav, indice_vocal)

    octets = await fichier.read()
    features = features_depuis_wav(octets)
    del octets

    indice = indice_vocal(features, BASELINE_VOCALE_GENERIQUE)

    await hub.diffuser(session_id, {
        "type": "frame",
        "payload": {"at": None, "heartRate": None, "skinConductance": None,
                    "faceTension": None, "voiceIndex": indice, "suspect": []},
    })
    return {"voiceIndex": round(indice, 3), **{k: round(v, 3) for k, v in features.items()}}
```

- [ ] **Étape 6 : Vérifier qu'aucun fichier n'est écrit**

```bash
grep -rn "open(\|NamedTemporaryFile\|\.save(" app/services/voix.py app/api/v1/assess.py
```
Attendu : **aucun résultat.** Si quelque chose sort, la promesse du dossier est fausse dans le code.

- [ ] **Étape 7 : Commit**

```bash
git add app/services/voix.py app/api/v1/assess.py tests/test_voix.py
git commit -m "ia: indice vocal par eGeMAPS et endpoints media sans persistance"
```

---

# PÔLE CLIENT

### Tâche 11 : Grille cabine 800 × 480

**Files:**
- Modify: `Frontend/src/styles/index.css`
- Modify: `figma-calme/src/00-tokens.js`

**Interfaces:**
- Consomme : rien.
- Produit : les variables CSS `--cabine-*` et une classe utilitaire, utilisées par les écrans de la cabine.

L'écran de la cabine fait 800 × 480 en paysage. Il ne tombe sur aucun des trois breakpoints existants (1440 / 1024 / 390). La cabine et le tableau de bord du médecin sont deux produits sur deux machines : il est sain qu'ils aient deux grilles.

- [ ] **Étape 1 : Ajouter le breakpoint au design system**

Dans `figma-calme/src/00-tokens.js`, ajouter à la fin du tableau `BP` :

```js
  { key: 'cabine', label: 'Cabine 7"', w: 800, cols: 8, gutter: 16, margin: 24 }
```

- [ ] **Étape 2 : Ajouter les variables CSS**

Dans `Frontend/src/styles/index.css`, à la fin du bloc `@theme inline` :

```css
  /* Grille de l'ecran de la cabine : 800 x 480 en paysage, tactile.
     480 px de haut, c'est court : le budget vertical de l'ecran seance est
     24 de marge, 260 pour le cercle, 36 pour le compte a rebours, 56 pour la
     consigne, 24 de marge. Il reste 80 px de jeu, pas davantage. */
  --cabine-w: 800px;
  --cabine-h: 480px;
  --cabine-marge: 24px;
  --cabine-gouttiere: 16px;
  --cabine-cible-min: 44px;   /* aucune cible tactile en dessous */
  --cabine-cercle: 260px;
```

- [ ] **Étape 3 : Neutraliser le survol et la sélection en tactile**

À la fin de `Frontend/src/styles/index.css` :

```css
/* L'ecran de la cabine est tactile : il n'y a pas de curseur, donc pas de
   survol. Un etat :hover y reste colle apres un appui et ment sur l'etat
   reel du bouton. */
@media (pointer: coarse) {
  * {
    -webkit-tap-highlight-color: transparent;
  }
  body {
    user-select: none;
    -webkit-user-select: none;
    touch-action: manipulation;
  }
}
```

- [ ] **Étape 4 : Vérifier au bon format**

```bash
npm run dev
```

Ouvrir les outils de développement, mode appareil, dimensions personnalisées **800 × 480**, et parcourir les cinq écrans via `/ecrans`. Noter ceux qui débordent verticalement — ils seront à reprendre, l'écran `séance` en premier.

- [ ] **Étape 5 : Commit**

```bash
git add src/styles/index.css
git commit -m "ui: grille de la cabine 800x480 et regles tactiles"
```

---

### Tâche 12 : Indice facial par MediaPipe

**Files:**
- Create: `Frontend/src/features/cabin/hooks/use-face-index.ts`
- Modify: `Frontend/src/api/transport.ts`
- Modify: `Frontend/src/api/live.ts`
- Modify: `Frontend/src/api/mock/transport.ts`

**Interfaces:**
- Consomme : la webcam du Pi via `getUserMedia`.
- Produit :
  - `Transport.sendFaceIndex(sessionId: string, indice: FaceIndex): Promise<void>` avec `interface FaceIndex { at: string; tension: number; blinkRate: number; stillness: number }`
  - le hook `useFaceIndex(sessionId: string | null, actif: boolean): { pret: boolean; erreur: string | null }`

- [ ] **Étape 1 : Installer MediaPipe**

```bash
npm install @mediapipe/tasks-vision
```

- [ ] **Étape 2 : Étendre le contrat de transport**

Dans `Frontend/src/api/transport.ts`, ajouter avant `export interface Transport` :

```ts
/**
 * L'indice facial calculé dans le navigateur de la cabine.
 *
 * Seuls ces quatre nombres partent. L'image est analysée sur le poste et
 * détruite image par image : la promesse « aucune image conservée » est vraie
 * dans l'architecture, pas seulement dans la politique.
 */
export interface FaceIndex {
  at: string;
  /** Tension du visage, 0 à 1. */
  tension: number;
  /** Clignements par minute, sur une fenêtre glissante de 30 s. */
  blinkRate: number;
  /** Immobilité, 0 à 1. */
  stillness: number;
}
```

Puis, dans l'interface `Transport`, sous le commentaire `/* ---- Cabine ---- */` :

```ts
  /** Pousse l'indice facial calculé localement. Une fois par seconde. */
  sendFaceIndex(sessionId: string, indice: FaceIndex): Promise<void>;
  /** Pousse dix secondes de voix. La réponse ne contient que des indicateurs. */
  sendVoiceSample(sessionId: string, wav: Blob): Promise<{ voiceIndex: number }>;
```

- [ ] **Étape 3 : Implémenter côté live**

Dans `Frontend/src/api/live.ts`, ajouter à l'objet `liveTransport` :

```ts
  sendFaceIndex(sessionId, indice) {
    return request<void>(`/sessions/${segment(sessionId)}/face`, {
      method: 'POST',
      body: JSON.stringify(indice),
    });
  },

  sendVoiceSample(sessionId, wav) {
    const corps = new FormData();
    corps.append('fichier', wav, 'voix.wav');
    return request<{ voiceIndex: number }>(`/sessions/${segment(sessionId)}/audio`, {
      method: 'POST',
      body: corps,
    });
  },
```

- [ ] **Étape 4 : Implémenter côté mock**

Dans `Frontend/src/api/mock/transport.ts`, ajouter à l'objet exporté :

```ts
  async sendFaceIndex() {
    /* Le transport simulé accepte et oublie : les écrans n'ont pas à savoir
       lequel des deux transports ils utilisent. */
  },

  async sendVoiceSample() {
    return { voiceIndex: 0.42 };
  },
```

- [ ] **Étape 5 : Écrire le hook**

```ts
// Frontend/src/features/cabin/hooks/use-face-index.ts
import { FaceLandmarker, FilesetResolver } from '@mediapipe/tasks-vision';
import { useEffect, useRef, useState } from 'react';

import { transport } from '../../../api';

/**
 * L'indice facial, calculé dans le navigateur de la cabine.
 *
 * Bridé à 320×240 et 10 images par seconde. Ce n'est pas de la prudence
 * gratuite : le Pi fait tourner Chromium, la webcam et MediaPipe sur les mêmes
 * cœurs, et l'indice facial est le moins discriminant des quatre signaux. Il
 * n'a pas à prendre le CPU des trois autres.
 */

const FPS = 10;
const FENETRE_S = 30;
const SEUIL_CLIGNEMENT = 0.5;

function valeur(formes: { categoryName: string; score: number }[], nom: string): number {
  return formes.find((f) => f.categoryName === nom)?.score ?? 0;
}

export function useFaceIndex(sessionId: string | null, actif: boolean) {
  const [pret, setPret] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);
  const clignements = useRef<number[]>([]);
  const yeuxFermes = useRef(false);
  const tensions = useRef<number[]>([]);
  const matrices = useRef<number[][]>([]);

  useEffect(() => {
    if (!actif || !sessionId) return;
    let vivant = true;
    let flux: MediaStream | null = null;
    let landmarker: FaceLandmarker | null = null;
    let timerAnalyse = 0;
    let timerEnvoi = 0;

    async function demarrer() {
      try {
        flux = await navigator.mediaDevices.getUserMedia({
          video: { width: 320, height: 240, frameRate: FPS },
        });
        const video = document.createElement('video');
        video.srcObject = flux;
        video.muted = true;
        await video.play();

        const fileset = await FilesetResolver.forVisionTasks(
          'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision/wasm',
        );
        landmarker = await FaceLandmarker.createFromOptions(fileset, {
          baseOptions: { modelAssetPath: '/models/face_landmarker.task' },
          outputFaceBlendshapes: true,
          outputFacialTransformationMatrixes: true,
          runningMode: 'VIDEO',
          numFaces: 1,
        });

        if (!vivant) return;
        setPret(true);

        timerAnalyse = window.setInterval(() => {
          if (!landmarker) return;
          const resultat = landmarker.detectForVideo(video, performance.now());
          const formes = resultat.faceBlendshapes?.[0]?.categories ?? [];
          if (formes.length === 0) return;

          const sourcils =
            (valeur(formes, 'browDownLeft') +
              valeur(formes, 'browDownRight') +
              valeur(formes, 'browInnerUp')) /
            3;
          const bouche =
            (valeur(formes, 'mouthPressLeft') + valeur(formes, 'mouthPressRight')) / 2;
          tensions.current.push(sourcils * 0.7 + bouche * 0.3);
          if (tensions.current.length > FPS * FENETRE_S) tensions.current.shift();

          // Front montant seulement : sans ça, un œil fermé deux secondes
          // compterait pour vingt clignements.
          const ferme =
            Math.max(valeur(formes, 'eyeBlinkLeft'), valeur(formes, 'eyeBlinkRight')) >
            SEUIL_CLIGNEMENT;
          if (ferme && !yeuxFermes.current) clignements.current.push(Date.now());
          yeuxFermes.current = ferme;

          const matrice = resultat.facialTransformationMatrixes?.[0]?.data;
          if (matrice) {
            matrices.current.push([matrice[12], matrice[13], matrice[14]]);
            if (matrices.current.length > FPS * FENETRE_S) matrices.current.shift();
          }
        }, 1000 / FPS);

        timerEnvoi = window.setInterval(() => {
          if (tensions.current.length === 0) return;
          const limite = Date.now() - FENETRE_S * 1000;
          clignements.current = clignements.current.filter((t) => t > limite);

          const tension =
            tensions.current.reduce((a, b) => a + b, 0) / tensions.current.length;
          const blinkRate = (clignements.current.length * 60) / FENETRE_S;
          const stillness = calculerImmobilite(matrices.current);

          void transport
            .sendFaceIndex(sessionId!, {
              at: new Date().toISOString(),
              tension: Math.min(1, Math.max(0, tension)),
              blinkRate,
              stillness,
            })
            .catch(() => {
              /* Une coupure réseau est un état, pas un échec : la passerelle
                 tamponne, l'indice facial suivant repartira. */
            });
        }, 1000);
      } catch (e) {
        if (vivant) setErreur(e instanceof Error ? e.message : 'caméra indisponible');
      }
    }

    void demarrer();

    return () => {
      vivant = false;
      window.clearInterval(timerAnalyse);
      window.clearInterval(timerEnvoi);
      landmarker?.close();
      flux?.getTracks().forEach((piste) => piste.stop());
    };
  }, [sessionId, actif]);

  return { pret, erreur };
}

function calculerImmobilite(positions: number[][]): number {
  if (positions.length < 2) return 1;
  const moyennes = [0, 1, 2].map(
    (i) => positions.reduce((a, p) => a + p[i], 0) / positions.length,
  );
  const variance =
    positions.reduce(
      (a, p) => a + [0, 1, 2].reduce((s, i) => s + (p[i] - moyennes[i]) ** 2, 0),
      0,
    ) / positions.length;
  return Math.min(1, Math.max(0, 1 - variance / 10));
}
```

- [ ] **Étape 6 : Déposer le modèle en local**

Le CDN jsDelivr ne sera pas joignable à bord. Télécharger le modèle maintenant et le committer :

```bash
mkdir -p public/models
curl -L -o public/models/face_landmarker.task \
  https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task
ls -lh public/models/face_landmarker.task   # ~3,7 Mo attendus
```

Le fichier WASM du `FilesetResolver` doit être traité de même avant jeudi soir : copier `node_modules/@mediapipe/tasks-vision/wasm` dans `public/wasm/` et remplacer l'URL du CDN par `/wasm`.

- [ ] **Étape 7 : Vérifier la compilation**

```bash
npm run typecheck
```
Attendu : aucune erreur. Si `transport` n'est pas exporté depuis `src/api/index.ts`, corriger l'import du hook.

- [ ] **Étape 8 : Commit**

```bash
git add src/features/cabin/hooks/use-face-index.ts src/api/ public/models package.json
git commit -m "cabine: indice facial calcule localement par MediaPipe"
```

---

### Tâche 13 : Brancher le vrai serveur

**Files:**
- Modify: `Frontend/.env`

**Interfaces:**
- Consomme : les tâches 1, 7 et 12.
- Produit : la chaîne visible de bout en bout.

- [ ] **Étape 1 : Pointer sur le serveur**

```bash
cat > .env <<'ENV'
VITE_API_BASE_URL=/api/v1
VITE_DEV_API_TARGET=http://192.168.1.10:8000
VITE_USE_MOCK=false
VITE_CABIN_ID=cabine-01
ENV
```

Remplacer `192.168.1.10` par l'IP réelle du serveur.

- [ ] **Étape 2 : Lancer et observer**

```bash
npm run dev
```

Dans un autre terminal, lancer `python simulator/send_measures.py`.

Attendu à l'écran : le pouls bouge, la progression avance, et l'état de connexion affiche « connecté ».

- [ ] **Étape 3 : Déclencher une évaluation**

```bash
curl -X POST http://192.168.1.10:8000/api/v1/sessions/1/assess
```

Attendu : l'écran passe au résultat, avec un indice et une couleur, **sans rechargement**. C'est la preuve que le WebSocket, les indicateurs, l'indice et la diffusion fonctionnent ensemble.

- [ ] **Étape 4 : Lancer Chromium en kiosque sur le Pi**

```bash
chromium-browser --kiosk --force-device-scale-factor=1 \
  --user-data-dir=/tmp/kiosk --noerrdialogs --disable-infobars \
  --unsafely-treat-insecure-origin-as-secure=http://192.168.1.10:8000 \
  http://192.168.1.10:8000
```

⚠️ **Sans le dernier drapeau, `getUserMedia` est bloqué** : ni caméra, ni micro, et Chromium ne dira rien d'utile dans la console. C'est la panne la plus coûteuse en temps de toute la chaîne.

- [ ] **Étape 5 : Commit**

```bash
git add .env.example
git commit -m "client: branchement sur le serveur de bord reel"
```

---

# PÔLE SERVEUR — dette à solder avant jeudi soir

### Tâche 16 : Les cinq correctifs du back existant

**Files:**
- Modify: `requirements.txt`
- Modify: `app/api/v1/ingest.py`
- Create: `migrations/versions/<hash>_astronaute_complet.py`
- Test: `tests/test_signature.py`

**Interfaces:**
- Consomme : `Appareil.cle_signature` (déjà en base).
- Produit : `verifier_signature(message: IngestMessage, cle: str) -> bool`, appelé par `/ingest`.

Le dossier promet qu'« un message non signé ou signé avec une clé inconnue est rejeté et journalisé ». Aujourd'hui la colonne existe et personne ne la lit. C'est une promesse fausse dans le code — à corriger avant que le jury le demande.

- [ ] **Étape 1 : Écrire le test qui échoue**

```python
# tests/test_signature.py
import hashlib
import hmac

from app.api.v1.ingest import verifier_signature
from app.schemas.ingest import IngestMessage

CLE = "cle-de-test"
BASE = {
    "v": 1, "device_id": "cabine-01", "ts": "2026-09-23T10:00:00+00:00",
    "seq": 7, "qualite": {"cardiaque": 0.9, "eda": 0.9},
}


def signer(device_id: str, seq: int, ts: str, cle: str) -> str:
    return hmac.new(cle.encode(), f"{device_id}|{seq}|{ts}".encode(), hashlib.sha256).hexdigest()


def test_accepte_une_signature_valide():
    m = IngestMessage(**BASE, sig=signer("cabine-01", 7, BASE["ts"], CLE))
    assert verifier_signature(m, CLE) is True


def test_refuse_une_cle_inconnue():
    m = IngestMessage(**BASE, sig=signer("cabine-01", 7, BASE["ts"], "autre-cle"))
    assert verifier_signature(m, CLE) is False


def test_refuse_un_message_non_signe():
    m = IngestMessage(**BASE)
    assert verifier_signature(m, CLE) is False


def test_refuse_un_message_rejoue_avec_un_autre_seq():
    """La signature couvre le numero de sequence : on ne peut pas rejouer."""
    m = IngestMessage(**{**BASE, "seq": 8}, sig=signer("cabine-01", 7, BASE["ts"], CLE))
    assert verifier_signature(m, CLE) is False
```

- [ ] **Étape 2 : Lancer le test, vérifier qu'il échoue**

```bash
pytest tests/test_signature.py -v
```
Attendu : ÉCHEC, `ImportError: cannot import name 'verifier_signature'`.

- [ ] **Étape 3 : Ajouter le champ `sig` au schéma**

Dans `app/schemas/ingest.py`, à `IngestMessage` :

```python
    sig: str | None = None
```

- [ ] **Étape 4 : Implémenter la vérification**

En haut de `app/api/v1/ingest.py` :

```python
import hashlib
import hmac

from app.models.tables import Appareil


def verifier_signature(message: IngestMessage, cle: str) -> bool:
    """HMAC-SHA256 sur device_id | seq | ts.

    Le numero de sequence est dans la signature : sans lui, un message capture
    pourrait etre rejoue indefiniment avec la meme signature valide.
    """
    if not message.sig:
        return False
    ts = message.ts.isoformat()
    attendu = hmac.new(
        cle.encode(), f"{message.device_id}|{message.seq}|{ts}".encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(attendu, message.sig)
```

Puis, au début de `ingest()`, **avant** `get_or_create_session` :

```python
    appareil = db.query(Appareil).filter(Appareil.device_id == message.device_id).first()
    if appareil and not verifier_signature(message, appareil.cle_signature):
        # Journalise et rejette. Un capteur qui parle mal n'est pas une urgence
        # medicale, c'est un capteur qui deconne — ou quelqu'un d'autre.
        print(f"signature refusee: {message.device_id} seq={message.seq}", flush=True)
        raise HTTPException(status_code=401, detail="signature invalide")
```

Ajouter `HTTPException` à l'import `from fastapi import ...`.

> Un appareil inconnu de la table `appareils` reste accepté : c'est ce qui laisse le simulateur fonctionner sans clé. À durcir jeudi si le temps le permet, en refusant aussi les appareils non déclarés.

- [ ] **Étape 5 : Lancer le test, vérifier qu'il passe**

```bash
pytest tests/test_signature.py -v
```
Attendu : 4 passed.

- [ ] **Étape 6 : Compléter la table des astronautes**

Le `CrewMember` du front attend quatre champs que `Astronaute` n'a pas. Dans `app/models/tables.py`, classe `Astronaute` :

```python
    role: Mapped[str] = mapped_column(String(80), default="")
    initiales: Mapped[str] = mapped_column(String(4), default="")
    sol_embarquement: Mapped[int] = mapped_column(Integer, default=0)
```

```bash
alembic revision --autogenerate -m "astronaute complet"
alembic upgrade head
```

- [ ] **Étape 7 : Réduire `requirements.txt` aux dépendances directes**

Le fichier actuel est un `pip freeze` complet : `agent-detector`, `detect-installer`, `fastar`, `rignore`, `sentry-sdk` ne sont importés nulle part dans `app/`. L'archive d'installation hors ligne doit être auditable.

```bash
cat > requirements.txt <<'REQ'
fastapi==0.141.1
uvicorn==0.53.0
pydantic==2.13.5
pydantic-settings==2.15.0
SQLAlchemy==2.0.54
alembic==1.20.0
psycopg[binary]==3.3.6
python-dotenv==1.2.3
python-multipart==0.0.32
websockets==17.1
httpx==0.28.1

numpy==2.5.3
scipy==1.18.1
neurokit2
opensmile
soundfile
ollama

pytest==9.1.1
pytest-asyncio
REQ
pip install -r requirements.txt
pytest -v
```
Attendu : toute la suite passe. Si un import manque, c'est qu'une dépendance directe avait été oubliée — l'ajouter explicitement, ne pas remettre le `freeze`.

- [ ] **Étape 8 : Commit**

```bash
git add requirements.txt app/api/v1/ingest.py app/schemas/ingest.py app/models/tables.py migrations/ tests/test_signature.py
git commit -m "serveur: verification de signature, table astronautes completee, dependances reduites"
```

---

### Tâche 17 : Déploiement Coolify et réseau de la cabine

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.env.example`

**Interfaces:**
- Consomme : l'image construite depuis le `Dockerfile` existant.
- Produit : la pile déployée, joignable par le Pi.

⚠️ **Coolify est la cible de déploiement, pas la boucle de développement.** Un redéploiement prend 2 à 5 minutes ; un mercredi d'intégration à quatre, c'est fatal. Toute la journée : `uvicorn --reload`. Cette tâche se fait **le soir**, sur la version stable.

- [ ] **Étape 1 : Isoler le réseau de la cabine**

Beaucoup de réseaux scolaires isolent les clients WiFi entre eux : si le Pi est en WiFi et le serveur en Ethernet, ils peuvent ne pas pouvoir se parler, **sans message d'erreur explicite**.

Brancher le Pi, le serveur et un portable sur un switch dédié. IP statique côté serveur.

```bash
# Depuis le Pi, avant tout le reste :
ping -c 3 192.168.1.10
curl -s http://192.168.1.10:8000/api/v1/health
```
Attendu : `{"api":"ok","base":"ok"}`. Tant que cette ligne ne sort pas, rien d'autre ne sert.

> C'est aussi un argument de soutenance : le vaisseau a son propre réseau et ne demande rien à la Terre. Et vendredi matin, la démonstration ne dépend plus de l'IT de l'école.

- [ ] **Étape 2 : Déclarer PostgreSQL comme ressource Coolify**

Dans Coolify : *New Resource → Database → PostgreSQL*. Coolify fournit un nom d'hôte interne sur son réseau Docker.

Reporter ce nom dans les variables d'environnement de l'application, **jamais `127.0.0.1`** :

```
DATABASE_URL=postgresql+psycopg://<user>:<mdp>@<hote-interne-coolify>:5432/calme
```

Retirer le service `db` du `docker-compose.yml` s'il y en avait un : la base est gérée par Coolify, pas par le compose.

- [ ] **Étape 3 : Déclarer Ollama**

*New Resource → Service → Ollama*, avec un **volume persistant** pour les modèles. Puis, depuis le conteneur :

```bash
ollama pull llama3.2:3b
ollama pull llama3.2:1b
```

Renseigner dans l'application : `HOTE_OLLAMA=http://<hote-ollama-coolify>:11434` et `MODELE_OLLAMA=llama3.2:3b`.

- [ ] **Étape 4 : Ne pas mettre de TLS**

Sans accessibilité publique, pas de Let's Encrypt. Un certificat auto-signé est possible via `/data/coolify/proxy/certs`, mais Chromium en kiosque affichera un écran d'avertissement bloquant tant que l'autorité n'est pas dans le magasin du Pi.

**Rester en HTTP** et utiliser le drapeau Chromium de la tâche 13, étape 4. Une ligne de commande contre une chaîne de certificats — et le drapeau ne peut pas échouer le vendredi matin.

- [ ] **Étape 5 : Prouver le fonctionnement hors ligne**

Coolify tire ses images et Ollama ses modèles depuis le réseau. Ce n'est pas une contradiction avec le discours « entièrement hors ligne » : c'est le même argument que la compilation du front, qui a lieu au sol, avant le départ. Mais il faut le prouver.

**Jeudi soir, une fois tout tiré :**

```bash
# Couper Internet sur le serveur, garder le LAN, puis :
docker compose restart          # ou redemarrage de la pile depuis Coolify
curl -s http://192.168.1.10:8000/api/v1/health
```
Attendu : la pile remonte et `health` répond. Si ce n'est pas le cas, vous l'avez découvert jeudi et non vendredi — et c'est un point de démonstration de plus si ça marche.

- [ ] **Étape 6 : Commit**

```bash
git add docker-compose.yml .env.example
git commit -m "deploiement: base et Ollama en ressources Coolify, reseau de cabine isole"
```

---

# RENDU

### Tâche 18 : Aligner le dossier LaTeX sur le matériel réel

**Files:**
- Modify: `dossier/sections/02-conception.tex`
- Modify: `dossier/sections/03-fabrication.tex`
- Modify: `dossier/sections/04-epreuve.tex`
- Modify: `dossier/sections/06-annexe.tex`

**Interfaces:**
- Consomme : l'architecture des tâches 14 à 17.
- Produit : un dossier qui décrit la machine qu'on démontre.

Le dossier décrit un ESP32-WROOM, un ESP32-CAM et un INMP441. Aucun des trois n'est dans la cabine. Un jury qui ouvre le capot et ne trouve pas ce qui est écrit ne croira plus rien du reste.

- [ ] **Étape 1 : Nomenclature**

`03-fabrication.tex`, tableau ligne 16 et suivantes :
- `ESP32-WROOM` → `Arduino Mega ADK`
- supprimer les lignes `ESP32-CAM` et `Microphone INMP441`
- ajouter `Webcam USB Logitech C270 (micro integre) & 1 & Image et voix de l'occupant`
- ajouter `Adaptateur audio USB & 1 & Sortie son (le Pi 5 n'a pas de prise jack)`
- ajouter `Raspberry Pi + ecran tactile 7" & 1 & Passerelle, interface et indice facial`

- [ ] **Étape 2 : Câblage**

`03-fabrication.tex` ligne 38. Réécrire : I²C sur les broches 20 et 21, GSR sur A0, **adaptation de niveau I²C entre le Mega 5 V et le MAX30102**, plus aucun bus I²S.

- [ ] **Étape 3 : Firmware — la correction qui compte le plus**

`03-fabrication.tex` ligne 48. La phrase « il résume sur une seconde » décrit une conception qui **détruirait la variabilité cardiaque et la fréquence respiratoire**, c'est-à-dire les deux indicateurs sur lesquels repose tout le projet. Remplacer par :

> Le programme embarqué échantillonne à cadence fixe et émet le signal brut, sans rien résumer. La détection de battements a lieu sur le serveur : le détecteur à seuil des bibliothèques Arduino rate des battements et en invente sous artefact de mouvement, et la variabilité entre battements est notre indicateur le mieux pondéré. À sept cents octets par seconde sur une liaison série, transmettre le brut ne coûte rien.

Et sur le tampon :

> Le microcontrôleur ne dispose que de huit kilooctets de mémoire vive : il ne peut pas tamponner dix minutes de mesures, et il n'a pas de réseau. C'est le Raspberry Pi qui fait les deux, en passerelle. Le tampon vit donc là où la mémoire ne coûte rien, et la démonstration de la coupure réseau s'en trouve plus solide, pas moins.

- [ ] **Étape 4 : Schéma d'architecture**

`02-conception.tex` ligne 121 : nœud `ESP32` → `Arduino Mega ADK`. Les nœuds `Caméra` et `Micro` passent du côté client. Ajouter un nœud `Raspberry Pi` entre le microcontrôleur et le serveur, avec l'étiquette `série USB` d'un côté et `HTTP / WS` de l'autre.

- [ ] **Étape 5 : Données personnelles — l'argument se renforce**

`04-epreuve.tex`, section « Données personnelles ». Ajouter :

> L'image n'est pas transmise puis détruite : elle n'est jamais transmise. L'analyse a lieu dans le navigateur de la cabine, et seul un nombre entre zéro et un quitte le poste. La différence n'est pas rhétorique : dans le premier cas il faut nous croire, dans le second il suffit de regarder le trafic réseau.

- [ ] **Étape 6 : Livrables**

`06-annexe.tex` ligne 62 : « le firmware de l'ESP32 » → « le firmware Arduino, la passerelle Python du Raspberry Pi ».

- [ ] **Étape 7 : Recompiler et relire**

```bash
cd dossier && ./compile.sh
```
Attendu : le PDF se génère sans erreur. Relire la nomenclature et le schéma côte à côte avec la cabine réelle.

- [ ] **Étape 8 : Commit**

```bash
git add dossier/
git commit -m "dossier: aligner le materiel decrit sur la cabine reelle"
```

---

## Ce qu'on coupe si 18 h arrive

La liste des coupes est exactement la chaîne de repli du dossier. Couper n'est pas un échec de planning, c'est une démonstration du mode dégradé.

1. **Tâche 12 (visage)** → poids 0,10 retiré, confiance 0,90. Le front affiche déjà « confiance réduite ».
2. **Tâche 10 (voix)** → poids 0,15 retiré, confiance 0,75. Les deux capteurs biologiques portent tout.
3. **Tâche 9 (Ollama)** → `source="rules"`, consignes génériques. Le système garde sa fonction, il perd la personnalisation.
4. **Capteur GSR absent** → `simulator/send_measures.py` prend le relais.

**Ne se coupent pas**, dans l'ordre : la tâche 1 (WebSocket), la tâche 3 (PPG), la tâche 5 (respiration avant/après). Sans ces trois-là, il n'y a plus de démonstration.
