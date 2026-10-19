"""Envoi de la vidéo sur YouTube (Short) via l'API YouTube Data v3."""
from __future__ import annotations

import json
import os
from pathlib import Path

from ..http import ErreurHTTP, post_formulaire, requete

SECRETS = ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN")


def disponible() -> bool:
    return all(os.environ.get(s) for s in SECRETS)


def jeton_acces() -> str:
    rep = post_formulaire("https://oauth2.googleapis.com/token", {
        "client_id": os.environ["YOUTUBE_CLIENT_ID"],
        "client_secret": os.environ["YOUTUBE_CLIENT_SECRET"],
        "refresh_token": os.environ["YOUTUBE_REFRESH_TOKEN"],
        "grant_type": "refresh_token",
    })
    return rep["access_token"]


def _propre(texte: str, limite: int) -> str:
    texte = texte.replace("<", "‹").replace(">", "›")     # caractères refusés par YouTube
    return texte if len(texte) <= limite else texte[:limite - 1].rsplit(" ", 1)[0] + "…"


def publier(video: Path, titre: str, description: str, tags: list[str],
            visibilite: str = "public", synthetique: bool = True, placement_paye: bool = False) -> dict:
    jeton = jeton_acces()
    meta = {
        "snippet": {
            "title": _propre(titre, 100),
            "description": _propre(description, 4900),
            "tags": tags[:15],
            "categoryId": "25",              # Actualités et politique
            "defaultLanguage": "fr",
            "defaultAudioLanguage": "fr",
        },
        "status": {
            "privacyStatus": visibilite,
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": synthetique,
        },
    }
    taille = video.stat().st_size

    def ouvrir_envoi(meta: dict, parties: str):
        return requete(
            f"https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part={parties}",
            methode="POST", donnees=json.dumps(meta).encode("utf-8"),
            entetes={"Authorization": f"Bearer {jeton}", "Content-Type": "application/json; charset=UTF-8",
                     "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(taille)})

    if placement_paye:     # partenaire de la semaine : case « placement de produit payant »
        try:
            _, entetes, _ = ouvrir_envoi({**meta, "paidProductPlacementDetails": {"hasPaidProductPlacement": True}},
                                         "snippet,status,paidProductPlacementDetails")
        except ErreurHTTP as e:
            if e.code != 400:
                raise
            print("::warning::YouTube n'a pas accepté la case « placement de produit payant » : "
                  "cochez-la dans YouTube Studio pour cette vidéo.")
            _, entetes, _ = ouvrir_envoi(meta, "snippet,status")
    else:
        _, entetes, _ = ouvrir_envoi(meta, "snippet,status")
    adresse = {k.lower(): v for k, v in entetes.items()}["location"]
    _, _, corps = requete(adresse, methode="PUT", donnees=video.read_bytes(), delai=600, essais=3,
                          entetes={"Authorization": f"Bearer {jeton}", "Content-Type": "video/mp4"})
    identifiant = json.loads(corps)["id"]
    return {"id": identifiant, "url": f"https://www.youtube.com/shorts/{identifiant}"}
