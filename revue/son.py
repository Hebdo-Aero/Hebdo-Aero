"""Habillage sonore généré par le programme (aucun droit d'auteur).

- `musique` : une musique d'accompagnement en ré majeur, posée et lumineuse (piano électrique,
  nappe chaude, basse, percussions douces, arpèges, réverbération), qui se termine sur un accord
  résolu. Avec `impact`, elle commence par une montée et un « impact » calé sur le générique.
- `souffles` : un léger souffle à chaque changement de scène.

Si vous déposez votre propre musique libre de droits dans assets/musique.mp3, elle remplace
la musique générée (le générique garde alors son impact sonore, joué par-dessus).
"""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
from scipy.signal import butter, fftconvolve, sosfilt

FREQ = 48000

# Progression en ré majeur : Dmaj9, Bm7(11), Gmaj7(9), Asus — voix conduites au plus près.
ACCORDS = [
    {"basse": 38, "notes": [54, 57, 61, 64]},   # Dmaj9 : fa# la do# mi
    {"basse": 35, "notes": [54, 57, 62, 64]},   # Bm7(11) : fa# la ré mi
    {"basse": 31, "notes": [54, 57, 59, 62]},   # Gmaj7(9) : fa# la si ré
    {"basse": 33, "notes": [52, 57, 59, 62]},   # Asus : mi la si ré
]
# Pont, pour varier toutes les 8 mesures : Gmaj7, A6, F#m7, Bm7.
PONT = [
    {"basse": 31, "notes": [54, 57, 59, 62]},
    {"basse": 33, "notes": [52, 57, 61, 66]},
    {"basse": 30, "notes": [54, 57, 61, 64]},
    {"basse": 35, "notes": [54, 57, 62, 66]},
]
TONIQUE = {"basse": 38, "notes": [54, 57, 61, 64, 69]}


def accord_de_la_mesure(k: int) -> dict:
    """Couplet (8 mesures) puis pont (4 mesures), en boucle."""
    position = k % 12
    return PONT[position - 8] if position >= 8 else ACCORDS[position % 4]


def hz(midi: float) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)


def _filtre(signal: np.ndarray, frequence: float | tuple, type_: str = "lowpass", ordre: int = 2) -> np.ndarray:
    sos = butter(ordre, frequence, btype=type_, fs=FREQ, output="sos")
    return sosfilt(sos, signal, axis=0)


def _ajouter(piste: np.ndarray, debut: float, son: np.ndarray, gain: float = 1.0, pan: float = 0.5) -> None:
    """Mixe un son mono dans une piste stéréo, à l'instant `debut` (secondes)."""
    i = int(debut * FREQ)
    if i >= len(piste) or i + len(son) <= 0:
        return
    if i < 0:
        son, i = son[-i:], 0
    son = son[: len(piste) - i]
    piste[i:i + len(son), 0] += son * gain * np.cos(pan * np.pi / 2)
    piste[i:i + len(son), 1] += son * gain * np.sin(pan * np.pi / 2)


def _ecrire(chemin: Path, stereo: np.ndarray) -> Path:
    donnees = (np.clip(stereo, -1, 1) * 32767).astype("<i2")
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(chemin), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(FREQ)
        w.writeframes(donnees.tobytes())
    return chemin


# --- Instruments ------------------------------------------------------------------------

def piano(midi: float, duree: float, force: float = 1.0) -> np.ndarray:
    """Piano électrique par synthèse FM (timbre rond, attaque en cloche)."""
    t = np.arange(int((duree + 1.6) * FREQ)) / FREQ
    f = hz(midi)
    indice = 1.6 * force * np.exp(-t / 0.35)
    ton = np.sin(2 * np.pi * f * t + indice * np.sin(2 * np.pi * f * t))
    ton += 0.12 * np.sin(2 * np.pi * 4.0 * f * t) * np.exp(-t / 0.12)
    env = np.minimum(1, t / 0.004) * np.exp(-t / 1.4)
    env *= np.clip((duree + 1.6 - t) / 0.25, 0, 1)
    return ton * env * force


def nappe_note(midi: float, duree: float) -> np.ndarray:
    """Nappe chaude : trois dents de scie désaccordées (filtrées ensuite)."""
    t = np.arange(int((duree + 1.2) * FREQ)) / FREQ
    f = hz(midi)
    ton = sum(2 * ((t * f * (1 + c) + phase) % 1) - 1 for c, phase in ((-0.004, 0.1), (0, 0.5), (0.0045, 0.8)))
    env = np.minimum(1, t / 0.9) * np.clip((duree + 1.2 - t) / 1.2, 0, 1)
    return ton * env / 3


def basse(midi: float, duree: float) -> np.ndarray:
    t = np.arange(int((duree + 0.15) * FREQ)) / FREQ
    f = hz(midi)
    ton = np.sin(2 * np.pi * f * t) + 0.25 * np.sin(4 * np.pi * f * t) + 0.08 * np.sin(6 * np.pi * f * t)
    env = np.minimum(1, t / 0.01) * (0.75 + 0.25 * np.exp(-t / 0.15)) * np.clip((duree + 0.15 - t) / 0.12, 0, 1)
    return ton * env


def pince(midi: float) -> np.ndarray:
    t = np.arange(int(0.9 * FREQ)) / FREQ
    f = hz(midi)
    return (np.sin(2 * np.pi * f * t) + 0.3 * np.sin(4 * np.pi * f * t) * np.exp(-t / 0.08)) * np.exp(-t / 0.28) \
        * np.minimum(1, t / 0.003)


def grosse_caisse() -> np.ndarray:
    t = np.arange(int(0.45 * FREQ)) / FREQ
    phase = 2 * np.pi * np.cumsum(45 + 75 * np.exp(-t / 0.035)) / FREQ
    return np.sin(phase) * np.exp(-t / 0.16) * np.minimum(1, t / 0.002)


def caisse_claire(rng) -> np.ndarray:
    t = np.arange(int(0.35 * FREQ)) / FREQ
    bruit = _filtre(rng.normal(0, 1, len(t)), (900, 5000), "bandpass")
    corps = np.sin(2 * np.pi * 185 * t) * np.exp(-t / 0.05)
    return (bruit * np.exp(-t / 0.085) * 0.9 + corps * 0.5) * np.minimum(1, t / 0.002)


def charleston(rng, ouvert: bool = False) -> np.ndarray:
    t = np.arange(int((0.25 if ouvert else 0.08) * FREQ)) / FREQ
    bruit = _filtre(rng.normal(0, 1, len(t)), 7000, "highpass")
    return bruit * np.exp(-t / (0.09 if ouvert else 0.022))


def cymbale(rng, duree: float = 2.5) -> np.ndarray:
    t = np.arange(int(duree * FREQ)) / FREQ
    bruit = _filtre(rng.normal(0, 1, len(t)), 4500, "highpass")
    return bruit * np.exp(-t / 0.9) * np.minimum(1, t / 0.003)


def reponse_impulsionnelle(rng, duree: float = 2.4, decroissance: float = 0.55) -> np.ndarray:
    """Réverbération synthétique : bruit stéréo qui décroît, assombri avec le temps."""
    t = np.arange(int(duree * FREQ)) / FREQ
    ri = rng.normal(0, 1, (len(t), 2)) * np.exp(-t / decroissance)[:, None]
    ri = _filtre(ri, 5500)
    ri[: int(0.012 * FREQ)] = 0                       # petit pré-délai
    return ri / np.sqrt((ri ** 2).sum(axis=0))


# --- Composition ------------------------------------------------------------------------

def musique(duree: float, chemin: Path, graine: int = 1, tempo: float = 92.0,
            impact: float | None = None, energique: bool = False) -> Path:
    """Musique d'accompagnement de `duree` secondes.

    `impact` : instant (s) de l'impact du générique ; la musique démarre sur ce temps fort,
    précédée d'une montée. `energique` : percussions dès la première mesure (shorts).
    """
    rng = np.random.default_rng(graine)
    n = int(duree * FREQ)
    temps_ = 60 / tempo
    mesure = 4 * temps_
    pistes = {k: np.zeros((n, 2)) for k in ("piano", "nappe", "basse", "arpege", "batterie", "effets")}
    debut = impact if impact is not None else 0.0
    fin_motif = duree - 2.6                      # place pour l'accord final
    kicks: list[float] = []

    k = 0
    while debut + (k + 1) * mesure <= fin_motif or k == 0:
        t0 = debut + k * mesure
        accord = accord_de_la_mesure(k)
        # nappe (toute la mesure)
        for note in accord["notes"]:
            _ajouter(pistes["nappe"], t0, nappe_note(note, mesure), 0.16, pan=0.35 + 0.1 * (note % 3))
        # piano électrique : temps 1, et-du-2, et-du-4 (léger décalage rythmique)
        for decalage, force in ((0, 1.0), (1.5, 0.55), (3.5, 0.45)):
            for j, note in enumerate(accord["notes"]):
                humain = rng.uniform(-0.006, 0.006) + j * 0.008          # accord légèrement égrené
                _ajouter(pistes["piano"], t0 + decalage * temps_ + humain,
                         piano(note + 12, temps_ * 1.2, force * rng.uniform(0.9, 1.0)),
                         0.085, pan=0.3 + 0.4 * j / 3)
        # basse
        for decalage, longueur in ((0, 1.5), (1.5, 0.5), (2.0, 1.0), (3.5, 0.5)):
            note = accord["basse"] + (12 if decalage == 3.5 else 0)
            _ajouter(pistes["basse"], t0 + decalage * temps_, basse(note + 12, longueur * temps_ * 0.95), 0.24)
        # arpèges (à partir de la 3e mesure, ou de la 2e pour les shorts)
        if k >= (1 if energique else 2):
            ordre = [0, 2, 1, 3, 2, 1, 3, 2]
            for c in range(8):
                note = accord["notes"][ordre[c]] + 24
                _ajouter(pistes["arpege"], t0 + c * temps_ / 2, pince(note), 0.04 * (1 if c % 2 == 0 else 0.7),
                         pan=0.2 if c % 2 == 0 else 0.8)
        # batterie (à partir de la 2e mesure, ou tout de suite pour les shorts)
        if k >= (0 if energique else 1):
            for b in (0, 2):
                _ajouter(pistes["batterie"], t0 + b * temps_, grosse_caisse(), 0.55)
                kicks.append(t0 + b * temps_)
            if k % 2 == 1:
                _ajouter(pistes["batterie"], t0 + 2.5 * temps_, grosse_caisse(), 0.3)
                kicks.append(t0 + 2.5 * temps_)
            if k >= (1 if energique else 2):
                for b in (1, 3):
                    _ajouter(pistes["batterie"], t0 + b * temps_, caisse_claire(rng), 0.16, pan=0.45)
            for c in range(8):
                swing = 0.055 * temps_ if c % 2 else 0.0
                ouvert = c == 7 and k % 4 == 3
                _ajouter(pistes["batterie"], t0 + c * temps_ / 2 + swing, charleston(rng, ouvert),
                         0.05 if c % 2 else 0.03, pan=0.62)
        k += 1

    # Accord final résolu, laissé résonner
    t_fin = debut + k * mesure
    reste = max(1.5, duree - t_fin)
    for j, note in enumerate(TONIQUE["notes"]):
        _ajouter(pistes["piano"], t_fin + j * 0.03, piano(note + 12, reste * 0.6, 0.9), 0.085, pan=0.3 + 0.1 * j)
        _ajouter(pistes["nappe"], t_fin, nappe_note(note, reste * 0.7), 0.13, pan=0.4 + 0.05 * j)
    _ajouter(pistes["basse"], t_fin, basse(TONIQUE["basse"] + 12, reste * 0.8), 0.22)
    _ajouter(pistes["batterie"], t_fin, grosse_caisse(), 0.5)
    _ajouter(pistes["effets"], t_fin, cymbale(rng, min(3.0, reste)), 0.06, pan=0.55)

    # Générique : montée puis impact
    if impact is not None:
        _sting(pistes["effets"], impact, rng)
        kicks.append(impact)

    # Traitements : filtrage, respiration de la nappe et du piano sur la grosse caisse, réverbération
    pistes["nappe"] = _filtre(_filtre(pistes["nappe"], 2300, ordre=4), 160, "highpass")
    pistes["basse"] = _filtre(pistes["basse"], 520, ordre=4)
    if kicks:
        pompe = np.ones(n)
        tt = np.arange(int(0.3 * FREQ)) / FREQ
        creux = 1 - 0.32 * np.exp(-tt / 0.11)
        for tk in kicks:
            i = int(tk * FREQ)
            if 0 <= i < n:
                m = min(len(creux), n - i)
                pompe[i:i + m] = np.minimum(pompe[i:i + m], creux[:m])
        pistes["nappe"] *= pompe[:, None]
        pistes["piano"] *= (0.5 + 0.5 * pompe)[:, None]
    ri = reponse_impulsionnelle(rng)
    envoi = (pistes["piano"] * 0.35 + pistes["nappe"] * 0.25 + pistes["arpege"] * 0.45
             + pistes["batterie"] * 0.08 + pistes["effets"] * 0.4)
    reverb = np.stack([fftconvolve(envoi[:, c], ri[:, c])[:n] for c in range(2)], axis=1)
    mix = _filtre(sum(pistes.values()) + reverb * 0.9, 32, "highpass")

    if impact is None:
        mix *= np.minimum(1, np.arange(n) / (0.4 * FREQ))[:, None]
    mix *= np.clip((n - np.arange(n)) / (0.25 * FREQ), 0, 1)[:, None]
    mix = np.tanh(mix * 1.15)                                # saturation douce
    mix *= 0.89 / max(1e-6, np.abs(mix).max())
    return _ecrire(chemin, mix)


def _sting(piste: np.ndarray, impact: float, rng) -> None:
    """Montée (bruit qui s'éclaircit + ton qui grimpe) puis impact grave et brillant."""
    # montée sur 1 seconde, faite de bandes de bruit de plus en plus aiguës
    longueur = min(impact, 1.05)
    t = np.arange(int(longueur * FREQ)) / FREQ
    x = t / longueur
    bruit = rng.normal(0, 1, len(t))
    montee = np.zeros(len(t))
    for j, (bas, haut) in enumerate(((250, 700), (600, 1600), (1400, 3500), (3000, 8000), (6000, 14000))):
        poids = np.exp(-((x - (0.15 + 0.2 * j)) / 0.22) ** 2)
        montee += _filtre(bruit, (bas, haut), "bandpass") * poids
    montee *= x ** 1.6
    glisse = np.sin(2 * np.pi * np.cumsum(hz(62) * 2 ** (x * 1.0)) / FREQ) * x ** 2 * 0.25
    _ajouter(piste, impact - longueur, montee * 0.22 + glisse * 0.5, 1.0)
    # impact : grondement, accord brillant, cymbale
    t = np.arange(int(2.6 * FREQ)) / FREQ
    grondement = np.sin(2 * np.pi * np.cumsum(38 + 30 * np.exp(-t / 0.08)) / FREQ) * np.exp(-t / 0.9)
    _ajouter(piste, impact, grondement, 0.75)
    for j, note in enumerate([50, 57, 62, 66, 69, 76]):
        _ajouter(piste, impact + j * 0.004, piano(note, 1.6, 1.0), 0.09, pan=0.2 + 0.12 * j)
    _ajouter(piste, impact, cymbale(rng, 2.6), 0.11, pan=0.5)


def nappe(duree: float, chemin: Path, graine: int = 1, tempo: float = 92.0) -> Path:
    """Compatibilité : ancienne fonction, désormais la musique complète sans générique."""
    return musique(duree, chemin, graine=graine, tempo=tempo)


def souffles(instants: list[float], duree: float, chemin: Path, graine: int = 2,
             impact: float | None = None) -> Path:
    """Piste d'effets : un « whoosh » discret à chaque changement de scène.

    `impact` ajoute la montée et l'impact du générique (utile avec une musique personnelle).
    """
    rng = np.random.default_rng(graine)
    n = int(duree * FREQ)
    piste = np.zeros((n, 2))
    if impact is not None:
        sting = np.zeros((n, 2))
        _sting(sting, impact, rng)
        ri = reponse_impulsionnelle(rng)
        sting += np.stack([fftconvolve(sting[:, c], ri[:, c])[:n] for c in range(2)], axis=1) * 0.4
    longueur = int(0.75 * FREQ)
    tt = np.arange(longueur) / FREQ
    for k, instant in enumerate(instants):
        bruit = rng.normal(0, 1, longueur)
        ouverture = np.sin(np.pi * np.clip(tt / 0.75, 0, 1)) ** 2
        son = (_filtre(bruit, 500) * (1 - ouverture) + _filtre(bruit, 2200) * ouverture) * ouverture
        pan = tt / 0.75 if k % 2 == 0 else 1 - tt / 0.75
        debut = int((instant - 0.45) * FREQ)
        if debut < 0 or debut + longueur > n:
            continue
        piste[debut:debut + longueur, 0] += son * (1 - pan)
        piste[debut:debut + longueur, 1] += son * pan
    crete = np.abs(piste).max()
    if crete > 0:
        piste *= 0.5 / crete
    if impact is not None:
        piste += sting * (0.8 / max(1e-6, np.abs(sting).max()))
    return _ecrire(chemin, piste)
