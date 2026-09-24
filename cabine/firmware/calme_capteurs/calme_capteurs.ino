// calme_capteurs.ino - firmware d'acquisition de la cabine C.A.L.M.E.
//
// Echantillonne a 100 Hz et ecrit le brut sur le port serie, sans rien
// decider ni rien resumer : la detection des battements a lieu sur le serveur
// (app/services/cardiaque.py attend un PPG a 100 Hz). Une ligne par
// echantillon, lue par cabine/passerelle.py sur le Raspberry Pi :
//
//   D,<ir>,<gsr>,-1                ex. D,118532,431,-1
//   (le dernier champ, courant, reste a -1 : l'INA219 n'est pas monte)
//   #...                           message d'etat, simplement journalise
//
// Commandes descendantes, une par ligne, envoyees par la passerelle :
//   L,r,v,b    couleur du bandeau LED
//   R,e,c      relais : e = ecran, c = camera (1 = alimente, 0 = coupe)
//
// Carte : Arduino Mega ADK. Bibliotheques : SparkFun MAX3010x, Adafruit
// NeoPixel. Cablage : voir le tutoriel, partie Arduino.

#include <Wire.h>
#include "MAX30105.h"          // SparkFun MAX3010x, compatible MAX30102
#include <Adafruit_NeoPixel.h>

const uint8_t BROCHE_GSR = A0;
const uint8_t BROCHE_LED = 6;
const uint8_t BROCHE_RELAIS_ECRAN = 7;
const uint8_t BROCHE_RELAIS_CAMERA = 8;
const uint16_t NB_LED = 60;
const unsigned long PERIODE_US = 10000UL;   // 100 Hz

// Selon le module relais, le contact se ferme sur HIGH ou sur LOW.
const uint8_t RELAIS_ACTIF = HIGH;

MAX30105 capteurCardiaque;
Adafruit_NeoPixel bandeau(NB_LED, BROCHE_LED, NEO_GRB + NEO_KHZ800);

bool cardiaqueOk = false;
unsigned long prochain = 0;
char commande[33];
uint8_t longueur = 0;

void couleur(uint8_t r, uint8_t v, uint8_t b) {
  for (uint16_t i = 0; i < NB_LED; i++) bandeau.setPixelColor(i, bandeau.Color(r, v, b));
  bandeau.show();
}

void relais(uint8_t broche, bool alimente) {
  digitalWrite(broche, alimente ? RELAIS_ACTIF : !RELAIS_ACTIF);
}

void traiterCommande(const char *c) {
  int a, b, d;
  if (sscanf(c, "L,%d,%d,%d", &a, &b, &d) == 3) {
    couleur(constrain(a, 0, 255), constrain(b, 0, 255), constrain(d, 0, 255));
  } else if (sscanf(c, "R,%d,%d", &a, &b) == 2) {
    relais(BROCHE_RELAIS_ECRAN, a == 1);
    relais(BROCHE_RELAIS_CAMERA, b == 1);
  }
}

void lireCommandes() {
  // Non bloquant : l'echantillonnage passe toujours avant les commandes.
  while (Serial.available()) {
    char ch = Serial.read();
    if (ch == '\n') {
      commande[longueur] = '\0';
      traiterCommande(commande);
      longueur = 0;
    } else if (ch != '\r' && longueur < sizeof(commande) - 1) {
      commande[longueur++] = ch;
    }
  }
}

// Liste les adresses qui repondent sur le bus : le diagnostic le plus utile
// quand un capteur manque (fil debranche, adaptateur de niveau sans courant).
void scannerI2C() {
  Serial.print("#I2C");
  uint8_t trouves = 0;
  for (uint8_t adresse = 1; adresse < 127; adresse++) {
    Wire.beginTransmission(adresse);
    if (Wire.endTransmission() == 0) {
      Serial.print(" 0x");
      if (adresse < 16) Serial.print('0');
      Serial.print(adresse, HEX);
      trouves++;
    }
  }
  Serial.println(trouves ? "" : " aucun peripherique (attendu : 0x57 MAX30102)");
}

void setup() {
  Serial.begin(115200);
  Serial.println("#BOOT calme_capteurs");
  Wire.begin();
  // Sans delai maximal, un bus I2C bloque (SDA tenue a la masse par un fil
  // ou un adaptateur de niveau non alimente) fige Wire pour toujours : la
  // carte ne dit alors plus rien. Avec lui, elle signale et continue.
  Wire.setWireTimeout(3000, true);
  scannerI2C();

  pinMode(BROCHE_RELAIS_ECRAN, OUTPUT);
  pinMode(BROCHE_RELAIS_CAMERA, OUTPUT);
  relais(BROCHE_RELAIS_ECRAN, true);
  relais(BROCHE_RELAIS_CAMERA, true);

  bandeau.begin();
  bandeau.setBrightness(80);
  couleur(10, 20, 40);

  cardiaqueOk = capteurCardiaque.begin(Wire, I2C_SPEED_FAST);
  if (cardiaqueOk) {
    // LED 0x1F, moyenne de 4, mode rouge + IR, 400 ech/s, 411 us, plage 4096 :
    // 400 echantillons par seconde moyennes par 4 = les 100 Hz du serveur.
    capteurCardiaque.setup(0x1F, 4, 2, 400, 411, 4096);
  } else {
    Serial.println("#ERR MAX30102 absent");
  }
  Serial.println("#OK calme_capteurs pret");

  prochain = micros();
}

void loop() {
  lireCommandes();

  if ((long)(micros() - prochain) < 0) return;
  prochain += PERIODE_US;

  uint32_t ir = cardiaqueOk ? capteurCardiaque.getIR() : 0;
  int gsr = analogRead(BROCHE_GSR);

  Serial.print("D,");
  Serial.print(ir);
  Serial.print(',');
  Serial.print(gsr);
  Serial.print(',');
  Serial.println("-1");
}
