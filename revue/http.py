"""Petites fonctions HTTP (bibliothèque standard uniquement), avec nouvelles tentatives."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

AGENT = "HebdoAero/1.0 (revue hebdomadaire automatisee)"
CODES_A_RETENTER = {408, 425, 429, 500, 502, 503, 504, 529}


class ErreurHTTP(RuntimeError):
    def __init__(self, code: int, message: str, corps: str = ""):
        super().__init__(f"HTTP {code} : {message} {corps[:600]}")
        self.code = code
        self.corps = corps


def requete(url: str, *, methode: str = "GET", donnees: bytes | None = None,
            entetes: dict | None = None, delai: float = 60, essais: int = 4) -> tuple[int, dict, bytes]:
    entetes = {"User-Agent": AGENT, **(entetes or {})}
    attente = 2.0
    for essai in range(1, essais + 1):
        req = urllib.request.Request(url, data=donnees, headers=entetes, method=methode)
        try:
            with urllib.request.urlopen(req, timeout=delai) as rep:
                return rep.status, dict(rep.headers), rep.read()
        except urllib.error.HTTPError as e:
            corps = e.read().decode("utf-8", "replace")
            if e.code in CODES_A_RETENTER and essai < essais:
                pause = float(e.headers.get("retry-after") or attente)
                time.sleep(min(pause, 60))
                attente *= 2
                continue
            raise ErreurHTTP(e.code, e.reason, corps) from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if essai < essais:
                time.sleep(attente)
                attente *= 2
                continue
            raise ErreurHTTP(0, f"connexion impossible ({e})") from None
    raise AssertionError("inaccessible")


def get_json(url: str, params: dict | None = None, **kw) -> dict:
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    _, _, corps = requete(url, **kw)
    return json.loads(corps)


def post_json(url: str, charge: dict, entetes: dict | None = None, **kw) -> dict:
    donnees = json.dumps(charge).encode("utf-8")
    entetes = {"Content-Type": "application/json", **(entetes or {})}
    _, _, corps = requete(url, methode="POST", donnees=donnees, entetes=entetes, **kw)
    return json.loads(corps) if corps else {}


def post_formulaire(url: str, champs: dict, entetes: dict | None = None, **kw) -> dict:
    donnees = urllib.parse.urlencode({k: v for k, v in champs.items() if v is not None}).encode()
    entetes = {"Content-Type": "application/x-www-form-urlencoded", **(entetes or {})}
    _, _, corps = requete(url, methode="POST", donnees=donnees, entetes=entetes, **kw)
    return json.loads(corps) if corps else {}
