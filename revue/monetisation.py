"""Partenaires (sponsors), soutien, statistiques et mentions légales : ce qui permet à la revue de rapporter.

Tout se règle dans config.toml ; chaque section est facultative.
"""
from __future__ import annotations

import re
from datetime import date
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

HEBERGEUR = "GitHub, Inc., 88 Colin P. Kelly Jr. Street, San Francisco, CA 94107, États-Unis"

STATISTIQUES = {   # mesure d'audience sans cookie
    "cloudflare": ('<script defer src="https://static.cloudflareinsights.com/beacon.min.js" '
                   "data-cf-beacon='{{\"token\": \"{id}\"}}'></script>", "Cloudflare Web Analytics"),
    "goatcounter": ('<script data-goatcounter="https://{id}.goatcounter.com/count" async '
                    'src="https://gc.zgo.at/count.js"></script>', "GoatCounter"),
    "umami": ('<script defer src="https://cloud.umami.is/script.js" data-website-id="{id}"></script>', "Umami"),
}


def _en_date(valeur) -> date | None:
    if valeur in (None, ""):
        return None
    if isinstance(valeur, date):
        return valeur
    return date.fromisoformat(str(valeur)[:10])


def partenaire_du_numero(config: dict, date_numero: str | date) -> dict | None:
    """Le partenaire dont la période (du … au …, dates des numéros) couvre ce numéro."""
    jour = _en_date(date_numero)
    for p in config.get("partenaires", []) or []:
        if not p.get("nom") or not p.get("lien"):
            continue
        debut, fin = _en_date(p.get("du")), _en_date(p.get("au"))
        if (debut is None or debut <= jour) and (fin is None or jour <= fin):
            return {"nom": p["nom"].strip(), "texte": (p.get("texte") or "").strip(), "lien": p["lien"].strip(),
                    "logo": (p.get("logo") or "").strip(), "bouton": (p.get("bouton") or "Découvrir").strip(),
                    "video": bool(p.get("video", True))}
    return None


def lien_suivi(lien: str, support: str, numero: int) -> str:
    """Ajoute des paramètres UTM au lien du partenaire, pour qu'il mesure ce que la revue lui apporte."""
    morceaux = urlsplit(lien)
    params = parse_qsl(morceaux.query, keep_blank_values=True)
    if any(k.startswith("utm_") for k, _ in params):
        return lien
    params += [("utm_source", "hebdo-aero"), ("utm_medium", support), ("utm_campaign", f"numero-{numero}")]
    return urlunsplit(morceaux._replace(query=urlencode(params)))


def statistiques(config: dict) -> tuple[str, str]:
    """(balise <script>, nom du service) de la mesure d'audience, ou ("", "") si non configurée."""
    s = config.get("statistiques") or {}
    modele = STATISTIQUES.get((s.get("fournisseur") or "").strip().lower())
    identifiant = (s.get("identifiant") or "").strip()
    if not modele or not identifiant or not all(c.isalnum() or c in "-_" for c in identifiant):
        return "", ""
    return modele[0].format(id=identifiant), modele[1]


def newsletter(config: dict) -> dict:
    n = dict(config.get("newsletter") or {})
    n["formulaire"] = (n.get("formulaire") or "").strip()
    n["champ_email"] = (n.get("champ_email") or "email_address").strip()
    n["prestataire"] = (n.get("prestataire") or "Kit").strip()
    n["active"] = n["formulaire"].startswith("https://")
    return n


def soutien(config: dict) -> dict:
    s = dict(config.get("soutien") or {})
    s["url"] = (s.get("url") or "").strip()
    s["plateforme"] = (s.get("plateforme") or "").strip()
    s["active"] = s["url"].startswith("https://")
    return s


CHAMPS_EDITEUR = ("nom", "adresse", "telephone", "directeur_publication")


AUTORITES = {   # autorité de protection des données selon le pays de l'éditeur
    "france": ("la CNIL", "https://www.cnil.fr", "cnil.fr"),
    "luxembourg": ("la CNPD", "https://cnpd.public.lu", "cnpd.public.lu"),
    "belgique": ("l'Autorité de protection des données", "https://www.autoriteprotectiondonnees.be",
                 "autoriteprotectiondonnees.be"),
    "suisse": ("le PFPDT", "https://www.edoeb.admin.ch", "edoeb.admin.ch"),
}


def editeur(config: dict) -> dict:
    e = {k: str(v).strip() for k, v in (config.get("editeur") or {}).items()}
    e["complet"] = all(e.get(k) for k in CHAMPS_EDITEUR)
    pays = (e.get("pays") or "France").strip().lower()
    e["france"] = pays == "france"
    e["autorite"], e["autorite_url"], e["autorite_site"] = AUTORITES.get(pays, AUTORITES["france"])
    return e


def revenus_actifs(config: dict) -> bool:
    """Vrai dès que le site peut rapporter de l'argent (partenaire, soutien, publicité) : mentions légales requises."""
    return bool(config.get("partenaires")) or soutien(config)["active"] or publicite(config)["active"]


def publicite(config: dict) -> dict:
    """Google AdSense : identifiant d'éditeur « ca-pub-… », blocs manuels facultatifs."""
    p = dict(config.get("publicite") or {})
    client = (p.get("adsense") or "").strip()
    p["active"] = bool(re.fullmatch(r"ca-pub-\d{10,20}", client))
    p["client"] = client if p["active"] else ""
    for cle in ("bloc_numero", "bloc_breves"):
        valeur = str(p.get(cle) or "").strip()
        p[cle] = valeur if valeur.isdigit() else ""
    p["masquer_avec_partenaire"] = bool(p.get("masquer_avec_partenaire", True))
    return p


def ads_txt(config: dict) -> tuple[str, str]:
    """(contenu du fichier ads.txt, avertissement éventuel). Le fichier n'est lu par Google qu'à la racine du domaine."""
    pub = publicite(config)
    if not pub["active"]:
        return "", ""
    contenu = f"google.com, {pub['client'].removeprefix('ca-')}, DIRECT, f08c47fec0942fa0\n"
    chemin = urlsplit(config["site"].get("url") or "").path
    alerte = ""
    if chemin not in ("", "/"):
        alerte = ("Le site est dans un sous-dossier : Google ne trouvera pas ads.txt. Renommez le dépôt en "
                  "« <compte>.github.io » ou utilisez un nom de domaine pour que le site soit à la racine.")
    return contenu, alerte
