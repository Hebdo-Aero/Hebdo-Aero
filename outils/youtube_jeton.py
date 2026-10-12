"""Obtenir le jeton YouTube (YOUTUBE_REFRESH_TOKEN), une seule fois, sur votre ordinateur.

Usage :
    python outils/youtube_jeton.py VOTRE_CLIENT_ID VOTRE_CLIENT_SECRET

Le navigateur s'ouvre : connectez-vous avec le compte Google propriétaire de la chaîne
YouTube et acceptez. Le jeton s'affiche ensuite dans le terminal ; copiez-le dans le
secret GitHub YOUTUBE_REFRESH_TOKEN.
"""
import json
import sys
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = 8765
REDIRECTION = f"http://127.0.0.1:{PORT}"
PORTEE = "https://www.googleapis.com/auth/youtube.upload"


def main() -> None:
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    client_id, client_secret = sys.argv[1], sys.argv[2]
    adresse = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": client_id, "redirect_uri": REDIRECTION, "response_type": "code",
        "scope": PORTEE, "access_type": "offline", "prompt": "consent"})
    recu = {}

    class Reponse(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            recu.update(dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.path).query)))
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("C'est fait, vous pouvez revenir au terminal.".encode("utf-8"))

        def log_message(self, *args):
            pass

    print("Ouverture du navigateur… Si rien ne s'ouvre, copiez cette adresse :\n" + adresse)
    webbrowser.open(adresse)
    HTTPServer(("127.0.0.1", PORT), Reponse).handle_request()
    if "code" not in recu:
        sys.exit(f"Autorisation refusée : {recu}")

    donnees = urllib.parse.urlencode({
        "code": recu["code"], "client_id": client_id, "client_secret": client_secret,
        "redirect_uri": REDIRECTION, "grant_type": "authorization_code"}).encode()
    with urllib.request.urlopen("https://oauth2.googleapis.com/token", data=donnees) as rep:
        jetons = json.load(rep)
    if "refresh_token" not in jetons:
        sys.exit(f"Pas de jeton de renouvellement dans la réponse : {jetons}")
    print("\nYOUTUBE_REFRESH_TOKEN =\n" + jetons["refresh_token"])


if __name__ == "__main__":
    main()
