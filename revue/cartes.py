"""Images du jour pour Instagram et TikTok (1080 × 1350), tirées du numéro de la semaine.

Une image par jour, du lundi au samedi : le chiffre de la semaine, les trois sujets « À la une »,
les brèves, puis l'annonce du numéro du lendemain. Le dimanche, c'est la vidéo d'annonce.
Les images et leur légende sont enregistrées dans data/cartes/ et publiées sur le site (/cartes/),
d'où Metricool les récupère pour les programmer aux heures de pointe.

Usage : python -m revue.generer cartes [--date AAAA-MM-JJ]
"""
from __future__ import annotations

import re
import tempfile
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from . import ciel
from .config import RACINE, RUBRIQUES, ecrire_json, periode_fr
from .reseaux import adresse_lisible

DOSSIER = RACINE / "data" / "cartes"
GABARITS = Path(__file__).parent / "templates"
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi"]
SENSIBLE = re.compile(r"attaqu|attentat|meurtr|\bmorts?\b|tué|crash|accident|bless|victime|otage", re.I)
MENTION_IA = "Résumés rédigés avec l'IA à partir des sources citées sur le site."


def _phrases(texte: str, nombre: int = 2, limite: int = 260) -> str:
    morceaux = re.split(r"(?<=[.!?])\s+", (texte or "").strip())
    resultat = ""
    for m in morceaux[:nombre]:
        if len(resultat) + len(m) > limite and resultat:
            break
        resultat = f"{resultat} {m}".strip()
    return resultat


def _sensible(sujet: dict) -> bool:
    return sujet.get("categorie") == "Sécurité & sûreté" or bool(SENSIBLE.search(sujet.get("titre", "") + " " + sujet.get("resume", "")))


def contenus(config: dict, numero: dict) -> list[dict]:
    """La liste des cartes de la semaine (données de l'image + légende), dans l'ordre des jours."""
    tags = " ".join("#" + h for h in config["reseaux"].get("hashtags", []))
    adresse = adresse_lisible(config["site"].get("url") or "https://hebdo-aero.github.io/Hebdo-Aero/")
    n = numero["numero"]
    appel = f"À lire dans le N° {n} d'Hebdo Aero, avec toutes les sources : lien en bio 👉 {adresse}"
    cartes: list[dict] = []

    if numero.get("chiffre"):
        c = numero["chiffre"]
        cartes.append({"type": "chiffre", "valeur": c["valeur"], "legende": c["legende"], "source": c["source"]["nom"],
                       "couleur": "soleil",
                       "texte_post": f"{c['valeur']} : {c['legende']}\n\nC'est le chiffre de la semaine ✈️\n\n{appel}\n\n{tags}"})
    for s in numero.get("une", []):
        if _sensible(s):          # pas d'accident ni d'attentat en image promotionnelle
            continue
        r = RUBRIQUES.get(s["categorie"], {})
        cartes.append({"type": "une", "titre": s["titre"], "texte": _phrases(s["resume"]), "categorie": s["categorie"],
                       "sources": [x["nom"] for x in s["sources"]], "couleur": r.get("couleur", "orange"),
                       "texte_post": f"{s['titre']}\n\n{_phrases(s['resume'], 3, 420)}\n\n{appel}\n\n{MENTION_IA}\n\n{tags}"})
    breves = [b for b in numero.get("breves", []) if not _sensible(b)][:4]
    if len(breves) >= 2:
        cartes.append({"type": "breves", "couleur": "ciel",
                       "breves": [{"titre": b["titre"], "categorie": b["categorie"],
                                   "couleur": RUBRIQUES.get(b["categorie"], {}).get("couleur", "orange")} for b in breves],
                       "texte_post": "Ce qu'il fallait aussi retenir cette semaine dans l'aviation commerciale ✈️\n\n"
                                     + "\n".join(f"▸ {b['titre']}" for b in breves)
                                     + f"\n\nLes détails et les sources dans le N° {n} : lien en bio 👉 {adresse}\n\n{MENTION_IA}\n\n{tags}"})
    cartes = cartes[:5]
    cartes.append({"type": "demain", "couleur": "orange",
                   "texte_post": f"Demain matin, le N° {n + 1} d'Hebdo Aero : toute l'actu de l'aviation commerciale de la "
                                 f"semaine, résumée en 5 minutes et sourcée ✈️\n\nLien en bio pour ne pas le rater 👉 {adresse}\n\n{tags}"})
    # une carte par jour du lundi au samedi : s'il en manque, la dernière (l'annonce) reste le samedi
    jours = JOURS[:len(cartes) - 1] + ["samedi"]
    for carte, jour in zip(cartes, jours):
        carte.update(jour=jour, numero=n, adresse=adresse)
    return cartes


def rendre(config: dict, numero: dict, dossier: Path = DOSSIER) -> list[dict]:
    """Dessine les images (JPG) et écrit le fichier data/cartes/<date>.json pour la publication."""
    from playwright.sync_api import sync_playwright

    dossier.mkdir(parents=True, exist_ok=True)
    travail = Path(tempfile.mkdtemp(prefix="cartes-"))
    fond = ciel.enregistrer(travail / "ciel.jpg", 1400, 1000, graine=int(numero["numero"]) + 70)
    env = Environment(loader=FileSystemLoader(GABARITS), autoescape=True)
    gabarit = env.get_template("carte.html")
    base = config["site"].get("url") or ""
    cartes = contenus(config, numero)
    with sync_playwright() as p:
        navigateur = p.chromium.launch()
        page = navigateur.new_page(viewport={"width": 1080, "height": 1350}, device_scale_factor=1)
        for k, carte in enumerate(cartes, start=1):
            html = travail / f"carte-{k}.html"
            html.write_text(gabarit.render(
                **carte, ciel=fond.as_uri(), polices=(RACINE / "assets" / "polices").as_uri(),
                logo=(RACINE / "assets" / "logo" / "logo-sombre.svg").as_uri()), encoding="utf-8")
            page.goto(html.as_uri(), wait_until="load")
            page.evaluate("document.fonts.ready")
            page.evaluate("preparer()")
            fichier = f"{numero['date']}-{k}.jpg"
            page.screenshot(path=str(dossier / fichier), type="jpeg", quality=88)
            carte["fichier"] = fichier
            carte["url"] = f"{base}cartes/{fichier}" if base else ""
        navigateur.close()
    manifeste = {"numero": numero["numero"], "date": numero["date"],
                 "periode": periode_fr(numero["debut"], numero["fin"]),
                 "cartes": [{"jour": c["jour"], "type": c["type"], "fichier": c["fichier"], "url": c["url"],
                             "legende": c["texte_post"]} for c in cartes]}
    ecrire_json(dossier / f"{numero['date']}.json", manifeste)
    return manifeste["cartes"]
