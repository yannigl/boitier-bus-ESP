# wifi.py - connexion WiFi.
# Les identifiants sont lus dans reglages.py, qui reste sur la carte et n'est jamais envoye sur GitHub.

import network
import time

try:
    from reglages import SSID, MDP
except ImportError:
    SSID = MDP = None

_w = network.WLAN(network.STA_IF)


def connect(timeout=20):
    if _w.isconnected():
        return True
    if not SSID:
        print("wifi : SSID absent de reglages.py")
        return False
    _w.active(True)
    try:
        _w.config(reconnects=5)
    except Exception:
        pass
    _w.connect(SSID, MDP)
    t0 = time.ticks_ms()
    while not _w.isconnected():
        if time.ticks_diff(time.ticks_ms(), t0) > timeout * 1000:
            return False
        time.sleep_ms(300)
    return True


def ensure():
    """A appeler avant chaque requete."""
    if _w.isconnected():
        return True
    try:
        _w.disconnect()
    except OSError:
        pass                # interface pas encore demarree : rien a deconnecter
    _w.active(False)
    time.sleep(1)
    return connect()


def ip():
    return _w.ifconfig()[0] if _w.isconnected() else None
