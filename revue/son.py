"""Habillage sonore généré par le programme (aucun droit d'auteur) :
une nappe musicale douce sous la voix, et un léger souffle aux changements de scène.

Si vous déposez votre propre musique libre de droits dans assets/musique.mp3,
elle remplace la nappe générée.
"""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

FREQ = 48000

# Progression d'accords posée, en la mineur : Am9, Fmaj7, Cmaj7(9), G6 (fréquences en Hz)
def _note(midi: float) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)


ACCORDS = [
    [57, 60, 64, 67, 71],   # Am9
    [53, 57, 60, 64, 69],   # Fmaj7
    [48, 55, 59, 62, 64],   # Cmaj7(9)
    [55, 59, 62, 64, 67],   # G6
]
BASSES = [45, 41, 36, 43]
ARPEGE = [0, 2, 1, 3, 2, 4, 3, 1]   # indices dans l'accord


def _ecrire(chemin: Path, stereo: np.ndarray) -> Path:
    stereo = np.clip(stereo, -1, 1)
    donnees = (stereo * 32767).astype("<i2")
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(chemin), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(FREQ)
        w.writeframes(donnees.tobytes())
    return chemin


def _passe_bas(signal: np.ndarray, coupure: float) -> np.ndarray:
    """Filtre passe-bas simple (deux pôles) pour adoucir le timbre."""
    a = np.exp(-2 * np.pi * coupure / FREQ)
    sortie = signal.copy()
    for _ in range(2):
        y = np.empty_like(sortie)
        precedent = 0.0
        for i, x in enumerate(sortie):
            precedent = (1 - a) * x + a * precedent
            y[i] = precedent
        sortie = y
    return sortie


def nappe(duree: float, chemin: Path, graine: int = 1, tempo: float = 84.0) -> Path:
    rng = np.random.default_rng(graine)
    n = int(duree * FREQ)
    t = np.arange(n) / FREQ
    gauche, droite = np.zeros(n), np.zeros(n)
    duree_accord = 4 * 60 / tempo * 2            # deux mesures par accord
    nb = int(np.ceil(duree / duree_accord)) + 1
    for k in range(nb):
        debut = k * duree_accord
        accord, basse = ACCORDS[k % 4], BASSES[k % 4]
        a0, a1 = int(debut * FREQ), min(n, int((debut + duree_accord + 1.5) * FREQ))
        if a0 >= n:
            break
        tt = t[a0:a1] - debut
        env = np.minimum(1, tt / 1.6) * np.clip((duree_accord + 1.5 - tt) / 1.5, 0, 1)   # attaque lente, fondu
        for j, midi in enumerate(accord):
            f = _note(midi + 12)
            desaccord = 1 + rng.uniform(-0.0025, 0.0025)
            ton = (np.sin(2 * np.pi * f * tt) + 0.35 * np.sin(2 * np.pi * 2 * f * desaccord * tt)
                   + 0.12 * np.sin(2 * np.pi * 3 * f * tt)) * env * 0.055
            pan = 0.3 + 0.4 * (j / (len(accord) - 1))
            gauche[a0:a1] += ton * (1 - pan)
            droite[a0:a1] += ton * pan
        sb = np.sin(2 * np.pi * _note(basse) * tt) * env * 0.11
        gauche[a0:a1] += sb
        droite[a0:a1] += sb
        # petites notes pincées en croches, très discrètes
        croche = 60 / tempo / 2
        for c in range(int(duree_accord / croche)):
            d0 = debut + c * croche
            p0, p1 = int(d0 * FREQ), min(n, int((d0 + 1.2) * FREQ))
            if p0 >= n:
                break
            tp = t[p0:p1] - d0
            f = _note(accord[ARPEGE[c % len(ARPEGE)]] + 24)
            pince = np.sin(2 * np.pi * f * tp) * np.exp(-tp * 5.5) * 0.035 * (1 if c % 2 == 0 else 0.7)
            cote = 0.25 if c % 2 == 0 else 0.75
            gauche[p0:p1] += pince * (1 - cote)
            droite[p0:p1] += pince * cote
    # souffle d'air très léger
    air = _passe_bas(rng.normal(0, 1, n // 8), 900)
    air = np.repeat(air, 8)[:n] * 0.006
    gauche += air
    droite += air
    stereo = np.stack([gauche, droite], axis=1)
    stereo *= np.minimum(1, t / 2.0)[:, None] * np.clip((duree - t) / 3.0, 0, 1)[:, None]   # fondus
    stereo /= max(1e-6, np.abs(stereo).max()) / 0.6
    return _ecrire(chemin, stereo)


def souffles(instants: list[float], duree: float, chemin: Path, graine: int = 2) -> Path:
    """Piste d'effets : un « whoosh » discret à chaque changement de scène."""
    rng = np.random.default_rng(graine)
    n = int(duree * FREQ)
    piste = np.zeros((n, 2))
    longueur = int(0.75 * FREQ)
    tt = np.arange(longueur) / FREQ
    for k, instant in enumerate(instants):
        bruit = rng.normal(0, 1, longueur)
        # balayage : le filtre s'ouvre puis se referme
        doux = _passe_bas(bruit, 2200)
        tres_doux = _passe_bas(bruit, 500)
        ouverture = np.sin(np.pi * np.clip(tt / 0.75, 0, 1)) ** 2
        son = (tres_doux * (1 - ouverture) + doux * ouverture) * ouverture * 0.35
        debut = int((instant - 0.45) * FREQ)
        if debut < 0 or debut + longueur > n:
            continue
        pan = tt / 0.75 if k % 2 == 0 else 1 - tt / 0.75
        piste[debut:debut + longueur, 0] += son * (1 - pan)
        piste[debut:debut + longueur, 1] += son * pan
    crete = np.abs(piste).max()
    if crete > 0:
        piste *= 0.5 / crete
    return _ecrire(chemin, piste)
