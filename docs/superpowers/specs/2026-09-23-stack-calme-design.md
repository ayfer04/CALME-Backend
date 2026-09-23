# C.A.L.M.E. — conception technique de la chaîne

**23 septembre 2026** · EPSI B3 groupe 10 · document de conception, à exécuter aujourd'hui.

Ce document fige la chaîne de bout en bout à partir du matériel réellement disponible.
Il corrige le dossier là où le dossier décrit un matériel qu'on n'a pas, et il liste
dans quel ordre attaquer pour que la chaîne tourne ce soir.

---

## 0. Le matériel réel

| Rôle | Matériel | Ce que ça implique |
|---|---|---|
| Microcontrôleur | **Arduino Mega ADK** (ATmega2560, 16 MHz, 8 Ko SRAM) | **Pas de WiFi.** 5 V. Il faut une passerelle. |
| Cardiaque | MAX30102 sur carte GY (I²C, 0x57) | Risque de niveau logique, cf. §3 |
| Sudation | Capteur GSR analogique | Entrée A0 |
| Consommation | INA219 (I²C, 0x40) | Partage le bus avec le MAX30102 |
| Écran | Raspberry Pi 7" **800 × 480 paysage**, tactile | Nouveau breakpoint, cf. §12 |
| Caméra + micro | Logitech HD 720p (C270) | 30 fps, micro intégré médiocre, cf. §7.5 |
| Serveur | **i5-12400 · 16 Go RAM** | Confortable. Un modèle 3B tourne à l'aise. |

Le dossier annonce un ESP32-WROOM, un ESP32-CAM et un INMP441. Aucun des trois n'est
dans cette liste. Les deltas du dossier sont en §16.

---

## 1. Topologie : le Pi devient la passerelle

L'Arduino Mega ADK n'a pas de réseau. Il ne peut donc pas poster sur `/api/v1/ingest`.
Il parle en **série USB au Raspberry Pi**, et c'est le Pi qui parle au serveur.

```
┌─ Cabine ───────────────────────────────────────────┐   ┌─ Serveur (i5-12400) ─────┐
│                                                    │   │                          │
│  Arduino Mega ADK                                  │   │  FastAPI + Uvicorn       │
│   ├── MAX30102   (I²C 0x57)  PPG brut 100 Hz       │   │  NeuroKit2 · opensmile   │
│   ├── GSR        (A0)        50 Hz → moy. 10 Hz    │   │  Ollama · Piper          │
│   └── INA219     (I²C 0x40)  1 Hz                  │   │  PostgreSQL              │
│            │                                       │   │                          │
│            │ USB série 115200, lignes CSV          │   └──────────────────────────┘
│            ▼                                       │              ▲
│  Raspberry Pi ── passerelle Python (tampon 10 min) │──HTTP + WS───┘
│            ├── Chromium kiosque 800×480, tactile   │
│            ├── Webcam C270 → MediaPipe (local)     │
│            └── Adaptateur audio USB → haut-parleurs│
└────────────────────────────────────────────────────┘
```

**Pourquoi c'est mieux que l'architecture du dossier**, et pas seulement un pis-aller :

- L'Arduino devient trivial : il lit et il imprime. ~80 lignes, aucun état, aucun tampon.
  Sur 8 Ko de SRAM, c'est la seule conception qui tient.
- **Le tampon de 10 minutes vit sur le Pi**, en Python, dans une `deque`. Plus de contrainte
  de mémoire. La démo « on débranche le réseau » devient : on débranche l'Ethernet du Pi,
  le Pi empile, on rebranche, il rejoue. Exactement le point de démo n°3, en plus solide.
- Le lien Arduino ↔ Pi est un **câble**, pas un réseau. La frontière de confiance se déplace
  honnêtement : c'est le Pi qui signe les messages (il détient la clé), pas l'Arduino.
  À écrire tel quel dans le dossier plutôt qu'à masquer.

---

## 2. Les trois machines, et qui calcule quoi

| | Arduino Mega ADK | Raspberry Pi (cabine) | Serveur i5 |
|---|---|---|---|
| Acquisition PPG / GSR / courant | ✅ | | |
| Détection de battements | | | ✅ NeuroKit2 |
| HRV, EDA tonique/phasique, respiration | | | ✅ NeuroKit2 |
| Indice facial | | ✅ MediaPipe (WASM, Chromium) | |
| Capture audio 10 s | | ✅ getUserMedia | |
| Indice vocal | | | ✅ opensmile |
| Indice de charge, niveau, règles | | | ✅ code déterministe |
| Rédaction de la consigne | | | ✅ Ollama |
| Affichage, son, lumière | | ✅ | |
| Tampon hors ligne | | ✅ deque 10 min | |

**Règle :** aucune image ne quitte le Pi. Seul un flottant par seconde part. L'audio part,
il est analysé en mémoire, et il est détruit dans la même requête.

---

## 3. ⚠️ Risque matériel n°1 — I²C 5 V ↔ MAX30102

Le Mega est en logique 5 V. Beaucoup de cartes GY-MAX30102 tirent leurs résistances de
rappel I²C sur le **1,8 V interne** du capteur. Un Mega considère HIGH à partir de ~3 V :
il ne verra jamais rien. Symptôme : le scanner I²C ne trouve aucune adresse, ou le capteur
renvoie des valeurs constantes.

**À faire en premier ce matin, avant tout le reste :**

1. Câbler VIN → 5 V (la carte a son régulateur), GND → GND, SDA → 20, SCL → 21.
2. Lancer un scanner I²C. On doit voir **0x57** (MAX30102) et **0x40** (INA219).
3. Si 0x57 n'apparaît pas : c'est le problème des rappels. Deux correctifs :
   - un **adaptateur de niveau bidirectionnel** (type BSS138, ~2 €) sur SDA/SCL ; ou
   - ou dessouder les rappels de la carte et rappeler SDA/SCL à 5 V par 4,7 kΩ.
     Les tensions maximales admissibles sur SDA/SCL du MAX30102 ne sont pas liées à son
     Vdd, ce qui rend cette option légitime — **mais vérifiez la ligne « Absolute Maximum
     Ratings » de la datasheet Analog Devices avant de dessouder quoi que ce soit.**
     L'adaptateur de niveau est réversible, le fer à souder ne l'est pas : commencez par lui.

Ne mettez rien d'autre en route tant que le scanner ne voit pas les deux adresses.
C'est le seul point de la journée qui peut tout arrêter.

---

## 4. Protocole Arduino → Pi (série 115200)

Une ligne par événement. Pas de JSON sur l'AVR, pas de tampon, pas d'état.

```
P,<ir>                 # PPG brut, canal IR, 100 Hz — pas d'horodatage par échantillon
E,<raw>                # GSR moyenné, 10 Hz (échantillonné à 50, moyenné par 5)
T,<millis>,<n_ppg>     # ancre temporelle, 1 Hz : n_ppg = nb de lignes P de la seconde
I,<ma>                 # courant INA219, 1 Hz
```

Pas d'horodatage par échantillon : la cadence est fixe et connue, et `micros()` déborde
toutes les 71 minutes. La ligne `T` sert d'ancre et **permet à la passerelle de détecter
les pertes** — si `n_ppg` vaut 97 au lieu de 100, la qualité du signal descend d'autant.

Débit : 100 × ~8 o + 10 × ~6 o + ~20 o ≈ **0,9 ko/s**, soit 8 % de la capacité à
115200 baud. Très large.

**Pourquoi le PPG brut et pas les IBI ?** Le détecteur de battements des bibliothèques
Arduino pour MAX30102 est un simple seuil : il rate des battements et en invente sous
artefact de mouvement. `nk.ppg_findpeaks()` (méthode Elgendi) sur le serveur est d'un
autre niveau, et la VFC est votre indicateur le mieux pondéré. À 700 o/s, le brut ne
coûte rien. On met la science sur l'i5, pas sur un AVR à 16 MHz.

**Sudation à 10 Hz et non 50.** Une réponse électrodermale phasique monte en 1 à 3 s.
10 Hz est très au-dessus du nécessaire. On échantillonne bien à 50 Hz comme le dit le
dossier, mais on moyenne par 5 avant d'émettre : moins de bruit *et* moins de débit.

---

## 5. La passerelle Python sur le Pi

Un service systemd, ~150 lignes.

- Lit la série, accumule 1 seconde, construit le message `IngestMessage`.
- **Signe en HMAC-SHA256** avec la clé de l'appareil (`Appareil.cle_signature`).
- `POST /api/v1/ingest`. En cas d'échec : empile dans une `deque(maxlen=600)`.
- Au retour du réseau : vide par paquets de 60 messages, puis reprend le rythme normal.
- Publie un indicateur de qualité par capteur (`qualite.cardiaque`, `qualite.eda`) :
  proportion d'échantillons dans les bornes sur la dernière seconde.

C'est ce service qui rend le point de démo n°3 possible, et il est infiniment plus simple
à écrire en Python sur un Pi qu'en C sur 8 Ko de SRAM.

---

## 6. Extension du contrat `/ingest` — rétro-compatible

`app/schemas/ingest.py` accepte déjà `ibi_ms` et `eda_us`. On **ajoute deux champs
optionnels**, on ne casse rien, et `simulator/send_measures.py` continue de marcher.

```python
class IngestMessage(BaseModel):
    v: int = 1
    device_id: str
    ts: datetime
    seq: int = Field(ge=0)
    ibi_ms: list[int] = Field(default_factory=list)      # existant
    eda_us: list[float] = Field(default_factory=list)    # existant
    ppg_raw: list[int] = Field(default_factory=list)     # NOUVEAU — 100 Hz, canal IR
    ma: float | None = None                              # NOUVEAU — INA219
    qualite: Qualite
```

`Mesure.valeurs` est déjà une colonne JSON : aucune migration nécessaire pour le stockage.
Quand `ppg_raw` est présent, le serveur détecte les battements et **ignore** `ibi_ms`.
Quand il est absent (simulateur), il retombe sur `ibi_ms`. Les deux chemins restent vivants,
ce qui permet de démontrer sans capteur si le MAX30102 lâche.

---

## 7. Calcul des indicateurs

Service `app/services/indicateurs.py`, appelé sur fenêtre glissante de 30 s, rafraîchie
toutes les 5 s, écrivant dans la table `indicateurs` qui existe déjà.

### 7.1 Cardiaque

```python
sig, info = nk.ppg_process(ppg_raw, sampling_rate=100)
peaks = info["PPG_Peaks"]
rr = np.diff(peaks) * 10.0                       # en ms (100 Hz → 10 ms/échantillon)

rr = rr[(rr > 273) & (rr < 2000)]                # mêmes bornes que Pydantic
d  = np.abs(np.diff(rr))
rr = rr[1:][d < 0.2 * rr[:-1]]                   # rejet des sauts > 20 %

fc_moyenne = 60000.0 / rr.mean()
hrv_rmssd  = float(np.sqrt(np.mean(np.diff(rr) ** 2)))
```

RMSSD et SDNN se calculent à la main en trois lignes — inutile de passer par
`nk.hrv_time()`, qui veut des pics et non des RR.

### 7.2 Sudation

```python
sig, info = nk.eda_process(eda_us, sampling_rate=10, method_phasic="highpass")
eda_fond     = float(sig["EDA_Tonic"].mean())
eda_reponses = len(info["SCR_Peaks"]) * 60.0 / duree_s      # réponses par minute
```

`method_phasic="highpass"` — attention, le paramètre `method` pilote le *nettoyage*
et n'accepte que `neurokit` ou `biosppy` ; lui passer `"highpass"` lève une
`ValueError`. Vérifié sur NeuroKit2 0.2.13. Pas de dépendance supplémentaire. cvxEDA (`method="cvxeda"`,
nécessite `cvxopt`) est plus propre — à tenter jeudi seulement.

### 7.3 Fréquence respiratoire — dérivée du rythme cardiaque (EDR)

C'est l'indicateur qui porte tout l'argument énergétique. Il s'obtient sans capteur
respiratoire, par arythmie sinusale respiratoire.

```python
t    = np.cumsum(rr) / 1000.0
ti   = np.arange(t[0], t[-1], 0.25)              # ré-échantillonnage à 4 Hz
tach = np.interp(ti, t, rr)
tach = tach - tach.mean()

filt = nk.signal_filter(tach, sampling_rate=4, lowcut=0.1, highcut=0.4,
                        method="butterworth", order=3)
psd  = nk.signal_psd(filt, sampling_rate=4, method="welch")
f_dom = psd.loc[psd["Power"].idxmax(), "Frequency"]
frequence_respiratoire = float(f_dom * 60.0)     # cycles/min
```

**Contrainte :** il faut **au moins 60 s** de RR pour résoudre 0,1 Hz. C'est exactement
votre minute de mesure. On ne calcule donc la respiration qu'une fois par phase
(avant / après), jamais en fenêtre glissante de 30 s.

Bande 0,1–0,4 Hz = 6 à 24 cycles/min. La cohérence cardiaque vise 6/min, soit la borne
basse — c'est mesurable, et c'est la convergence vers 6 qui prouve l'exercice.

### 7.4 Visage — sur le Pi, dans Chromium

`@mediapipe/tasks-vision`, `FaceLandmarker` avec `outputFaceBlendshapes: true`,
entrée bridée à **320 × 240** et **10 fps** pour laisser le CPU au reste.

```
tension   = (browDownLeft + browDownRight + browInnerUp) / 3
           interpolé avec (mouthPressLeft + mouthPressRight) / 2
clignement = front montant de max(eyeBlinkLeft, eyeBlinkRight) > 0.5, compté sur 30 s
immobilite = 1 - variance normalisée de facialTransformationMatrix sur 30 s
```

Agrégat envoyé **une fois par seconde**. À 10 fps, la fréquence de clignement est la
moins fiable des trois — ce qui est cohérent avec le dossier, qui classe déjà la vidéo
comme le plus bruité des quatre signaux.

### 7.5 Voix — opensmile seul

```python
import opensmile
smile = opensmile.Smile(feature_set=opensmile.FeatureSet.eGeMAPSv02,
                        feature_level=opensmile.FeatureLevel.Functionals)
f = smile.process_signal(pcm, 16000).iloc[0]
```

**Le micro du C270 conditionne le choix des features.** Le jitter et le shimmer sont très
sensibles à la qualité du micro et à la distance ; sur une webcam à 60 cm, ils sont du
bruit. On les **exclut** de l'indice. On garde le sous-ensemble robuste :

| Feature eGeMAPSv02 | Ce que ça capte | Poids |
|---|---|---|
| `F0semitoneFrom27.5Hz_sma3nz_amean` | hauteur moyenne ↑ | 0,25 |
| `F0semitoneFrom27.5Hz_sma3nz_stddevNorm` | monotonie / instabilité | 0,15 |
| `loudness_sma3_amean` | intensité ↑ (meilleur indicateur en littérature) | 0,25 |
| `VoicedSegmentsPerSec` | débit de parole ↑ | 0,20 |
| `MeanUnvoicedSegmentLength` | proportion de silences ↑ (repli) | 0,15 |

eGeMAPS donne déjà le débit et les silences : **`praat-parselmouth` et `silero-vad`
deviennent inutiles**. Une seule bibliothèque au lieu de trois.

> Vérifier les noms exacts au premier lancement avec `smile.feature_names` — ils varient
> d'une version d'openSMILE à l'autre.

---

## 8. Indice de charge et moteur de règles

Chaque indicateur est ramené à un écart à l'historique de la personne :

```
z_i = clip((x_i - moyenne_perso_i) / ecart_type_perso_i, -3, +3)
```

`hrv_rmssd` est **inversé** (une VFC basse signe le stress).

| Indicateur | Poids | Justification |
|---|---|---|
| `hrv_rmssd` (inversé) | 0,30 | le mieux établi, non contrôlable |
| `eda_reponses` | 0,25 | non contrôlable volontairement |
| `voix` | 0,15 | se dégrade tôt |
| `eda_fond` | 0,10 | dérive lente |
| `fc_moyenne` | 0,10 | robuste mais peu spécifique |
| `visage` | 0,10 | le plus bruité |

```
indice = clip(30 + 20 * Σ(w_i · z_i), 0, 100)
```

Cet étalonnage reproduit le scénario du dossier : à sa normale, Mei sort à 30 ;
à +1,4 σ, elle sort à 58, en orange. Les seuils **40** (soit +0,5 σ) et **70** (+2,0 σ)
sont ceux du dossier.

**Signal manquant :** son poids est retiré et les autres sont renormalisés.
`confiance = Σ des poids disponibles`. C'est la mécanique que le dossier promet, et elle
est la même en mode dégradé (caméra coupée → 0,90) et en panne de capteur.

**Nouvel utilisateur :** moins de 10 séances → on compare à une baseline générique et
`confiance × 0,6`. À dire à l'écran, pas à cacher.

**Paliers.** Vert < 40 : journal vocal, playlist. Orange 40–70 : respiration, ancrage.
Rouge ≥ 70 : cohérence cardiaque prolongée + alerte. `unreliable` si confiance < 0,4
ou si plus de deux signaux sont suspects → aucun exercice, message de maintenance.

---

## 9. L'IA : ce qu'elle décide, et sur quel modèle

Le code fixe l'indice, le niveau et la **liste des exercices autorisés**. Le modèle
choisit *dans cette liste* et rédige. Rien d'autre.

Avec un i5-12400 et 16 Go, le choix est confortable :

| Usage | Modèle | Débit attendu | Consigne de ~70 tokens |
|---|---|---|---|
| Nominal | `llama3.2:3b` (Q4) | 8–12 tok/s | 6–9 s |
| Dégradé | `llama3.2:1b` (Q4) | 25–35 tok/s | 2–3 s |
| Panne | aucun — règles seules | — | instantané |

La chaîne de repli du dossier (« un modèle plus petit, puis les règles seules ») est donc
implémentée telle quelle, sans invention.

Contrainte de sortie par **JSON Schema natif d'Ollama** (`format=`), pas par vérification
a posteriori : le schéma Pydantic est passé au décodage.

```python
class Consigne(BaseModel):
    exercice_id: Literal["cc365", "carre", "478", "ancrage5432",
                         "playlist", "circadien", "sieste", "journal"]
    message: str = Field(max_length=280)
```

Si `exercice_id` n'est pas dans la liste autorisée par le palier, le serveur prend le
premier de la liste et note `source="rules"`. Table `decisions`, colonnes déjà présentes.

---

## 10. WebSocket — la brique qui débloque le front

`WS /api/v1/sessions/{id}/stream`. Le serveur pousse, le client ne renvoie qu'un ping.
Les sept types d'événements sont déjà définis dans `Frontend/src/api/types.ts`
(`StreamEvent`) : `frame`, `indicators`, `assessment`, `recommendation`, `mode`,
`progress`, `notice`. **Respecter ces noms au caractère près** — le front est déjà écrit
contre eux.

C'est la première chose à faire côté serveur : tant qu'elle manque, tout le travail
sur les indicateurs est invisible et indémontrable.

---

## 11. Les deux endpoints média manquants

```
POST /api/v1/sessions/{id}/face
  → { at, tension: 0..1, blinkRate: float, stillness: 0..1 }
  ← 202. Un appel par seconde. Aucune image, jamais.

POST /api/v1/sessions/{id}/audio
  multipart, WAV 16 kHz mono, ≤ 15 s
  ← { voiceIndex: 0..1, f0Mean, f0StdNorm, loudness, voicedPerSec, unvoicedMeanLen }
  Le fichier est traité en mémoire et n'est jamais écrit sur disque.
```

Le second doit écrire dans un `tempfile.SpooledTemporaryFile` ou un `io.BytesIO` — pas
dans `/tmp`. La promesse « aucun son brut conservé » doit être vraie dans le code, pas
seulement dans le dossier.

---

## 12. Le front sur 800 × 480 paysage

Chromium en kiosque, `--force-device-scale-factor=1` → 800 × 480 px CSS.
Ajouter un **quatrième breakpoint** dans `figma-calme/src/00-tokens.js` :

```js
{ key: 'cabine', label: 'Cabine 7"', w: 800, h: 480, cols: 8, gutter: 16, margin: 24 }
```

Ce n'est pas un pis-aller : la cabine et le tableau de bord du médecin sont deux produits
sur deux machines. Il est sain qu'ils aient deux grilles.

Budget vertical de l'écran `séance`, le plus contraint des cinq :

```
480 ─┬─  24  marge haute
     ├─ 260  cercle respiratoire      ← le héros, tout le reste s'efface
     ├─  36  compte à rebours
     ├─  56  consigne, 2 lignes max
     └─  24  marge basse                    total 400, il reste 80 de jeu
```

Contraintes tactiles : cibles ≥ 44 px, **aucun état `:hover`**, `user-select: none`,
et désactivation du menu contextuel au long-press.

Lancement du kiosque :

```bash
chromium-browser --kiosk --force-device-scale-factor=1 \
  --user-data-dir=/tmp/kiosk --noerrdialogs --disable-infobars \
  --unsafely-treat-insecure-origin-as-secure=http://<ip-serveur>:8000 \
  http://<ip-serveur>:8000
```

⚠️ **Sans ce dernier drapeau, `getUserMedia` est bloqué** (origine non sécurisée en HTTP
sur IP distante) : ni caméra, ni micro, et Chromium ne dira rien d'utile dans la console.

---

## 13. Correctifs du back existant

1. **`.env.example` pointe sur `127.0.0.1:15432`.** Dans un conteneur, `127.0.0.1` désigne
   le conteneur lui-même : la connexion échouera. Avec Coolify, PostgreSQL se déclare comme
   **ressource managée** et Coolify fournit un nom d'hôte interne sur son réseau Docker.
   `DATABASE_URL` doit utiliser ce nom, jamais `127.0.0.1`. Cf. §17.
2. **`requirements.txt` est un `pip freeze` complet.** `agent-detector`, `detect-installer`,
   `fastar`, `rignore`, `sentry-sdk` ne sont importés nulle part dans `app/`. À réduire aux
   dépendances directes : l'archive d'installation hors ligne doit être auditable.
3. **`/ingest` ne vérifie jamais la signature** alors que `Appareil.cle_signature` existe.
   Le dossier promet que « un message non signé est rejeté et journalisé ».
4. **`Astronaute` n'a que `nom`.** Le `CrewMember` du front attend `displayName`, `role`,
   `initials`, `joinedSol`. Migration Alembic à ajouter.
5. **`get_or_create_session()` prend le premier astronaute venu.** Acceptable aujourd'hui,
   à remplacer par une identification explicite avant vendredi.

### Dépendances à ajouter

```
neurokit2        # HRV, EDA, respiration
opensmile        # eGeMAPSv02
ollama           # client
```

**Pas de PyTorch.** Ni silero-vad, ni parselmouth : eGeMAPS couvre le débit et les silences.
Le surcoût d'installation est de ~120 Mo, pas de 1,2 Go.

---

## 14. Chemin critique du 23 septembre

Par pôle, en parallèle. L'étape 0 bloque tout le monde : elle passe en premier.

| # | Pôle | Tâche | Durée | Bloque |
|---|---|---|---|---|
| **0** | Embarqué | **Scanner I²C : voir 0x57 et 0x40** (§3) | 1 h | tout |
| 1 | Embarqué | Sketch Arduino, sortie série CSV (§4) | 1 h | 2 |
| 2 | Embarqué | Passerelle Python sur le Pi (§5) | 1 h 30 | — |
| 3 | Serveur | **WebSocket `/stream`** (§10) | 1 h | le front |
| 4 | Serveur | Indicateurs NeuroKit2 (§7.1–7.3) | 2 h | 5 |
| 5 | Serveur | Indice + moteur de règles (§8) | 1 h | 6 |
| 6 | IA | Ollama + JSON Schema (§9) | 1 h | — |
| 7 | IA | `POST /audio` + opensmile (§7.5, §11) | 1 h 30 | — |
| 8 | Client | Breakpoint cabine 800×480 (§12) | 2 h | — |
| 9 | Client | MediaPipe + `POST /face` (§7.4, §11) | 1 h 30 | — |
| 10 | Client | `VITE_USE_MOCK=false`, brancher le vrai transport | 30 min | — |

**Ordre de bascule du front :** faire 3 avant 4. Un WebSocket qui pousse des valeurs
fausses est démontrable ; des indicateurs justes sans WebSocket ne se voient pas.

---

## 15. Ce qu'on coupe si 18 h arrive

La bonne nouvelle : **la liste des coupes est exactement la chaîne de repli du dossier.**
Couper n'est donc pas un échec, c'est une démonstration du mode dégradé.

1. **Visage** → poids 0,10 retiré, `confiance` tombe à 0,90. Le front affiche déjà
   « confiance réduite ». Coût : zéro.
2. **Voix** → poids 0,15 retiré, confiance 0,75. Les deux capteurs biologiques portent tout,
   comme annoncé au §« scénario de crise ».
3. **Ollama** → `source="rules"`, consignes génériques pré-écrites. Le système garde
   sa fonction, il perd la personnalisation. C'est le discours du dossier, mot pour mot.
4. **Capteur GSR** → le générateur de mesures de test côté serveur prend le relais,
   comme prévu au §« ce qui peut mal tourner ».

Ce qu'on **ne coupe pas**, dans l'ordre : le PPG, la respiration avant/après, le WebSocket.
Sans ces trois-là, il n'y a plus de démonstration.

---

## 16. Deltas du dossier LaTeX

| Fichier | Ligne | Correction |
|---|---|---|
| `03-fabrication.tex` | 16 | `ESP32-WROOM` → `Arduino Mega ADK` |
| `03-fabrication.tex` | 19–20 | Supprimer `ESP32-CAM` et `INMP441` ; ajouter `Webcam USB Logitech C270 (micro intégré)` et `Adaptateur audio USB` |
| `03-fabrication.tex` | 16+ | Ajouter `Raspberry Pi (passerelle + écran tactile 7")` |
| `03-fabrication.tex` | 38 | Réécrire le §Câblage : I²C sur 20/21, GSR sur A0, **adaptation de niveau I²C**, plus d'I²S |
| `03-fabrication.tex` | 48 | « il résume sur une seconde » → **faux et coûteux** : il émet le PPG brut, la détection de battements se fait sur le serveur |
| `03-fabrication.tex` | 48+ | Le tampon de 10 min est sur le Pi, pas sur le microcontrôleur — et dire pourquoi (8 Ko de SRAM) |
| `03-fabrication.tex` | 67 | Ligne « Capteurs et ESP32 » → « Capteurs, Arduino et Pi ». Budget à remesurer à l'INA219 |
| `02-conception.tex` | 121 | Schéma TikZ : nœud `ESP32` → `Arduino Mega ADK` ; caméra et micro basculent du côté client ; ajouter le nœud `Raspberry Pi` en passerelle |
| `02-conception.tex` | §La vidéo | Ajouter : l'image est analysée **sur le poste** et n'est jamais transmise |
| `04-epreuve.tex` | §Données | Renforcer : la vidéo ne quitte pas le Pi — vérifiable, pas déclaratif |
| `06-annexe.tex` | 62 | « le firmware de l'ESP32 » → « le firmware Arduino et la passerelle Python » |

Un gain à ne pas rater au passage : la nomenclature **perd** deux composants (ESP32-CAM,
INMP441) et en gagne deux plus simples. Un jury lit ça comme une simplification assumée,
pas comme un repli.

---

## 17. Déploiement, réseau et Coolify

Le serveur est sur le **réseau local de l'école**, inaccessible depuis l'extérieur, et
**Coolify** y est installé comme plateforme d'hébergement.

### Répartition des ressources Coolify

| Ressource | Type Coolify | Note |
|---|---|---|
| PostgreSQL | ressource managée | Coolify fournit un hôte interne — ne pas le mettre dans le compose |
| API FastAPI | application (Dockerfile) | sert aussi le front en fichiers statiques |
| Ollama | service *one-click* | **volume persistant obligatoire** pour les modèles |

Le front reste servi par le FastAPI, comme le dossier l'annonce. Une brique mobile en
moins, et surtout **aucun CORS à configurer** : même origine pour l'API, le WebSocket
et les fichiers statiques.

### ⚠️ Ne mettez pas la boucle d'itération d'aujourd'hui derrière un build Docker

Un redéploiement Coolify prend 2 à 5 minutes. Un mercredi d'intégration à quatre, c'est
fatal. **Coolify est votre cible de déploiement, pas votre boucle de développement.**

- Journée : `uvicorn app.main:app --reload --host 0.0.0.0` directement sur le serveur.
- Soir : on déploie sur Coolify la version stable, celle qu'on démontre.

### ⚠️ Isolation des clients sur le réseau de l'école

Beaucoup de réseaux scolaires isolent les clients WiFi entre eux. Si le Pi est en WiFi et
le serveur en Ethernet, **ils peuvent tout simplement ne pas pouvoir se parler**, sans
message d'erreur explicite. Et vendredi matin, vous dépendez de l'IT de l'école.

**Apportez un switch ou un routeur de voyage.** Pi + serveur + un portable sur leur propre
sous-réseau, IP statique côté serveur, une ligne dans le `/etc/hosts` du Pi.
Coût : 15 €. Bénéfice : la démonstration ne dépend plus de personne.

Et c'est *exactement* le scénario : le vaisseau a son propre réseau, il ne demande rien à
la Terre. Un argument de soutenance, pas un contournement.

### TLS : n'en mettez pas

Sans accessibilité publique, pas de Let's Encrypt. Coolify accepte un certificat
auto-signé déposé dans `/data/coolify/proxy/certs`, mais Chromium en mode kiosque
affichera alors un écran d'avertissement bloquant tant que l'autorité n'est pas installée
dans le magasin du Pi.

**Pour 48 h : restez en HTTP et utilisez le drapeau Chromium du §12.** C'est une ligne de
commande contre une chaîne de certificats — et le drapeau ne peut pas échouer le vendredi
matin.

### Internet au déploiement, pas à l'exécution

Coolify tire ses images, et Ollama tire ses modèles, depuis le réseau. Ce n'est pas une
contradiction avec le discours « entièrement hors ligne » : c'est le même argument que la
compilation du front, qui a lieu **au sol, avant le départ**.

Mais il faut le prouver. **Tout tirer avant jeudi soir** — images, modèle 3B, modèle 1B de
repli. Puis, jeudi soir, **couper Internet et redémarrer toute la pile.** Si ça remonte,
vous avez un point de démonstration de plus ; si ça ne remonte pas, vous l'avez découvert
jeudi et non vendredi.

---

## Ce que ce document ne tranche pas

- **Le modèle exact de Raspberry Pi** n'est pas connu. MediaPipe à 10 fps en 320×240 passe
  sur un Pi 4 ; un Pi 5 est confortable. À vérifier en branchant.
- **Les poids et les seuils du §8** sont posés par convention. Le dossier promet de les
  réétalonner sur les mesures réelles — c'est à faire jeudi, avec les données collectées
  aujourd'hui, et à dire au jury.
- **L'identification de l'astronaute** reste à une seule personne de test. Suffisant pour
  vendredi, insuffisant pour la thèse « comparaison à l'historique personnel ».
