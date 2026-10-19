"""Vidéos de présentation du site, pour TikTok et Instagram.

Usage : python outils/presentation.py [--format short|instagram]

Produit dans _medias/ :
  presentation-short.mp4       1080 × 1920, ~25 s : TikTok, Reels Instagram, YouTube Shorts
  presentation-instagram.mp4   1080 × 1350 (4:5), ~29 s : publication du fil Instagram
  presentation-*.jpg           image de couverture de chaque vidéo

La vidéo filme le vrai site (dernier numéro) dans un téléphone : construisez-le d'abord avec
python -m revue.construire. Les textes se règlent dans TEXTES ci-dessous.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from jinja2 import Environment, FileSystemLoader  # noqa: E402

from revue import ciel, son  # noqa: E402
from revue.config import DOSSIER_MEDIAS, DOSSIER_SITE, charger_config  # noqa: E402

IPS = 30
ETAPES = [
    {"titre": "Chaque dimanche,<br>un <em>nouveau numéro</em>",
     "texte": "Toute l'actualité de l'aviation commerciale de la semaine, en 5 minutes de lecture."},
    {"titre": "Les infos clés,<br><em>expliquées</em>",
     "texte": "Les sujets qui ont marqué la semaine, résumés clairement et remis dans leur contexte."},
    {"titre": "Toutes les brèves,<br><em>par rubrique</em>",
     "texte": "Constructeurs, compagnies, aéroports, sécurité, innovation : tout est classé."},
    {"titre": "Chaque info<br>est <em>sourcée</em>",
     "texte": "Un lien vers l'article d'origine, pour vérifier et aller plus loin."},
]
ACCROCHE = {"pastille": "NOUVEAU MÉDIA", "titre": "L'actu de<br>l'<em>aviation<br>commerciale</em><br>en 5 minutes"}

# Chronologie calée sur le tempo de la musique (changements de plan sur les temps forts).
FORMATS = {
    "short": {
        "L": 1080, "H": 1920, "classe": "vertical", "tempo": 100.0,
        "accroche": {"debut": 0.0, "fin": 2.4},
        "ident": {"debut": 2.4, "fin": 5.4, "impact": 1.2},
        "etapes": [(5.4, 9.0), (9.0, 12.6), (12.6, 16.2), (16.2, 20.4)],
        "fin": {"debut": 20.4, "fin": 25.2},
        "pose": {"x": 219, "y": 610, "s": 1.55},
        "zoom": {"facteur": 1.45, "x": 540, "y": 1175},
        "couverture": 1.2,
    },
    "instagram": {
        "L": 1080, "H": 1350, "classe": "flux", "tempo": 96.0,
        "accroche": None,
        "ident": {"debut": 0.0, "fin": 3.7, "impact": 1.2},
        "etapes": [(3.7, 8.7), (8.7, 13.7), (13.7, 18.7), (18.7, 23.7)],
        "fin": {"debut": 23.7, "fin": 28.7},
        "pose": {"x": 570, "y": 181, "s": 1.13},
        "zoom": {"facteur": 1.3, "x": 845, "y": 560},
        "couverture": 3.2,
    },
}


def page_html(nom_format: str, config: dict, travail: Path) -> tuple[Path, dict]:
    f = FORMATS[nom_format]
    duree = f["fin"]["fin"]
    plan = {"L": f["L"], "H": f["H"], "duree": duree, "accroche": f["accroche"], "ident": f["ident"],
            "etapes": [{"debut": a, "fin": b} for a, b in f["etapes"]],
            "tel": {"debut": f["etapes"][0][0]}, "fin": f["fin"], "pose": f["pose"], "zoom": f["zoom"]}
    url = config["site"].get("url") or "https://hebdo-aero.github.io/Hebdo-Aero/"
    adresse = url.split("://", 1)[-1].rstrip("/")
    logos = RACINE / "assets" / "logo"
    ciel_img = ciel.enregistrer(travail / "ciel.jpg", int(f["L"] * 1.5), f["H"], graine=11)
    env = Environment(loader=FileSystemLoader(Path(__file__).parent), autoescape=True)
    html = env.get_template("presentation.html").render(
        format=f["classe"], L=f["L"], H=f["H"], plan=plan,
        polices=(RACINE / "assets" / "polices").as_uri(), ciel=ciel_img.as_uri(),
        embleme_svg=(logos / "embleme.svg").read_text(encoding="utf-8"),
        embleme=(logos / "embleme.svg").as_uri(), logo=(logos / "logo-sombre.svg").as_uri(),
        nom=config["site"]["nom"].upper(), sous_titre=config["site"].get("sous_titre", ""),
        accroche=ACCROCHE if f["accroche"] else None, etapes=ETAPES,
        domaine=adresse.split("/")[0], site=(DOSSIER_SITE / "index.html").as_uri(),
        fin={"rdv": "Un nouveau numéro chaque dimanche", "cta": "LIEN EN BIO", "url": adresse,
             "plus": "Gratuit · sans inscription"})
    chemin = travail / f"presentation-{nom_format}.html"
    chemin.write_text(html, encoding="utf-8")
    return chemin, plan


def bande_son(nom_format: str, duree: float, travail: Path) -> tuple[Path, Path]:
    f = FORMATS[nom_format]
    instants = [a for a, _ in f["etapes"]] + [f["fin"]["debut"]]
    if f["accroche"]:
        # musique dès la première image (le short doit accrocher), impact du générique en effet
        musique = son.musique(duree + 0.4, travail / "musique.wav", graine=5, tempo=f["tempo"], energique=True)
        impact = f["ident"]["debut"] + f["ident"]["impact"]
        effets = son.souffles(instants, duree + 0.4, travail / "effets.wav", impact=impact)
    else:
        musique = son.musique(duree + 0.4, travail / "musique.wav", graine=3, tempo=f["tempo"],
                              impact=f["ident"]["impact"])
        effets = son.souffles(instants, duree + 0.4, travail / "effets.wav")
    return musique, effets


def rendre(nom_format: str, config: dict, sortie: Path) -> None:
    from playwright.sync_api import sync_playwright

    f = FORMATS[nom_format]
    travail = Path(tempfile.mkdtemp(prefix="presentation-"))
    html, plan = page_html(nom_format, config, travail)
    duree = plan["duree"]
    musique, effets = bande_son(nom_format, duree, travail)
    stereo = "aformat=sample_rates=48000:channel_layouts=stereo"
    commande = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "image2pipe", "-framerate", str(IPS), "-c:v", "png", "-i", "-",
        "-i", str(musique), "-i", str(effets),
        "-filter_complex",
        f"[1:a]{stereo},volume=0.9[m];[2:a]{stereo},volume={0.55 if f['accroche'] else 0.4}[e];"
        f"[m][e]amix=inputs=2:duration=first:normalize=0,afade=t=out:st={duree - 0.8:.2f}:d=0.8,"
        f"loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000,{stereo}[a]",
        "-map", "0:v", "-map", "[a]",
        "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p",
        "-profile:v", "high", "-level", "4.1", "-r", str(IPS),
        "-g", str(IPS * 2), "-keyint_min", str(IPS * 2), "-sc_threshold", "0", "-flags", "+cgop",
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart", "-t", f"{duree:.3f}", str(sortie)]

    sortie.parent.mkdir(parents=True, exist_ok=True)
    debut = time.time()
    with sync_playwright() as p:
        navigateur = p.chromium.launch()
        page = navigateur.new_page(viewport={"width": f["L"], "height": f["H"]}, device_scale_factor=1)
        page.emulate_media(reduced_motion="reduce")
        page.goto(html.as_uri(), wait_until="load")
        page.evaluate("document.fonts.ready")
        cadre = next(fr for fr in page.frames if fr != page.main_frame)
        cadre.evaluate("""() => {
            document.documentElement.style.scrollBehavior = 'auto';
            document.querySelectorAll('img[loading="lazy"]').forEach(i => i.loading = 'eager');
            return document.fonts.ready.then(() => true);
        }""")
        page.wait_for_timeout(1200)
        positions = cadre.evaluate("""() => {
            const haut = e => e.getBoundingClientRect().top + scrollY;
            const sujets = document.querySelectorAll('#une .sujet');
            const source = document.querySelector('#breves .breve .sources');
            const r = source.getBoundingClientRect();
            return { entete: document.querySelector('.bandeau').offsetHeight, vh: innerHeight,
                     une: haut(document.getElementById('une')), sujet2: haut(sujets[1] || sujets[0]),
                     breves: haut(document.getElementById('breves')), source: haut(source) + r.height / 2 };
        }""")
        page.evaluate("pos => preparer(pos)", positions)

        processus = subprocess.Popen(commande, stdin=subprocess.PIPE)
        derniere_cle, image, captures = None, b"", 0
        defil_actuel, surligne_actuel = None, None
        try:
            for n in range(int(round(duree * IPS))):
                etat = page.evaluate(f"seek({n / IPS:.4f})")
                if etat["defil"] is not None and etat["defil"] != defil_actuel:
                    cadre.evaluate(f"window.scrollTo(0, {etat['defil']})")
                    defil_actuel = etat["defil"]
                if etat["surligne"] != surligne_actuel:
                    cadre.evaluate("""h => {
                        const s = document.querySelector('#breves .breve .sources');
                        s.style.borderRadius = '6px';
                        s.style.background = `rgba(255,182,39,${0.38 * h})`;
                        s.style.boxShadow = `0 0 0 ${7 * h}px rgba(255,182,39,${0.38 * h})`;
                    }""", etat["surligne"])
                    surligne_actuel = etat["surligne"]
                if etat["cle"] != derniere_cle:
                    image = page.screenshot(type="png")
                    derniere_cle = etat["cle"]
                    captures += 1
                processus.stdin.write(image)
            processus.stdin.close()
        except BrokenPipeError:
            pass
        finally:
            if processus.wait() != 0:
                raise RuntimeError("ffmpeg a échoué (voir le message ci-dessus).")
        navigateur.close()
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(f["couverture"]), "-i", str(sortie),
                    "-frames:v", "1", "-q:v", "2", str(sortie.with_suffix(".jpg"))], check=True)
    shutil.rmtree(travail, ignore_errors=True)
    print(f"{sortie.name} : {duree:.1f} s, {captures} images capturées en {time.time() - debut:.0f} s")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--format", choices=list(FORMATS), help="un seul format (par défaut : les deux)")
    args = parser.parse_args()
    if not (DOSSIER_SITE / "index.html").exists():
        print("Construisez d'abord le site : python -m revue.construire", file=sys.stderr)
        return 1
    config = charger_config()
    for nom in [args.format] if args.format else list(FORMATS):
        rendre(nom, config, DOSSIER_MEDIAS / f"presentation-{nom}.mp4")
    return 0


if __name__ == "__main__":
    sys.exit(main())
