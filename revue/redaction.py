"""Rédaction du numéro de la semaine par Claude, puis contrôle qualité."""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timezone

from . import claude
from .config import CATEGORIES, REGIONS, periode_fr
from .flux import Article, normaliser_url

SYSTEME = """Tu es le rédacteur en chef de « {nom} », une revue hebdomadaire en français consacrée \
à l'aviation commerciale dans le monde (compagnies aériennes, constructeurs, commandes et livraisons, \
aéroports, maintenance, résultats financiers, sécurité, réglementation, environnement). \
La défense, le spatial et l'aviation légère sont hors sujet, sauf s'ils touchent directement \
le transport aérien commercial.

Règles absolues :
1. Tu n'écris que des faits présents dans les articles fournis ou dans tes résultats de recherche web. \
Aucun chiffre, aucune date, aucun nom ne doit venir de ta mémoire.
2. Chaque sujet cite 1 à 3 sources, avec leur URL exacte telle qu'elle apparaît dans la liste \
ou dans tes résultats de recherche.
3. Tu reformules entièrement, en français, avec tes propres mots. Tu ne recopies jamais une phrase \
d'article ; pas de citation de plus de dix mots.
4. Un même événement couvert par plusieurs médias devient un seul sujet qui cite ces médias.
5. Ton factuel, précis et neutre, comme une agence de presse. Pas d'opinion, pas d'emphase, \
pas d'emojis. Les drames humains sont traités avec sobriété.
6. Ne retiens que les faits de la période indiquée.

Tu peux utiliser la recherche web pour vérifier un fait important ou combler un manque évident \
(par exemple un événement majeur de la semaine absent des flux), en restant sobre sur le nombre \
de recherches.

Quand la revue est prête, appelle l'outil publier_numero, une seule fois."""

CONSIGNE = """Période couverte : du {periode} (numéro {numero}).

Rédige la revue de la semaine :
- un titre de semaine accrocheur mais exact (moins de 100 caractères) ;
- un éditorial de 3 ou 4 phrases qui dégage les grandes tendances ;
- exactement 3 sujets « À la une », les plus importants de la semaine pour le transport aérien mondial ;
- environ {breves} brèves, variées en catégories et en régions du monde ;
- le chiffre de la semaine, tiré d'un des sujets.

Chaque résumé fait 2 à 4 phrases et donne les faits essentiels (qui, quoi, combien, quand).

Articles collectés dans les flux RSS ({nb} articles) :

{articles}"""

_ILLUSTRATION = ("2 à 4 mots-clés EN ANGLAIS pour chercher une photo d'illustration générique, sans nom de "
                 "compagnie, de marque ni de lieu précis. Exemples : « airport terminal night », "
                 "« cargo plane loading », « airplane cabin passengers ».")
_SOURCE = {
    "type": "object",
    "properties": {
        "nom": {"type": "string", "description": "Nom du média, par exemple « AeroTime »."},
        "url": {"type": "string", "description": "URL exacte de l'article."},
    },
    "required": ["nom", "url"],
}
_SUJET = {
    "type": "object",
    "properties": {
        "titre": {"type": "string", "description": "Titre informatif, 110 caractères au plus."},
        "resume": {"type": "string", "description": "2 à 4 phrases reformulées, 650 caractères au plus."},
        "categorie": {"type": "string", "enum": CATEGORIES},
        "region": {"type": "string", "enum": REGIONS},
        "sources": {"type": "array", "items": _SOURCE, "minItems": 1, "maxItems": 3},
        "illustration": {"type": "string", "description": _ILLUSTRATION},
    },
    "required": ["titre", "resume", "categorie", "region", "sources"],
}
OUTIL_PUBLIER = {
    "name": "publier_numero",
    "description": "Transmet le numéro complet de la revue, prêt à publier.",
    "input_schema": {
        "type": "object",
        "properties": {
            "titre": {"type": "string"},
            "edito": {"type": "string"},
            "illustration": {"type": "string", "description": "Photo d'ouverture du numéro. " + _ILLUSTRATION},
            "une": {"type": "array", "items": _SUJET, "minItems": 3, "maxItems": 3},
            "breves": {"type": "array", "items": _SUJET},
            "chiffre": {
                "type": "object",
                "properties": {
                    "valeur": {"type": "string", "description": "Court : « 6 Md$ », « 72 », « +16 % »."},
                    "legende": {"type": "string", "description": "Une phrase qui explique le chiffre."},
                    "source": _SOURCE,
                },
                "required": ["valeur", "legende", "source"],
            },
        },
        "required": ["titre", "edito", "une", "breves", "chiffre"],
    },
}


def formater_articles(articles: list[Article], longueur_extrait: int = 500) -> str:
    lignes = []
    for a in articles:
        extrait = a.extrait[:longueur_extrait].rsplit(" ", 1)[0] + "…" if len(a.extrait) > longueur_extrait else a.extrait
        lignes.append(f"- [{a.source}] {a.titre} ({a.publie:%Y-%m-%d})\n  URL : {a.url}\n  Extrait : {extrait}")
    return "\n".join(lignes)


def rediger(config: dict, articles: list[Article], numero: int, debut: date, fin: date,
            appelant=claude.appeler) -> dict:
    r = config["redaction"]
    systeme = SYSTEME.format(nom=config["site"]["nom"])
    consigne = CONSIGNE.format(periode=periode_fr(debut, fin), numero=numero, breves=r["breves_cible"],
                               nb=len(articles), articles=formater_articles(articles))
    brut, urls_recherche, conso = claude.executer_avec_outil(
        modele=r["modele"], systeme=systeme, consigne=consigne, outil_final=OUTIL_PUBLIER,
        recherches_max=r.get("recherches_web_max", 0), appelant=appelant)
    claude.log("Rédaction : " + claude.resume_conso(r["modele"], conso))

    numero_valide = valider(brut, articles, urls_recherche, minimum=r.get("articles_minimum", 6))
    numero_valide.update({
        "numero": numero,
        "date": fin.isoformat(),
        "debut": debut.isoformat(),
        "fin": fin.isoformat(),
        "genere_par": r["modele"],
        "genere_le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    return numero_valide


# --- Contrôle qualité -----------------------------------------------------------------

class NumeroInvalide(RuntimeError):
    pass


def _mots(texte: str) -> list[str]:
    texte = unicodedata.normalize("NFKD", texte.lower())
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    return re.findall(r"[a-z0-9]+", texte)


def recopie(resume: str, extraits: list[str], n: int = 9) -> bool:
    """Vrai si le résumé reprend mot pour mot une suite de `n` mots d'un extrait."""
    mots = _mots(resume)
    if len(mots) < n:
        return False
    sequences = {" ".join(mots[i:i + n]) for i in range(len(mots) - n + 1)}
    for extrait in extraits:
        m = _mots(extrait)
        if any(" ".join(m[i:i + n]) in sequences for i in range(len(m) - n + 1)):
            return True
    return False


def _couper(texte: str, limite: int) -> str:
    texte = re.sub(r"\s+", " ", (texte or "")).strip()
    if len(texte) <= limite:
        return texte
    coupe = texte[:limite]
    fin_phrase = coupe.rfind(". ")
    return coupe[:fin_phrase + 1] if fin_phrase > limite * 0.6 else coupe.rsplit(" ", 1)[0] + "…"


def valider(brut: dict, articles: list[Article], urls_recherche: set[str], minimum: int = 6) -> dict:
    autorisees = {normaliser_url(a.url): a.url for a in articles}
    autorisees.update({normaliser_url(u): u for u in urls_recherche})
    extraits = [a.extrait for a in articles]
    rejets: list[str] = []

    def sources_valides(sources) -> list[dict]:
        propres = []
        for s in sources or []:
            cle = normaliser_url(s.get("url", ""))
            if cle in autorisees and all(normaliser_url(p["url"]) != cle for p in propres):
                propres.append({"nom": _couper(s.get("nom") or "Source", 60), "url": autorisees[cle]})
        return propres[:3]

    def sujet_valide(s: dict) -> dict | None:
        sources = sources_valides(s.get("sources"))
        if not sources:
            rejets.append(f"sans source vérifiable : {s.get('titre')}")
            return None
        if s.get("categorie") not in CATEGORIES or s.get("region") not in REGIONS:
            rejets.append(f"catégorie ou région inconnue : {s.get('titre')}")
            return None
        if recopie(s.get("resume", ""), extraits):
            rejets.append(f"résumé trop proche d'un article : {s.get('titre')}")
            return None
        propre = {
            "titre": _couper(s.get("titre"), 110),
            "resume": _couper(s.get("resume"), 650),
            "categorie": s["categorie"],
            "region": s["region"],
            "sources": sources,
        }
        if s.get("illustration"):
            propre["illustration"] = _couper(s["illustration"], 60)
        return propre

    une = [v for v in (sujet_valide(s) for s in brut.get("une", [])) if v]
    breves = [v for v in (sujet_valide(s) for s in brut.get("breves", [])) if v]
    while len(une) < 3 and breves:      # une brève remonte si un sujet de une est écarté
        une.append(breves.pop(0))

    for r in rejets:
        claude.log(f"  écarté, {r}")
    if len(une) + len(breves) < minimum:
        raise NumeroInvalide(f"Seulement {len(une) + len(breves)} sujet(s) valides (minimum {minimum}).")

    chiffre = brut.get("chiffre") or {}
    source_chiffre = sources_valides([chiffre.get("source")]) if chiffre.get("source") else []
    return {
        "titre": _couper(brut.get("titre"), 110),
        "edito": _couper(brut.get("edito"), 900),
        "illustration": _couper(brut.get("illustration") or "airplane sunset sky", 60),
        "chiffre": {
            "valeur": _couper(chiffre.get("valeur"), 16),
            "legende": _couper(chiffre.get("legende"), 180),
            "source": source_chiffre[0],
        } if chiffre.get("valeur") and source_chiffre else None,
        "une": une[:3],
        "breves": breves,
    }
