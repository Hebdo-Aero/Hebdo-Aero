"""Publication des Reels sur Instagram et Facebook via l'API Graph de Meta.

Les deux utilisent le même jeton de Page Facebook (qui n'expire pas s'il est obtenu
à partir d'un jeton utilisateur longue durée, voir outils/meta_jetons.py).
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from ..http import ErreurHTTP, get_json, post_formulaire, requete

GRAPH = "https://graph.facebook.com"
RUPLOAD = "https://rupload.facebook.com"


def instagram_disponible() -> bool:
    return bool(os.environ.get("META_PAGE_TOKEN") and os.environ.get("INSTAGRAM_USER_ID"))


def facebook_disponible() -> bool:
    return bool(os.environ.get("META_PAGE_TOKEN") and os.environ.get("FACEBOOK_PAGE_ID"))


def _envoyer_binaire(url: str, jeton: str, video: Path) -> None:
    donnees = video.read_bytes()
    _, _, corps = requete(url, methode="POST", donnees=donnees, delai=600, essais=3, entetes={
        "Authorization": f"OAuth {jeton}", "offset": "0", "file_size": str(len(donnees)),
        "Content-Type": "application/octet-stream"})
    if b'"success":true' not in corps.replace(b" ", b""):
        raise RuntimeError(f"Envoi refusé par Meta : {corps[:300]!r}")


def instagram(video: Path, url_publique: str, legende: str, version: str, attente_max: int = 900) -> dict:
    jeton, ig = os.environ["META_PAGE_TOKEN"], os.environ["INSTAGRAM_USER_ID"]
    base = f"{GRAPH}/{version}"
    commun = {"media_type": "REELS", "caption": legende, "share_to_feed": "true",
              "thumb_offset": "1400", "access_token": jeton}
    try:   # envoi direct du fichier (pas besoin que le site soit déjà en ligne)
        conteneur = post_formulaire(f"{base}/{ig}/media", {**commun, "upload_type": "resumable"})["id"]
        _envoyer_binaire(f"{RUPLOAD}/ig-api-upload/{version}/{conteneur}", jeton, video)
    except (ErreurHTTP, RuntimeError, KeyError) as e:
        print(f"  envoi direct impossible ({e}), Instagram va chercher la vidéo sur le site")
        conteneur = post_formulaire(f"{base}/{ig}/media", {**commun, "video_url": url_publique})["id"]

    debut = time.time()
    while True:
        etat = get_json(f"{base}/{conteneur}", {"fields": "status_code,status", "access_token": jeton})
        code = etat.get("status_code")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED") or time.time() - debut > attente_max:
            raise RuntimeError(f"Traitement Instagram en échec : {etat}")
        time.sleep(15)

    media = post_formulaire(f"{base}/{ig}/media_publish", {"creation_id": conteneur, "access_token": jeton})["id"]
    lien = get_json(f"{base}/{media}", {"fields": "permalink", "access_token": jeton}).get("permalink", "")
    return {"id": media, "url": lien}


def facebook(video: Path, description: str, version: str) -> dict:
    jeton, page = os.environ["META_PAGE_TOKEN"], os.environ["FACEBOOK_PAGE_ID"]
    base = f"{GRAPH}/{version}"
    debut = post_formulaire(f"{base}/{page}/video_reels", {"upload_phase": "start", "access_token": jeton})
    video_id = debut["video_id"]
    _envoyer_binaire(f"{RUPLOAD}/video-upload/{version}/{video_id}", jeton, video)
    fin = post_formulaire(f"{base}/{page}/video_reels", {
        "upload_phase": "finish", "video_id": video_id, "video_state": "PUBLISHED",
        "description": description, "access_token": jeton})
    if not fin.get("success"):
        raise RuntimeError(f"Publication du Reel Facebook refusée : {fin}")
    return {"id": video_id, "url": f"https://www.facebook.com/reel/{video_id}"}
