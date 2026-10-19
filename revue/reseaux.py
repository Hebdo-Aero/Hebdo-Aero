"""Script de la vidéo et textes des publications, rédigés par Claude à partir du numéro validé."""
from __future__ import annotations

import json
import re

from . import claude, monetisation
from .config import periode_fr

SYSTEME = """Tu prépares la déclinaison vidéo et réseaux sociaux de « {nom} », revue hebdomadaire \
en français sur l'aviation commerciale. Tu travailles UNIQUEMENT à partir du numéro fourni : aucun \
fait, chiffre ou nom qui n'y figure pas. Ton clair, vivant et précis, jamais racoleur. \
Les sujets graves (accidents, attaques, victimes) sont traités avec sobriété.

La vidéo est verticale, dure moins de 85 secondes au total et est lue par une voix de synthèse : \
écris la narration pour l'oreille (phrases courtes, nombres faciles à dire, pas de sigles obscurs, \
pas de parenthèses). Les textes à l'écran sont très courts, car lus sur téléphone.

Tu écris aussi 3 shorts d'accroche de 20 à 30 secondes pour TikTok et Instagram. Leur but : arrêter \
le défilement dès la première seconde et donner envie de lire le numéro sur le site. Règles :
- la première phrase est l'accroche : un chiffre frappant, un contraste ou une question, en moins de \
12 mots, compréhensible sans contexte ;
- puis un seul fait central, raconté simplement ;
- la fin laisse une question ouverte (le pourquoi, la suite, les conséquences) que le numéro développe, \
sans rien inventer ni promettre ce que le numéro ne contient pas ;
- jamais de piège à clics (« vous ne devinerez jamais », « incroyable »…) ;
- évite de prendre un drame humain (accident, attaque, victimes) comme accroche : préfère les sujets \
industriels, économiques, de réseau ou insolites.

Appelle l'outil preparer_reseaux une seule fois."""

CONSIGNE = """Voici le numéro {numero} (semaine du {periode}) au format JSON :

{json}

Prépare :
- 5 scènes vidéo pour les 5 sujets les plus marquants (les 3 sujets à la une d'abord), sans reprendre \
le sujet du chiffre de la semaine, qui a sa propre scène ;
- la narration de la scène « chiffre de la semaine » ;
- le titre YouTube et les textes Instagram, Facebook et Threads (sans lien ni hashtag : ils sont ajoutés \
automatiquement) ;
- 3 shorts d'accroche, chacun sur un sujet différent du numéro."""

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
            "accroches": {
                "type": "array", "minItems": 1, "maxItems": 3,
                "items": {
                    "type": "object",
                    "properties": {
                        "accroche_ecran": {"type": "string", "description":
                            "Texte géant de la première seconde : 32 caractères au plus (« 250 avions d'un coup »)."},
                        "accroche_voix": {"type": "string", "description": "Première phrase lue : 12 mots au plus."},
                        "surtitre": {"type": "string", "description": "Thème ou lieu, 28 caractères au plus."},
                        "titre_ecran": {"type": "string", "description": "Le fait central à l'écran, 46 caractères au plus."},
                        "texte_ecran": {"type": "string", "description": "Précision à l'écran, 70 caractères au plus."},
                        "narration": {"type": "string", "description":
                            "Suite lue après l'accroche : 2 ou 3 phrases, 40 mots au plus, finissant sur une "
                            "question ouverte que le numéro développe."},
                        "recherche_video": {"type": "string", "description":
                            "2 à 4 mots-clés EN ANGLAIS pour un plan vidéo générique, sans marque."},
                        "legende": {"type": "string", "description":
                            "Légende TikTok/Instagram : 1 ou 2 phrases, 150 caractères au plus, sans hashtag."},
                    },
                    "required": ["accroche_ecran", "accroche_voix", "surtitre", "titre_ecran", "texte_ecran",
                                 "narration", "recherche_video", "legende"],
                },
            },
        },
        "required": ["scenes", "chiffre_narration", "youtube_titre", "instagram", "facebook", "threads", "accroches"],
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
        outil_final=OUTIL, max_tokens=8000, appelant=appelant)
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
        "narration": f"{nom_parle}. L'actualité de l'aviation commerciale, semaine du {periode}.",
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
    # Partenaire de la semaine : cité à la fin de la vidéo, et signalé comme le veut la loi du 9 juin 2023
    # (mention « Collaboration commerciale » pendant toute la vidéo et dans les légendes).
    partenaire = monetisation.partenaire_du_numero(config, numero["date"])
    if partenaire and not partenaire["video"]:
        partenaire = None
    fin = {
        "type": "fin",
        "surtitre": "Sources et détails",
        "titre_ecran": nom,
        "texte_ecran": "{lien_court}",
        "narration": f"Toutes les sources sont sur le site {nom_parle}. Rendez-vous dimanche prochain.",
        "recherche_video": config["video"].get("recherche_fin", "airplane above clouds"),
    }
    if partenaire:
        fin["partenaire"] = f"Partenaire de la semaine : {partenaire['nom']}"
        fin["narration"] = (f"Toutes les sources sont sur le site {nom_parle}. Merci à notre partenaire de la semaine, "
                            f"{partenaire['nom']}. Rendez-vous dimanche prochain.")
    scenes.append(fin)

    # Garde-fou de durée : environ 2,7 mots par seconde ; on retire des sujets si besoin.
    budget = int(config["video"].get("duree_max", 88) * 2.6)
    while sum(_mots(s["narration"]) for s in scenes) > budget and \
            sum(1 for s in scenes if s["type"] == "sujet") > 3:
        dernier = max(i for i, s in enumerate(scenes) if s["type"] == "sujet")
        scenes.pop(dernier)

    lien = "{lien}"   # remplacé par l'adresse réelle du site au moment du rendu et de la publication
    tags = " ".join("#" + h for h in config["reseaux"].get("hashtags", []))
    titre_yt = _court(brut.get("youtube_titre") or numero["titre"], 90)
    pub = f"Collaboration commerciale avec {partenaire['nom']}." if partenaire else ""
    return {
        "numero": numero["numero"],
        "date": numero["date"],
        "partenaire": {"nom": partenaire["nom"], "lien": partenaire["lien"]} if partenaire else None,
        "video": {"scenes": scenes, "publicite": "Collaboration commerciale" if partenaire else ""},
        "legendes": {
            "youtube_titre": titre_yt,
            "youtube_description": "\n\n".join(filter(None, [
                pub,
                brut.get("facebook", "").strip(),
                f"Le numéro complet et toutes les sources : {lien}" if lien else "",
                MENTION_IA,
                tags + " #Shorts",
            ])),
            "instagram": "\n\n".join(filter(None, [
                pub,
                brut.get("instagram", "").strip(),
                "Le numéro complet et toutes les sources : lien en bio.",
                MENTION_IA,
                tags,
            ]))[:2200],
            "facebook": "\n\n".join(filter(None, [
                pub,
                brut.get("facebook", "").strip(),
                f"Le numéro complet et toutes les sources : {lien}" if lien else "",
                MENTION_IA,
            ])),
            "threads": _threads(brut.get("threads", ""), lien, pub),
        },
        "accroches": [assembler_accroche(config, a) for a in brut.get("accroches", [])[:3]
                      if a.get("accroche_voix") and a.get("narration")],
        "publications": {},
    }


APPEL_VOIX = "Toute l'histoire, et les autres actus de la semaine, sur {nom}. Lien en bio."


def assembler_accroche(config: dict, a: dict) -> dict:
    """Short de 20 à 30 s : accroche plein écran, fait central, appel vers le site."""
    nom = config["site"]["nom"]
    nom_parle = config["site"].get("nom_parle") or nom
    tags = " ".join("#" + h for h in config["reseaux"].get("hashtags", []))
    scenes = [
        {"type": "accroche", "surtitre": _court(a.get("surtitre"), 28) or "Cette semaine",
         "titre_ecran": _court(a["accroche_ecran"], 34), "texte_ecran": "",
         "narration": a["accroche_voix"].strip(), "recherche_video": _court(a.get("recherche_video"), 60)},
        {"type": "sujet", "surtitre": _court(a.get("surtitre"), 28),
         "titre_ecran": _court(a.get("titre_ecran"), 52), "texte_ecran": _court(a.get("texte_ecran"), 80),
         "narration": a["narration"].strip(), "recherche_video": _court(a.get("recherche_video"), 60)},
        {"type": "appel", "surtitre": "La suite sur le site", "titre_ecran": nom, "texte_ecran": "Lien en bio",
         "narration": APPEL_VOIX.format(nom=nom_parle), "recherche_video": ""},
    ]
    legende = _court(a.get("legende"), 160)
    return {
        "scenes": scenes,
        "legende": "\n\n".join(filter(None, [
            legende,
            "Toute l'histoire et les sources : lien en bio.",
            "Résumé rédigé par IA, voix de synthèse.",
            tags,
        ])),
    }


def _threads(texte: str, lien: str, pub: str = "") -> str:
    # 500 caractères au maximum sur Threads ; on garde 110 caractères pour l'adresse du site.
    if pub:
        return pub + "\n\n" + _court(texte, 380 - len(pub) - 2) + f"\n\n{lien}"
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
