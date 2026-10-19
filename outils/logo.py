"""Génère le logo Hebdo Aero (SVG) et ses déclinaisons pour les réseaux (PNG).

Usage : python outils/logo.py
Produit dans assets/logo/ : embleme.svg, logo-clair.svg, logo-sombre.svg,
favicon.svg, avatar-1024.png (photo de profil des réseaux),
banniere-youtube.png (2560 × 1440) et logo-email.png (en-tête de la newsletter).

Les couleurs et le texte se règlent ci-dessous ; relancez le script pour tout régénérer.
"""
from __future__ import annotations

import math
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

RACINE = Path(__file__).resolve().parent.parent
SORTIE = RACINE / "assets" / "logo"
POLICE = RACINE / "assets" / "polices" / "BigShoulders-Bold.woff"

NUIT = "#0B1A2E"
NUIT_2 = "#13294A"
ORANGE = "#FF6A1F"      # l'orange des enregistreurs de vol
SOLEIL = "#FFB627"
CIEL = "#3FA9F5"
BLANC = "#FFFFFF"
TEXTE = "HEBDO AERO"

# Silhouette d'un jet vu de dessus, nez vers le haut, centrée sur (0, 0), longueur 210.
DEMI_JET = [(0, -104), (5, -92), (8, -74), (8, -14), (99, 37), (99, 48), (8, 24), (6, 70),
            (38, 93), (38, 102), (5, 93), (2, 104)]
REACTEUR = (26, -8, 11, 25)   # x, y, largeur, hauteur (côté droit)
# Position du jet dans l'écusson : décalé vers le haut à droite pour que seul le nez crève l'anneau.
POSE = "translate(151 102) rotate(42) scale(0.8)"


def chemin_jet() -> str:
    droite = DEMI_JET
    gauche = [(-x, y) for x, y in reversed(DEMI_JET[1:-1])]
    points = droite + [(0, 106)] + gauche
    d = "M" + " L".join(f"{x:g} {y:g}" for x, y in points) + " Z"
    x, y, l, h = REACTEUR
    for signe in (1, -1):
        x0 = x if signe == 1 else -x - l
        d += f" M{x0} {y + 3} Q{x0} {y} {x0 + 3} {y} L{x0 + l - 3} {y} Q{x0 + l} {y} {x0 + l} {y + 3} " \
             f"L{x0 + l} {y + h} L{x0} {y + h} Z"
    return d


def texte_en_chemin(texte: str, hauteur_capitale: float, x: float, y: float,
                    inclinaison: float = -9, interlettre: float = 0.02) -> tuple[str, float]:
    """Contours vectoriels du texte (le logo ne dépend d'aucune police installée)."""
    police = TTFont(POLICE)
    glyphes = police.getGlyphSet()
    cmap = police.getBestCmap()
    capitale = police["OS/2"].sCapHeight or police["head"].unitsPerEm * 0.7
    echelle = hauteur_capitale / capitale
    pente = math.tan(math.radians(-inclinaison))
    stylo = SVGPathPen(glyphes)
    curseur = 0.0
    for c in texte:
        nom = cmap[ord(c)]
        # y inversé (les polices comptent vers le haut), puis inclinaison vers l'avant
        transfo = (echelle, 0, echelle * pente, -echelle, x + curseur, y)
        glyphes[nom].draw(TransformPen(stylo, transfo))
        curseur += glyphes[nom].width * echelle + hauteur_capitale * interlettre
    return stylo.getCommands(), curseur


def embleme(id_: str = "e", simple: bool = False) -> str:
    """Écusson 256 × 256 : un jet qui crève le cadre en montée, au-dessus d'un horizon en feu."""
    jet = chemin_jet()
    trainees = "" if simple else f"""
    <g clip-path="url(#{id_}-disque)" class="trainees">
      <g transform="{POSE}" stroke-linecap="round" fill="none">
        <path d="M31.5 20 L31.5 300" stroke="url(#{id_}-trainee)" stroke-width="7"/>
        <path d="M-31.5 20 L-31.5 300" stroke="url(#{id_}-trainee)" stroke-width="7"/>
        <path d="M0 112 L0 300" stroke="url(#{id_}-trainee)" stroke-width="3" opacity=".6"/>
      </g>
    </g>"""
    horizon = "" if simple else f"""
    <g clip-path="url(#{id_}-disque)" class="horizon">
      <path d="M20 182 Q128 166 236 182 L236 240 L20 240 Z" fill="{NUIT}" opacity=".55"/>
      <path d="M20 182 Q128 166 236 182" fill="none" stroke="{SOLEIL}" stroke-width="2.5" opacity=".9"/>
    </g>"""
    return f"""
  <defs>
    <linearGradient id="{id_}-ciel" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{NUIT}"/>
      <stop offset=".52" stop-color="{NUIT_2}"/>
      <stop offset=".78" stop-color="#B8441F"/>
      <stop offset=".9" stop-color="{ORANGE}"/>
      <stop offset="1" stop-color="{SOLEIL}"/>
    </linearGradient>
    <linearGradient id="{id_}-trainee" x1="0" y1="20" x2="0" y2="230" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="{BLANC}" stop-opacity=".95"/>
      <stop offset="1" stop-color="{BLANC}" stop-opacity="0"/>
    </linearGradient>
    <clipPath id="{id_}-disque"><circle cx="128" cy="128" r="101"/></clipPath>
  </defs>
  <circle class="fond" cx="128" cy="128" r="124" fill="{NUIT}"/>
  <circle class="ciel" cx="128" cy="128" r="101" fill="url(#{id_}-ciel)"/>
  {horizon}
  {trainees}
  <circle class="anneau" cx="128" cy="128" r="110" fill="none" stroke="{ORANGE}" stroke-width="12"
          transform="rotate(-90 128 128)"/>
  <path class="jet" transform="{POSE}" d="{jet}" fill="{BLANC}"
        stroke="{NUIT}" stroke-width="7" stroke-linejoin="round" paint-order="stroke" fill-rule="nonzero"/>
"""


def svg(contenu: str, largeur: float, hauteur: float) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {largeur:g} {hauteur:g}" '
            f'width="{largeur:g}" height="{hauteur:g}" role="img" aria-label="Hebdo Aero">'
            f"<title>Hebdo Aero</title>{contenu}</svg>\n")


def logotype(couleur_texte: str, id_: str) -> str:
    texte, largeur_texte = texte_en_chemin(TEXTE, 112, 296, 180)
    largeur = 296 + largeur_texte + 12
    fin = 296 + largeur_texte * 0.64      # traînée effilée sous le nom
    trait = f'<path d="M300 207 L{fin:.0f} 200 L{fin - 5:.0f} 212 Z" fill="{ORANGE}"/>'
    return svg(f'{embleme(id_)}<path d="{texte}" fill="{couleur_texte}"/>{trait}', largeur, 256)


def main() -> None:
    SORTIE.mkdir(parents=True, exist_ok=True)
    (SORTIE / "embleme.svg").write_text(svg(embleme("e"), 256, 256), encoding="utf-8")
    (SORTIE / "logo-clair.svg").write_text(logotype(NUIT, "c"), encoding="utf-8")
    (SORTIE / "logo-sombre.svg").write_text(logotype(BLANC, "s"), encoding="utf-8")
    (SORTIE / "favicon.svg").write_text(svg(embleme("f", simple=True), 256, 256), encoding="utf-8")
    print("SVG générés dans", SORTIE)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright absent : les PNG ne sont pas générés.")
        return
    banniere = f"""<html><body style="margin:0;width:2560px;height:1440px;background:
      radial-gradient(120% 90% at 50% 120%, {ORANGE} 0%, #B8441F 22%, {NUIT_2} 52%, {NUIT} 80%);
      display:flex;align-items:center;justify-content:center;overflow:hidden">
      <img src="{(SORTIE / 'logo-sombre.svg').as_uri()}" style="height:300px"></body></html>"""
    avatar = (f'<html><body style="margin:0;background:{NUIT}">'
              f'<img src="embleme.svg" style="width:1024px;height:1024px;display:block"></body></html>')
    # Logo des e-mails (les messageries n'affichent pas le SVG) : fond transparent, 3 fois la taille affichée.
    email = ('<html><body style="margin:0;background:transparent">'
             '<img src="logo-sombre.svg" style="height:144px;display:block"></body></html>')
    temporaire = SORTIE / "_rendu.html"
    with sync_playwright() as p:
        navigateur = p.chromium.launch()
        for html, (l, h), nom in [(avatar, (1024, 1024), "avatar-1024.png"),
                                  (banniere, (2560, 1440), "banniere-youtube.png"),
                                  (email, (535, 144), "logo-email.png")]:
            temporaire.write_text(html, encoding="utf-8")
            page = navigateur.new_page(viewport={"width": l, "height": h})
            page.goto(temporaire.as_uri())
            page.wait_for_timeout(200)
            page.screenshot(path=str(SORTIE / nom), omit_background=True)
        navigateur.close()
    temporaire.unlink()
    print("PNG générés : avatar-1024.png, banniere-youtube.png, logo-email.png")


if __name__ == "__main__":
    main()
