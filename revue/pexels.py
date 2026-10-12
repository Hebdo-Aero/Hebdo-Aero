"""Images d'illustration libres de droits (vidéos et photos) via l'API Pexels.

Clé gratuite sur https://www.pexels.com/api/ (secret PEXELS_API_KEY).
Conformément aux conditions de Pexels, chaque image est créditée (auteur + lien).
Sans clé, ou si rien ne convient, le programme se rabat sur le ciel généré.
"""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path

from .http import ErreurHTTP, get_json, requete

API = "https://api.pexels.com"
CHEMINS_VIDEO = ["/videos/search", "/v1/videos/search"]


def disponible() -> bool:
    return bool(os.environ.get("PEXELS_API_KEY"))


def _get(chemin: str, params: dict) -> dict:
    return get_json(API + chemin, params, entetes={"Authorization": os.environ["PEXELS_API_KEY"]},
                    delai=30, essais=2)


def chercher_video(recherche: str, duree_min: float, deja_pris: set[int]) -> dict | None:
    """Meilleure vidéo verticale pour `recherche` : renvoie {id, lien, auteur, page, duree}."""
    resultats = None
    for chemin in CHEMINS_VIDEO:
        try:
            resultats = _get(chemin, {"query": recherche, "orientation": "portrait", "size": "medium",
                                      "per_page": 15})
            break
        except ErreurHTTP as e:
            if e.code != 404:
                print(f"  Pexels indisponible ({e})", file=sys.stderr)
                return None
    candidats = []
    for v in (resultats or {}).get("videos", []):
        if v["id"] in deja_pris or v.get("height", 0) <= v.get("width", 1):
            continue
        fichiers = [f for f in v.get("video_files", []) if f.get("file_type") == "video/mp4"
                    and f.get("height") and f.get("width") and f["height"] > f["width"] and 1000 <= f["height"] <= 2200]
        if not fichiers:
            continue
        meilleur = min(fichiers, key=lambda f: abs(f["height"] - 1920))
        # on préfère les plans assez longs pour couvrir la scène sans boucler
        score = (v.get("duration", 0) >= duree_min, -abs(meilleur["height"] - 1920))
        candidats.append((score, {"id": v["id"], "lien": meilleur["link"], "duree": v.get("duration", 0),
                                  "auteur": v.get("user", {}).get("name", "Pexels"), "page": v.get("url", "")}))
    if not candidats:
        return None
    return max(candidats, key=lambda c: c[0])[1]


def chercher_photo(recherche: str, deja_pris: set[int], orientation: str = "landscape") -> dict | None:
    try:
        resultats = _get("/v1/search", {"query": recherche, "orientation": orientation, "per_page": 15})
    except ErreurHTTP as e:
        print(f"  Pexels indisponible ({e})", file=sys.stderr)
        return None
    for p in resultats.get("photos", []):
        if p["id"] not in deja_pris:
            return {"id": p["id"], "lien": p["src"].get("large2x") or p["src"]["original"],
                    "auteur": p.get("photographer", "Pexels"), "page": p.get("url", "")}
    return None


def telecharger(lien: str, cible: Path) -> Path:
    _, _, contenu = requete(lien, delai=180, essais=3)
    cible.parent.mkdir(parents=True, exist_ok=True)
    cible.write_bytes(contenu)
    return cible


def telecharger_photo(photo: dict, cible: Path, largeur_max: int = 1600) -> Path:
    """Télécharge, redimensionne et compresse une photo pour le site."""
    from PIL import Image
    _, _, contenu = requete(photo["lien"], delai=120, essais=3)
    image = Image.open(io.BytesIO(contenu)).convert("RGB")
    if image.width > largeur_max:
        image = image.resize((largeur_max, round(image.height * largeur_max / image.width)), Image.LANCZOS)
    cible.parent.mkdir(parents=True, exist_ok=True)
    image.save(cible, quality=80, optimize=True, progressive=True)
    return cible


def illustrer_numero(numero: dict, dossier: Path) -> dict:
    """Ajoute une photo d'ouverture et une photo par sujet à la une (si Pexels est configuré)."""
    if not disponible():
        return numero
    pris: set[int] = set()
    demandes = [("couverture", numero, numero.get("illustration") or "airplane sunset sky")]
    demandes += [(f"une-{i + 1}", s, s.get("illustration") or "airplane") for i, s in enumerate(numero.get("une", []))]
    for suffixe, cible, recherche in demandes:
        photo = chercher_photo(recherche, pris) or chercher_photo("airplane", pris)
        if not photo:
            continue
        pris.add(photo["id"])
        fichier = f"{numero['date']}-{suffixe}.jpg"
        try:
            telecharger_photo(photo, dossier / fichier)
        except (ErreurHTTP, OSError) as e:
            print(f"  photo ignorée ({e})", file=sys.stderr)
            continue
        cible["image"] = {"fichier": fichier, "auteur": photo["auteur"], "page": photo["page"]}
    return numero
