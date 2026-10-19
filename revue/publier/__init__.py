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
    parser.add_argument("--accroche", action="store_true",
                        help="publie seulement le prochain short d'accroche sur Instagram (mardi et jeudi)")
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
    if args.accroche:
        return publier_accroche_suivante(config, numero, script, chemin_script)
    video = DOSSIER_MEDIAS / f"{numero['date']}.mp4"
    if not script or not video.exists():
        print(f"Pas de vidéo pour le numéro {numero['numero']} : rien à publier.", file=sys.stderr)
        return 1

    site = config["site"]["url"]
    url_video = f"{site}videos/{video.name}" if site else ""
    leg = {k: remplir_liens(v, config, numero["numero"]) for k, v in script["legendes"].items()}
    if script.get("credits_video"):        # crédit des vidéastes, demandé par Pexels
        credit = "Images d'illustration : " + ", ".join(script["credits_video"]) + "."
        for cle in ("youtube_description", "facebook", "instagram"):
            leg[cle] = f"{leg[cle]}\n\n{credit}"
    reseaux = config["reseaux"]
    version = reseaux.get("meta_version_api", "v25.0")

    def publier_instagram() -> dict:
        # Par défaut, Instagram reçoit le short d'accroche n° 1 plutôt que le récap complet.
        if reseaux.get("instagram_accroches", True) and script.get("accroches"):
            resultat = publier_accroche(config, numero, script, 1)
            if resultat:
                return resultat
        return meta.instagram(video, url_video, leg["instagram"], version)

    def publier_threads() -> dict:
        if not url_video:
            raise RuntimeError("Adresse du site inconnue : Threads a besoin d'une vidéo en ligne.")
        attendre_en_ligne(url_video)
        return threads.publier(leg["threads"], url_video, url_numero(config, numero["numero"]))

    actions = {
        "youtube": (youtube.disponible, lambda: youtube.publier(
            video, leg["youtube_titre"], leg["youtube_description"],
            ["aviation", "aéronautique", "compagnies aériennes", "actualité", config["site"]["nom"]],
            reseaux.get("youtube_visibilite", "public"), reseaux.get("youtube_contenu_synthetique", True),
            placement_paye=bool(script.get("partenaire")))),
        "instagram": (meta.instagram_disponible, publier_instagram),
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


def recuperer(fichier, config: dict) -> bool:
    """Télécharge depuis le site un média absent du disque (vidéos produites le dimanche)."""
    if fichier.exists():
        return True
    site = config["site"]["url"]
    if not site:
        return False
    try:
        _, _, contenu = requete(f"{site}videos/{fichier.name}", delai=180, essais=3)
    except ErreurHTTP:
        return False
    fichier.parent.mkdir(parents=True, exist_ok=True)
    fichier.write_bytes(contenu)
    return True


def publier_accroche(config: dict, numero: dict, script: dict, k: int) -> dict | None:
    """Publie le short d'accroche n° k sur Instagram ; None si le fichier n'existe pas."""
    accroches = script.get("accroches", [])
    if k > len(accroches):
        return None
    fichier = DOSSIER_MEDIAS / f"{numero['date']}-accroche-{k}.mp4"
    if not recuperer(fichier, config):
        return None
    accroche = accroches[k - 1]
    legende = accroche.get("legende", "")
    if accroche.get("credits"):
        legende += "\n\nImages d'illustration : " + ", ".join(accroche["credits"]) + "."
    site = config["site"]["url"]
    resultat = meta.instagram(fichier, f"{site}videos/{fichier.name}" if site else "", legende[:2200],
                              config["reseaux"].get("meta_version_api", "v25.0"))
    resultat["le"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    script.setdefault("publications", {}).setdefault("accroches", {})[str(k)] = resultat
    return resultat


def publier_accroche_suivante(config: dict, numero: dict, script: dict | None, chemin_script) -> int:
    """Mardi et jeudi : publie sur Instagram le prochain short d'accroche pas encore publié."""
    if not script or not script.get("accroches"):
        print("Pas de short d'accroche pour ce numéro.")
        return 0
    if not config["reseaux"].get("instagram", True) or not meta.instagram_disponible():
        print("Instagram désactivé ou non configuré : rien à publier.")
        return 0
    deja = script.get("publications", {}).get("accroches", {})
    suivant = next((k for k in range(1, len(script["accroches"]) + 1) if str(k) not in deja), None)
    if suivant is None:
        print("Tous les shorts d'accroche de la semaine sont déjà publiés.")
        return 0
    print(f"Publication du short d'accroche {suivant} sur Instagram…")
    try:
        resultat = publier_accroche(config, numero, script, suivant)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        print(f"::error::Échec de la publication du short {suivant} : {e}")
        return 1
    if not resultat:
        print(f"::warning::Vidéo du short {suivant} introuvable.")
        return 1
    ecrire_json(chemin_script, script)
    print(f"  publié : {resultat.get('url')}")
    return 0
