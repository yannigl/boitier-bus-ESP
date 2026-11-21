# updater.py - met a jour les fichiers de la carte depuis GitHub, au demarrage.
#
# Le depot contient esp32/manifest.json : {"files": {"app.py": "<sha256>", ...}}
# Pour chaque fichier liste dont l'empreinte locale differe :
#   1. tout est telecharge dans des fichiers .new et verifie (rien n'est touche si ca echoue)
#   2. puis chaque .new remplace l'original, qui est garde en .bak
# main.py, updater.py, boot.py et reglages.py ne sont jamais mis a jour de cette facon.

import os
import binascii

try:
    import hashlib
except ImportError:
    import uhashlib as hashlib

try:
    import urequests as rq
except ImportError:
    import requests as rq

try:
    from reglages import UPDATE_URL
except ImportError:
    UPDATE_URL = None

PROTEGES = ("main.py", "updater.py", "boot.py", "reglages.py")
REFUS = "refuse.txt"        # empreintes des versions qui ont plante : jamais reinstallees
MAX_OCTETS = 60000


def _hash(data):
    h = hashlib.sha256(data)
    return binascii.hexlify(h.digest()).decode()


def _hash_fichier(nom):
    try:
        h = hashlib.sha256()
        with open(nom, "rb") as f:
            while True:
                bloc = f.read(512)
                if not bloc:
                    break
                h.update(bloc)
        return binascii.hexlify(h.digest()).decode()
    except OSError:
        return None


def _existe(nom):
    try:
        os.stat(nom)
        return True
    except OSError:
        return False


def _supprime(nom):
    try:
        os.remove(nom)
    except OSError:
        pass


def _refuses():
    try:
        with open(REFUS) as f:
            return set(l.strip() for l in f if l.strip())
    except OSError:
        return set()


def _get(base, chemin):
    r = rq.get(base + chemin)
    try:
        if r.status_code != 200:
            raise OSError("HTTP %d pour %s" % (r.status_code, chemin))
        data = r.content
    finally:
        r.close()
    if len(data) > MAX_OCTETS:
        raise OSError("fichier trop gros : " + chemin)
    return data


def sync():
    """Retourne la liste des fichiers mis a jour ([] si rien a faire)."""
    if _existe("noupdate"):
        print("maj : suspendue (fichier 'noupdate')")
        return []
    if not UPDATE_URL:
        print("maj : UPDATE_URL absent de reglages.py")
        return []

    import json
    base = UPDATE_URL if UPDATE_URL.endswith("/") else UPDATE_URL + "/"
    manifeste = json.loads(_get(base, "manifest.json"))["files"]
    refus = _refuses()

    a_faire = []
    try:
        # Phase 1 : tout telecharger et verifier. En cas d'echec, rien n'a change.
        for nom, attendu in manifeste.items():
            if "/" in nom or nom.startswith(".") or nom in PROTEGES:
                continue
            if _hash_fichier(nom) == attendu:
                continue
            if attendu in refus:
                print("maj : %s ignore (version deja refusee)" % nom)
                continue
            data = _get(base, nom)
            if _hash(data) != attendu:
                raise OSError("empreinte incorrecte : " + nom)
            a_faire.append(nom)
            with open(nom + ".new", "wb") as f:
                f.write(data)
            if _hash_fichier(nom + ".new") != attendu:
                raise OSError("ecriture incorrecte : " + nom)
    except Exception:
        for nom in a_faire:
            _supprime(nom + ".new")
        raise

    # Phase 2 : mise en place (l'ancienne version reste en .bak)
    for nom in a_faire:
        _supprime(nom + ".bak")
        if _existe(nom):
            os.rename(nom, nom + ".bak")
        os.rename(nom + ".new", nom)
        print("maj : %s mis a jour" % nom)
    return a_faire


def rollback():
    """Remet les .bak en place et memorise les versions fautives.
    Retourne True si quelque chose a ete restaure."""
    restaure = False
    for nom in os.listdir():
        if not nom.endswith(".bak"):
            continue
        cible = nom[:-4]
        mauvais = _hash_fichier(cible)
        if mauvais:
            with open(REFUS, "a") as f:
                f.write(mauvais + "\n")
        _supprime(cible)
        os.rename(nom, cible)
        restaure = True
    return restaure


def valide():
    """A appeler quand l'appli a fonctionne : les sauvegardes ne servent plus."""
    for nom in os.listdir():
        if nom.endswith(".bak"):
            _supprime(nom)
