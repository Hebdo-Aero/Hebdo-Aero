"""Étapes de production de la revue.

  python -m revue.generer numero [--force]       rédige le numéro de la semaine (Claude)
  python -m revue.generer reseaux [--date …]     script vidéo et textes des réseaux (Claude)
  python -m revue.generer video [--sans-voix]    narration Google TTS + rendu MP4
  python -m revue.generer photos                 photos d'illustration Pexels du dernier numéro
  python -m revue.generer voix                   échantillons des voix, pour choisir à l'oreille
  python -m revue.generer apercu                 affiche les articles collectés, sans appeler Claude
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, timedelta

from .config import (DOSSIER_MEDIAS, DOSSIER_NUMEROS, DOSSIER_RESEAUX, RACINE, aujourdhui, charger_config,
                     ecrire_json, lire_json, lister_numeros, periode_fr)


def sortie_github(**valeurs) -> None:
    """Transmet des valeurs aux étapes suivantes du workflow GitHub Actions."""
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            for cle, valeur in valeurs.items():
                f.write(f"{cle}={valeur}\n")


def periode_a_couvrir(config: dict, force: bool) -> tuple[int, date, date] | None:
    fin = aujourdhui(config)
    numeros = lister_numeros()
    dernier = numeros[0] if numeros else None
    debut = fin - timedelta(days=6)
    if dernier:
        fin_precedente = date.fromisoformat(dernier["fin"])
        if (fin - fin_precedente).days < 7 and not force:
            print(f"Le numéro {dernier['numero']} couvre déjà cette semaine (jusqu'au {dernier['fin']}).")
            return None
        if fin_precedente >= debut:
            debut = fin_precedente + timedelta(days=1)
        if debut > fin:
            print("Rien de nouveau à couvrir depuis le dernier numéro.")
            return None
    return (dernier["numero"] + 1 if dernier else 1), debut, fin


def etape_numero(config: dict, force: bool) -> int:
    from .flux import collecter
    from .redaction import rediger

    periode = periode_a_couvrir(config, force)
    if not periode:
        sortie_github(nouveau="false")
        return 0
    numero, debut, fin = periode
    print(f"Numéro {numero}, semaine du {periode_fr(debut, fin)}")
    print("Lecture des flux RSS…")
    articles = collecter(config.get("flux", []), debut, fin, config["site"].get("fuseau", "Europe/Paris"))
    print(f"{len(articles)} article(s) collecté(s).")
    if len(articles) < 10:
        print("::warning::Peu d'articles dans les flux cette semaine ; Claude s'appuiera davantage sur la recherche web.")
    contenu = rediger(config, articles, numero, debut, fin)
    from .pexels import disponible, illustrer_numero
    if disponible():
        print("Recherche des photos d'illustration (Pexels)…")
        illustrer_numero(contenu, RACINE / "data" / "images")
    chemin = DOSSIER_NUMEROS / f"{fin.isoformat()}.json"
    ecrire_json(chemin, contenu)
    print(f"Numéro enregistré : {chemin.relative_to(RACINE)} "
          f"({len(contenu['une'])} à la une, {len(contenu['breves'])} brèves)")
    sortie_github(nouveau="true", date=fin.isoformat(), numero=numero)
    return 0


def _numero_vise(date_: str | None) -> dict:
    numeros = lister_numeros()
    if not numeros:
        raise SystemExit("Aucun numéro enregistré.")
    if date_:
        for n in numeros:
            if n["date"] == date_:
                return n
        raise SystemExit(f"Aucun numéro daté du {date_}.")
    return numeros[0]


def etape_reseaux(config: dict, date_: str | None, force: bool) -> int:
    from .reseaux import preparer

    numero = _numero_vise(date_)
    chemin = DOSSIER_RESEAUX / f"{numero['date']}.json"
    if chemin.exists() and not force:
        print(f"Script déjà prêt : {chemin.relative_to(RACINE)}")
    else:
        ecrire_json(chemin, preparer(config, numero))
        print(f"Script vidéo et textes enregistrés : {chemin.relative_to(RACINE)}")
    sortie_github(date=numero["date"])
    return 0


def etape_video(config: dict, date_: str | None, sans_voix: bool) -> int:
    from .video import image_partage, rendre

    numero = _numero_vise(date_)
    script = lire_json(DOSSIER_RESEAUX / f"{numero['date']}.json")
    if not script:
        raise SystemExit("Lancez d'abord l'étape « reseaux ».")
    image_partage(config, numero, RACINE / "data" / "images" / f"{numero['date']}-partage.jpg")
    sortie = DOSSIER_MEDIAS / f"{numero['date']}.mp4"
    infos = rendre(config, script, sortie, avec_voix=not sans_voix)
    print(f"Vidéo prête : {sortie.relative_to(RACINE)} ({infos['duree']} s, {infos['scenes']} scènes, "
          f"{infos['plans_pexels']} plan(s) filmé(s))")
    script["credits_video"] = infos["credits"]
    ecrire_json(DOSSIER_RESEAUX / f"{numero['date']}.json", script)
    sortie_github(video="true", date=numero["date"])
    return 0


def etape_photos(config: dict, date_: str | None) -> int:
    """Photos d'illustration d'un numéro déjà rédigé (utile pour le numéro 1)."""
    from .pexels import disponible, illustrer_numero
    numero = _numero_vise(date_)
    if not disponible():
        print("Pas de clé Pexels : le site utilisera le ciel généré.")
        return 0
    if numero.get("image"):
        print("Photos déjà présentes.")
        return 0
    illustrer_numero(numero, RACINE / "data" / "images")
    ecrire_json(DOSSIER_NUMEROS / f"{numero['date']}.json", numero)
    print("Photos ajoutées.")
    return 0


def etape_voix(config: dict) -> int:
    """Échantillons des voix françaises, publiés sur la page /voix/ du site."""
    from .voix import echantillons
    dossier = DOSSIER_MEDIAS / "voix"
    liste = echantillons(dossier, config["video"].get("vitesse", 1.0))
    ecrire_json(dossier / "voix.json", {"voix": liste, "actuelle": config["video"]["voix"]})
    print(f"{len(liste)} voix enregistrées dans {dossier.relative_to(RACINE)}")
    return 0


def etape_apercu(config: dict) -> int:
    from .flux import collecter
    from .redaction import formater_articles

    fin = aujourdhui(config)
    articles = collecter(config.get("flux", []), fin - timedelta(days=6), fin, config["site"].get("fuseau"))
    print(formater_articles(articles, 200))
    print(f"\n{len(articles)} article(s).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sous = parser.add_subparsers(dest="etape", required=True)
    p = sous.add_parser("numero")
    p.add_argument("--force", action="store_true", help="rédiger même si la semaine est déjà couverte")
    p = sous.add_parser("reseaux")
    p.add_argument("--date")
    p.add_argument("--force", action="store_true")
    p = sous.add_parser("video")
    p.add_argument("--date")
    p.add_argument("--sans-voix", action="store_true", help="aperçu muet, sans appel à Google TTS")
    p = sous.add_parser("photos")
    p.add_argument("--date")
    sous.add_parser("voix")
    sous.add_parser("apercu")
    args = parser.parse_args(argv)

    config = charger_config()
    if args.etape == "numero":
        return etape_numero(config, args.force)
    if args.etape == "reseaux":
        return etape_reseaux(config, args.date, args.force)
    if args.etape == "video":
        return etape_video(config, args.date, args.sans_voix)
    if args.etape == "photos":
        return etape_photos(config, args.date)
    if args.etape == "voix":
        return etape_voix(config)
    return etape_apercu(config)


if __name__ == "__main__":
    sys.exit(main())
