"""Chargement de la configuration, chemins du projet et utilitaires de dates."""
from __future__ import annotations

import json
import os
import tomllib
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

RACINE = Path(__file__).resolve().parent.parent
DOSSIER_NUMEROS = RACINE / "data" / "numeros"
DOSSIER_RESEAUX = RACINE / "data" / "reseaux"
DOSSIER_MEDIAS = RACINE / "_medias"   # vidéos rendues (non versionnées)
DOSSIER_SITE = RACINE / "_site"       # site généré (non versionné)

CATEGORIES = [
    "Constructeurs & commandes",
    "Compagnies & réseaux",
    "Résultats & marchés",
    "Aéroports & maintenance",
    "Sécurité & sûreté",
    "Innovation & environnement",
]
# Identité visuelle de chaque rubrique sur le site : ancre, couleur, pictogramme.
RUBRIQUES = {
    "Constructeurs & commandes": {"ancre": "constructeurs", "couleur": "orange", "icone": "avion"},
    "Compagnies & réseaux": {"ancre": "compagnies", "couleur": "ciel", "icone": "route"},
    "Résultats & marchés": {"ancre": "resultats", "couleur": "soleil", "icone": "courbe"},
    "Aéroports & maintenance": {"ancre": "aeroports", "couleur": "violet", "icone": "tour"},
    "Sécurité & sûreté": {"ancre": "securite", "couleur": "rouge", "icone": "bouclier"},
    "Innovation & environnement": {"ancre": "innovation", "couleur": "vert", "icone": "feuille"},
}
REGIONS = [
    "Europe",
    "Amérique du Nord",
    "Amérique latine",
    "Afrique",
    "Moyen-Orient",
    "Asie-Pacifique",
    "Monde",
]

MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
        "août", "septembre", "octobre", "novembre", "décembre"]


def charger_config(chemin: Path | None = None) -> dict:
    chemin = chemin or RACINE / "config.toml"
    with open(chemin, "rb") as f:
        config = tomllib.load(f)
    # L'adresse écrite dans config.toml l'emporte ; sinon celle fournie par GitHub Pages.
    url = config["site"].get("url") or os.environ.get("SITE_URL") or ""
    config["site"]["url"] = url.rstrip("/") + "/" if url else ""
    return config


def aujourdhui(config: dict) -> date:
    return datetime.now(ZoneInfo(config["site"].get("fuseau", "Europe/Paris"))).date()


def date_fr(d: date | str) -> str:
    d = _en_date(d)
    jour = "1er" if d.day == 1 else str(d.day)
    return f"{jour} {MOIS[d.month - 1]} {d.year}"


def periode_fr(debut: date | str, fin: date | str) -> str:
    """« 5 au 11 octobre 2026 », « 28 septembre au 4 octobre 2026 »…"""
    debut, fin = _en_date(debut), _en_date(fin)
    j1 = "1er" if debut.day == 1 else str(debut.day)
    if debut.year != fin.year:
        return f"{date_fr(debut)} au {date_fr(fin)}"
    if debut.month != fin.month:
        return f"{j1} {MOIS[debut.month - 1]} au {date_fr(fin)}"
    return f"{j1} au {date_fr(fin)}"


def _en_date(d: date | str) -> date:
    return date.fromisoformat(d) if isinstance(d, str) else d


def semaine_se_terminant(fin: date) -> tuple[date, date]:
    return fin - timedelta(days=6), fin


def lister_numeros() -> list[dict]:
    """Tous les numéros publiés, du plus récent au plus ancien."""
    numeros = []
    for chemin in sorted(DOSSIER_NUMEROS.glob("*.json")):
        with open(chemin, encoding="utf-8") as f:
            numeros.append(json.load(f))
    return sorted(numeros, key=lambda n: n["date"], reverse=True)


def lire_json(chemin: Path) -> dict | None:
    if not chemin.exists():
        return None
    with open(chemin, encoding="utf-8") as f:
        return json.load(f)


def ecrire_json(chemin: Path, donnees: dict) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(donnees, f, ensure_ascii=False, indent=2)
        f.write("\n")
