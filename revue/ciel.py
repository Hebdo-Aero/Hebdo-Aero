"""Ciel de coucher de soleil généré par le programme (aucun droit d'auteur).

Sert de fond aux vidéos quand Pexels ne fournit pas d'images, et d'image d'ouverture
du site quand aucune photo n'est disponible. Chaque numéro a son propre ciel (graine).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

PALETTE_CIEL = [  # position verticale (0 = haut), couleur
    (0.00, (11, 26, 46)), (0.30, (22, 46, 84)), (0.46, (52, 64, 112)),
    (0.55, (128, 72, 104)), (0.60, (226, 110, 62)), (0.625, (255, 184, 98)),
]
PALETTE_MER = [  # mer de nuages sous l'horizon
    (0.625, (240, 160, 110)), (0.70, (120, 92, 120)), (0.82, (44, 50, 88)), (1.00, (16, 24, 46)),
]


def _degrade(v: np.ndarray, palette) -> np.ndarray:
    pos = np.array([p for p, _ in palette])
    cols = np.array([c for _, c in palette], dtype=np.float32)
    return np.stack([np.interp(v, pos, cols[:, k]) for k in range(3)], axis=-1)


def bruit(largeur: int, hauteur: int, graine: int, echelle: float, octaves: int = 6,
          etirement: float = 3.0) -> np.ndarray:
    """Bruit fractal lissé, étiré horizontalement (nuages en couches)."""
    rng = np.random.default_rng(graine)
    total = np.zeros((hauteur, largeur), dtype=np.float32)
    amplitude, somme = 1.0, 0.0
    for o in range(octaves):
        pas = echelle / (2 ** o)
        gx = max(3, int(largeur / (pas * etirement)) + 2)
        gy = max(3, int(hauteur / pas) + 2)
        grille = Image.fromarray(rng.random((gy, gx), dtype=np.float32), mode="F")
        total += amplitude * np.asarray(grille.resize((largeur, hauteur), Image.BICUBIC))
        somme += amplitude
        amplitude *= 0.52
    total /= somme
    return (total - total.min()) / (total.max() - total.min() + 1e-6)


def lisse(a: float, b: float, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def generer(largeur: int, hauteur: int, graine: int = 1, horizon: float = 0.625,
            soleil_x: float = 0.68) -> Image.Image:
    v = np.linspace(0, 1, hauteur, dtype=np.float32)[:, None] * np.ones((1, largeur), np.float32)
    x = np.linspace(0, 1, largeur, dtype=np.float32)[None, :] * np.ones((hauteur, 1), np.float32)
    ciel = np.where(v[..., None] <= horizon, _degrade(v, PALETTE_CIEL), _degrade(v, PALETTE_MER))

    # Halo du soleil sur l'horizon
    rapport = largeur / hauteur
    d2 = ((x - soleil_x) * rapport) ** 2 + ((v - horizon) * 1.6) ** 2
    halo = np.exp(-d2 / 0.018)[..., None]
    ciel = ciel + halo * np.array([255, 170, 90], np.float32) * 0.55

    # Nuages d'altitude : étirés, éclairés par en dessous près de l'horizon
    n = bruit(largeur, hauteur, graine, echelle=hauteur * 0.2, etirement=6.0)
    densite = lisse(0.52, 0.78, n) * lisse(0.12, 0.45, v) * (1 - lisse(horizon - 0.03, horizon, v))
    lumiere = lisse(0.25, horizon, v)[..., None]
    couleur_haut = (1 - lumiere) * np.array([92, 98, 144], np.float32) + lumiere * np.array([255, 150, 104], np.float32)
    relief = np.clip((n - np.roll(n, 6, axis=0)) * 6 + 0.6, 0.35, 1.15)[..., None]
    ciel = ciel * (1 - densite[..., None] * 0.85) + couleur_haut * relief * densite[..., None] * 0.85

    # Mer de nuages sous l'horizon, sommets dorés
    m = bruit(largeur, hauteur, graine + 7, echelle=hauteur * 0.16, etirement=2.6)
    sous = lisse(horizon - 0.005, horizon + 0.03, v)
    crete = np.clip((m - np.roll(m, 10, axis=0)) * 7 + 0.5, 0, 1)[..., None]
    proche = (1 - lisse(horizon, 0.85, v))[..., None]
    couleur_mer = crete * (proche * np.array([255, 178, 120], np.float32) + (1 - proche) * np.array([96, 104, 150], np.float32)) \
        + (1 - crete) * np.array([30, 38, 72], np.float32)
    melange = (sous * lisse(0.25, 0.6, m))[..., None]
    ciel = ciel * (1 - melange) + couleur_mer * melange

    image = Image.fromarray(np.clip(ciel, 0, 255).astype(np.uint8), "RGB")
    return image.filter(ImageFilter.GaussianBlur(1.2))


def enregistrer(chemin: Path, largeur: int, hauteur: int, graine: int, qualite: int = 86) -> Path:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    generer(largeur, hauteur, graine).save(chemin, quality=qualite, optimize=True, progressive=True)
    return chemin


if __name__ == "__main__":
    enregistrer(Path("ciel-test.jpg"), 1800, 1000, 1)
