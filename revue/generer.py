"""Étapes de production de la revue.

  python -m revue.generer numero [--force]       rédige le numéro de la semaine (Claude)
  python -m revue.generer reseaux [--date …]     script vidéo et textes des réseaux (Claude)
  python -m revue.generer video [--sans-voix]    narration Google TTS + rendu MP4
  python -m revue.generer annonce                vidéo d'annonce de la sortie (sans voix, pour TikTok et Reels)
  python -m revue.generer photos                 photos d'illustration du dernier numéro
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


def dernier_dimanche(jour: date) -> date:
    """Le dimanche le plus récent (le jour même si c'est un dimanche)."""
    return jour - timedelta(days=(jour.weekday() - 6) % 7)


def periode_a_couvrir(config: dict, force: bool) -> tuple[int, date, date] | None:
    """Numéro et semaine à rédiger : toujours une semaine du lundi au dimanche.

    Lancé un autre jour que le dimanche (relance à la main après un échec, par exemple), le numéro
    couvre quand même la semaine qui s'est terminée le dimanche précédent : le rythme reste le même.
    Avec `force`, le numéro de cette semaine est rédigé à nouveau s'il existe déjà.
    """
    fin = dernier_dimanche(aujourdhui(config))
    debut = fin - timedelta(days=6)
    numeros = lister_numeros()
    dernier = numeros[0] if numeros else None
    if dernier:
        fin_precedente = date.fromisoformat(dernier["fin"])
        if fin_precedente >= fin:
            if force:
                print(f"Le numéro {dernier['numero']} est rédigé à nouveau.")
                return dernier["numero"], date.fromisoformat(dernier.get("debut", debut.isoformat())), fin_precedente
            print(f"Le numéro {dernier['numero']} couvre déjà cette semaine (jusqu'au {dernier['fin']}).")
            return None
        if fin_precedente >= debut:
            debut = fin_precedente + timedelta(days=1)
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
    from .illustrations import disponible, illustrer_numero
    if disponible():
        print("Recherche des photos d'illustration…")
        illustrer_numero(contenu, RACINE / "data" / "images",
                         photos_sujets=bool(config.get("illustrations", {}).get("photos_sujets", False)))
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
          f"{infos['plans_filmes']} plan(s) filmé(s))")
    script["credits_video"] = infos["credits"]

    # Shorts d'accroche pour TikTok et Instagram : un échec n'empêche pas la publication du récap.
    for k, accroche in enumerate(script.get("accroches", []), start=1):
        fichier = DOSSIER_MEDIAS / f"{numero['date']}-accroche-{k}.mp4"
        try:
            infos_k = rendre(config, script, fichier, avec_voix=not sans_voix, scenes=accroche["scenes"], court=True)
        except Exception as e:  # noqa: BLE001
            print(f"::warning::Short d'accroche {k} non produit : {e}")
            continue
        accroche["credits"] = infos_k["credits"]
        print(f"Short d'accroche {k} prêt : {fichier.relative_to(RACINE)} ({infos_k['duree']} s)")
    ecrire_json(DOSSIER_RESEAUX / f"{numero['date']}.json", script)
    sortie_github(video="true", date=numero["date"])
    return 0


def etape_annonce(config: dict, date_: str | None) -> int:
    """Vidéo d'annonce de la sortie du numéro (sans voix), avec les vrais titres de la semaine."""
    from .annonce import rendre
    numero = _numero_vise(date_)
    sortie = DOSSIER_MEDIAS / f"{numero['date']}-annonce.mp4"
    infos = rendre(config, numero, sortie)
    ecrire_json(RACINE / "data" / "annonces" / f"{numero['date']}.json", infos)
    fond = "plans d'avions filmés" if infos["filme"] else "avions dessinés"
    print(f"Vidéo d'annonce prête : {sortie.relative_to(RACINE)} ({infos['duree']} s, {fond})")
    return 0


def etape_photos(config: dict, date_: str | None) -> int:
    """Photos d'illustration d'un numéro déjà rédigé (utile pour le numéro 1)."""
    from .illustrations import disponible, illustrer_numero
    numero = _numero_vise(date_)
    if not disponible():
        print("Pas de clé Pexels ni Pixabay : le site utilisera le ciel généré.")
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


def etape_recuperer(config: dict) -> int:
    """Avant de reconstruire le site, récupère les vidéos de la semaine déjà en ligne.

    Sans cela, une simple mise à jour du site (modification de config.toml, par exemple)
    effacerait la vidéo et les shorts de la semaine, que le mardi et le jeudi publient encore.
    """
    from .http import ErreurHTTP, requete
    site = config["site"]["url"]
    numeros = lister_numeros()
    if not site or not numeros:
        return 0
    numero = numeros[0]
    script = lire_json(DOSSIER_RESEAUX / f"{numero['date']}.json") or {}
    noms = [f"{numero['date']}.mp4", f"{numero['date']}.jpg",
            f"{numero['date']}-annonce.mp4", f"{numero['date']}-annonce.jpg"]
    for k in range(1, len(script.get("accroches", [])) + 1):
        noms += [f"{numero['date']}-accroche-{k}.mp4", f"{numero['date']}-accroche-{k}.jpg"]
    for nom in noms:
        cible = DOSSIER_MEDIAS / nom
        if cible.exists():
            continue
        try:
            _, _, contenu = requete(f"{site}videos/{nom}", delai=180, essais=2)
        except ErreurHTTP:
            continue
        cible.parent.mkdir(parents=True, exist_ok=True)
        cible.write_bytes(contenu)
        print(f"  récupéré : {nom}")
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
    p = sous.add_parser("annonce")
    p.add_argument("--date")
    p = sous.add_parser("photos")
    p.add_argument("--date")
    sous.add_parser("voix")
    sous.add_parser("recuperer")
    sous.add_parser("apercu")
    args = parser.parse_args(argv)

    config = charger_config()
    if args.etape in ("numero", "reseaux"):
        from .claude import ErreurClaude, expliquer
        from .http import ErreurHTTP
        try:
            if args.etape == "numero":
                return etape_numero(config, args.force)
            return etape_reseaux(config, args.date, args.force)
        except (ErreurClaude, ErreurHTTP) as e:   # message clair dans le résumé GitHub et l'e-mail d'échec
            print(f"::error title=Rédaction (Claude)::{expliquer(e)}")
            return 1
    if args.etape == "video":
        from .voix import ErreurVoix
        try:
            return etape_video(config, args.date, args.sans_voix)
        except ErreurVoix as e:      # message clair dans GitHub plutôt qu'une pile d'appels
            print(f"::error title=Voix-off::{e}")
            return 1
    if args.etape == "annonce":
        return etape_annonce(config, args.date)
    if args.etape == "photos":
        return etape_photos(config, args.date)
    if args.etape == "voix":
        return etape_voix(config)
    if args.etape == "recuperer":
        return etape_recuperer(config)
    return etape_apercu(config)


if __name__ == "__main__":
    sys.exit(main())
