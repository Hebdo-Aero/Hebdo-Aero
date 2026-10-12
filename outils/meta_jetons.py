"""Obtenir les jetons Meta (Facebook, Instagram, Threads), une seule fois, sur votre ordinateur.

Facebook + Instagram :
    python outils/meta_jetons.py facebook ID_APP SECRET_APP JETON_COURT
  JETON_COURT : jeton utilisateur copié depuis l'explorateur de l'API Graph, avec les
  autorisations pages_show_list, pages_read_engagement, pages_manage_posts,
  instagram_basic, instagram_content_publish et business_management.
  Le script affiche, pour chacune de vos Pages, FACEBOOK_PAGE_ID, META_PAGE_TOKEN
  (jeton de Page sans expiration) et INSTAGRAM_USER_ID.

Threads :
    python outils/meta_jetons.py threads SECRET_APP_THREADS JETON_COURT_THREADS
  Affiche THREADS_TOKEN (valable 60 jours, prolongé automatiquement chaque semaine).
"""
import json
import sys
import urllib.parse
import urllib.request

VERSION = "v25.0"


def get(url: str, params: dict) -> dict:
    with urllib.request.urlopen(url + "?" + urllib.parse.urlencode(params)) as rep:
        return json.load(rep)


def facebook(id_app: str, secret_app: str, jeton_court: str) -> None:
    longue = get(f"https://graph.facebook.com/{VERSION}/oauth/access_token", {
        "grant_type": "fb_exchange_token", "client_id": id_app,
        "client_secret": secret_app, "fb_exchange_token": jeton_court})["access_token"]
    pages = get(f"https://graph.facebook.com/{VERSION}/me/accounts", {
        "fields": "id,name,access_token,instagram_business_account", "access_token": longue})
    if not pages.get("data"):
        sys.exit("Aucune Page trouvée : vérifiez les autorisations du jeton.")
    for p in pages["data"]:
        print(f"\nPage « {p['name']} »")
        print(f"  FACEBOOK_PAGE_ID  = {p['id']}")
        print(f"  META_PAGE_TOKEN   = {p['access_token']}")
        ig = (p.get("instagram_business_account") or {}).get("id")
        print(f"  INSTAGRAM_USER_ID = {ig or 'aucun compte Instagram professionnel relié à cette Page'}")


def threads(secret_app: str, jeton_court: str) -> None:
    rep = get("https://graph.threads.net/access_token", {
        "grant_type": "th_exchange_token", "client_secret": secret_app, "access_token": jeton_court})
    print(f"\nTHREADS_TOKEN = {rep['access_token']}")
    print(f"(valable {int(rep.get('expires_in', 0)) // 86400} jours)")


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "facebook":
        facebook(*sys.argv[2:])
    elif len(sys.argv) == 4 and sys.argv[1] == "threads":
        threads(*sys.argv[2:])
    else:
        print(__doc__)
        sys.exit(1)
