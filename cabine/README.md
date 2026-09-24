# Cabine : ce qui tourne hors de la tour

| Fichier | Où | Rôle |
|---|---|---|
| `firmware/calme_capteurs/calme_capteurs.ino` | Arduino Mega ADK | Lit les capteurs à 100 Hz, écrit `D,ir,gsr,mA` sur le port série |
| `passerelle.py` | Raspberry Pi | Lit le port série, signe, poste sur `/api/v1/ingest`, tamponne 10 min hors ligne |
| `calme-passerelle.service` | Raspberry Pi | Lance la passerelle au démarrage et la relance si elle s'arrête |
| `installer-pi.sh` | Raspberry Pi | Installe tout : relais Caddy, kiosque Chromium, passerelle |

## Installer le Pi

```bash
# depuis ce dossier, sur votre ordinateur
scp -r ../cabine calme@<ip-du-pi>:~/
ssh calme@<ip-du-pi> 'cd ~/cabine && sh installer-pi.sh 10.61.8.36'
ssh calme@<ip-du-pi> sudo reboot
```

Le script est relançable. Il ne touche pas à `/etc/calme/passerelle.env` s'il existe
déjà (le port série et l'étalonnage GSR s'y règlent à la main).

## Vérifier

```bash
journalctl -u calme-passerelle -f      # sur le Pi : « port serie ouvert », aucun « refuse »
curl http://localhost/api/v1/health    # sur le Pi : {"api":"ok","base":"ok"}
```

Les tests de la passerelle (`tests/test_passerelle.py`) passent ses messages par le vrai
schéma et la vraie vérification de signature du serveur.
