#!/bin/sh
# Installe la cabine sur un Raspberry Pi (teste pour un Pi 3, Raspberry Pi OS
# 64 bits avec bureau) : relais Caddy, kiosque Chromium, passerelle capteurs.
#
#   sh installer-pi.sh 10.61.8.36
#
# A lancer en tant qu'utilisateur de la session graphique (pas en root), dans
# le dossier cabine/ copie sur le Pi. Relancable sans risque : chaque etape
# ecrase sa propre configuration et rien d'autre.
set -eu

IP_TOUR="${1:?usage : sh installer-pi.sh <ip-de-la-tour>}"
PORT_API="${PORT_API:-8001}"
PORT_FRONT="${PORT_FRONT:-8081}"
ICI="$(cd "$(dirname "$0")" && pwd)"
UTILISATEUR="$(id -un)"

echo "== 1/5 paquets"
sudo apt-get update -q
sudo apt-get install -y -q caddy python3-serial python3-httpx v4l-utils alsa-utils
if apt-cache show chromium >/dev/null 2>&1; then
    sudo apt-get install -y -q chromium
fi
NAVIGATEUR="$(command -v chromium || command -v chromium-browser)"

echo "== 2/5 droits et ecran"
# dialout : le port serie de l'Arduino ; video/audio : webcam et son.
sudo usermod -aG dialout,video,audio "$UTILISATEUR"
sudo raspi-config nonint do_blanking 1 || true          # pas de mise en veille
sudo raspi-config nonint do_boot_behaviour B4 || true   # session graphique automatique

echo "== 3/5 relais Caddy (http://localhost -> tour $IP_TOUR)"
# Le navigateur n'autorise camera et micro que sur une page sure : ouvrir
# l'application en http://localhost, servie par ce relais, au lieu de
# http://<ip-de-la-tour>, suffit a le satisfaire.
sudo tee /etc/caddy/Caddyfile >/dev/null <<EOF
# Genere par cabine/installer-pi.sh - relais de la cabine C.A.L.M.E.
:80 {
	handle /api/* {
		reverse_proxy $IP_TOUR:$PORT_API
	}
	handle {
		reverse_proxy $IP_TOUR:$PORT_FRONT
	}
}
EOF
sudo systemctl enable caddy >/dev/null
sudo systemctl restart caddy

echo "== 4/5 kiosque ($NAVIGATEUR)"
mkdir -p "$HOME/.config/labwc"
cat > "$HOME/.config/labwc/autostart" <<EOF
# Genere par cabine/installer-pi.sh - l'application en plein ecran au demarrage
$NAVIGATEUR --kiosk http://localhost --noerrdialogs --disable-infobars --no-first-run --password-store=basic --autoplay-policy=no-user-gesture-required --use-fake-ui-for-media-stream --overscroll-history-navigation=0 --disable-pinch --renderer-process-limit=2 --check-for-update-interval=31536000 &
EOF
# Session X11 (anciennes images) : meme commande, autre fichier.
mkdir -p "$HOME/.config/lxsession/LXDE-pi"
printf '@%s --kiosk http://localhost --noerrdialogs --disable-infobars --no-first-run --password-store=basic --autoplay-policy=no-user-gesture-required --use-fake-ui-for-media-stream --overscroll-history-navigation=0 --disable-pinch --renderer-process-limit=2\n' \
    "$NAVIGATEUR" > "$HOME/.config/lxsession/LXDE-pi/autostart"

echo "== 5/5 passerelle capteurs"
sudo install -d -o "$UTILISATEUR" /opt/calme
sudo install -m 755 -o "$UTILISATEUR" "$ICI/passerelle.py" /opt/calme/passerelle.py
sudo install -d /etc/calme
if [ ! -f /etc/calme/passerelle.env ]; then
    PORT_SERIE="$(ls /dev/serial/by-id/* 2>/dev/null | head -n 1 || true)"
    sudo tee /etc/calme/passerelle.env >/dev/null <<EOF
CALME_PORT_SERIE=${PORT_SERIE:-/dev/ttyACM0}
CALME_URL_INGEST=http://$IP_TOUR:$PORT_API/api/v1/ingest
CALME_DEVICE_ID=cabine-01
CALME_CLE=cle-demo-cabine-01
CALME_CALIB_GSR=512
EOF
fi
sed "s/^User=.*/User=$UTILISATEUR/" "$ICI/calme-passerelle.service" \
    | sudo tee /etc/systemd/system/calme-passerelle.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now calme-passerelle

echo
echo "== verifications"
curl -s -m 5 "http://localhost/api/v1/health" && echo " <- relais vers l'API"
curl -s -m 5 -o /dev/null -w "front via le relais : HTTP %{http_code}\n" http://localhost/
systemctl is-active calme-passerelle | sed 's/^/passerelle : /'
echo
echo "Termine. Redemarrez le Pi (sudo reboot) : l'application s'ouvrira en plein ecran."
