"""Publie la vidéo de la semaine sur les réseaux configurés.

Usage : python -m revue.publier [--date AAAA-MM-JJ] [--plateformes youtube,instagram,facebook,threads]

Chaque plateforme est indépendante : une erreur sur l'une n'empêche pas les autres.
Une plateforme déjà publiée pour ce numéro est ignorée (pas de doublon si on relance).
Une plateforme sans ses secrets est ignorée silencieusement.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
from datetime import datetime, timezone

from ..config import DOSSIER_MEDIAS, DOSSIER_RESEAUX, charger_config, ecrire_json, lire_json, lister_numeros
from ..http import ErreurHTTP, requete
from ..reseaux import remplir_liens, url_numero
from . import meta, threads, youtube

ORDRE = ["youtube", "instagram", "facebook", "threads"]


def attendre_en_ligne(url: str, attente_max: int = 600) -> None:
    """Attend que GitHub Pages serve la vidéo (quelques secondes à quelques minutes)."""
    debut = time.time()
    while True:
        try:
            statut, _, _ = requete(url, methode="HEAD", delai=30, essais=1)
            if statut == 200:
                return
        except ErreurHTTP:
            pass
        if time.time() - debut > attente_max:
            raise RuntimeError(f"La vidéo n'est pas accessible en ligne : {url}")
        time.sleep(20)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="date du numéro (par défaut : le plus récent)")
    parser.add_argument("--plateformes", default=",".join(ORDRE))
    args = parser.parse_args(argv)

    config = charger_config()
    numeros = lister_numeros()
    if not numeros:
        print("Aucun numéro à publier.")
        return 0
    numero = next((n for n in numeros if n["date"] == args.date), None) if args.date else numeros[0]
    if numero is None:
        print(f"Aucun numéro daté du {args.date}.", file=sys.stderr)
        return 1

    chemin_script = DOSSIER_RESEAUX / f"{numero['date']}.json"
    script = lire_json(chemin_script)
    video = DOSSIER_MEDIAS / f"{numero['date']}.mp4"
    if not script or not video.exists():
        print(f"Pas de vidéo pour le numéro {numero['numero']} : rien à publier.", file=sys.stderr)
        return 1

    site = config["site"]["url"]
    url_video = f"{site}videos/{video.name}" if site else ""
    leg = {k: remplir_liens(v, config, numero["numero"]) for k, v in script["legendes"].items()}
    if script.get("credits_video"):        # crédit des vidéastes, demandé par Pexels
        credit = "Images d'illustration : " + ", ".join(script["credits_video"]) + " (Pexels)."
        for cle in ("youtube_description", "facebook", "instagram"):
            leg[cle] = f"{leg[cle]}\n\n{credit}"
    reseaux = config["reseaux"]
    version = reseaux.get("meta_version_api", "v25.0")

    def publier_threads() -> dict:
        if not url_video:
            raise RuntimeError("Adresse du site inconnue : Threads a besoin d'une vidéo en ligne.")
        attendre_en_ligne(url_video)
        return threads.publier(leg["threads"], url_video, url_numero(config, numero["numero"]))

    actions = {
        "youtube": (youtube.disponible, lambda: youtube.publier(
            video, leg["youtube_titre"], leg["youtube_description"],
            ["aviation", "aéronautique", "compagnies aériennes", "actualité", config["site"]["nom"]],
            reseaux.get("youtube_visibilite", "public"), reseaux.get("youtube_contenu_synthetique", True))),
        "instagram": (meta.instagram_disponible, lambda: meta.instagram(video, url_video, leg["instagram"], version)),
        "facebook": (meta.facebook_disponible, lambda: meta.facebook(video, leg["facebook"], version)),
        "threads": (threads.disponible, publier_threads),
    }

    demandees = [p.strip() for p in args.plateformes.split(",") if p.strip() in actions]
    publications = script.setdefault("publications", {})
    echecs, resume = [], []
    for nom in demandees:
        disponible, action = actions[nom]
        if not reseaux.get(nom, True):
            resume.append(f"| {nom} | désactivé dans config.toml | |")
            continue
        if nom in publications:
            resume.append(f"| {nom} | déjà publié | {publications[nom].get('url', '')} |")
            continue
        if not disponible():
            resume.append(f"| {nom} | secrets absents, ignoré | |")
            continue
        print(f"Publication sur {nom}…")
        try:
            resultat = action()
        except Exception as e:  # noqa: BLE001 — on veut continuer avec les autres réseaux
            traceback.print_exc()
            print(f"::error::Échec de la publication sur {nom} : {e}")
            echecs.append(nom)
            resume.append(f"| {nom} | échec : {str(e)[:120]} | |")
            continue
        resultat["le"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        publications[nom] = resultat
        ecrire_json(chemin_script, script)          # on enregistre au fur et à mesure
        resume.append(f"| {nom} | publié | {resultat.get('url', '')} |")
        print(f"  publié : {resultat.get('url')}")

    rapport = "### Réseaux sociaux\n\n| Plateforme | État | Lien |\n|---|---|---|\n" + "\n".join(resume) + "\n"
    print(rapport)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(rapport)
    return 1 if echecs else 0
