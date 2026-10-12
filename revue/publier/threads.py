"""Publication sur Threads (vidéo + texte), avec renouvellement automatique du jeton."""
from __future__ import annotations

import os
import subprocess
import time

from ..http import ErreurHTTP, get_json, post_formulaire

BASE = "https://graph.threads.net/v1.0"


def disponible() -> bool:
    return bool(os.environ.get("THREADS_TOKEN"))


def renouveler_jeton() -> str:
    """Prolonge le jeton de 60 jours. Si Meta en renvoie un nouveau, on l'enregistre
    dans les secrets GitHub (nécessite le secret facultatif GH_PAT_SECRETS)."""
    actuel = os.environ["THREADS_TOKEN"]
    try:
        rep = get_json("https://graph.threads.net/refresh_access_token",
                       {"grant_type": "th_refresh_token", "access_token": actuel})
    except ErreurHTTP as e:
        print(f"  renouvellement du jeton Threads impossible pour l'instant : {e}")
        return actuel
    nouveau = rep.get("access_token") or actuel
    jours = int(rep.get("expires_in", 0)) // 86400
    print(f"  jeton Threads valable encore {jours} jours")
    if nouveau != actuel:
        pat, depot = os.environ.get("GH_PAT_SECRETS"), os.environ.get("GITHUB_REPOSITORY")
        if pat and depot:
            subprocess.run(["gh", "secret", "set", "THREADS_TOKEN", "--repo", depot, "--body", nouveau],
                           check=True, env={**os.environ, "GH_TOKEN": pat})
            print("  nouveau jeton Threads enregistré dans les secrets GitHub")
        else:
            print("::warning::Meta a fourni un nouveau jeton Threads mais il n'a pas pu être enregistré. "
                  "Ajoutez le secret GH_PAT_SECRETS (voir README) ou mettez THREADS_TOKEN à jour à la main.")
    return nouveau


def _attendre(conteneur: str, jeton: str, attente_max: int = 600) -> None:
    debut = time.time()
    while True:
        etat = get_json(f"{BASE}/{conteneur}", {"fields": "status,error_message", "access_token": jeton})
        if etat.get("status") == "FINISHED":
            return
        if etat.get("status") in ("ERROR", "EXPIRED") or time.time() - debut > attente_max:
            raise RuntimeError(f"Traitement Threads en échec : {etat}")
        time.sleep(15)


def publier(texte: str, url_video: str, url_numero: str) -> dict:
    jeton = renouveler_jeton()
    try:
        conteneur = post_formulaire(f"{BASE}/me/threads", {
            "media_type": "VIDEO", "video_url": url_video, "text": texte, "access_token": jeton})["id"]
        _attendre(conteneur, jeton)
    except (ErreurHTTP, RuntimeError) as e:
        print(f"  vidéo refusée par Threads ({e}), publication du texte seul avec le lien")
        champs = {"media_type": "TEXT", "text": texte, "access_token": jeton}
        if url_numero:
            champs["link_attachment"] = url_numero
        conteneur = post_formulaire(f"{BASE}/me/threads", champs)["id"]
        time.sleep(5)
    media = post_formulaire(f"{BASE}/me/threads_publish", {"creation_id": conteneur, "access_token": jeton})["id"]
    lien = get_json(f"{BASE}/{media}", {"fields": "permalink", "access_token": jeton}).get("permalink", "")
    return {"id": media, "url": lien}
