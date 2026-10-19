"""Choix de la banque d'images libres : Pexels si sa clé existe, sinon Pixabay.

Sans aucune clé, le site et les vidéos utilisent le ciel généré par le programme.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

from . import pexels, pixabay
from .http import ErreurHTTP, requete


def banque():
    for module in (pexels, pixabay):
        if module.disponible():
            return module
    return None


def disponible() -> bool:
    return banque() is not None


def chercher_video(recherche: str, duree_min: float, deja_pris: set[int]) -> dict | None:
    b = banque()
    return b.chercher_video(recherche, duree_min, deja_pris) if b else None


def chercher_photo(recherche: str, deja_pris: set[int]) -> dict | None:
    b = banque()
    return b.chercher_photo(recherche, deja_pris) if b else None


def telecharger(lien: str, cible: Path) -> Path:
    _, _, contenu = requete(lien, delai=180, essais=3)
    cible.parent.mkdir(parents=True, exist_ok=True)
    cible.write_bytes(contenu)
    return cible


def telecharger_photo(photo: dict, cible: Path, largeur_max: int = 1600) -> Path:
    """Télécharge, redimensionne et compresse une photo pour le site (jamais de lien direct)."""
    from PIL import Image
    _, _, contenu = requete(photo["lien"], delai=120, essais=3)
    image = Image.open(io.BytesIO(contenu)).convert("RGB")
    if image.width > largeur_max:
        image = image.resize((largeur_max, round(image.height * largeur_max / image.width)), Image.LANCZOS)
    cible.parent.mkdir(parents=True, exist_ok=True)
    image.save(cible, quality=80, optimize=True, progressive=True)
    return cible


def illustrer_numero(numero: dict, dossier: Path) -> dict:
    """Ajoute une photo d'ouverture et une photo par sujet à la une."""
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
        cible["image"] = {"fichier": fichier, "auteur": photo["auteur"], "page": photo["page"],
                          "source": photo.get("source", "Pexels")}
    return numero
