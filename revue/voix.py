"""Narration par Google Cloud Text-to-Speech (une piste WAV par scène)."""
from __future__ import annotations

import base64
import json
import os
import wave
from pathlib import Path

from .http import post_json

URL_TTS = "https://texttospeech.googleapis.com/v1/text:synthesize"


class ErreurVoix(RuntimeError):
    pass


def _authentification() -> tuple[str, dict]:
    """Clé d'API (GOOGLE_TTS_API_KEY) ou compte de service (GOOGLE_TTS_CREDENTIALS, JSON)."""
    cle = os.environ.get("GOOGLE_TTS_API_KEY")
    if cle:
        return URL_TTS, {"x-goog-api-key": cle}
    compte = os.environ.get("GOOGLE_TTS_CREDENTIALS")
    if compte:
        try:
            from google.auth.transport.requests import Request
            from google.oauth2 import service_account
        except ImportError as e:  # pragma: no cover
            raise ErreurVoix("Installez google-auth pour utiliser un compte de service.") from e
        infos = json.loads(compte)
        cred = service_account.Credentials.from_service_account_info(
            infos, scopes=["https://www.googleapis.com/auth/cloud-platform"])
        cred.refresh(Request())
        return URL_TTS, {"Authorization": f"Bearer {cred.token}",
                         "x-goog-user-project": infos.get("project_id", "")}
    raise ErreurVoix("Aucune clé Google Text-to-Speech (secret GOOGLE_TTS_API_KEY).")


def synthetiser(textes: list[str], dossier: Path, voix: str, vitesse: float = 1.0) -> list[Path]:
    url, entetes = _authentification()
    langue = "-".join(voix.split("-")[:2])
    dossier.mkdir(parents=True, exist_ok=True)
    pistes = []
    for i, texte in enumerate(textes):
        rep = post_json(url, {
            "input": {"text": texte},
            "voice": {"languageCode": langue, "name": voix},
            "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": 48000, "speakingRate": vitesse},
        }, entetes=entetes, delai=120)
        piste = dossier / f"scene-{i:02d}.wav"
        piste.write_bytes(base64.b64decode(rep["audioContent"]))
        pistes.append(piste)
    return pistes


def duree(piste: Path) -> float:
    with wave.open(str(piste)) as w:
        return w.getnframes() / w.getframerate()


def estimer_duree(texte: str, vitesse: float = 1.0) -> float:
    """Durée approximative d'une narration (aperçu sans voix) : ~2,7 mots par seconde."""
    return max(1.5, len(texte.split()) / (2.7 * vitesse))


def segments_parole(piste: Path, seuil_db: float = -38, pause_min: float = 0.13) -> list[tuple[float, float]]:
    """Intervalles où la voix parle, repérés grâce aux silences (ffmpeg silencedetect)."""
    import re
    import subprocess
    sortie = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(piste), "-af",
                             f"silencedetect=noise={seuil_db}dB:d={pause_min}", "-f", "null", "-"],
                            capture_output=True, text=True).stderr
    total = duree(piste)
    debuts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", sortie)]
    fins = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", sortie)]
    segments, curseur = [], 0.0
    for d, f in zip(debuts, fins + [total] * (len(debuts) - len(fins))):
        if d - curseur > 0.05:
            segments.append((curseur, d))
        curseur = f
    if total - curseur > 0.05:
        segments.append((curseur, total))
    return segments


# Voix françaises proposées à l'écoute (descriptions de Google).
VOIX_A_ECOUTER = {
    "Sulafat": "chaleureuse, féminine",
    "Achird": "amicale, masculine",
    "Algieba": "douce, masculine",
    "Charon": "informative, masculine",
    "Despina": "posée, féminine",
    "Aoede": "légère, féminine",
    "Iapetus": "claire, masculine",
    "Vindemiatrix": "douce, féminine",
    "Umbriel": "détendue, masculine",
    "Kore": "assurée, féminine",
}
PHRASE_TEST = ("Bonjour et bienvenue dans Hebdo Aéro. Cette semaine, Airbus a livré soixante-douze avions, "
               "et le loueur Avolon a commandé deux cent cinquante appareils.")


def echantillons(dossier: Path, vitesse: float = 1.0) -> list[dict]:
    """Une courte lecture par voix, en MP3, pour choisir à l'oreille (page /voix/ du site)."""
    import subprocess
    sortie = []
    for nom, description in VOIX_A_ECOUTER.items():
        voix_complete = f"fr-FR-Chirp3-HD-{nom}"
        try:
            wav = synthetiser([PHRASE_TEST], dossier / nom, voix_complete, vitesse)[0]
        except Exception as e:  # noqa: BLE001
            print(f"  voix {nom} indisponible : {e}")
            continue
        mp3 = dossier / f"{nom}.mp3"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-b:a", "96k", str(mp3)], check=True)
        sortie.append({"nom": nom, "voix": voix_complete, "description": description, "fichier": mp3.name})
    return sortie
