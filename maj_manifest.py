#!/usr/bin/env python3
"""Regenere esp32/manifest.json : empreintes SHA-256 des fichiers mis a jour par la carte.

A lancer avant chaque commit qui touche au dossier esp32/ :
    python tools/maj_manifest.py

Les fins de ligne sont normalisees (CRLF -> LF) avant le calcul : c'est ce que Git
publie, donc l'empreinte correspond a ce que la carte telechargera, meme sous Windows.
"""

import hashlib
import json
import pathlib

ESP = pathlib.Path(__file__).resolve().parent / "esp32"
NON_GERES = {"main.py", "updater.py", "boot.py", "reglages.py", "reglages.example.py"}

fichiers = {}
for p in sorted(ESP.glob("*.py")):
    if p.name in NON_GERES:
        continue
    donnees = p.read_bytes().replace(b"\r\n", b"\n")
    fichiers[p.name] = hashlib.sha256(donnees).hexdigest()

sortie = ESP / "manifest.json"
sortie.write_text(json.dumps({"files": fichiers}, indent=2) + "\n", encoding="utf-8", newline="\n")

print("manifest.json :", len(fichiers), "fichier(s)")
for nom, h in fichiers.items():
    print("  %-12s %s" % (nom, h[:12]))
