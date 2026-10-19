"""Vidéo d'annonce de la sortie du numéro (TikTok, Reels), sans voix : 17 secondes, musique et textes.

Elle est produite chaque dimanche avec les vrais titres de la semaine, sur des plans d'avions filmés
(Pixabay ou Pexels) quand c'est possible, sinon sur un ciel animé où passent des avions dessinés.
Elle apparaît sur la page /shorts/ du site, prête à télécharger avec sa légende.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from . import ciel, illustrations, son
from .config import RACINE, periode_fr
from .reseaux import adresse_lisible

GABARITS = Path(__file__).parent / "templates"
IPS = 30
# Chronologie calée sur la musique (tempo 100 : un temps = 0,6 s, une mesure = 2,4 s)
TEMPS = {"accroche": [0.0, 2.4], "marque": [2.4, 4.8], "sommaire": [4.8, 12.0], "fin": [12.0, 16.8]}
IMPACT = 0.6                  # l'écusson se pose 0,6 s après le début de son plan (temps fort)
CARTES = [5.4, 6.9, 8.4, 9.9]  # arrivée des titres du sommaire, puis de la dernière ligne
DUREE = 16.8
RUBRIQUE_SENSIBLE = "Sécurité & sûreté"   # pas d'accidents ni d'attentats sur une musique entraînante
PLANS = [("airplane takeoff", "accroche"), ("airplane flying above clouds", "sommaire"), ("airplane sunset", "fin")]
GENERIQUE = ["Les infos clés de la semaine, expliquées", "Le chiffre qui résume la semaine",
             "Toutes les brèves, rubrique par rubrique"]


def _court(texte: str, limite: int) -> str:
    texte = re.sub(r"\s+", " ", texte or "").strip()
    return texte if len(texte) <= limite else texte[:limite - 1].rsplit(" ", 1)[0] + "…"


def choisir_titres(numero: dict, nombre: int = 3) -> list[str]:
    """Les titres « À la une », puis des brèves, en écartant la rubrique Sécurité & sûreté."""
    sujets = [s for s in numero.get("une", []) + numero.get("breves", []) if s.get("categorie") != RUBRIQUE_SENSIBLE]
    return [_court(s["titre"], 84) for s in sujets[:nombre]]


def donnees(config: dict, numero: dict, generique: bool = False) -> dict:
    site = config["site"]
    titres = GENERIQUE if generique else choisir_titres(numero)
    if generique or not titres:
        titres, plus = GENERIQUE, "Chaque info est sourcée"
    else:
        morceaux = []
        if numero.get("chiffre"):
            morceaux.append(f"le chiffre de la semaine : {numero['chiffre']['valeur']}")
        if numero.get("breves"):
            morceaux.append(f"{len(numero['breves'])} brèves")
        plus = "+ " + " · ".join(morceaux) if morceaux else "Chaque info est sourcée"
    return {
        "numero": numero["numero"], "periode": periode_fr(numero["debut"], numero["fin"]),
        "nom": site["nom"].upper(), "tag": "L'actu de l'aviation commerciale, chaque dimanche",
        "titres": titres, "plus": plus, "adresse": adresse_lisible(site.get("url") or "https://hebdo-aero.github.io/"),
        "mention": "Gratuit · 5 minutes de lecture", "temps": TEMPS, "impact": IMPACT,
        "cartes": CARTES[:len(titres)] + [CARTES[-1]], "duree": DUREE,
    }


def legende(config: dict, numero: dict, d: dict, generique: bool = False) -> str:
    tags = " ".join("#" + h for h in config["reseaux"].get("hashtags", []))
    if generique:
        sommaire = "Les infos clés, le chiffre de la semaine et toutes les brèves, sources à l'appui."
    else:
        sommaire = "Au sommaire : " + " ; ".join(t.rstrip("…") for t in d["titres"]) + "."
    return "\n\n".join([f"Le N° {d['numero']} de {config['site']['nom']} est en ligne ✈️ "
                        f"L'actu de l'aviation commerciale, semaine du {d['periode']}.",
                        sommaire, "À lire gratuitement : lien en bio.", tags])


def _plans_filmes(travail: Path) -> list[dict | None]:
    if not illustrations.disponible():
        return [None] * len(PLANS)
    plans, pris = [], set()
    for recherche, cle in PLANS:
        debut, fin = TEMPS[cle][0], (TEMPS[cle][1] if cle != "accroche" else TEMPS["marque"][1])
        trouve = illustrations.chercher_video(recherche, fin - debut, pris)
        if not trouve:
            plans.append(None)
            continue
        try:
            fichier = illustrations.telecharger(trouve["lien"], travail / f"plan-{len(plans)}.mp4")
        except Exception as e:  # noqa: BLE001
            print(f"  plan ignoré ({e})")
            plans.append(None)
            continue
        pris.add(trouve["id"])
        plans.append({**trouve, "fichier": str(fichier), "debut": debut, "fin": fin})
    return plans


def commande(sortie: Path, film: bool, fond_ciel: Path, plans: list[dict | None], musique: Path, effets: Path) -> list[str]:
    entrees = ["-f", "image2pipe", "-framerate", str(IPS), "-c:v", "png", "-i", "-"]
    filtres, n = [], 1
    if film:
        entrees += ["-loop", "1", "-framerate", str(IPS), "-t", f"{DUREE:.2f}", "-i", str(fond_ciel)]
        filtres.append(f"[1:v]crop=1080:1920:x='(in_w-1080)*t/{DUREE}':y=0,setsar=1,format=yuva420p[f0]")
        courant, n = "f0", 2
        for p in plans:
            if not p:
                continue
            d = p["fin"] - p["debut"]
            entrees += ["-stream_loop", "-1", "-t", f"{d + 0.5:.2f}", "-i", p["fichier"]]
            filtres.append(
                f"[{n}:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps={IPS},setsar=1,"
                f"eq=saturation=1.1:contrast=1.05:brightness=-0.04,format=yuva420p,fade=t=in:st=0:d=0.35:alpha=1,"
                f"fade=t=out:st={d - 0.05:.2f}:d=0.35:alpha=1,setpts=PTS-STARTPTS+{p['debut']:.2f}/TB[c{n}]")
            filtres.append(f"[{courant}][c{n}]overlay=eof_action=pass:format=auto[f{n}]")
            courant, n = f"f{n}", n + 1
        filtres.append(f"[{courant}][0:v]overlay=format=auto,format=yuv420p[v]")
        video = "[v]"
    else:
        video = "0:v"
    stereo = "aformat=sample_rates=48000:channel_layouts=stereo"
    entrees += ["-i", str(musique), "-i", str(effets)]
    filtres.append(f"[{n}:a]{stereo},volume=0.9[m];[{n + 1}:a]{stereo},volume=0.5[e];"
                   f"[m][e]amix=inputs=2:duration=first:normalize=0,afade=t=out:st={DUREE - 0.7:.2f}:d=0.7,"
                   f"loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000,{stereo}[a]")
    return ["ffmpeg", "-y", "-loglevel", "error", *entrees, "-filter_complex", ";".join(filtres),
            "-map", video, "-map", "[a]", "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
            "-profile:v", "high", "-level", "4.1", "-r", str(IPS), "-g", str(IPS * 2), "-keyint_min", str(IPS * 2),
            "-sc_threshold", "0", "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart", "-t", f"{DUREE:.2f}", str(sortie)]


def rendre(config: dict, numero: dict, sortie: Path, generique: bool = False, filmer: bool = True) -> dict:
    """Produit la vidéo d'annonce (MP4 + affiche JPG) et renvoie sa légende et ses crédits."""
    from playwright.sync_api import sync_playwright

    travail = Path(tempfile.mkdtemp(prefix="annonce-"))
    d = donnees(config, numero, generique)
    plans = _plans_filmes(travail) if filmer else [None] * len(PLANS)
    film = any(plans)
    fond_ciel = ciel.enregistrer(travail / "ciel.jpg", 1600, 1920, graine=int(numero["numero"]) + 40)
    env = Environment(loader=FileSystemLoader(GABARITS), autoescape=True)
    page_html = travail / "annonce.html"
    page_html.write_text(env.get_template("annonce.html").render(
        d=d, mode="film" if film else "dessin", ciel=fond_ciel.as_uri(),
        polices=(RACINE / "assets" / "polices").as_uri(), embleme=(RACINE / "assets" / "logo" / "embleme.svg").as_uri()),
        encoding="utf-8")
    musique = son.musique(DUREE + 0.4, travail / "musique.wav", graine=int(numero["numero"]) + 21, tempo=100.0,
                          energique=True)
    transitions = [TEMPS["sommaire"][0], TEMPS["fin"][0]]
    effets = son.souffles(transitions, DUREE + 0.4, travail / "effets.wav", impact=TEMPS["marque"][0] + IMPACT)
    sortie.parent.mkdir(parents=True, exist_ok=True)
    cmd = commande(sortie, film, fond_ciel, plans, musique, effets)

    with sync_playwright() as p:
        navigateur = p.chromium.launch()
        page = navigateur.new_page(viewport={"width": 1080, "height": 1920}, device_scale_factor=1)
        page.goto(page_html.as_uri(), wait_until="load")
        page.evaluate("document.fonts.ready")
        page.wait_for_timeout(300)
        page.evaluate("preparer()")
        processus = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        derniere, image = None, b""
        try:
            for i in range(int(round(DUREE * IPS))):
                cle = page.evaluate(f"seek({i / IPS:.4f})")
                if cle != derniere:
                    image = page.screenshot(type="png", omit_background=film)
                    derniere = cle
                processus.stdin.write(image)
            processus.stdin.close()
        except BrokenPipeError:
            pass
        finally:
            if processus.wait() != 0:
                raise RuntimeError("ffmpeg a échoué pendant le montage de la vidéo d'annonce.")
        navigateur.close()
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "0.5", "-i", str(sortie), "-frames:v", "1",
                    "-q:v", "3", str(sortie.with_suffix(".jpg"))], check=True)
    shutil.rmtree(travail, ignore_errors=True)
    credits = sorted({f"{p['auteur']} ({p.get('source', 'Pixabay')})" for p in plans if p})
    texte = legende(config, numero, d, generique)
    if credits:
        texte += "\n\nImages : " + ", ".join(credits) + "."
    return {"legende": texte, "credits": credits, "filme": film, "duree": DUREE}


def enregistrer_legende(chemin: Path, infos: dict) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(infos, ensure_ascii=False, indent=1), encoding="utf-8")
