"""Script de la vidéo et textes des publications, rédigés par Claude à partir du numéro validé."""
from __future__ import annotations

import json
import re

from . import claude
from .config import periode_fr

SYSTEME = """Tu prépares la déclinaison vidéo et réseaux sociaux de « {nom} », revue hebdomadaire \
en français sur l'aviation commerciale. Tu travailles UNIQUEMENT à partir du numéro fourni : aucun \
fait, chiffre ou nom qui n'y figure pas. Ton clair, vivant et précis, jamais racoleur. \
Les sujets graves (accidents, attaques, victimes) sont traités avec sobriété.

La vidéo est verticale, dure moins de 85 secondes au total et est lue par une voix de synthèse : \
écris la narration pour l'oreille (phrases courtes, nombres faciles à dire, pas de sigles obscurs, \
pas de parenthèses). Les textes à l'écran sont très courts, car lus sur téléphone.

Appelle l'outil preparer_reseaux une seule fois."""

CONSIGNE = """Voici le numéro {numero} (semaine du {periode}) au format JSON :

{json}

Prépare :
- 5 scènes vidéo pour les 5 sujets les plus marquants (les 3 sujets à la une d'abord), sans reprendre \
le sujet du chiffre de la semaine, qui a sa propre scène ;
- la narration de la scène « chiffre de la semaine » ;
- le titre YouTube et les textes Instagram, Facebook et Threads (sans lien ni hashtag : ils sont ajoutés \
automatiquement)."""

OUTIL = {
    "name": "preparer_reseaux",
    "description": "Transmet le script vidéo et les textes des réseaux sociaux.",
    "input_schema": {
        "type": "object",
        "properties": {
            "scenes": {
                "type": "array", "minItems": 4, "maxItems": 5,
                "items": {
                    "type": "object",
                    "properties": {
                        "surtitre": {"type": "string", "description": "Lieu ou thème, 28 caractères au plus."},
                        "titre_ecran": {"type": "string", "description": "Titre à l'écran, 46 caractères au plus."},
                        "texte_ecran": {"type": "string", "description": "Le fait clé à l'écran, 70 caractères au plus."},
                        "narration": {"type": "string", "description": "Texte lu : 2 phrases, 34 mots au plus."},
                        "recherche_video": {"type": "string", "description":
                            "2 à 4 mots-clés EN ANGLAIS pour trouver un plan vidéo d'illustration générique "
                            "(banque d'images), sans nom de compagnie ni de marque. Exemples : « airplane takeoff », "
                            "« airport terminal crowd », « aircraft factory », « cargo plane loading »."},
                    },
                    "required": ["surtitre", "titre_ecran", "texte_ecran", "narration", "recherche_video"],
                },
            },
            "chiffre_narration": {"type": "string", "description": "25 mots au plus, commence par « Le chiffre de la semaine »."},
            "youtube_titre": {"type": "string", "description": "70 caractères au plus."},
            "instagram": {"type": "string", "description": "Légende de 2 à 4 phrases."},
            "facebook": {"type": "string", "description": "Publication de 2 à 4 phrases."},
            "threads": {"type": "string", "description": "300 caractères au plus."},
        },
        "required": ["scenes", "chiffre_narration", "youtube_titre", "instagram", "facebook", "threads"],
    },
}

MENTION_IA = ("Résumé rédigé par IA à partir des sources citées sur le site, "
              "voix de synthèse. Signalez toute erreur via le site.")


def _court(texte: str, limite: int) -> str:
    texte = re.sub(r"\s+", " ", texte or "").strip()
    return texte if len(texte) <= limite else texte[:limite - 1].rsplit(" ", 1)[0] + "…"


def _mots(texte: str) -> int:
    return len(re.findall(r"\w+", texte))


def preparer(config: dict, numero: dict, appelant=claude.appeler) -> dict:
    nom = config["site"]["nom"]
    publiable = {k: numero[k] for k in ("titre", "edito", "chiffre", "une", "breves")}
    brut, _, conso = claude.executer_avec_outil(
        modele=config["redaction"]["modele"],
        systeme=SYSTEME.format(nom=nom),
        consigne=CONSIGNE.format(numero=numero["numero"], periode=periode_fr(numero["debut"], numero["fin"]),
                                 json=json.dumps(publiable, ensure_ascii=False, indent=1)),
        outil_final=OUTIL, max_tokens=6000, appelant=appelant)
    claude.log("Réseaux : " + claude.resume_conso(config["redaction"]["modele"], conso))
    return assembler(config, numero, brut)


def assembler(config: dict, numero: dict, brut: dict) -> dict:
    """Construit le script complet (intro, sujets, chiffre, conclusion) et les légendes finales."""
    nom = config["site"]["nom"]
    nom_parle = config["site"].get("nom_parle") or nom   # orthographe pour la voix de synthèse
    periode = periode_fr(numero["debut"], numero["fin"])
    scenes = [{
        "type": "intro",
        "surtitre": f"N° {numero['numero']}",
        "titre_ecran": nom,
        "texte_ecran": f"Semaine du {periode}",
        "narration": f"{nom_parle}, numéro {numero['numero']}. L'essentiel de l'aviation commerciale, "
                     f"semaine du {periode}.",
        "recherche_video": config["video"].get("recherche_intro", "airplane takeoff sunset"),
    }]
    for s in brut.get("scenes", [])[:5]:
        if not s.get("narration") or not s.get("titre_ecran"):
            continue
        scenes.append({
            "type": "sujet",
            "surtitre": _court(s.get("surtitre"), 28),
            "titre_ecran": _court(s["titre_ecran"], 52),
            "texte_ecran": _court(s.get("texte_ecran"), 80),
            "narration": s["narration"].strip(),
            "recherche_video": _court(s.get("recherche_video") or "airplane flying", 60),
        })
    if numero.get("chiffre") and brut.get("chiffre_narration"):
        scenes.append({
            "type": "chiffre",
            "surtitre": "Le chiffre de la semaine",
            "titre_ecran": numero["chiffre"]["valeur"],
            "texte_ecran": _court(numero["chiffre"]["legende"], 110),
            "narration": brut["chiffre_narration"].strip(),
        })
    scenes.append({
        "type": "fin",
        "surtitre": "Sources et détails",
        "titre_ecran": nom,
        "texte_ecran": "{lien_court}",
        "narration": f"Toutes les sources sont sur le site {nom_parle}. Rendez-vous dimanche prochain.",
        "recherche_video": config["video"].get("recherche_fin", "airplane above clouds"),
    })

    # Garde-fou de durée : environ 2,7 mots par seconde ; on retire des sujets si besoin.
    budget = int(config["video"].get("duree_max", 88) * 2.6)
    while sum(_mots(s["narration"]) for s in scenes) > budget and \
            sum(1 for s in scenes if s["type"] == "sujet") > 3:
        dernier = max(i for i, s in enumerate(scenes) if s["type"] == "sujet")
        scenes.pop(dernier)

    lien = "{lien}"   # remplacé par l'adresse réelle du site au moment du rendu et de la publication
    tags = " ".join("#" + h for h in config["reseaux"].get("hashtags", []))
    titre_yt = _court(brut.get("youtube_titre") or numero["titre"], 90)
    return {
        "numero": numero["numero"],
        "date": numero["date"],
        "video": {"scenes": scenes},
        "legendes": {
            "youtube_titre": titre_yt,
            "youtube_description": "\n\n".join(filter(None, [
                brut.get("facebook", "").strip(),
                f"Le numéro complet et toutes les sources : {lien}" if lien else "",
                MENTION_IA,
                tags + " #Shorts",
            ])),
            "instagram": "\n\n".join(filter(None, [
                brut.get("instagram", "").strip(),
                "Le numéro complet et toutes les sources : lien en bio.",
                MENTION_IA,
                tags,
            ]))[:2200],
            "facebook": "\n\n".join(filter(None, [
                brut.get("facebook", "").strip(),
                f"Le numéro complet et toutes les sources : {lien}" if lien else "",
                MENTION_IA,
            ])),
            "threads": _threads(brut.get("threads", ""), lien),
        },
        "publications": {},
    }


def _threads(texte: str, lien: str) -> str:
    # 500 caractères au maximum sur Threads ; on garde 110 caractères pour l'adresse du site.
    return _court(texte, 380) + f"\n\n{lien}"


def adresse_lisible(url: str) -> str:
    return re.sub(r"^https?://", "", url or "").rstrip("/") or "le site"


def url_numero(config: dict, numero: int) -> str:
    base = config["site"]["url"]
    return f"{base}numeros/{numero}/" if base else ""


def remplir_liens(texte: str, config: dict, numero: int) -> str:
    """Remplace {lien} (page du numéro) et {lien_court} (adresse du site, sans https)."""
    url = url_numero(config, numero)
    if not url:
        texte = re.sub(r"[^\n]*\{lien\}[^\n]*\n?", "", texte).strip()
    return texte.replace("{lien}", url).replace("{lien_court}", adresse_lisible(config["site"]["url"]))
