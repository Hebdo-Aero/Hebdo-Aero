"""Génère le site statique dans _site/ à partir des numéros enregistrés dans data/.

Usage : python -m revue.construire
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, time
from email.utils import format_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import (CATEGORIES, RUBRIQUES, DOSSIER_MEDIAS, DOSSIER_RESEAUX, DOSSIER_SITE, RACINE, charger_config,
                     lire_json, lister_numeros, periode_fr)

NOMS_RESEAUX = {"youtube": "YouTube", "instagram": "Instagram", "facebook": "Facebook", "threads": "Threads"}


def preparer_numero(n: dict, config: dict, sortie: Path, voisins: tuple[int | None, int | None]) -> dict:
    n = json.loads(json.dumps(n))          # copie profonde : on n'altère pas les données
    n["periode"] = periode_fr(n["debut"], n["fin"])
    rubriques = {c: [] for c in CATEGORIES}
    for s in n.get("breves", []):
        rubriques.setdefault(s["categorie"], []).append(s)
    n["rubriques"] = [(c, sujets) for c, sujets in rubriques.items() if sujets]
    n["precedent"], n["suivant"] = voisins
    parution = datetime.combine(datetime.fromisoformat(n["date"]).date(), time(7, 0),
                                ZoneInfo(config["site"].get("fuseau", "Europe/Paris")))
    n["date_rss"] = format_datetime(parution)

    # Vidéo de la semaine (présente uniquement lors de la publication hebdomadaire)
    video = DOSSIER_MEDIAS / f"{n['date']}.mp4"
    if video.exists():
        (sortie / "videos").mkdir(exist_ok=True)
        shutil.copy2(video, sortie / "videos" / video.name)
        n["video"] = f"videos/{video.name}"
        affiche = video.with_suffix(".jpg")
        if affiche.exists():
            shutil.copy2(affiche, sortie / "videos" / affiche.name)
            n["affiche"] = f"videos/{affiche.name}"

    images = RACINE / "data" / "images"
    (sortie / "images").mkdir(exist_ok=True)
    if (images / f"{n['date']}-partage.jpg").exists():
        n["image_partage"] = f"images/{n['date']}-partage.jpg"

    # Image d'ouverture : la photo Pexels si elle existe, sinon le ciel généré pour ce numéro.
    if n.get("image") and (images / n["image"]["fichier"]).exists():
        n["couverture"] = {"src": f"images/{n['image']['fichier']}", "auteur": n["image"]["auteur"],
                           "page": n["image"]["page"]}
    else:
        ciel_fichier = images / f"{n['date']}-ciel.jpg"
        if not ciel_fichier.exists():
            from .ciel import enregistrer
            enregistrer(ciel_fichier, 1800, 1000, graine=int(n["numero"]), qualite=82)
        n["couverture"] = {"src": f"images/{ciel_fichier.name}"}
    for i, s in enumerate(n.get("une", [])):
        if s.get("image") and (images / s["image"]["fichier"]).exists():
            s["visuel"] = {"src": f"images/{s['image']['fichier']}", "auteur": s["image"]["auteur"],
                           "page": s["image"]["page"]}
        else:   # vignette dessinée : le ciel du numéro teinté à la couleur de la rubrique
            s["visuel"] = {"src": n["couverture"]["src"], "dessine": True, "position": ["20% 60%", "60% 70%", "90% 55%"][i % 3]}
    mots = len(" ".join([n.get("edito", "")] + [x["resume"] for x in n.get("une", []) + n.get("breves", [])]).split())
    n["lecture"] = max(1, round(mots / 220))

    reseaux = lire_json(DOSSIER_RESEAUX / f"{n['date']}.json") or {}
    n["liens_reseaux"] = [(NOMS_RESEAUX[k], v["url"]) for k, v in (reseaux.get("publications") or {}).items()
                          if k in NOMS_RESEAUX and v.get("url")]
    return n


def construire(sortie: Path = DOSSIER_SITE) -> Path:
    config = charger_config()
    site = config["site"]
    if sortie.exists():
        shutil.rmtree(sortie)
    sortie.mkdir(parents=True)

    env = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"),
                      autoescape=select_autoescape(["html", "xml"]), trim_blocks=True, lstrip_blocks=True)
    bruts = lister_numeros()
    nums = [b["numero"] for b in bruts]
    numeros = []
    for i, b in enumerate(bruts):            # du plus récent au plus ancien
        suivant = nums[i - 1] if i > 0 else None
        precedent = nums[i + 1] if i + 1 < len(bruts) else None
        numeros.append(preparer_numero(b, config, sortie, (precedent, suivant)))

    def ecrire(chemin: str, gabarit: str, racine: str, **contexte) -> None:
        cible = sortie / chemin
        cible.parent.mkdir(parents=True, exist_ok=True)
        url_page = site["url"] + chemin.removesuffix("index.html") if site["url"] else ""
        image = contexte.pop("image", None)
        html = env.get_template(gabarit).render(
            site=site, racine=racine, url_page=url_page, flux=config.get("flux", []),
            rubriques=RUBRIQUES, profils=profils,
            image_partage=(site["url"] + image) if image and site["url"] else "", **contexte)
        cible.write_text(html, encoding="utf-8")

    profils = [(NOMS_RESEAUX[k], v) for k, v in (config["reseaux"].get("profils") or {}).items()
               if k in NOMS_RESEAUX and v]
    dernier = numeros[0] if numeros else None
    ecrire("index.html", "accueil.html", "", page="accueil", dernier=dernier, precedents=numeros[1:9],
           image=dernier.get("image_partage") if dernier else None)
    for n in numeros:
        ecrire(f"numeros/{n['numero']}/index.html", "numero.html", "../../", n=n, image=n.get("image_partage"))
    ecrire("archives/index.html", "archives.html", "../", numeros=numeros, page="archives")
    ecrire("a-propos/index.html", "a-propos.html", "../", page="a-propos")
    ecrire("404.html", "404.html", site["url"] or "/")
    ecrire("flux.xml", "flux.xml", "", numeros=numeros)
    if site["url"]:
        ecrire("sitemap.xml", "sitemap.xml", "", numeros=numeros)

    images = RACINE / "data" / "images"
    if images.exists():
        shutil.copytree(images, sortie / "images", dirs_exist_ok=True)
    echantillons = lire_json(DOSSIER_MEDIAS / "voix" / "voix.json")
    if echantillons:      # page d'écoute des voix (action « Écouter les voix disponibles »)
        (sortie / "voix").mkdir(exist_ok=True)
        for v in echantillons["voix"]:
            shutil.copy2(DOSSIER_MEDIAS / "voix" / v["fichier"], sortie / "voix" / v["fichier"])
        ecrire("voix/index.html", "voix.html", "../", **echantillons)
    shutil.copytree(RACINE / "assets" / "polices", sortie / "assets" / "polices")
    shutil.copytree(RACINE / "assets" / "logo", sortie / "assets" / "logo",
                    ignore=shutil.ignore_patterns("banniere-*"))
    robots = "User-agent: *\nAllow: /\n" + (f"Sitemap: {site['url']}sitemap.xml\n" if site["url"] else "")
    (sortie / "robots.txt").write_text(robots, encoding="utf-8")
    (sortie / ".nojekyll").write_text("", encoding="utf-8")
    print(f"Site généré : {len(numeros)} numéro(s) dans {sortie}")
    return sortie


if __name__ == "__main__":
    construire()
