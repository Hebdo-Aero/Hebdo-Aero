"""Montage de la vidéo verticale 1080×1920.

Trois couches, assemblées par ffmpeg :
  1. le fond : plans filmés Pexels ou Pixabay (un par scène), sinon le ciel généré qui défile ;
  2. le calque graphique transparent (titres, route, sous-titres mot à mot), dessiné en HTML
     et capturé image par image ;
  3. le son : voix Google, musique (nappe générée ou votre fichier), souffles aux transitions,
     mixés avec atténuation automatique de la musique sous la voix et volume normalisé.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from . import ciel, illustrations, son, voix
from .config import RACINE
from .reseaux import remplir_liens

GABARITS = Path(__file__).parent / "templates"
POLICES = RACINE / "assets" / "polices"
AVANT, APRES, APRES_INTRO = 0.30, 0.55, 0.35
IMPACT = 1.2          # instant de l'impact du générique (le jet se pose, la musique démarre)
VOIX_GENERIQUE = 1.5  # la voix commence juste après l'impact
DUREE_GENERIQUE = 4.2  # durée minimale du générique animé
FIN_PONCTUATION = re.compile(r"[,;:.!?…]$")
FIN_PHRASE = re.compile(r"[.!?…]$")


class ErreurVideo(RuntimeError):
    pass


# --- Chronologie et sous-titres ---------------------------------------------------------

def chronologie(durees_audio: list[float], court: bool = False, generique: bool = False) -> list[dict]:
    """Début et fin de chaque scène, et instant où démarre sa narration.

    En format court, la voix démarre dès la première image et les silences sont resserrés.
    Avec `generique`, la première scène est le générique animé : la voix part après l'impact.
    """
    temps, t = [], 0.0
    for i, d in enumerate(durees_audio):
        avant = (0.05 if i == 0 else 0.15) if court else AVANT
        apres = 0.3 if court else (APRES_INTRO if i == 0 else APRES)
        if generique and i == 0:
            avant = VOIX_GENERIQUE
        fin = t + avant + d + apres
        if generique and i == 0:
            fin = max(fin, DUREE_GENERIQUE)
        temps.append({"debut": round(t, 3), "voix": round(t + avant, 3), "fin": round(fin, 3)})
        t = temps[-1]["fin"]
    temps[-1]["fin"] = round(temps[-1]["fin"] + 0.8, 3)          # dernière image tenue un peu plus longtemps
    return temps


def _repartir(indices: list[int], poids: list[float], debut: float, fin: float, sortie: list) -> None:
    total = sum(poids[i] for i in indices) or 1
    t = debut
    for i in indices:
        d = (fin - debut) * poids[i] / total
        sortie[i] = (round(t, 3), round(t + d, 3))
        t += d


def minutage_mots(narration: str, duree_audio: float,
                  segments: list[tuple[float, float]] | None = None) -> list[tuple[float, float, str]]:
    """Instant de chaque mot (relatif au début de la narration).

    Si les silences de la voix ont été repérés et correspondent aux propositions du texte
    (virgules, points), chaque proposition est calée exactement sur son passage parlé ;
    sinon, les mots sont répartis sur le temps de parole au prorata de leur longueur.
    """
    mots = narration.split()
    if not mots:
        return []
    poids = [len(m) + 1.5 for m in mots]
    places: list = [None] * len(mots)
    if segments:
        propositions, courante = [], []
        for i, m in enumerate(mots):
            courante.append(i)
            if FIN_PONCTUATION.search(m):
                propositions.append(courante)
                courante = []
        if courante:
            propositions.append(courante)
        if len(propositions) == len(segments):
            for indices, (a, b) in zip(propositions, segments):
                _repartir(indices, poids, a, b, places)
        else:   # temps de parole « mis bout à bout », puis replacé sur les vrais instants
            parole = sum(b - a for a, b in segments)
            continu: list = [None] * len(mots)
            _repartir(list(range(len(mots))), poids, 0, parole, continu)

            def reel(x: float) -> float:
                for a, b in segments:
                    if x <= b - a:
                        return a + x
                    x -= b - a
                return segments[-1][1]
            places = [(reel(a), reel(b)) for a, b in continu]
    else:
        _repartir(list(range(len(mots))), poids, 0.05, max(0.1, duree_audio - 0.05), places)
    return [(a, b, m) for (a, b), m in zip(places, mots)]


def sous_titres(scenes: list[dict], temps: list[dict], minutages: list[list], limite: int = 34) -> list[dict]:
    """Groupes de quelques mots affichés ensemble, avec l'instant de chaque mot."""
    morceaux = []
    for s, t, mots in zip(scenes, temps, minutages):
        groupes, courant = [], []
        for a, b, m in mots:
            texte = " ".join(x[2] for x in courant + [(a, b, m)])
            if courant and (len(texte) > limite or FIN_PHRASE.search(courant[-1][2])
                            or (FIN_PONCTUATION.search(courant[-1][2]) and len(texte) > limite * 0.6)):
                groupes.append(courant)
                courant = []
            courant.append((a, b, m))
        if courant:
            groupes.append(courant)
        for j, g in enumerate(groupes):
            debut = t["voix"] + g[0][0]
            fin = t["voix"] + groupes[j + 1][0][0] if j + 1 < len(groupes) else min(t["voix"] + g[-1][1] + 0.45, t["fin"] - 0.05)
            morceaux.append({"debut": round(debut, 3), "fin": round(fin, 3),
                             "mots": [{"t": round(t["voix"] + a, 3), "m": m} for a, _, m in g]})
    return morceaux


def decouper_phrases(texte: str, limite: int = 34) -> list[str]:
    """Découpage indicatif d'une narration en sous-titres (même règle que la vidéo)."""
    mots = minutage_mots(texte, 10.0)
    return [" ".join(m["m"] for m in g["mots"])
            for g in sous_titres([{"narration": texte}], [{"debut": 0, "voix": 0, "fin": 99}], [mots], limite)]


# --- Son --------------------------------------------------------------------------------

def _normaliser_piste(source: Path, cible: Path) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(source), "-ar", "48000", "-ac", "1",
                    "-sample_fmt", "s16", str(cible)], check=True)


def piste_narration(pistes: list[Path], temps: list[dict], cible: Path) -> None:
    """Assemble les narrations de chaque scène sur une piste unique, aux bons instants."""
    total = int(temps[-1]["fin"] * 48000)
    tampon = bytearray(total * 2)
    with tempfile.TemporaryDirectory() as tmp:
        for i, (piste, t) in enumerate(zip(pistes, temps)):
            norme = Path(tmp) / f"{i}.wav"
            _normaliser_piste(piste, norme)
            with wave.open(str(norme)) as w:
                pcm = w.readframes(w.getnframes())
            debut = int(t["voix"] * 48000) * 2
            pcm = pcm[: max(0, len(tampon) - debut)]
            tampon[debut:debut + len(pcm)] = pcm
    with wave.open(str(cible), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(bytes(tampon))


# --- Fonds -----------------------------------------------------------------------------

def preparer_fonds(scenes: list[dict], temps: list[dict], travail: Path) -> list[dict | None]:
    """Un plan filmé (Pexels ou Pixabay) par scène quand c'est possible ; None = ciel généré."""
    plans: list[dict | None] = []
    pris: set[int] = set()
    actif = illustrations.disponible()
    for s, t in zip(scenes, temps):
        recherche = s.get("recherche_video")
        if not actif or not recherche or s["type"] == "chiffre":
            plans.append(None)
            continue
        duree = t["fin"] - t["debut"]
        trouve = (illustrations.chercher_video(recherche, duree, pris)
                  or illustrations.chercher_video("airplane flying", duree, pris))
        if not trouve:
            plans.append(None)
            continue
        try:
            fichier = illustrations.telecharger(trouve["lien"], travail / "plans" / f"{len(plans):02d}.mp4")
        except Exception as e:  # noqa: BLE001 — un plan manquant n'empêche pas la vidéo
            print(f"  plan ignoré ({e})")
            plans.append(None)
            continue
        pris.add(trouve["id"])
        plans.append({**trouve, "fichier": str(fichier)})
    return plans


# --- Rendu ------------------------------------------------------------------------------

def _page_html() -> str:
    env = Environment(loader=FileSystemLoader(GABARITS), autoescape=True)
    logos = RACINE / "assets" / "logo"
    return env.get_template("video.html").render(polices=POLICES.as_uri(),
                                                 logo=(logos / "logo-sombre.svg").as_uri(),
                                                 embleme=(logos / "embleme.svg").as_uri(),
                                                 embleme_svg=(logos / "embleme.svg").read_text(encoding="utf-8"),
                                                 impact=IMPACT)


def commande_ffmpeg(total: float, ips: int, ciel_img: Path, plans: list[dict | None], temps: list[dict],
                    voix_wav: Path | None, musique: Path, effets: Path, cfg: dict, sortie: Path,
                    musique_generee: bool = True, generique: bool = False) -> list[str]:
    entrees = ["-f", "image2pipe", "-framerate", str(ips), "-c:v", "png", "-i", "-",
               "-loop", "1", "-framerate", str(ips), "-t", f"{total:.3f}", "-i", str(ciel_img)]
    filtres = [f"[1:v]crop=1080:1920:x='(in_w-1080)*t/{total:.3f}':y=0,setsar=1,format=yuva420p[f0]"]
    n, courant = 2, "f0"
    for i, plan in enumerate(plans):
        if not plan:
            continue
        d = temps[i]["fin"] - temps[i]["debut"]
        entrees += ["-stream_loop", "-1", "-t", f"{d + 0.5:.3f}", "-i", plan["fichier"]]
        filtres.append(
            f"[{n}:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps={ips},setsar=1,"
            f"eq=saturation=1.08:contrast=1.04:brightness=-0.05,format=yuva420p,fade=t=in:st=0:d=0.4:alpha=1,"
            f"fade=t=out:st={max(0.1, d - 0.1):.3f}:d=0.4:alpha=1,setpts=PTS-STARTPTS+{temps[i]['debut']:.3f}/TB[c{n}]")
        filtres.append(f"[{courant}][c{n}]overlay=eof_action=pass:format=auto[f{n}]")
        courant, n = f"f{n}", n + 1
    filtres.append(f"[{courant}][0:v]overlay=format=auto,format=yuv420p[v]")

    if voix_wav:
        entrees += ["-i", str(voix_wav)]
    else:
        entrees += ["-f", "lavfi", "-t", f"{total:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
    iv = n
    entrees += (["-stream_loop", "-1"] if musique.suffix != ".wav" else []) + ["-t", f"{total:.3f}", "-i", str(musique)]
    entrees += ["-i", str(effets)]
    stereo = "aformat=sample_rates=48000:channel_layouts=stereo"
    filtres += [
        f"[{iv}:a]{stereo},highpass=f=70,acompressor=threshold=0.08:ratio=3:attack=5:release=150:makeup=1.6,"
        f"asplit=2[voix][cle]",
        f"[{iv + 1}:a]{stereo},{_reglage_musique(cfg, total, musique_generee, generique)}[mus0]",
        "[mus0][cle]sidechaincompress=threshold=0.035:ratio=7:attack=25:release=450[mus]",
        f"[{iv + 2}:a]{stereo},volume={cfg.get('volume_transitions', 0.35)}[fx]",
        "[voix][mus][fx]amix=inputs=3:duration=first:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11,"
        f"aresample=48000,{stereo}[a]",
    ]
    return ["ffmpeg", "-y", "-loglevel", "error", *entrees, "-filter_complex", ";".join(filtres),
            "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
            "-profile:v", "high", "-level", "4.1", "-r", str(ips),
            "-g", str(ips * 2), "-keyint_min", str(ips * 2), "-sc_threshold", "0", "-flags", "+cgop",
            "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart", "-t", f"{total:.3f}", str(sortie)]


def _reglage_musique(cfg: dict, total: float, generee: bool, generique: bool) -> str:
    """Volume de la musique : plus fort pendant le générique (avant la voix), puis en retrait.

    La musique générée a son propre début (montée, impact) et sa propre fin (accord final) ;
    une musique personnelle est décalée pour démarrer sur l'impact, avec fondus.
    """
    base = cfg.get("volume_musique", 0.32)
    filtres = []
    if not generee:
        if generique:
            ms = int(IMPACT * 1000)
            filtres.append(f"adelay={ms}|{ms}")
        filtres += [f"afade=t=in:st={IMPACT if generique else 0}:d=1.0",
                    f"afade=t=out:st={max(0, total - 2.5):.2f}:d=2.5"]
    if generique:
        bascule = VOIX_GENERIQUE + 0.1
        filtres.append(f"volume='{base}+{max(0.0, 0.8 - base):.2f}*clip(({bascule}-t)/0.3,0,1)':eval=frame")
    else:
        filtres.append(f"volume={base}")
    return ",".join(filtres)


def rendre(config: dict, script: dict, sortie: Path, *, avec_voix: bool = True,
           dossier_travail: Path | None = None, scenes: list[dict] | None = None,
           court: bool = False) -> dict:
    """Produit `sortie` (MP4) et son affiche (JPG). Renvoie les métadonnées, dont les crédits.

    `court=True` : short d'accroche (texte plein écran dès la première image, rythme plus vif).
    """
    from playwright.sync_api import sync_playwright

    cfg = config["video"]
    ips = int(cfg.get("images_par_seconde", 30))
    vitesse = cfg.get("vitesse", 1.0) * (1.06 if court else 1.0)
    duree_max = 35 if court else cfg.get("duree_max", 88)
    scenes = [dict(s, texte_ecran=remplir_liens(s["texte_ecran"], config, script["numero"]))
              for s in (scenes or script["video"]["scenes"])]
    travail = Path(dossier_travail or tempfile.mkdtemp(prefix="video-"))
    travail.mkdir(parents=True, exist_ok=True)

    if avec_voix:
        pistes = voix.synthetiser([s["narration"] for s in scenes], travail / "voix", cfg["voix"], vitesse)
        durees = [voix.duree(p) for p in pistes]
    else:
        pistes, durees = [], [voix.estimer_duree(s["narration"], vitesse) for s in scenes]

    # Garde-fou : on retire des sujets tant que la vidéo dépasse la durée maximale.
    while not court and sum(durees) + len(durees) * (AVANT + APRES) + 0.8 > duree_max:
        sujets = [i for i, s in enumerate(scenes) if s["type"] == "sujet"]
        if len(sujets) <= 2:
            raise ErreurVideo("Narration trop longue, même réduite à deux sujets.")
        i = sujets[-1]
        scenes, durees = scenes[:i] + scenes[i + 1:], durees[:i] + durees[i + 1:]
        pistes = pistes[:i] + pistes[i + 1:] if pistes else pistes

    generique = (not court) and scenes and scenes[0]["type"] == "intro"
    temps = chronologie(durees, court=court, generique=generique)
    total = temps[-1]["fin"]
    if total > duree_max:
        raise ErreurVideo(f"Vidéo trop longue ({total:.0f} s pour {duree_max} s au plus).")
    segments = [voix.segments_parole(p) for p in pistes] if pistes else [None] * len(scenes)
    minutages = [minutage_mots(s["narration"], d, seg) for s, d, seg in zip(scenes, durees, segments)]

    plans = preparer_fonds(scenes, temps, travail)
    for s, plan in zip(scenes, plans):
        s["credit"] = f"Image d'illustration : {plan['auteur']} / {plan.get('source', 'Pexels')}" if plan else ""
    ciel_img = ciel.enregistrer(travail / "ciel.jpg", 1700, 1920, graine=int(script["numero"]))

    voix_wav = None
    if avec_voix:
        voix_wav = travail / "narration.wav"
        piste_narration(pistes, temps, voix_wav)
    musique = RACINE / cfg.get("musique", "assets/musique.mp3")
    musique_generee = not (cfg.get("musique") and musique.is_file())
    if musique_generee:
        musique = son.musique(total + 0.5, travail / "musique.wav", graine=int(script["numero"]) + (7 if court else 0),
                              tempo=100.0 if court else 92.0, impact=IMPACT if generique else None, energique=court)
    effets = son.souffles([t["debut"] for t in temps[1:]], total, travail / "souffles.wav",
                          impact=IMPACT if (generique and not musique_generee) else None)

    donnees = {"scenes": scenes, "temps": temps, "soustitres": sous_titres(scenes, temps, minutages),
               "marque": f"N° {script['numero']}", "direct": court,
               "sous_titre": config["site"].get("sous_titre", ""),
               # mention légale d'un partenaire, visible pendant toute la vidéo (récap seulement)
               "publicite": "" if court else (script.get("video") or {}).get("publicite", "")}
    page_html = travail / "video.html"
    page_html.write_text(_page_html(), encoding="utf-8")
    sortie.parent.mkdir(parents=True, exist_ok=True)
    commande = commande_ffmpeg(total, ips, ciel_img, plans, temps, voix_wav, musique, effets, cfg, sortie,
                               musique_generee=musique_generee, generique=generique)

    nb_images, captures = int(total * ips), 0
    with sync_playwright() as p:
        navigateur = p.chromium.launch()
        page = navigateur.new_page(viewport={"width": 1080, "height": 1920}, device_scale_factor=1)
        page.goto(page_html.as_uri())
        page.evaluate("document.fonts.ready")
        page.evaluate("d => preparer(d)", donnees)
        processus = subprocess.Popen(commande, stdin=subprocess.PIPE)
        cle_precedente, image = None, b""
        try:
            for n in range(nb_images):
                cle = page.evaluate(f"seek({n / ips:.4f})")
                if cle != cle_precedente:
                    image = page.screenshot(type="png", omit_background=True)
                    cle_precedente = cle
                    captures += 1
                processus.stdin.write(image)
            processus.stdin.close()
        except BrokenPipeError:
            pass
        finally:
            if processus.wait() != 0:
                raise ErreurVideo("ffmpeg a échoué (voir le message ci-dessus).")
        navigateur.close()

    # Affiche : une image de l'ouverture, extraite de la vidéo finale.
    instant_affiche = 0.4 if court else min(1.6, temps[0]["fin"] - 0.3)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{instant_affiche:.2f}",
                    "-i", str(sortie), "-frames:v", "1", "-q:v", "3", str(sortie.with_suffix(".jpg"))], check=True)
    if not dossier_travail:
        shutil.rmtree(travail, ignore_errors=True)
    credits = sorted({f"{p['auteur']} ({p.get('source', 'Pexels')})" for p in plans if p})
    return {"duree": round(total, 2), "images": nb_images, "captures": captures, "scenes": len(scenes),
            "voix": avec_voix, "plans_filmes": sum(1 for p in plans if p), "credits": credits}


def image_partage(config: dict, numero: dict, sortie: Path) -> None:
    """Image 1200×630 pour les aperçus de lien (Open Graph) sur Facebook, Threads, etc."""
    from playwright.sync_api import sync_playwright

    from .config import periode_fr
    env = Environment(loader=FileSystemLoader(GABARITS), autoescape=True)
    html = env.get_template("partage.html").render(
        polices=POLICES.as_uri(), nom=config["site"]["nom"], numero=numero,
        logo=(RACINE / "assets" / "logo" / "logo-sombre.svg").as_uri(),
        periode=periode_fr(numero["debut"], numero["fin"]))
    with tempfile.TemporaryDirectory() as tmp:
        page_html = Path(tmp) / "partage.html"
        page_html.write_text(html, encoding="utf-8")
        with sync_playwright() as p:
            navigateur = p.chromium.launch()
            page = navigateur.new_page(viewport={"width": 1200, "height": 630})
            page.goto(page_html.as_uri())
            page.evaluate("document.fonts.ready")
            sortie.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(sortie), type="jpeg", quality=90)
            navigateur.close()


def apercu_json(script: dict) -> str:
    return json.dumps(script["video"], ensure_ascii=False, indent=1)
