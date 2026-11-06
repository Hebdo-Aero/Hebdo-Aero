"""Quiz de la semaine, en deux niveaux : « Curieux » et « Passionné ».

Une partie compte 8 questions, de deux sources :
- l'actualité de la semaine : questions rédigées par Claude chaque dimanche à partir du numéro validé,
  puis vérifiées ici (une seule bonne réponse, chiffres présents dans le sujet, pas de sujet dramatique) ;
  elles sont enregistrées dans data/quiz/<date>.json ;
- la culture aéronautique : la banque CULTURE ci-dessous, faite de faits historiques et techniques stables,
  vérifiés à la main. Le navigateur y pioche au hasard, si bien que chaque partie est différente.

Si la rédaction du quiz échoue, la page reste jouable avec les seules questions de culture.

Usage : python -m revue.generer quiz [--date AAAA-MM-JJ] [--force]
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from . import claude
from .config import RACINE, periode_fr

DOSSIER = RACINE / "data" / "quiz"
NIVEAUX = {"curieux": "Curieux", "passionne": "Passionné"}
PAR_NIVEAU = 6            # questions d'actualité demandées par niveau (la page en tire 5 au plus)
SENSIBLE = re.compile(r"attaqu|attentat|meurtr|\bmorts?\b|tué|crash|accident|bless|victime|otage|disparu", re.I)


def _q(niveau: str, question: str, options: list[str], explication: str, bonne: int = 0) -> dict:
    return {"niveau": niveau, "question": question, "options": options, "bonne": bonne, "explication": explication}


# Culture aéronautique : uniquement des faits établis qui ne changent pas d'une semaine à l'autre
# (histoire, unités, sigles, règles). Pas de classement ni de chiffre d'actualité, qui vieillissent mal.
CULTURE = [
    # --- Curieux --------------------------------------------------------------------------------
    _q("curieux", "Quel avion de ligne est surnommé le « Jumbo Jet » ?",
       ["Le Boeing 747", "L'Airbus A380", "Le Boeing 777", "Le Concorde"],
       "Entré en service en 1970, le 747 a été le premier gros-porteur ; sa bosse caractéristique abrite le "
       "poste de pilotage."),
    _q("curieux", "Qui est généralement crédité du premier vol motorisé et contrôlé, en 1903 ?",
       ["Les frères Wright", "Louis Blériot", "Clément Ader", "Alberto Santos-Dumont"],
       "Le 17 décembre 1903, à Kitty Hawk, en Caroline du Nord, Orville Wright vole une douzaine de secondes "
       "à bord du Flyer."),
    _q("curieux", "Qui a traversé la Manche en avion pour la première fois, en 1909 ?",
       ["Louis Blériot", "Roland Garros", "Charles Lindbergh", "Henri Farman"],
       "Le 25 juillet 1909, Louis Blériot relie les environs de Calais à Douvres en un peu plus d'une "
       "demi-heure, sur son Blériot XI."),
    _q("curieux", "De quelle couleur sont les « boîtes noires » des avions ?",
       ["Orange", "Noires", "Rouges", "Jaunes"],
       "Les enregistreurs de vol sont peints en orange vif, avec des bandes réfléchissantes, pour être "
       "repérés facilement."),
    _q("curieux", "Combien de réacteurs possède l'Airbus A380 ?",
       ["Quatre", "Deux", "Trois", "Six"],
       "Le plus gros avion de ligne de passagers jamais construit en série vole avec quatre réacteurs, des "
       "Rolls-Royce Trent 900 ou des Engine Alliance GP7200."),
    _q("curieux", "À quelle vitesse de croisière volait le Concorde ?",
       ["Environ Mach 2, deux fois la vitesse du son", "Environ Mach 0,85", "Environ Mach 1,2", "Environ Mach 5"],
       "Le Concorde croisait vers Mach 2, jusqu'à 18 000 m d'altitude, et traversait l'Atlantique en "
       "3 h 30 environ, deux fois plus vite qu'un avion de ligne classique."),
    _q("curieux", "Quel est le surnom du Boeing 787 ?",
       ["Dreamliner", "Stratoliner", "Jumbo", "Triple Seven"],
       "Entré en service en 2011 chez All Nippon Airways, le 787 Dreamliner a été le premier avion de ligne "
       "au fuselage en matériaux composites."),
    _q("curieux", "Que mesure le « nœud » en aviation ?",
       ["La vitesse", "L'altitude", "La distance", "La consommation de carburant"],
       "Un nœud vaut un mille marin par heure, soit 1,852 km/h. Un avion de ligne croise vers 450 à "
       "500 nœuds."),
    _q("curieux", "À quelle altitude vole en général un avion de ligne en croisière ?",
       ["Environ 10 à 12 km", "Environ 2 à 3 km", "Environ 25 km", "Environ 50 km"],
       "Les avions de ligne croisent le plus souvent entre 31 000 et 41 000 pieds, soit 9,5 à 12,5 km, où "
       "l'air peu dense permet de consommer moins."),
    _q("curieux", "Dans l'alphabet radio des pilotes, comment épelle-t-on la lettre F ?",
       ["Foxtrot", "Fox", "Frank", "Falcon"],
       "L'alphabet radio international (Alpha, Bravo, Charlie…) évite les confusions entre lettres qui se "
       "ressemblent à l'oral."),
    _q("curieux", "Que signifie « Mayday » à la radio ?",
       ["Un appel de détresse", "Une demande d'atterrissage", "Un message de bienvenue", "La fin du vol"],
       "Répété trois fois, « Mayday » signale une détresse. Le mot viendrait du français « (venez) m'aider »."),
    _q("curieux", "Combien de pilotes faut-il au minimum dans le poste de pilotage d'un Airbus A320 ?",
       ["Deux", "Un", "Trois", "Quatre"],
       "L'A320 est certifié pour un équipage de deux pilotes : un commandant de bord et un copilote."),
    _q("curieux", "Quelle alliance de compagnies regroupe notamment Air France et KLM ?",
       ["SkyTeam", "Star Alliance", "Oneworld", "Alliance Atlantique"],
       "Air France a cofondé SkyTeam en 2000 avec Delta, Aeroméxico et Korean Air ; KLM l'a rejointe en 2004."),
    _q("curieux", "Quel aéroport est désigné par le code « CDG » ?",
       ["Paris-Charles-de-Gaulle", "Copenhague", "Cologne-Bonn", "Chicago-O'Hare"],
       "Ces codes de trois lettres attribués par l'IATA identifient les aéroports sur les billets et les "
       "étiquettes de bagages."),
    _q("curieux", "Dans quelle ville l'Airbus A350 est-il assemblé ?",
       ["Toulouse", "Hambourg", "Seattle", "Séville"],
       "Comme l'A330, l'A350 sort des chaînes d'assemblage de Toulouse ; Hambourg assemble surtout des "
       "avions de la famille A320."),
    _q("curieux", "À quoi servent les volets qui sortent à l'arrière des ailes avant l'atterrissage ?",
       ["À voler lentement en gardant de la portance", "À freiner une fois au sol", "À tourner à gauche ou à droite",
        "À refroidir les moteurs"],
       "En augmentant la surface et la courbure de l'aile, les volets permettent de voler plus lentement au "
       "décollage et à l'atterrissage."),
    _q("curieux", "Que désigne le « roulage » d'un avion ?",
       ["Son déplacement au sol par ses propres moyens", "Sa rotation au décollage", "Un virage serré en vol",
        "Le chargement des bagages"],
       "Entre la porte d'embarquement et la piste, l'avion roule sur les voies de circulation (les taxiways), "
       "sur instruction du contrôle."),
    # --- Passionné ------------------------------------------------------------------------------
    _q("passionne", "Le Concorde et le Boeing 747 ont fait leur premier vol la même année. Laquelle ?",
       ["1969", "1965", "1972", "1976"],
       "Le 747 a décollé le 9 février 1969 à Everett, le Concorde 001 le 2 mars 1969 à Toulouse."),
    _q("passionne", "Quelle compagnie est la plus ancienne encore en activité sous son nom d'origine ?",
       ["KLM", "Lufthansa", "Qantas", "Air France"],
       "Fondée le 7 octobre 1919, KLM vole toujours sous le même nom. Qantas date de 1920, Air France "
       "de 1933."),
    _q("passionne", "Que signifie le sigle ATR, le constructeur franco-italien de turbopropulseurs ?",
       ["Avions de transport régional", "Aéronautique et transport réunis", "Air Transport Research",
        "Avions Toulouse-Rome"],
       "ATR, coentreprise d'Airbus et de l'italien Leonardo installée à Toulouse, produit les ATR 42 et "
       "ATR 72."),
    _q("passionne", "Où siège l'OACI, l'Organisation de l'aviation civile internationale ?",
       ["Montréal", "Genève", "Paris", "New York"],
       "Agence des Nations unies née de la convention de Chicago de 1944, l'OACI a son siège à Montréal."),
    _q("passionne", "Quel est le code OACI de l'aéroport de Paris-Charles-de-Gaulle ?",
       ["LFPG", "CDGP", "LFPO", "PCDG"],
       "Les pilotes et les contrôleurs utilisent ces codes de quatre lettres ; LFPO désigne Paris-Orly."),
    _q("passionne", "Que signale un équipage qui affiche le code transpondeur 7700 ?",
       ["Une urgence à bord", "Une panne de radio", "Un vol militaire", "Une attente avant l'atterrissage"],
       "Le code 7700 signale une urgence et le 7600 une panne de radio ; ils alertent immédiatement les "
       "contrôleurs."),
    _q("passionne", "Que permettent les règles ETOPS ?",
       ["À un biréacteur de voler loin de tout aéroport de dégagement", "De voler sans copilote",
        "De décoller avec un moteur en panne", "De dépasser la vitesse du son au-dessus de la mer"],
       "Elles fixent à combien de minutes de vol d'un aéroport de dégagement un biréacteur peut s'éloigner, "
       "ce qui a ouvert les océans aux bimoteurs."),
    _q("passionne", "Quel a été le premier avion de ligne à réaction en service commercial ?",
       ["Le de Havilland Comet", "Le Boeing 707", "La Caravelle", "Le Tupolev Tu-104"],
       "Le Comet de la BOAC a assuré le premier vol commercial à réaction le 2 mai 1952, entre Londres et "
       "Johannesburg."),
    _q("passionne", "Sous quel nom l'Airbus A220 a-t-il été lancé ?",
       ["CSeries, chez Bombardier", "E2, chez Embraer", "Fokker 100", "Superjet, chez Sukhoi"],
       "Conçu par Bombardier sous le nom de CSeries, l'avion a été rebaptisé A220 en 2018 quand Airbus a "
       "pris le contrôle du programme."),
    _q("passionne", "En quelle année l'Airbus A300, le premier avion d'Airbus, a-t-il fait son premier vol ?",
       ["1972", "1965", "1979", "1985"],
       "Premier biréacteur gros-porteur au monde, l'A300 a décollé de Toulouse le 28 octobre 1972."),
    _q("passionne", "Combien mesure un mille marin, l'unité de distance de l'aviation ?",
       ["1 852 m", "1 609 m", "1 000 m", "2 000 m"],
       "Le mille marin correspond à une minute d'arc de latitude ; le mille terrestre anglo-saxon, lui, "
       "mesure 1 609 m."),
    _q("passionne", "À quoi sert l'APU d'un avion de ligne ?",
       ["À fournir électricité et air quand les moteurs sont arrêtés", "À reculer sans tracteur",
        "À dégivrer la piste", "À mesurer la vitesse"],
       "Ce petit groupe turbine, souvent logé dans la queue, alimente l'avion au sol et fournit l'air qui "
       "sert à démarrer les moteurs."),
    _q("passionne", "À quel rythme se tient le salon aéronautique du Bourget ?",
       ["Tous les deux ans, les années impaires", "Tous les ans", "Tous les deux ans, les années paires",
        "Tous les quatre ans"],
       "Il alterne avec le salon britannique de Farnborough, organisé les années paires."),
    _q("passionne", "Quelle alliance Lufthansa a-t-elle cofondée en 1997 ?",
       ["Star Alliance", "SkyTeam", "Oneworld", "Qualiflyer"],
       "Star Alliance est née le 14 mai 1997, fondée par Lufthansa, United, Air Canada, SAS et Thai Airways."),
    _q("passionne", "Qu'annonce un contrôleur qui autorise un avion au « niveau 350 » (FL350) ?",
       ["Une altitude d'environ 35 000 pieds", "Une vitesse de 350 nœuds", "Le vol numéro 350",
        "Une piste de 3 500 m"],
       "Les niveaux de vol s'expriment en centaines de pieds : FL350 correspond à 35 000 pieds, environ "
       "10 700 m."),
    _q("passionne", "Que signifie « neo » dans le nom de l'Airbus A320neo ?",
       ["New Engine Option", "Next Economy Operation", "New European Order", "Nouvelle ère opérationnelle"],
       "L'A320neo reprend la cellule de l'A320 avec des moteurs plus sobres, CFM LEAP-1A ou Pratt & Whitney "
       "GTF."),
    _q("passionne", "Quel avion de ligne est certifié pour le plus grand nombre de passagers ?",
       ["L'Airbus A380", "Le Boeing 747-8", "Le Boeing 777-9", "L'Airbus A350-1000"],
       "L'A380 est certifié pour 853 passagers, même si les compagnies l'aménagent en général avec 450 à "
       "600 sièges."),
]


# --- Rédaction du quiz d'actualité par Claude ------------------------------------------------------

SYSTEME = """Tu rédiges le quiz hebdomadaire de « {nom} », une revue en français sur l'aviation commerciale, \
à partir du numéro de la semaine qui t'est fourni.

Règles absolues :
1. Chaque question porte sur un seul sujet du numéro, désigné par son identifiant (« une-1 », « breve-3 »…).
2. La bonne réponse figure explicitement dans le titre ou le résumé de ce sujet. Aucun fait, chiffre ou nom \
ne doit venir de ta mémoire.
3. Quatre propositions courtes, plausibles et du même type (quatre villes, quatre chiffres…), une seule juste. \
Pas de « toutes ces réponses », pas de piège sur l'orthographe.
4. Aucune question sur un accident, un attentat, des morts ou des blessés.
5. Niveau « curieux » : l'idée principale d'un sujet (qui, quoi, où), compréhensible par quelqu'un qui \
découvre l'aviation. Niveau « passionne » : un détail précis (chiffre, modèle d'avion, date, lieu).
6. Varie les sujets : pas plus de deux questions sur le même sujet.
7. L'explication tient en une phrase et rappelle le fait, sans recopier le résumé.

Appelle l'outil publier_quiz une seule fois."""

CONSIGNE = """Numéro {numero}, semaine du {periode}. Rédige {par_niveau} questions de niveau « curieux » et \
{par_niveau} questions de niveau « passionne ».

Sujets du numéro :
{sujets}"""

OUTIL = {
    "name": "publier_quiz",
    "description": "Transmet les questions du quiz de la semaine.",
    "input_schema": {
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "niveau": {"type": "string", "enum": list(NIVEAUX)},
                        "sujet": {"type": "string", "description": "Identifiant du sujet : « une-1 », « breve-2 »…"},
                        "question": {"type": "string", "description": "Une question, 160 caractères au plus."},
                        "options": {"type": "array", "items": {"type": "string"}, "minItems": 4, "maxItems": 4,
                                    "description": "Quatre propositions de 70 caractères au plus."},
                        "bonne": {"type": "integer", "minimum": 0, "maximum": 3,
                                  "description": "Indice de la bonne proposition (0 à 3)."},
                        "explication": {"type": "string", "description": "Une phrase, 240 caractères au plus."},
                    },
                    "required": ["niveau", "sujet", "question", "options", "bonne", "explication"],
                },
            },
        },
        "required": ["questions"],
    },
}


def sujets(numero: dict) -> dict[str, dict]:
    """Les sujets du numéro par identifiant (le même que l'ancre de la page du numéro)."""
    tous = {f"une-{i}": s for i, s in enumerate(numero.get("une", []), start=1)}
    tous.update({f"breve-{i}": s for i, s in enumerate(numero.get("breves", []), start=1)})
    return tous


def _normaliser(texte: str) -> str:
    texte = texte.replace(" ", " ").replace("\xa0", " ")
    return re.sub(r"(?<=\d) (?=\d{3}\b)", "", texte)        # « 4 800 » -> « 4800 »


def _nombres(texte: str) -> set[str]:
    return {n.replace(".", ",") for n in re.findall(r"\d+(?:[.,]\d+)?", _normaliser(texte))}


def _sensible(sujet: dict) -> bool:
    return sujet.get("categorie") == "Sécurité & sûreté" or bool(
        SENSIBLE.search(sujet.get("titre", "") + " " + sujet.get("resume", "")))


def valider(brut: dict | list, numero: dict) -> list[dict]:
    """Ne garde que les questions sûres ; renvoie au plus PAR_NIVEAU questions par niveau."""
    questions = brut.get("questions", []) if isinstance(brut, dict) else brut
    connus = sujets(numero)
    gardees: list[dict] = []
    vues: set[str] = set()
    rejets: list[str] = []
    for q in questions or []:
        if not isinstance(q, dict):
            continue
        texte = re.sub(r"\s+", " ", str(q.get("question", ""))).strip()
        options = [re.sub(r"\s+", " ", str(o)).strip() for o in (q.get("options") or [])]
        bonne, niveau, sujet = q.get("bonne"), q.get("niveau"), connus.get(str(q.get("sujet", "")))
        explication = re.sub(r"\s+", " ", str(q.get("explication", ""))).strip()
        if niveau not in NIVEAUX or not sujet or not (10 <= len(texte) <= 200) or not texte.endswith("?"):
            rejets.append(f"question mal formée : {texte[:60]}")
            continue
        if len(options) != 4 or any(not o or len(o) > 90 for o in options) \
                or len({o.lower() for o in options}) < 4 or not isinstance(bonne, int) or not 0 <= bonne <= 3:
            rejets.append(f"propositions invalides : {texte[:60]}")
            continue
        if not (10 <= len(explication) <= 320):
            rejets.append(f"explication manquante : {texte[:60]}")
            continue
        if _sensible(sujet):
            rejets.append(f"sujet dramatique écarté : {texte[:60]}")
            continue
        # Un chiffre de la bonne réponse doit figurer dans le sujet : sinon il viendrait de la mémoire de l'IA.
        source = sujet.get("titre", "") + " " + sujet.get("resume", "")
        if not _nombres(options[bonne]) <= _nombres(source):
            rejets.append(f"chiffre introuvable dans le sujet : {texte[:60]}")
            continue
        cle = texte.lower()
        if cle in vues:
            continue
        vues.add(cle)
        gardees.append({"niveau": niveau, "sujet": str(q["sujet"]), "question": texte, "options": options,
                        "bonne": bonne, "explication": explication})
    for r in rejets:
        claude.log(f"  quiz : écarté, {r}")
    resultat = []
    for niveau in NIVEAUX:
        resultat += [q for q in gardees if q["niveau"] == niveau][:PAR_NIVEAU]
    return resultat


def rediger(config: dict, numero: dict, appelant=claude.appeler) -> dict:
    """Rédige et vérifie le quiz d'actualité du numéro."""
    r = config["redaction"]
    liste = [{"id": cle, "titre": s["titre"], "resume": s["resume"], "categorie": s["categorie"]}
             for cle, s in sujets(numero).items() if not _sensible(s)]
    brut, _, conso = claude.executer_avec_outil(
        modele=r["modele"], systeme=SYSTEME.format(nom=config["site"]["nom"]),
        consigne=CONSIGNE.format(numero=numero["numero"], periode=periode_fr(numero["debut"], numero["fin"]),
                                 par_niveau=PAR_NIVEAU, sujets=json.dumps(liste, ensure_ascii=False, indent=1)),
        outil_final=OUTIL, max_tokens=6000, tours_max=3, appelant=appelant)
    claude.log("Quiz : " + claude.resume_conso(r["modele"], conso))
    return {"numero": numero["numero"], "date": numero["date"], "questions": valider(brut, numero),
            "genere_par": r["modele"], "genere_le": datetime.now(timezone.utc).isoformat(timespec="seconds")}


# --- Données de la page -------------------------------------------------------------------------

def donnees_page(numero: dict | None, quiz: dict | None, lien_numero: str) -> dict:
    """Ce que la page /quiz/ embarque : questions d'actualité (avec un lien vers le sujet) et banque de culture."""
    actu = []
    if numero and quiz:
        connus = sujets(numero)
        for q in quiz.get("questions", []):
            s = connus.get(q["sujet"])
            if s:
                actu.append({**q, "lien": f"{lien_numero}#{q['sujet']}", "titre_sujet": s["titre"]})
    return {
        "numero": numero["numero"] if numero else None,
        "periode": periode_fr(numero["debut"], numero["fin"]) if numero else "",
        "lien_numero": lien_numero,
        "niveaux": NIVEAUX,
        "actu": actu,
        "culture": CULTURE,
    }
