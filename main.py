# main.py - amorce de la carte. A ne modifier que depuis Thonny :
# ce fichier n'est JAMAIS mis a jour depuis GitHub (c'est ce qui rend la mise a jour sure).
#
#   1. connecte le WiFi
#   2. recupere les mises a jour (updater.py) et redemarre si quelque chose a change
#   3. lance l'appli (app.py) ; si elle plante au demarrage, remet la version precedente
#
# Pour suspendre les mises a jour pendant le developpement : creer un fichier vide "noupdate".

import sys
import time
import machine


def maj():
    try:
        import wifi
        import updater
        if wifi.connect():
            if updater.sync():
                print("maj : redemarrage")
                time.sleep(1)
                machine.reset()
        else:
            print("maj : pas de wifi, on lance la version installee")
    except Exception as e:
        print("maj :", type(e).__name__, e)


maj()

try:
    import app
except Exception as e:
    sys.print_exception(e)
    try:
        import updater
        restaure = updater.rollback()
    except Exception:
        restaure = False
    print("appli en erreur, version precedente restauree :", restaure)
    time.sleep(1 if restaure else 30)       # 30 s : evite une boucle de redemarrage rapide
    machine.reset()
