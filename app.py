# app.py - afficheur de prochains passages de bus (ESP32 + ST7796 480x320)
#
# Lance par main.py (l'amorceur) apres la mise a jour depuis GitHub.
# Le relais (relais/relais_bus.py) doit tourner sur le PC ou le NAS.
#
# Test depuis Thonny : creer un fichier vide "noupdate" sur la carte (sinon le
# demarrage ecrase tes modifications), puis ouvrir ce fichier et F5.

import gc
import time

from machine import Pin

import lcd
import wifi

try:
    import ntptime
except ImportError:
    ntptime = None

try:
    import urequests as rq
except ImportError:
    import requests as rq

# ---- a regler ---------------------------------------------------------
RELAIS = "http://192.168.1.160:8080/bus"   # IP de la machine qui fait tourner le relais
TITRE = "Hoche - St Honore"                # 26 caracteres max, sans accents
PERIODE = 15                               # secondes entre deux lectures du relais

# Plages d'allumage (heure de Paris) : jour (0 = lundi ... 6 = dimanche) -> [(debut, fin)]
# Hors de ces plages l'ecran est eteint et la carte ne contacte plus le relais.
FENETRES = {j: [((7, 30), (8, 15))] for j in range(5)}   # lundi a vendredi
FENETRES[5] = [((9, 0), (11, 0))]                          # samedi
FENETRES[6] = [((9, 0), (11, 0))]                          # dimanche
PIN_BOUTON = 0                             # bouton BOOT de la carte (appui = niveau bas)
DUREE_BOUTON = 15 * 60                     # secondes d'allumage apres un appui

# Correspondance identifiant PRIM -> numero affiche ("Bus 43").
# Un code absent de la table s'affiche sans etiquette.
LIGNES = {"C01086": "43"}
# -----------------------------------------------------------------------

NB_LIGNES = 4
LARGEUR = 480
H_ENTETE = 32
H_LIGNE = 66                               # 32 (entete) + 4 x 66 + 24 (pied) = 320 pixels
Y_HORLOGE = 300                            # pied de page : de 296 a 320
X_DROITE = 232                             # colonne etiquette + destination
X_HORLOGE = 296                            # "15/11 16:27" : 11 car. x 16 px = 176 px
X_VOYANT = 462

_msg = None                                # message plein ecran actuellement affiche
_quai = [None] * NB_LIGNES                 # mode d'affichage precedent de chaque ligne

_heure_ok = False                          # l'horloge a-t-elle ete reglee par NTP ?
_synchro_ms = None
_horloge_txt = ""
_temp_txt = None                           # derniere temperature affichee
_valide = False                            # la mise a jour a-t-elle ete validee ?
_allume = False                            # l'ecran est-il allume ?
_force = None                              # ticks_ms de fin d'allumage force par le bouton
_dernier_ok = None                         # ticks_ms de la derniere lecture reussie
_age_relais = 0


# ---------------------------------------------------------------- heure

def _dernier_dimanche(an, mois):
    """Jour du mois du dernier dimanche (mars et octobre ont 31 jours)."""
    for j in range(31, 24, -1):
        if time.localtime(time.mktime((an, mois, j, 12, 0, 0, 0, 0)))[6] == 6:
            return j


def heure_locale():
    """Heure de Paris (heure d'ete incluse) a partir de l'horloge UTC de la carte.
    Heure d'ete : du dernier dimanche de mars au dernier dimanche d'octobre,
    changements a 01:00 UTC."""
    t = time.time()
    an = time.localtime(t)[0]
    debut = time.mktime((an, 3, _dernier_dimanche(an, 3), 1, 0, 0, 0, 0))
    fin = time.mktime((an, 10, _dernier_dimanche(an, 10), 1, 0, 0, 0, 0))
    return time.localtime(t + (7200 if debut <= t < fin else 3600))


def maj_heure():
    """Regle l'horloge par NTP au demarrage, puis toutes les 6 heures."""
    global _heure_ok, _synchro_ms
    if ntptime is None:
        return
    if _heure_ok and time.ticks_diff(time.ticks_ms(), _synchro_ms) < 6 * 3600 * 1000:
        return
    try:
        ntptime.timeout = 3
    except Exception:
        pass
    try:
        ntptime.settime()                  # regle l'horloge interne, en UTC
        _heure_ok = True
        _synchro_ms = time.ticks_ms()
    except Exception as e:
        print("NTP:", type(e).__name__, e)


def horloge():
    """Affiche 'jj/mm hh:mm' en haut a droite, seulement quand le texte change."""
    global _horloge_txt
    if _heure_ok:
        t = heure_locale()
        txt = "%02d/%02d %02d:%02d" % (t[2], t[1], t[3], t[4])
    else:
        txt = "--/-- --:--"
    if txt != _horloge_txt:
        lcd.text(txt, X_HORLOGE, Y_HORLOGE, lcd.WHITE, lcd.BLACK, 2)
        _horloge_txt = txt


# -------------------------------------------------------------- affichage

def temperature(t):
    """Temperature en bas a gauche (t en degres C, ou None si inconnue)."""
    global _temp_txt
    txt = "--" if t is None else "%d" % round(t)
    if txt == _temp_txt:
        return
    lcd.fill_rect(0, 296, 150, 24, lcd.BLACK)
    lcd.text(txt, 8, Y_HORLOGE, lcd.WHITE, lcd.BLACK, 2)
    x = 8 + len(txt) * 16 + 2
    # symbole degre dessine a la main : la police 8x8 n'en a pas
    for dx, dy, w, h in ((2, 0, 4, 2), (0, 2, 2, 4), (6, 2, 2, 4), (2, 6, 4, 2)):
        lcd.fill_rect(x + dx, Y_HORLOGE + dy, w, h, lcd.WHITE)
    lcd.text("C", x + 12, Y_HORLOGE, lcd.WHITE, lcd.BLACK, 2)
    _temp_txt = txt


def efface_corps():
    lcd.fill_rect(0, H_ENTETE, LARGEUR, NB_LIGNES * H_LIGNE, lcd.BLACK)
    for i in range(NB_LIGNES):
        _quai[i] = None


def message(txt, couleur):
    """Affiche un message au centre, sans le redessiner s'il y est deja."""
    global _msg
    if _msg == txt:
        return
    efface_corps()
    lcd.text(txt, 8, 140, couleur, lcd.BLACK, 3)
    _msg = txt


def ligne(i, p):
    """Dessine le passage p sur la ligne i (ou efface la ligne si p est None)."""
    y = H_ENTETE + i * H_LIGNE
    if p is None:
        lcd.fill_rect(0, y, LARGEUR, H_LIGNE, lcd.BLACK)
        _quai[i] = None
        return

    m = min(p["m"], 99)
    quai = (m == 0)
    # vert = temps reel, gris = horaire theorique
    couleur = lcd.GREEN if p["r"] else lcd.GREY

    # Les deux affichages n'ont pas la meme taille : on efface la cellule
    # quand on passe de l'un a l'autre, pour ne laisser aucun residu.
    if _quai[i] != quai:
        lcd.fill_rect(0, y, X_DROITE, H_LIGNE, lcd.BLACK)
        _quai[i] = quai

    if quai:
        lcd.text("A L'ARRET", 8, y + 21, couleur, lcd.BLACK, 3)
    else:
        lcd.text("%2d min" % m, 8, y + 17, couleur, lcd.BLACK, 4)

    # Etiquette "Bus 43" seulement si le code de la ligne est dans LIGNES
    num = LIGNES.get(p["l"].strip(":").split(":")[-1])
    etiquette = ("Bus " + num) if num else ""
    lcd.text("%-8s" % etiquette, X_DROITE, y + 4, lcd.WHITE, lcd.BLACK, 3)
    lcd.text("%-15s" % p["d"][:15], X_DROITE, y + 36, lcd.YELLOW, lcd.BLACK, 2)


def voyant(dernier_ok, age_relais):
    """Petit carre en haut a droite : fraicheur de la donnee affichee.
    vert < 90 s, orange < 180 s, rouge au-dela (ou jamais de donnee)."""
    if dernier_ok is None:
        c = lcd.RED
    else:
        s = time.ticks_diff(time.ticks_ms(), dernier_ok) // 1000 + age_relais
        c = lcd.GREEN if s < 90 else (lcd.ORANGE if s < 180 else lcd.RED)
    lcd.fill_rect(X_VOYANT, 8, 16, 16, c)


def age_donnee(dernier_ok, age_relais):
    if dernier_ok is None:
        return None
    return time.ticks_diff(time.ticks_ms(), dernier_ok) // 1000 + age_relais


# ---------------------------------------------------------- allumage / veille

def doit_etre_allume():
    """Plage horaire en cours, ou allumage force par le bouton."""
    global _force
    if _force is not None:
        if time.ticks_diff(_force, time.ticks_ms()) > 0:
            return True
        _force = None                      # expire : evite le tour de ticks_ms
    if not _heure_ok:
        return True                        # heure inconnue : mieux vaut allume qu'eteint
    t = heure_locale()
    minute = t[3] * 60 + t[4]
    for (h1, m1), (h2, m2) in FENETRES.get(t[6], ()):
        if h1 * 60 + m1 <= minute < h2 * 60 + m2:
            return True
    return False


def ecran_on():
    global _allume, _msg, _horloge_txt, _temp_txt, _dernier_ok
    lcd.init(landscape=True, bl=False)
    lcd.fill(lcd.BLACK)
    _msg = None
    _horloge_txt = ""
    _temp_txt = None
    for i in range(NB_LIGNES):
        _quai[i] = None
    lcd.text(TITRE[:26], 8, 8, lcd.WHITE, lcd.BLACK, 2)
    horloge()
    voyant(_dernier_ok, _age_relais)
    temperature(None)
    message("Chargement...", lcd.GREY)
    lcd.backlight(True)
    _allume = True


def ecran_off():
    global _allume
    lcd.sleep()
    _allume = False



# ------------------------------------------------------------------ reseau

def lire():
    try:
        r = rq.get(RELAIS, timeout=8)
    except TypeError:                      # ancien urequests : pas de timeout
        r = rq.get(RELAIS)
    try:
        if r.status_code != 200:
            raise OSError("HTTP %d" % r.status_code)
        return r.json()
    finally:
        r.close()


def cycle():
    """Une lecture du relais et la mise a jour de l'ecran."""
    global _msg, _dernier_ok, _age_relais
    try:
        if not wifi.ensure():
            raise OSError("wifi indisponible")

        d = lire()
        passages = d.get("p") or []
        _dernier_ok = time.ticks_ms()
        _age_relais = d.get("age") or 0
        temperature(d.get("temp"))

        if d.get("err") and not passages:
            message("Relais: erreur PRIM", lcd.ORANGE)
        elif not passages:
            message("Aucun passage", lcd.GREY)
        else:
            if _msg is not None:           # sortie d'un ecran de message
                efface_corps()
                _msg = None
            for i in range(NB_LIGNES):
                ligne(i, passages[i] if i < len(passages) else None)

    except Exception as e:
        print("Erreur:", type(e).__name__, e)
        s = age_donnee(_dernier_ok, _age_relais)
        if s is None:
            message("Relais injoignable", lcd.RED)
        elif s > 300:                      # donnee trop vieille : ne plus l'afficher
            message("Donnees perimees", lcd.RED)
    voyant(_dernier_ok, _age_relais)
    gc.collect()


def valider_maj():
    """La mise a jour est jugee bonne apres 30 s de fonctionnement sans plantage."""
    global _valide
    _valide = True
    try:
        import updater
        updater.valide()
    except ImportError:
        pass                               # lance a la main depuis Thonny


def main():
    global _force, _valide

    bouton = Pin(PIN_BOUTON, Pin.IN, Pin.PULL_UP)
    appuye = False
    ecran_on()                             # au demarrage : allume le temps de connaitre l'heure
    try:
        wifi.connect()
    except Exception as e:
        print("wifi.connect:", e)

    debut = time.ticks_ms()
    prochaine_lecture = debut
    derniere_seconde = debut
    ntp_essai = debut

    while True:
        try:
            now = time.ticks_ms()

            # bouton : un appui allume 15 min (un nouvel appui relance le compteur)
            v = bouton.value() == 0
            if v and not appuye:
                _force = time.ticks_add(now, DUREE_BOUTON * 1000)
                print("Bouton : allume %d min" % (DUREE_BOUTON // 60))
            appuye = v

            if time.ticks_diff(now, derniere_seconde) >= 1000:
                derniere_seconde = now
                if (not _heure_ok and time.ticks_diff(now, ntp_essai) >= 0) or \
                        (_heure_ok and time.ticks_diff(now, _synchro_ms) >= 6 * 3600 * 1000):
                    ntp_essai = time.ticks_add(now, 30000)   # au plus un essai / 30 s
                    if wifi.ensure():
                        maj_heure()
                if not _valide and time.ticks_diff(now, debut) > 30000:
                    valider_maj()
                if _allume:
                    horloge()
                    voyant(_dernier_ok, _age_relais)

            veut = doit_etre_allume()
            if veut and not _allume:
                ecran_on()
                prochaine_lecture = now
            elif _allume and not veut:
                ecran_off()

            if _allume and time.ticks_diff(now, prochaine_lecture) >= 0:
                cycle()
                prochaine_lecture = time.ticks_add(time.ticks_ms(), PERIODE * 1000)
        except Exception as e:
            print("Boucle:", type(e).__name__, e)

        time.sleep_ms(100)


main()
