"""Newsletter du dimanche : envoie le numéro de la semaine aux abonnés, via Kit (secret KIT_API_KEY).

Usage :
  python -m revue.newsletter                       envoie le dernier numéro (une seule fois par numéro)
  python -m revue.newsletter --apercu email.html   écrit l'e-mail dans un fichier, sans rien envoyer

L'e-mail part à l'heure réglée dans config.toml ([newsletter] heure_envoi, heure de Paris),
ou quelques minutes après la mise en ligne si cette heure est déjà passée.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import monetisation
from .config import CATEGORIES, RACINE, RUBRIQUES, charger_config, ecrire_json, lire_json, lister_numeros, periode_fr
from .http import ErreurHTTP, get_json, post_json, requete

API = "https://api.kit.com/v4"
DOSSIER_ENVOIS = RACINE / "data" / "newsletter"
# Couleurs des rubriques lisibles sur fond blanc
COULEURS = {"orange": "#C2410C", "ciel": "#1667A8", "soleil": "#A16207", "violet": "#7C3AED",
            "rouge": "#DC2626", "vert": "#15803D"}
NOMS_RESEAUX = {"youtube": "YouTube", "instagram": "Instagram", "facebook": "Facebook", "threads": "Threads"}


class ErreurNewsletter(RuntimeError):
    pass


def disponible() -> bool:
    return bool(os.environ.get("KIT_API_KEY"))


def _entetes() -> dict:
    return {"X-Kit-Api-Key": os.environ["KIT_API_KEY"], "Accept": "application/json"}


def nombre_abonnes() -> int | None:
    """Nombre d'abonnés actifs (affiché sur la page « Annoncer » au-delà d'un seuil), ou None."""
    if not disponible():
        return None
    try:
        rep = get_json(f"{API}/subscribers", {"status": "active", "include_total_count": "true", "per_page": 1},
                       entetes=_entetes(), delai=30, essais=2)
    except (ErreurHTTP, ValueError):
        return None
    for source in (rep.get("pagination") or {}, rep):
        if isinstance(source.get("total_count"), int):
            return source["total_count"]
    return None


def _existe_en_ligne(url: str) -> bool:
    try:
        statut, _, _ = requete(url, methode="HEAD", delai=20, essais=2)
        return statut == 200
    except ErreurHTTP:
        return False


def _premiere_phrase(texte: str, limite: int = 140) -> str:
    phrase = re.split(r"(?<=[.!?])\s", texte.strip(), maxsplit=1)[0]
    return phrase if len(phrase) <= limite else phrase[:limite - 1].rsplit(" ", 1)[0] + "…"


def contenu(config: dict, numero: dict, verifier_en_ligne: bool = True) -> dict:
    """Sujet, texte d'aperçu et HTML de l'e-mail d'un numéro."""
    site = config["site"]
    base = site["url"]
    n = dict(numero)
    n["periode"] = periode_fr(n["debut"], n["fin"])
    n["une"] = [dict(s, couleur=COULEURS.get(RUBRIQUES.get(s["categorie"], {}).get("couleur"), "#4B5D73"))
                for s in n.get("une", [])]
    rubriques = []
    for c in CATEGORIES:
        breves = [b for b in n.get("breves", []) if b["categorie"] == c]
        if breves:
            r = RUBRIQUES[c]
            rubriques.append({"nom": c, "ancre": r["ancre"], "couleur": COULEURS.get(r["couleur"], "#4B5D73"),
                              "breves": breves})
    n["rubriques"] = rubriques

    url_numero = f"{base}numeros/{n['numero']}/"
    affiche = f"{base}videos/{n['date']}.jpg"
    if not verifier_en_ligne or not _existe_en_ligne(affiche):
        affiche = ""

    partenaire = monetisation.partenaire_du_numero(config, n["date"])
    if partenaire:
        partenaire["lien_email"] = monetisation.lien_suivi(partenaire["lien"], "newsletter", n["numero"])
        logo = partenaire["logo"]
        partenaire["logo_url"] = logo if logo.startswith("https://") else (
            f"{base}assets/partenaires/{logo}" if logo and (RACINE / "assets" / "partenaires" / logo).is_file() else "")

    profils = [(NOMS_RESEAUX[k], v) for k, v in (config["reseaux"].get("profils") or {}).items()
               if k in NOMS_RESEAUX and v]
    apercu = _premiere_phrase(n.get("edito", ""))
    env = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"),
                      autoescape=select_autoescape(["html"]), trim_blocks=True, lstrip_blocks=True)
    html = env.get_template("email.html").render(
        site=site, n=n, url_site=base, url_numero=url_numero, logo=f"{base}assets/logo/logo-email.png",
        affiche=affiche, partenaire=partenaire, soutien=monetisation.soutien(config),
        profils=profils, apercu=apercu)
    sujet = f"N° {n['numero']} · {n['titre']}"
    if len(sujet) > 120:
        sujet = sujet[:119].rsplit(" ", 1)[0] + "…"
    return {"sujet": sujet, "apercu": apercu, "html": html, "partenaire": partenaire["nom"] if partenaire else None}


def heure_envoi(config: dict, maintenant: datetime | None = None) -> datetime:
    """L'heure prévue (heure de Paris par défaut) aujourd'hui, ou dans 5 minutes si elle est passée."""
    fuseau = ZoneInfo(config["site"].get("fuseau", "Europe/Paris"))
    maintenant = maintenant or datetime.now(timezone.utc)
    h, m = (int(x) for x in str((config.get("newsletter") or {}).get("heure_envoi", "08:30")).split(":")[:2])
    prevue = maintenant.astimezone(fuseau).replace(hour=h, minute=m, second=0, microsecond=0)
    plancher = maintenant + timedelta(minutes=5)
    return max(prevue.astimezone(timezone.utc), plancher).replace(microsecond=0)


def envoyer(config: dict, numero: dict, maintenant: datetime | None = None) -> dict:
    """Programme l'envoi du numéro à tous les abonnés (Kit) et renvoie le résumé de l'envoi."""
    if not config["site"]["url"]:
        raise ErreurNewsletter("Adresse du site inconnue : les liens de l'e-mail seraient cassés.")
    mail = contenu(config, numero)
    maintenant = maintenant or datetime.now(timezone.utc)
    quand = heure_envoi(config, maintenant)
    charge = {
        "subject": mail["sujet"],
        "preview_text": mail["apercu"],
        "content": mail["html"],
        "description": f"{config['site']['nom']} N° {numero['numero']}",
        "public": False,
        "published_at": maintenant.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "send_at": quand.isoformat().replace("+00:00", "Z"),
    }
    try:
        # Un seul essai : un nouvel essai après une erreur réseau pourrait créer un doublon.
        rep = post_json(f"{API}/broadcasts", charge, entetes=_entetes(), delai=60, essais=1)
    except ErreurHTTP as e:
        if e.code == 401:
            raise ErreurNewsletter("Clé Kit refusée : vérifiez le secret KIT_API_KEY (clé API v4).") from None
        if e.code == 403:
            raise ErreurNewsletter("Kit refuse l'envoi : votre compte doit être confirmé et avoir une adresse "
                                   "d'expédition vérifiée.") from None
        raise ErreurNewsletter(f"Kit a refusé l'envoi : {e}") from None
    diffusion = rep.get("broadcast", rep)
    return {"id": diffusion.get("id"), "envoi_prevu": charge["send_at"], "sujet": mail["sujet"],
            "partenaire": mail["partenaire"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--date", help="date du numéro (par défaut : le plus récent)")
    parser.add_argument("--apercu", type=Path, help="écrit l'e-mail dans ce fichier HTML, sans l'envoyer")
    parser.add_argument("--force", action="store_true", help="envoyer même un numéro de plus d'une semaine")
    args = parser.parse_args(argv)

    config = charger_config()
    numeros = lister_numeros()
    numero = next((n for n in numeros if n["date"] == args.date), None) if args.date else (numeros[0] if numeros else None)
    if not numero:
        print("Aucun numéro à envoyer.")
        return 0
    if args.apercu:
        mail = contenu(config, numero, verifier_en_ligne=False)
        args.apercu.write_text(f"<!-- Sujet : {mail['sujet']} -->\n{mail['html']}", encoding="utf-8")
        print(f"Aperçu écrit dans {args.apercu} (sujet : {mail['sujet']})")
        return 0
    if not disponible():
        print("Pas de secret KIT_API_KEY : la newsletter n'est pas envoyée.")
        return 0
    trace = DOSSIER_ENVOIS / f"{numero['date']}.json"
    if lire_json(trace):
        print(f"La newsletter du numéro {numero['numero']} est déjà partie.")
        return 0
    age = (datetime.now(timezone.utc).date() - datetime.fromisoformat(numero["date"]).date()).days
    if age > 6 and not args.force:
        print(f"Le dernier numéro date de {age} jours : rien n'est envoyé (utilisez --force pour l'envoyer quand même).")
        return 0
    try:
        envoi = envoyer(config, numero)
    except ErreurNewsletter as e:
        print(f"::error title=Newsletter::{e}")
        return 1
    ecrire_json(trace, {"numero": numero["numero"], **envoi})
    rapport = (f"### Newsletter\n\nNuméro {numero['numero']} programmé pour {envoi['envoi_prevu']} (UTC)"
               f" : « {envoi['sujet']} »" + (f", partenaire : {envoi['partenaire']}" if envoi["partenaire"] else "") + "\n")
    print(rapport)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(rapport)
    return 0


if __name__ == "__main__":
    sys.exit(main())
