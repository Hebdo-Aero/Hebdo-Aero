"""Appels à l'API Claude (Messages API), sans dépendance externe.

`executer_avec_outil` laisse Claude faire ses recherches web (outil serveur), puis
récupère le résultat structuré qu'il transmet en appelant un outil « final ».
"""
from __future__ import annotations

import os
import sys

from .http import post_json

URL_API = "https://api.anthropic.com/v1/messages"
OUTIL_RECHERCHE = "web_search_20250305"

# Tarifs indicatifs (USD par million de jetons) pour estimer le coût dans les journaux.
TARIFS = {
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-opus-5-5": (4.0, 20.0),
}


class ErreurClaude(RuntimeError):
    pass


def appeler(charge: dict, cle: str | None = None) -> dict:
    cle = cle or os.environ.get("ANTHROPIC_API_KEY")
    if not cle:
        raise ErreurClaude("ANTHROPIC_API_KEY manquante (secret GitHub à créer).")
    return post_json(URL_API, charge, entetes={
        "x-api-key": cle,
        "anthropic-version": "2023-06-01",
    }, delai=600, essais=4)


def executer_avec_outil(*, modele: str, systeme: str, consigne: str, outil_final: dict,
                        recherches_max: int = 0, max_tokens: int = 16000, tours_max: int = 8,
                        appelant=appeler) -> tuple[dict, set[str], dict]:
    """Renvoie (entrée de l'outil final, URLs vues dans les recherches, consommation)."""
    outils = []
    if recherches_max > 0:
        outils.append({"type": OUTIL_RECHERCHE, "name": "web_search", "max_uses": recherches_max})
    outils.append(outil_final)

    messages: list[dict] = [{"role": "user", "content": consigne}]
    urls_recherche: set[str] = set()
    conso = {"entree": 0, "sortie": 0, "recherches": 0}
    relances = 0

    for _ in range(tours_max):
        rep = appelant({
            "model": modele,
            "max_tokens": max_tokens,
            "system": systeme,
            "messages": messages,
            "tools": outils,
        })
        usage = rep.get("usage", {})
        conso["entree"] += usage.get("input_tokens", 0) + usage.get("cache_read_input_tokens", 0) \
            + usage.get("cache_creation_input_tokens", 0)
        conso["sortie"] += usage.get("output_tokens", 0)
        conso["recherches"] += (usage.get("server_tool_use") or {}).get("web_search_requests", 0)

        contenu = rep.get("content", [])
        for bloc in contenu:
            if bloc.get("type") == "web_search_tool_result" and isinstance(bloc.get("content"), list):
                for r in bloc["content"]:
                    if r.get("url"):
                        urls_recherche.add(r["url"])
        for bloc in contenu:
            if bloc.get("type") == "tool_use" and bloc.get("name") == outil_final["name"]:
                return bloc.get("input") or {}, urls_recherche, conso

        raison = rep.get("stop_reason")
        messages.append({"role": "assistant", "content": contenu})
        if raison == "pause_turn":
            continue
        if raison in ("end_turn", "max_tokens", "stop_sequence", "refusal", "tool_use"):
            relances += 1
            if relances > 2 or raison == "refusal":
                break
            messages.append({"role": "user", "content":
                             f"Appelle maintenant l'outil {outil_final['name']} avec le résultat complet, "
                             "sans autre texte."})
            continue
        break
    raise ErreurClaude(f"Claude n'a pas appelé l'outil {outil_final['name']}.")


def resume_conso(modele: str, conso: dict) -> str:
    prix_e, prix_s = TARIFS.get(modele, (2.0, 10.0))
    cout = conso["entree"] / 1e6 * prix_e + conso["sortie"] / 1e6 * prix_s + conso["recherches"] * 0.01
    def nombre(n: int) -> str:
        return f"{n:,}".replace(",", " ")
    return (f"{nombre(conso['entree'])} jetons en entrée, {nombre(conso['sortie'])} en sortie, "
            f"{conso['recherches']} recherche(s) web, environ {cout:.2f} $")


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)
