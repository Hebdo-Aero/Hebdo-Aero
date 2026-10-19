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

from . import monetisation
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

    # Image d'ouverture : la photo de la banque d'images si elle existe, sinon le ciel généré pour ce numéro.
    if n.get("image") and (images / n["image"]["fichier"]).exists():
        n["couverture"] = {"src": f"images/{n['image']['fichier']}", "auteur": n["image"]["auteur"],
                           "page": n["image"]["page"], "source": n["image"].get("source", "Pexels")}
    else:
        ciel_fichier = images / f"{n['date']}-ciel.jpg"
        if not ciel_fichier.exists():
            from .ciel import enregistrer
            enregistrer(ciel_fichier, 1800, 1000, graine=int(n["numero"]), qualite=82)
        n["couverture"] = {"src": f"images/{ciel_fichier.name}"}
    for i, s in enumerate(n.get("une", [])):
        if s.get("image") and (images / s["image"]["fichier"]).exists():
            s["visuel"] = {"src": f"images/{s['image']['fichier']}", "auteur": s["image"]["auteur"],
                           "page": s["image"]["page"], "source": s["image"].get("source", "Pexels")}
        else:   # vignette dessinée : le ciel du numéro teinté à la couleur de la rubrique
            s["visuel"] = {"src": n["couverture"]["src"], "dessine": True, "position": ["20% 60%", "60% 70%", "90% 55%"][i % 3]}
    mots = len(" ".join([n.get("edito", "")] + [x["resume"] for x in n.get("une", []) + n.get("breves", [])]).split())
    n["lecture"] = max(1, round(mots / 220))

    reseaux = lire_json(DOSSIER_RESEAUX / f"{n['date']}.json") or {}
    # Shorts d'accroche de la semaine (page de travail /shorts/, pour TikTok)
    n["shorts"] = []
    publies = (reseaux.get("publications") or {}).get("accroches", {})
    for k, accroche in enumerate(reseaux.get("accroches", []), start=1):
        fichier = DOSSIER_MEDIAS / f"{n['date']}-accroche-{k}.mp4"
        if not fichier.exists():
            continue
        (sortie / "videos").mkdir(exist_ok=True)
        shutil.copy2(fichier, sortie / "videos" / fichier.name)
        if fichier.with_suffix(".jpg").exists():
            shutil.copy2(fichier.with_suffix(".jpg"), sortie / "videos" / fichier.with_suffix(".jpg").name)
        legende = accroche.get("legende", "")
        if accroche.get("credits"):
            legende += "\n\nImages d'illustration : " + ", ".join(accroche["credits"]) + "."
        n["shorts"].append({"video": f"videos/{fichier.name}", "affiche": f"videos/{fichier.with_suffix('.jpg').name}",
                            "legende": legende, "publie": str(k) in publies})
    # Vidéo d'annonce de la sortie (page /shorts/), produite même sans voix de synthèse
    fichier = DOSSIER_MEDIAS / f"{n['date']}-annonce.mp4"
    infos_annonce = lire_json(RACINE / "data" / "annonces" / f"{n['date']}.json") or {}
    n["annonce"] = None
    if fichier.exists():
        (sortie / "videos").mkdir(exist_ok=True)
        shutil.copy2(fichier, sortie / "videos" / fichier.name)
        if fichier.with_suffix(".jpg").exists():
            shutil.copy2(fichier.with_suffix(".jpg"), sortie / "videos" / fichier.with_suffix(".jpg").name)
        n["annonce"] = {"video": f"videos/{fichier.name}", "affiche": f"videos/{fichier.with_suffix('.jpg').name}",
                        "legende": infos_annonce.get("legende", "")}
    n["liens_reseaux"] = [(NOMS_RESEAUX[k], v["url"]) for k, v in (reseaux.get("publications") or {}).items()
                          if k in NOMS_RESEAUX and v.get("url")]

    # Partenaire de la semaine (publicité signalée), choisi d'après les dates indiquées dans config.toml
    partenaire = monetisation.partenaire_du_numero(config, n["date"])
    if partenaire:
        partenaire["lien_site"] = monetisation.lien_suivi(partenaire["lien"], "site", n["numero"])
        logo = partenaire["logo"]
        partenaire["logo_externe"] = logo.startswith("https://")
        partenaire["logo_src"] = logo if partenaire["logo_externe"] else (
            f"assets/partenaires/{logo}" if logo and (RACINE / "assets" / "partenaires" / logo).is_file() else "")
    n["partenaire"] = partenaire
    return n


def audience(config: dict, numeros: list[dict]) -> list[dict]:
    """Chiffres affichés sur la page « Annoncer » : ceux calculés ici, plus ceux indiqués dans config.toml."""
    def nombre(x: int) -> str:
        return f"{x:,}".replace(",", "\u202f")
    chiffres = [{"valeur": nombre(len(numeros)), "libelle": "numéro publié" if len(numeros) == 1 else "numéros publiés"}]
    infos = sum(len(n.get("une", [])) + len(n.get("breves", [])) for n in numeros)
    if infos:
        chiffres.append({"valeur": nombre(infos), "libelle": "informations sourcées publiées"})
    nl = monetisation.newsletter(config)
    if nl["active"]:
        from .newsletter import nombre_abonnes
        abonnes = nombre_abonnes()
        if abonnes is not None and abonnes >= int(nl.get("seuil_affichage_abonnes", 100)):
            chiffres.append({"valeur": nombre(abonnes), "libelle": "abonnés à la newsletter"})
    stats = config.get("statistiques") or {}
    if int(stats.get("visites_par_mois") or 0):
        chiffres.append({"valeur": nombre(int(stats["visites_par_mois"])), "libelle": "visites par mois sur le site"})
    if int(stats.get("abonnes_reseaux") or 0):
        chiffres.append({"valeur": nombre(int(stats["abonnes_reseaux"])), "libelle": "abonnés sur les réseaux sociaux"})
    if int(stats.get("vues_videos_par_mois") or 0):
        chiffres.append({"valeur": nombre(int(stats["vues_videos_par_mois"])), "libelle": "vues des vidéos par mois"})
    return chiffres


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

    def ecrire(chemin: str, gabarit: str, racine: str, pub: bool = False, **contexte) -> None:
        """`pub` : la page peut afficher des annonces (pages éditoriales seulement, jamais les pages de service)."""
        cible = sortie / chemin
        cible.parent.mkdir(parents=True, exist_ok=True)
        url_page = site["url"] + chemin.removesuffix("index.html") if site["url"] else ""
        image = contexte.pop("image", None)
        html = env.get_template(gabarit).render(
            site=site, racine=racine, url_page=url_page, flux=config.get("flux", []),
            rubriques=RUBRIQUES, profils=profils, newsletter=newsletter, soutien=soutien,
            publicite=dict(publicite, affichee=pub and publicite["active"] and bool(site["url"])),
            statistiques=balise_stats, statistiques_nom=nom_stats, annee=datetime.now().year,
            image_partage=(site["url"] + image) if image and site["url"] else "", **contexte)
        cible.write_text(html, encoding="utf-8")

    profils = [(NOMS_RESEAUX[k], v) for k, v in (config["reseaux"].get("profils") or {}).items()
               if k in NOMS_RESEAUX and v]
    newsletter, soutien = monetisation.newsletter(config), monetisation.soutien(config)
    # Mesure d'audience seulement sur le site en ligne (pas sur les aperçus locaux)
    balise_stats, nom_stats = monetisation.statistiques(config)
    if not site["url"]:
        balise_stats = ""
    publicite = monetisation.publicite(config)

    def pub_permise(n: dict | None) -> bool:     # exclusivité du partenaire de la semaine
        return not (n and n.get("partenaire") and publicite["masquer_avec_partenaire"])

    editeur = monetisation.editeur(config)
    if monetisation.revenus_actifs(config) and not editeur["complet"]:
        print("::warning title=Mentions légales::Le site peut rapporter de l'argent : complétez la section "
              "[editeur] de config.toml (nom, adresse, téléphone, directeur de la publication).")
    dernier = numeros[0] if numeros else None
    ecrire("index.html", "accueil.html", "", pub=pub_permise(dernier), page="accueil", dernier=dernier,
           precedents=numeros[1:9],
           image=dernier.get("image_partage") if dernier else None)
    for n in numeros:
        ecrire(f"numeros/{n['numero']}/index.html", "numero.html", "../../", pub=pub_permise(n), n=n,
               image=n.get("image_partage"))
    ecrire("archives/index.html", "archives.html", "../", pub=True, numeros=numeros, page="archives")
    if dernier:
        ecrire("shorts/index.html", "shorts.html", "../", n=dernier, shorts=dernier["shorts"])
    ecrire("a-propos/index.html", "a-propos.html", "../", pub=True, page="a-propos")
    ecrire("annoncer/index.html", "annoncer.html", "../", page="annoncer", audience=audience(config, numeros),
           annonceurs=config.get("annonceurs") or {})
    ecrire("mentions-legales/index.html", "mentions-legales.html", "../", page="mentions",
           editeur=editeur, hebergeur=monetisation.HEBERGEUR, revenus=monetisation.revenus_actifs(config))
    if newsletter["active"]:
        ecrire("newsletter/index.html", "newsletter.html", "../", page="newsletter", dernier=dernier)
        ecrire("newsletter/merci/index.html", "newsletter-merci.html", "../../", page="newsletter", dernier=dernier)
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
    if (RACINE / "assets" / "partenaires").is_dir():
        shutil.copytree(RACINE / "assets" / "partenaires", sortie / "assets" / "partenaires")
    # Images du jour pour les réseaux (data/cartes), publiées sur le site pour que Metricool les récupère
    cartes = RACINE / "data" / "cartes"
    if cartes.is_dir():
        (sortie / "cartes").mkdir(exist_ok=True)
        for image in cartes.glob("*.jpg"):
            shutil.copy2(image, sortie / "cartes" / image.name)
    # Vidéos de présentation du site, en ligne pour les publier sur les réseaux (Metricool lit une adresse publique)
    if (RACINE / "assets" / "promo").is_dir():
        shutil.copytree(RACINE / "assets" / "promo", sortie / "assets" / "promo")
    contenu_ads, alerte_ads = monetisation.ads_txt(config)
    if contenu_ads:
        (sortie / "ads.txt").write_text(contenu_ads, encoding="utf-8")
        if alerte_ads:
            print(f"::warning title=Publicité::{alerte_ads}")
    robots = "User-agent: *\nAllow: /\n" + (f"Sitemap: {site['url']}sitemap.xml\n" if site["url"] else "")
    (sortie / "robots.txt").write_text(robots, encoding="utf-8")
    (sortie / ".nojekyll").write_text("", encoding="utf-8")
    print(f"Site généré : {len(numeros)} numéro(s) dans {sortie}")
    return sortie


if __name__ == "__main__":
    construire()
