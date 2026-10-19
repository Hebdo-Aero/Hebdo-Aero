"""Images d'illustration libres de droits (vidéos et photos) via l'API Pixabay.

Clé gratuite et immédiate : créez un compte sur pixabay.com, puis ouvrez
https://pixabay.com/api/docs/ (la clé s'affiche dans la page). Secret : PIXABAY_API_KEY.
Pixabay demande d'indiquer la provenance des images : chaque image est créditée.
"""
from __future__ import annotations

import os
import sys

from .http import ErreurHTTP, get_json

API = "https://pixabay.com/api/"
TAILLE_MAX_4K = 80 * 1024 * 1024     # on évite de télécharger des fichiers 4K trop lourds


# Images écartées : une compagnie ou une marque reconnaissable ferait croire qu'elle est concernée par le sujet.
MARQUES = {
    "dhl", "fedex", "ups", "lufthansa", "emirates", "ryanair", "easyjet", "wizz", "klm", "delta", "united",
    "american", "southwest", "qatar", "etihad", "turkish", "british", "iberia", "swiss", "austrian", "alitalia",
    "ita", "tap", "aeroflot", "airfrance", "france", "transavia", "vueling", "norwegian", "finnair", "sas",
    "singapore", "cathay", "qantas", "jetblue", "alaska", "spirit", "frontier", "condor", "eurowings", "tui",
    "jet2", "flybe", "virgin", "aircanada", "canada", "westjet", "ana", "jal", "korean", "asiana", "china",
    "hainan", "garuda", "thai", "malaysia", "saudia", "royal", "aegean", "lot", "icelandair", "brussels",
    "luxair", "corsair", "airbaltic", "pegasus", "indigo", "vistara", "avianca", "latam", "aeromexico",
    "boeing", "airbus", "embraer", "bombardier", "cessna", "pilatus", "dassault", "gulfstream", "atr",
}


def _marque(v: dict) -> bool:
    """Vrai si les mots-clés de l'image citent une compagnie, un constructeur ou une marque."""
    mots = {m.strip().lower().replace(" ", "") for m in (v.get("tags") or "").split(",")}
    mots |= {m.strip().lower() for m in (v.get("tags") or "").replace(",", " ").split()}
    return bool(mots & MARQUES)


def disponible() -> bool:
    return bool(os.environ.get("PIXABAY_API_KEY"))


def _get(chemin: str, params: dict) -> dict:
    return get_json(API + chemin, {"key": os.environ["PIXABAY_API_KEY"], "lang": "en",
                                   "safesearch": "true", **params}, delai=30, essais=2)


def _meilleur_rendu(rendus: dict) -> dict | None:
    """Rendu le mieux adapté à un recadrage vertical 1080×1920."""
    valides = [r for r in rendus.values() if r.get("url") and r.get("width") and r.get("height")]
    if not valides:
        return None
    verticaux = [r for r in valides if r["height"] > r["width"]]
    if verticaux:
        return min(verticaux, key=lambda r: abs(r["height"] - 1920))
    # plan horizontal : il sera recadré au centre, on prend la meilleure définition raisonnable
    grands = [r for r in valides if r["height"] >= 1080 and (r.get("size") or 0) <= TAILLE_MAX_4K]
    return max(grands or valides, key=lambda r: r["height"])


def chercher_video(recherche: str, duree_min: float, deja_pris: set[int]) -> dict | None:
    try:
        resultats = _get("videos/", {"q": recherche[:100], "video_type": "film", "per_page": 20})
    except ErreurHTTP as e:
        print(f"  Pixabay indisponible ({e})", file=sys.stderr)
        return None
    candidats = []
    for v in resultats.get("hits", []):
        if v["id"] in deja_pris or _marque(v):
            continue
        rendu = _meilleur_rendu(v.get("videos", {}))
        if not rendu:
            continue
        score = (rendu["height"] > rendu["width"], v.get("duration", 0) >= duree_min, rendu["height"] >= 1080)
        candidats.append((score, {"id": v["id"], "lien": rendu["url"], "duree": v.get("duration", 0),
                                  "auteur": v.get("user") or "Pixabay", "page": v.get("pageURL", ""),
                                  "source": "Pixabay"}))
    if not candidats:
        return None
    return max(candidats, key=lambda c: c[0])[1]


def chercher_photo(recherche: str, deja_pris: set[int], orientation: str = "horizontal") -> dict | None:
    try:
        resultats = _get("", {"q": recherche[:100], "image_type": "photo", "orientation": orientation,
                              "per_page": 20})
    except ErreurHTTP as e:
        print(f"  Pixabay indisponible ({e})", file=sys.stderr)
        return None
    for p in resultats.get("hits", []):
        if p["id"] not in deja_pris and p.get("largeImageURL") and not _marque(p):
            return {"id": p["id"], "lien": p["largeImageURL"], "auteur": p.get("user") or "Pixabay",
                    "page": p.get("pageURL", ""), "source": "Pixabay"}
    return None
