"""Tests de la chaîne complète, sans réseau (Claude et les réseaux sont simulés).

Lancer : python -m unittest discover -s tests -v
"""
import json
import os
import shutil
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from pathlib import Path
from unittest import mock

from revue import claude, flux, generer, redaction, reseaux, video
from revue.config import charger_config, lire_json, periode_fr, RACINE

# Les tests s'appuient sur le numéro 1, quel que soit le nombre de numéros publiés depuis dans data/.
_NUMEROS_TEST = None


def setUpModule():
    global _NUMEROS_TEST
    from revue import config as module_config
    _NUMEROS_TEST = Path(tempfile.mkdtemp())
    shutil.copy(RACINE / "data" / "numeros" / "2026-10-11.json", _NUMEROS_TEST)
    module_config._DOSSIER_NUMEROS_REEL = module_config.DOSSIER_NUMEROS
    module_config.DOSSIER_NUMEROS = _NUMEROS_TEST


def tearDownModule():
    from revue import config as module_config
    module_config.DOSSIER_NUMEROS = module_config._DOSSIER_NUMEROS_REEL
    shutil.rmtree(_NUMEROS_TEST, ignore_errors=True)


RSS = b"""<?xml version="1.0"?><rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel><title>Test</title>
<item><title>Airbus livre 72 avions</title><link>https://www.exemple.com/airbus-72/?utm_source=rss</link>
<pubDate>Fri, 09 Oct 2026 10:00:00 +0000</pubDate><description><![CDATA[<p>Airbus a livre 72 avions a 37 clients en septembre selon le constructeur europeen.</p>
The post <a href="x">Airbus</a> appeared first on <a href="y">Test</a>.]]></description></item>
<item><title>Vieille nouvelle</title><link>https://www.exemple.com/vieux</link>
<pubDate>Mon, 01 Sep 2026 10:00:00 +0000</pubDate><description>Ancien</description></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>A</title>
<entry><title>Delta revoit sa prevision</title><link rel="alternate" href="https://atom.exemple.org/delta"/>
<published>2026-10-09T14:00:00Z</published><summary>Delta abaisse sa prevision.</summary></entry></feed>"""


def article(url, titre="Titre", extrait="Un extrait d'article tout a fait ordinaire."):
    return flux.Article("Média", titre, url, datetime(2026, 10, 9, tzinfo=timezone.utc), extrait)


def sujet(url, titre="Un sujet", resume="Un résumé reformulé en français.", cat="Compagnies & réseaux"):
    return {"titre": titre, "resume": resume, "categorie": cat, "region": "Europe",
            "sources": [{"nom": "Média", "url": url}]}


class TestFlux(unittest.TestCase):
    def test_rss_et_atom(self):
        a = flux.analyser(RSS, "Test")
        self.assertEqual(len(a), 2)
        self.assertNotIn("appeared first", a[0].extrait)
        b = flux.analyser(ATOM, "Atom")
        self.assertEqual(b[0].url, "https://atom.exemple.org/delta")

    def test_collecte_filtre_la_semaine(self):
        with mock.patch.object(flux, "requete", return_value=(200, {}, RSS)):
            a = flux.collecter([{"nom": "T", "url": "u"}], date(2026, 10, 5), date(2026, 10, 11))
        self.assertEqual([x.titre for x in a], ["Airbus livre 72 avions"])

    def test_normalisation_url(self):
        self.assertEqual(flux.normaliser_url("http://www.Ex.com/a/?utm_source=x&id=3#h"),
                         flux.normaliser_url("https://ex.com/a?id=3"))


class TestClaude(unittest.TestCase):
    def test_boucle_avec_pause_et_recherche(self):
        reponses = [
            {"stop_reason": "pause_turn", "usage": {"input_tokens": 10, "output_tokens": 5,
                                                    "server_tool_use": {"web_search_requests": 1}},
             "content": [{"type": "web_search_tool_result", "tool_use_id": "s",
                          "content": [{"type": "web_search_result", "url": "https://trouve.com/x"}]}]},
            {"stop_reason": "tool_use", "usage": {"input_tokens": 10, "output_tokens": 5},
             "content": [{"type": "tool_use", "id": "t", "name": "fin", "input": {"ok": True}}]},
        ]
        envoyes = []

        def appelant(charge):
            envoyes.append(charge)
            return reponses[len(envoyes) - 1]

        sortie, urls, conso = claude.executer_avec_outil(
            modele="m", systeme="s", consigne="c", outil_final={"name": "fin", "input_schema": {}},
            recherches_max=3, appelant=appelant)
        self.assertEqual(sortie, {"ok": True})
        self.assertIn("https://trouve.com/x", urls)
        self.assertEqual(conso["recherches"], 1)
        self.assertEqual(envoyes[1]["messages"][1]["role"], "assistant")   # tour repris tel quel
        self.assertEqual(envoyes[0]["tools"][0]["type"], "web_search_20250305")

    def test_relance_si_pas_d_outil(self):
        reps = iter([{"stop_reason": "end_turn", "content": [{"type": "text", "text": "voilà"}]},
                     {"stop_reason": "tool_use", "content": [{"type": "tool_use", "name": "fin", "input": {"a": 1}}]}])
        sortie, _, _ = claude.executer_avec_outil(modele="m", systeme="s", consigne="c",
                                                  outil_final={"name": "fin"}, appelant=lambda c: next(reps))
        self.assertEqual(sortie, {"a": 1})


class TestRedaction(unittest.TestCase):
    def setUp(self):
        self.articles = [article(f"https://media.com/{i}") for i in range(10)]

    def brut(self, n_breves=6, une_urls=None):
        une = [sujet(u) for u in (une_urls or ["https://media.com/0", "https://media.com/1", "https://media.com/2"])]
        return {"titre": "T", "edito": "E", "une": une,
                "breves": [sujet(f"https://media.com/{3 + i}") for i in range(n_breves)],
                "chiffre": {"valeur": "72", "legende": "L", "source": {"nom": "M", "url": "https://media.com/0"}}}

    def test_source_inventee_ecartee_et_breve_promue(self):
        brut = self.brut(une_urls=["https://media.com/0", "https://invente.com/x", "https://media.com/2"])
        n = redaction.valider(brut, self.articles, set())
        self.assertEqual(len(n["une"]), 3)
        self.assertEqual(len(n["breves"]), 5)
        self.assertEqual(n["une"][2]["sources"][0]["url"], "https://media.com/3")

    def test_url_de_recherche_acceptee(self):
        brut = self.brut()
        brut["breves"].append(sujet("https://web.com/trouve"))
        n = redaction.valider(brut, self.articles, {"https://web.com/trouve/"})
        self.assertEqual(len(n["breves"]), 7)

    def test_recopie_detectee(self):
        texte = "le constructeur a livré soixante douze avions à trente sept clients au cours du mois"
        self.assertTrue(redaction.recopie(texte + " dernier", ["En bref : " + texte + "."]))
        self.assertFalse(redaction.recopie("Airbus a remis 72 appareils en septembre.", [texte]))

    def test_trop_peu_de_sujets(self):
        with self.assertRaises(redaction.NumeroInvalide):
            redaction.valider(self.brut(n_breves=0, une_urls=["https://x.com/1"] * 3), self.articles, set())

    def test_redaction_complete_simulee(self):
        config = charger_config()
        reponse = {"stop_reason": "tool_use", "content": [
            {"type": "tool_use", "name": "publier_numero", "input": self.brut()}]}
        n = redaction.rediger(config, self.articles, 7, date(2026, 10, 12), date(2026, 10, 18),
                              appelant=lambda c: reponse)
        self.assertEqual((n["numero"], n["date"], n["debut"]), (7, "2026-10-18", "2026-10-12"))
        self.assertIsNotNone(n["chiffre"])

    def test_titre_reecrit_quand_un_sujet_est_ecarte(self):
        config = charger_config()
        brut = self.brut(une_urls=["https://media.com/0", "https://invente.com/x", "https://media.com/2"])
        brut["titre"] = "Lufthansa rachète TAP"          # sujet retiré par le contrôle des sources
        appels = []

        def appelant(charge):
            appels.append(charge["tools"][-1]["name"])
            if charge["tools"][-1]["name"] == "titre_edito":
                return {"stop_reason": "tool_use", "content": [
                    {"type": "tool_use", "name": "titre_edito", "input": {"titre": "Nouveau titre", "edito": "Nouvel édito."}}]}
            return {"stop_reason": "tool_use", "content": [{"type": "tool_use", "name": "publier_numero", "input": brut}]}

        n = redaction.rediger(config, self.articles, 2, date(2026, 10, 12), date(2026, 10, 18), appelant=appelant)
        self.assertEqual(appels, ["publier_numero", "titre_edito"])
        self.assertEqual((n["titre"], n["edito"]), ("Nouveau titre", "Nouvel édito."))
        self.assertNotIn("_ecartes", n)

    def test_titre_de_secours(self):
        config = charger_config()
        brut = self.brut(une_urls=["https://media.com/0", "https://invente.com/x", "https://media.com/2"])
        reponse = {"stop_reason": "tool_use", "content": [{"type": "tool_use", "name": "publier_numero", "input": brut}]}
        n = redaction.rediger(config, self.articles, 2, date(2026, 10, 12), date(2026, 10, 18), appelant=lambda c: reponse)
        self.assertEqual(n["titre"], n["une"][0]["titre"])


class TestReseaux(unittest.TestCase):
    def setUp(self):
        self.config = charger_config()
        self.config["site"]["url"] = "https://moi.github.io/hebdo-aero/"
        self.numero = lire_json(RACINE / "data" / "numeros" / "2026-10-11.json")
        self.script = lire_json(RACINE / "data" / "reseaux" / "2026-10-11.json")

    def test_script_du_numero_1(self):
        types = [s["type"] for s in self.script["video"]["scenes"]]
        self.assertEqual(types[0], "intro")
        self.assertEqual(types[-2:], ["chiffre", "fin"])

    def test_liens_et_longueur_threads(self):
        t = reseaux.remplir_liens(self.script["legendes"]["threads"], self.config, 1)
        self.assertIn("https://moi.github.io/hebdo-aero/numeros/1/", t)
        self.assertLessEqual(len(t), 500)
        fin = reseaux.remplir_liens("{lien_court}", self.config, 1)
        self.assertEqual(fin, "moi.github.io/hebdo-aero")

    def test_sans_adresse_la_ligne_du_lien_disparait(self):
        self.config["site"]["url"] = ""
        t = reseaux.remplir_liens("Texte\n\nSources : {lien}\n\nFin", self.config, 1)
        self.assertNotIn("{lien}", t)
        self.assertIn("Fin", t)

    def test_shorts_d_accroche_assembles(self):
        accroches = self.script["accroches"]
        self.assertEqual(len(accroches), 3)
        for a in accroches:
            self.assertEqual([x["type"] for x in a["scenes"]], ["accroche", "sujet", "appel"])
            self.assertIn("Lien en bio", a["scenes"][-1]["narration"])
            self.assertIn("lien en bio", a["legende"])
            self.assertLessEqual(len(a["scenes"][0]["titre_ecran"]), 34)

    def test_garde_fou_de_duree(self):
        brut = {"scenes": [{"surtitre": "x", "titre_ecran": "t", "texte_ecran": "f",
                            "narration": "mot " * 60} for _ in range(5)],
                "chiffre_narration": "Le chiffre.", "youtube_titre": "Y", "instagram": "I",
                "facebook": "F", "threads": "T"}
        s = reseaux.assembler(self.config, self.numero, brut)
        self.assertEqual(sum(1 for x in s["video"]["scenes"] if x["type"] == "sujet"), 3)


class TestVideo(unittest.TestCase):
    def test_chronologie(self):
        temps = video.chronologie([2.0, 5.0, 3.0])
        self.assertAlmostEqual(temps[1]["debut"], temps[0]["fin"])
        self.assertAlmostEqual(temps[1]["voix"], temps[1]["debut"] + video.AVANT)

    def test_chronologie_avec_generique(self):
        temps = video.chronologie([3.0, 5.0], generique=True)
        self.assertAlmostEqual(temps[0]["voix"], video.VOIX_GENERIQUE)
        self.assertGreater(video.VOIX_GENERIQUE, video.IMPACT)              # la voix part après l'impact
        self.assertGreaterEqual(temps[0]["fin"], video.DUREE_GENERIQUE)

    def test_volume_musique_generique(self):
        reglage = video._reglage_musique({"volume_musique": 0.3}, 60, generee=False, generique=True)
        self.assertIn("adelay=1200|1200", reglage)                          # musique perso calée sur l'impact
        self.assertIn("clip(", reglage)
        self.assertEqual(video._reglage_musique({"volume_musique": 0.3}, 60, True, False), "volume=0.3")

    def test_chronologie_courte(self):
        temps = video.chronologie([2.0, 5.0, 3.0], court=True)
        self.assertLessEqual(temps[0]["voix"], 0.05)          # la voix part dès la première image
        self.assertLess(temps[-1]["fin"], 2 + 5 + 3 + 2.2)

    def test_mots_cales_sur_les_silences(self):
        # deux propositions et deux passages parlés repérés : chacune tombe dans le sien
        mots = video.minutage_mots("Airbus livre soixante-douze avions, Boeing attend.", 3.0,
                                   [(0.1, 1.6), (2.0, 2.9)])
        self.assertEqual(len(mots), 6)
        self.assertAlmostEqual(mots[0][0], 0.1)
        self.assertAlmostEqual(mots[3][1], 1.6)          # « avions, » finit avec le 1er passage
        self.assertAlmostEqual(mots[4][0], 2.0)          # « Boeing » commence avec le 2e
        self.assertAlmostEqual(mots[-1][1], 2.9)

    def test_mots_sans_correspondance_exacte(self):
        mots = video.minutage_mots("Un deux trois quatre.", 4.0, [(0, 1), (2, 3)])
        self.assertTrue(all(a < b for a, b, _ in mots))
        self.assertTrue(all(not (1 < a < 2) for a, _, _ in mots))   # aucun mot dans le silence

    def test_sous_titres_par_groupes(self):
        scenes = [{"narration": "Bonjour."}, {"narration": "Une phrase assez longue pour être coupée en deux "
                                                            "groupes, puis une autre phrase. Fin."}]
        durees = [1.0, 6.0]
        temps = video.chronologie(durees)
        minutages = [video.minutage_mots(s["narration"], d) for s, d in zip(scenes, durees)]
        groupes = video.sous_titres(scenes, temps, minutages)
        self.assertGreaterEqual(len(groupes), 4)
        for g in groupes:
            self.assertLessEqual(len(" ".join(m["m"] for m in g["mots"])), 40)
            self.assertLess(g["debut"], g["fin"])
        for a, b in zip(groupes, groupes[1:]):
            self.assertLessEqual(a["fin"], b["debut"] + 1e-6)

    def test_commande_ffmpeg_avec_plans(self):
        temps = video.chronologie([2.0, 3.0, 2.0])
        plans = [None, {"fichier": "/tmp/plan.mp4", "auteur": "A"}, None]
        cmd = video.commande_ffmpeg(9.0, 30, Path("/tmp/ciel.jpg"), plans, temps, None,
                                    Path("/tmp/nappe.wav"), Path("/tmp/fx.wav"), {}, Path("/tmp/s.mp4"))
        graphe = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("/tmp/plan.mp4", cmd)
        self.assertIn(f"setpts=PTS-STARTPTS+{temps[1]['debut']:.3f}/TB", graphe)
        self.assertIn("sidechaincompress", graphe)
        self.assertIn("loudnorm=I=-14", graphe)


class TestHabillage(unittest.TestCase):
    def test_ciel_et_son(self):
        from revue import ciel, son
        image = ciel.generer(160, 90, graine=2)
        self.assertEqual(image.size, (160, 90))
        tmp = Path(tempfile.mkdtemp())
        import wave
        with wave.open(str(son.nappe(3, tmp / "n.wav"))) as w:
            self.assertEqual((w.getnchannels(), w.getframerate()), (2, 48000))
        with wave.open(str(son.musique(12, tmp / "m.wav", impact=1.2))) as w:
            self.assertEqual(w.getnframes(), 12 * 48000)
        son.souffles([1.0, 2.0], 3, tmp / "s.wav", impact=1.2)
        self.assertEqual(son.accord_de_la_mesure(8), son.PONT[0])          # le pont arrive à la 9e mesure
        shutil.rmtree(tmp)

    def test_choix_du_plan_pexels(self):
        from revue import pexels
        reponse = {"videos": [
            {"id": 1, "width": 1920, "height": 1080, "duration": 20, "video_files": []},          # paysage : refusé
            {"id": 2, "width": 1080, "height": 1920, "duration": 4, "user": {"name": "Court"}, "url": "u2",
             "video_files": [{"file_type": "video/mp4", "width": 1080, "height": 1920, "link": "l2"}]},
            {"id": 3, "width": 1080, "height": 1920, "duration": 15, "user": {"name": "Long"}, "url": "u3",
             "video_files": [{"file_type": "video/mp4", "width": 720, "height": 1280, "link": "l3"},
                             {"file_type": "video/mp4", "width": 1080, "height": 1920, "link": "l3hd"}]},
        ]}
        with mock.patch.dict(os.environ, {"PEXELS_API_KEY": "k"}), \
             mock.patch.object(pexels, "_get", return_value=reponse):
            choisi = pexels.chercher_video("airplane", 8, set())
            self.assertEqual((choisi["id"], choisi["lien"], choisi["auteur"]), (3, "l3hd", "Long"))
            self.assertEqual(pexels.chercher_video("airplane", 8, {3})["id"], 2)


class TestPixabay(unittest.TestCase):
    def test_choix_du_plan_et_de_la_banque(self):
        from revue import illustrations, pixabay
        reponse = {"hits": [
            {"id": 1, "duration": 20, "user": "Paysage", "pageURL": "p1", "videos": {
                "large": {"url": "", "width": 0, "height": 0, "size": 0},
                "medium": {"url": "m1", "width": 1920, "height": 1080, "size": 9_000_000}}},
            {"id": 2, "duration": 12, "user": "Vertical", "pageURL": "p2", "videos": {
                "medium": {"url": "m2", "width": 1080, "height": 1920, "size": 8_000_000},
                "small": {"url": "s2", "width": 720, "height": 1280, "size": 3_000_000}}},
        ]}
        with mock.patch.dict(os.environ, {"PIXABAY_API_KEY": "k"}, clear=False):
            os.environ.pop("PEXELS_API_KEY", None)
            self.assertIs(illustrations.banque(), pixabay)
            with mock.patch.object(pixabay, "_get", return_value=reponse):
                choisi = illustrations.chercher_video("airplane", 8, set())
                self.assertEqual((choisi["id"], choisi["lien"], choisi["source"]), (2, "m2", "Pixabay"))
                self.assertEqual(illustrations.chercher_video("airplane", 8, {2})["lien"], "m1")


class TestCartes(unittest.TestCase):
    def test_une_carte_par_jour_sans_sujet_sensible(self):
        from revue import cartes
        c = charger_config()
        c["site"]["url"] = "https://hebdo-aero.github.io/Hebdo-Aero/"
        numero = lire_json(RACINE / "data" / "numeros" / "2026-10-11.json")
        liste = cartes.contenus(c, numero)
        self.assertEqual([x["jour"] for x in liste], ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi"][:len(liste) - 1] + ["samedi"])
        self.assertEqual(liste[0]["type"], "chiffre")
        self.assertEqual(liste[-1]["type"], "demain")
        tout = " ".join(x.get("titre", "") + x["texte_post"] for x in liste)
        self.assertNotIn("missile", tout)                       # l'attaque de Riyad n'est pas mise en avant
        for x in liste:
            self.assertIn("lien en bio", x["texte_post"].lower())
            self.assertLessEqual(len(x["texte_post"]), 2200)

    def test_titre_coupe_pas_en_image(self):
        from revue import cartes
        c = charger_config()
        numero = lire_json(RACINE / "data" / "numeros" / "2026-10-11.json")
        numero["breves"][0]["titre"] = "Un titre trop long coupé en plein milieu de la…"
        numero["une"][0]["titre"] = "Un autre titre coupé…"
        tout = " ".join(x.get("titre", "") + x["texte_post"] for x in cartes.contenus(c, numero))
        self.assertNotIn("…", tout)

    def test_format_story(self):
        from jinja2 import Environment, FileSystemLoader
        from revue import cartes
        gabarit = Environment(loader=FileSystemLoader(cartes.GABARITS), autoescape=True).get_template("carte.html")
        commun = dict(type="chiffre", valeur="42", legende="L", source="S", couleur="soleil", numero=2,
                      adresse="exemple.org", compte="hebdoaeronews", ciel="", polices="", logo="")
        story = gabarit.render(**commun, story=True)
        self.assertIn("const STORY = true", story)
        self.assertIn("Touchez @hebdoaeronews", story)
        publication = gabarit.render(**commun, story=False)
        self.assertIn("const STORY = false", publication)
        self.assertNotIn("Touchez @", publication)


class TestImagesSansMarque(unittest.TestCase):
    def test_marques_ecartees(self):
        from revue import pixabay
        self.assertTrue(pixabay._marque({"tags": "dhl, freight, cargo, airline, airplane"}))
        self.assertTrue(pixabay._marque({"tags": "british airways, airport"}))
        self.assertTrue(pixabay._marque({"tags": "aircraft, pilatus pc-24, jet"}))
        self.assertFalse(pixabay._marque({"tags": "airplane, sunset, sky, clouds"}))

    def test_sujets_sans_photo_par_defaut(self):
        from revue import illustrations
        demandes = []
        numero = {"date": "2026-10-18", "une": [{"titre": "A"}, {"titre": "B"}]}
        with mock.patch.object(illustrations, "disponible", return_value=True), \
             mock.patch.object(illustrations, "chercher_photo", side_effect=lambda r, p: demandes.append(r) or None):
            illustrations.illustrer_numero(numero, Path(tempfile.mkdtemp()))
        self.assertEqual(demandes, ["airplane sunset sky", "airplane sky clouds"])     # la couverture seulement


class TestPeriode(unittest.TestCase):
    def test_periode_fr(self):
        self.assertEqual(periode_fr("2026-10-05", "2026-10-11"), "5 au 11 octobre 2026")
        self.assertEqual(periode_fr("2026-09-28", "2026-10-04"), "28 septembre au 4 octobre 2026")
        self.assertEqual(periode_fr("2026-12-28", "2027-01-03"), "28 décembre 2026 au 3 janvier 2027")
        self.assertEqual(periode_fr("2026-06-01", "2026-06-07"), "1er au 7 juin 2026")

    def test_semaine_deja_couverte(self):
        config = charger_config()
        dernier = [{"numero": 1, "debut": "2026-10-05", "fin": "2026-10-11"}]
        with mock.patch.object(generer, "lister_numeros", return_value=dernier):
            with mock.patch.object(generer, "aujourdhui", return_value=date(2026, 10, 13)):
                self.assertIsNone(generer.periode_a_couvrir(config, force=False))
                # « forcer » rédige à nouveau le numéro de la semaine
                self.assertEqual(generer.periode_a_couvrir(config, force=True),
                                 (1, date(2026, 10, 5), date(2026, 10, 11)))
            with mock.patch.object(generer, "aujourdhui", return_value=date(2026, 10, 18)):
                self.assertEqual(generer.periode_a_couvrir(config, force=False),
                                 (2, date(2026, 10, 12), date(2026, 10, 18)))

    def test_relance_un_autre_jour_garde_la_semaine(self):
        config = charger_config()
        dernier = [{"numero": 1, "debut": "2026-10-05", "fin": "2026-10-11"}]
        with mock.patch.object(generer, "lister_numeros", return_value=dernier):
            with mock.patch.object(generer, "aujourdhui", return_value=date(2026, 10, 19)):   # lundi
                self.assertEqual(generer.periode_a_couvrir(config, force=False),
                                 (2, date(2026, 10, 12), date(2026, 10, 18)))
        deuxieme = [{"numero": 2, "debut": "2026-10-12", "fin": "2026-10-18"}]
        with mock.patch.object(generer, "lister_numeros", return_value=deuxieme):
            with mock.patch.object(generer, "aujourdhui", return_value=date(2026, 10, 25)):   # dimanche suivant
                self.assertEqual(generer.periode_a_couvrir(config, force=False),
                                 (3, date(2026, 10, 19), date(2026, 10, 25)))


class TestSite(unittest.TestCase):
    def test_construction(self):
        from revue import construire
        sortie = Path(tempfile.mkdtemp()) / "_site"
        with mock.patch.dict(os.environ, {"SITE_URL": "https://moi.github.io/hebdo-aero"}):
            construire.construire(sortie)
        accueil = (sortie / "index.html").read_text(encoding="utf-8")
        self.assertIn("Riyad sous les missiles", accueil)
        self.assertIn("https://www.aerotime.aero/articles/delta-cuts-2026-profit-forecast-fuel-costs", accueil)
        self.assertIn('href="assets/polices/', accueil.replace("url(\"", 'href="'))
        page = (sortie / "numeros" / "1" / "index.html").read_text(encoding="utf-8")
        self.assertIn('<link rel="canonical" href="https://moi.github.io/hebdo-aero/numeros/1/">', page)
        ET.parse(sortie / "flux.xml")
        ET.parse(sortie / "sitemap.xml")
        shutil.rmtree(sortie.parent)


class TestPublication(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "reseaux").mkdir()
        (self.tmp / "medias").mkdir()
        shutil.copy(RACINE / "data" / "reseaux" / "2026-10-11.json", self.tmp / "reseaux")
        (self.tmp / "medias" / "2026-10-11.mp4").write_bytes(b"video")
        for k in (1, 2, 3):
            (self.tmp / "medias" / f"2026-10-11-accroche-{k}.mp4").write_bytes(b"short")
        from revue import publier
        self.publier = publier
        self.patches = [mock.patch.object(publier, "DOSSIER_RESEAUX", self.tmp / "reseaux"),
                        mock.patch.object(publier, "DOSSIER_MEDIAS", self.tmp / "medias"),
                        mock.patch.dict(os.environ, {"SITE_URL": "https://moi.github.io/pdv/",
                                                     "YOUTUBE_CLIENT_ID": "a", "YOUTUBE_CLIENT_SECRET": "b",
                                                     "YOUTUBE_REFRESH_TOKEN": "c", "META_PAGE_TOKEN": "d",
                                                     "FACEBOOK_PAGE_ID": "e", "INSTAGRAM_USER_ID": "f"}),
                        mock.patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": ""})]
        for p in self.patches:
            p.start()
        os.environ.pop("THREADS_TOKEN", None)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp)

    def test_un_echec_n_empeche_pas_les_autres_et_pas_de_doublon(self):
        p = self.publier
        with mock.patch.object(p.youtube, "publier", return_value={"id": "Y", "url": "https://yt/Y"}) as yt, \
             mock.patch.object(p.meta, "instagram", side_effect=RuntimeError("panne")), \
             mock.patch.object(p.meta, "facebook", return_value={"id": "F", "url": "https://fb/F"}):
            code = p.main(["--date", "2026-10-11"])
        self.assertEqual(code, 1)
        script = json.loads((self.tmp / "reseaux" / "2026-10-11.json").read_text(encoding="utf-8"))
        self.assertEqual(set(script["publications"]), {"youtube", "facebook"})
        titre, description = yt.call_args.args[1], yt.call_args.args[2]
        self.assertIn("https://moi.github.io/pdv/numeros/1/", description)
        self.assertNotIn("{lien}", description)

        with mock.patch.object(p.youtube, "publier") as yt2, \
             mock.patch.object(p.meta, "instagram", return_value={"id": "I", "url": "https://ig/I"}), \
             mock.patch.object(p.meta, "facebook") as fb2:
            code = p.main(["--date", "2026-10-11"])
        self.assertEqual(code, 0)
        yt2.assert_not_called()
        fb2.assert_not_called()

    def test_shorts_d_accroche_sur_instagram(self):
        p = self.publier
        envoyes = []

        def faux_instagram(video, url, legende, version):
            envoyes.append((video.name, legende))
            return {"id": video.name, "url": "https://ig/" + video.name}

        with mock.patch.object(p.meta, "instagram", side_effect=faux_instagram), \
             mock.patch.object(p.youtube, "publier", return_value={"id": "Y", "url": "y"}), \
             mock.patch.object(p.meta, "facebook", return_value={"id": "F", "url": "f"}):
            self.assertEqual(p.main(["--date", "2026-10-11"]), 0)          # dimanche : short n° 1
            self.assertEqual(p.main(["--accroche"]), 0)                    # mardi : short n° 2
            self.assertEqual(p.main(["--accroche"]), 0)                    # jeudi : short n° 3
            self.assertEqual(p.main(["--accroche"]), 0)                    # plus rien à publier
        self.assertEqual([e[0] for e in envoyes],
                         ["2026-10-11-accroche-1.mp4", "2026-10-11-accroche-2.mp4", "2026-10-11-accroche-3.mp4"])
        self.assertIn("lien en bio", envoyes[0][1])
        script = json.loads((self.tmp / "reseaux" / "2026-10-11.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(script["publications"]["accroches"]), ["1", "2", "3"])

    def test_youtube_envoi_resumable(self):
        from revue.publier import youtube
        appels = []

        def faux_requete(url, **kw):
            appels.append((url, kw.get("methode")))
            if "uploadType=resumable" in url:
                return 200, {"Location": "https://upload/session"}, b""
            return 200, {}, b'{"id": "abc123"}'

        video = self.tmp / "medias" / "2026-10-11.mp4"
        with mock.patch.object(youtube, "post_formulaire", return_value={"access_token": "t"}), \
             mock.patch.object(youtube, "requete", side_effect=faux_requete):
            r = youtube.publier(video, "Titre <test>", "Desc", ["aviation"])
        self.assertEqual(r["url"], "https://www.youtube.com/shorts/abc123")
        self.assertEqual(appels[1], ("https://upload/session", "PUT"))


class TestVoix(unittest.TestCase):
    def test_demande_et_erreurs_claires(self):
        import base64
        from revue import voix
        from revue.http import ErreurHTTP
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        envoye = {}

        def faux_post(url, charge, entetes=None, **kw):
            envoye.update(url=url, charge=charge, entetes=entetes)
            return {"audioContent": base64.b64encode(b"RIFF....").decode()}

        with mock.patch.dict(os.environ, {"GOOGLE_TTS_API_KEY": "cle"}), \
             mock.patch.object(voix, "post_json", side_effect=faux_post):
            pistes = voix.synthetiser(["Bonjour"], tmp, "fr-FR-Chirp3-HD-Sulafat")
        self.assertTrue(pistes[0].exists())
        self.assertEqual(envoye["entetes"], {"x-goog-api-key": "cle"})
        self.assertEqual(envoye["charge"]["voice"], {"languageCode": "fr-FR", "name": "fr-FR-Chirp3-HD-Sulafat"})
        self.assertNotIn("sampleRateHertz", envoye["charge"]["audioConfig"])

        refus = ErreurHTTP(403, "Forbidden", '{"error": {"message": "Cloud Text-to-Speech API has not been '
                                             'used in project 123 before or it is disabled."}}')
        with mock.patch.dict(os.environ, {"GOOGLE_TTS_API_KEY": "cle"}), \
             mock.patch.object(voix, "post_json", side_effect=refus):
            with self.assertRaises(voix.ErreurVoix) as ctx:
                voix.synthetiser(["Bonjour"], tmp, "fr-FR-Chirp3-HD-Sulafat")
        self.assertIn("pas activée", str(ctx.exception))

        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(voix.ErreurVoix):
                voix.synthetiser(["Bonjour"], tmp, "fr-FR-Chirp3-HD-Sulafat")



PARTENAIRE = {"nom": "École Exemple", "texte": "Portes ouvertes le 15 novembre.", "lien": "https://exemple.fr/po?x=1",
              "du": date(2026, 10, 4), "au": date(2026, 10, 18)}


def config_revenus():
    c = charger_config()
    c["site"]["url"] = "https://moi.github.io/hebdo-aero/"
    c["newsletter"] = {"formulaire": "https://app.kit.com/forms/123/subscriptions", "heure_envoi": "08:30"}
    c["soutien"] = {"url": "https://fr.tipeee.com/hebdo-aero", "plateforme": "Tipeee"}
    c["statistiques"] = {"fournisseur": "cloudflare", "identifiant": "jeton123", "visites_par_mois": 1200}
    c["partenaires"] = [dict(PARTENAIRE)]
    return c


class TestMonetisation(unittest.TestCase):
    def test_partenaire_selon_les_dates(self):
        from revue import monetisation
        c = {"partenaires": [dict(PARTENAIRE), {"nom": "Autre", "lien": "https://autre.fr", "du": "2026-10-25"}]}
        self.assertEqual(monetisation.partenaire_du_numero(c, "2026-10-11")["nom"], "École Exemple")
        self.assertIsNone(monetisation.partenaire_du_numero(c, "2026-09-27"))
        self.assertEqual(monetisation.partenaire_du_numero(c, "2026-11-01")["nom"], "Autre")
        self.assertIsNone(monetisation.partenaire_du_numero({}, "2026-10-11"))

    def test_autorite_selon_le_pays(self):
        from revue import monetisation
        self.assertEqual(monetisation.editeur({})["autorite"], "la CNIL")
        lux = monetisation.editeur({"editeur": {"pays": "Luxembourg"}})
        self.assertEqual(lux["autorite"], "la CNPD")
        self.assertFalse(lux["france"])

    def test_lien_suivi_et_statistiques(self):
        from revue import monetisation
        lien = monetisation.lien_suivi("https://exemple.fr/po?x=1", "newsletter", 3)
        self.assertIn("x=1", lien)
        self.assertIn("utm_source=hebdo-aero", lien)
        self.assertIn("utm_campaign=numero-3", lien)
        self.assertEqual(monetisation.lien_suivi("https://e.fr/?utm_source=moi", "site", 1), "https://e.fr/?utm_source=moi")
        balise, nom = monetisation.statistiques({"statistiques": {"fournisseur": "cloudflare", "identifiant": "abc"}})
        self.assertIn('"token": "abc"', balise)
        self.assertEqual(nom, "Cloudflare Web Analytics")
        self.assertEqual(monetisation.statistiques({"statistiques": {"fournisseur": "cloudflare",
                                                                    "identifiant": "a\"><script>"}}), ("", ""))
        self.assertFalse(monetisation.newsletter(charger_config())["active"])

    def test_site_avec_revenus(self):
        from revue import construire
        sortie = Path(tempfile.mkdtemp()) / "_site"
        with mock.patch.object(construire, "charger_config", config_revenus):
            construire.construire(sortie)
        page = (sortie / "numeros" / "1" / "index.html").read_text(encoding="utf-8")
        self.assertIn("Publicité · Partenaire de la semaine", page)
        self.assertIn('rel="sponsored noopener"', page)
        self.assertIn("utm_medium=site", page)
        self.assertIn('action="https://app.kit.com/forms/123/subscriptions"', page)
        self.assertIn('name="email_address"', page)
        self.assertIn("Soutenir sur Tipeee", page)
        self.assertIn("static.cloudflareinsights.com", page)
        for chemin in ("annoncer", "mentions-legales", "newsletter", "newsletter/merci"):
            self.assertTrue((sortie / chemin / "index.html").exists(), chemin)
        annonceurs = (sortie / "annoncer" / "index.html").read_text(encoding="utf-8")
        self.assertIn("visites par mois", annonceurs)
        mentions = (sortie / "mentions-legales" / "index.html").read_text(encoding="utf-8")
        self.assertIn("Cloudflare Web Analytics", mentions)
        self.assertNotIn("non professionnel", mentions)      # le site rapporte : pas de mention « particulier »
        ET.parse(sortie / "sitemap.xml")
        shutil.rmtree(sortie.parent)

    def test_site_sans_revenus_n_affiche_rien(self):
        from revue import construire
        sortie = Path(tempfile.mkdtemp()) / "_site"
        construire.construire(sortie)
        page = (sortie / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("Publicité · Partenaire de la semaine", page)
        self.assertNotIn('class="formulaire-abo', page)
        self.assertNotIn("cloudflareinsights", page)
        self.assertFalse((sortie / "newsletter").exists())
        self.assertTrue((sortie / "mentions-legales" / "index.html").exists())
        shutil.rmtree(sortie.parent)


class TestPublicite(unittest.TestCase):
    def construire(self, partenaires=True, url="https://hebdo-aero.github.io/"):
        from revue import construire

        def config():
            c = config_revenus()
            c["site"]["url"] = url
            c["publicite"] = {"adsense": "ca-pub-1234567890123456", "bloc_numero": "111", "bloc_breves": "222"}
            if not partenaires:
                c["partenaires"] = []
            return c

        sortie = Path(tempfile.mkdtemp()) / "_site"
        self.addCleanup(shutil.rmtree, sortie.parent)
        with mock.patch.object(construire, "charger_config", config):
            construire.construire(sortie)
        return sortie

    def test_annonces_sur_les_pages_editoriales(self):
        sortie = self.construire(partenaires=False)
        page = (sortie / "numeros" / "1" / "index.html").read_text(encoding="utf-8")
        self.assertIn("adsbygoogle.js?client=ca-pub-1234567890123456", page)
        self.assertIn('data-ad-slot="111"', page)
        self.assertIn('data-ad-slot="222"', page)
        self.assertIn("Gérer les cookies", page)
        for service in ("mentions-legales", "newsletter", "annoncer", "shorts"):
            html = (sortie / service / "index.html").read_text(encoding="utf-8")
            self.assertNotIn("adsbygoogle.js", html, service)
            self.assertIn('name="google-adsense-account"', html)       # vérification du site par Google
        self.assertEqual((sortie / "ads.txt").read_text(), "google.com, pub-1234567890123456, DIRECT, f08c47fec0942fa0\n")
        mentions = (sortie / "mentions-legales" / "index.html").read_text(encoding="utf-8")
        self.assertIn("policies.google.com/technologies/partner-sites", mentions)
        self.assertNotIn("Ce site ne dépose aucun cookie", mentions)

    def test_exclusivite_du_partenaire(self):
        sortie = self.construire(partenaires=True)
        page = (sortie / "numeros" / "1" / "index.html").read_text(encoding="utf-8")
        self.assertIn("Publicité · Partenaire de la semaine", page)
        self.assertNotIn("adsbygoogle.js", page)
        self.assertNotIn('class="adsbygoogle"', page)
        self.assertIn("adsbygoogle.js", (sortie / "archives" / "index.html").read_text(encoding="utf-8"))

    def test_ads_txt_hors_racine(self):
        from revue import monetisation
        c = {"publicite": {"adsense": "ca-pub-1234567890123456"}, "site": {"url": "https://x.github.io/Depot/"}}
        contenu, alerte = monetisation.ads_txt(c)
        self.assertTrue(contenu)
        self.assertIn("sous-dossier", alerte)
        self.assertFalse(monetisation.publicite({"publicite": {"adsense": "ca-pub-12\"><script>"}})["active"])


class TestAnnonce(unittest.TestCase):
    def setUp(self):
        from revue import annonce
        self.a = annonce
        self.config = charger_config()
        self.config["site"]["url"] = "https://hebdo-aero.github.io/"
        self.numero = lire_json(RACINE / "data" / "numeros" / "2026-10-11.json")

    def test_titres_sans_la_rubrique_securite(self):
        titres = self.a.choisir_titres(self.numero)
        self.assertEqual(len(titres), 3)
        self.assertFalse(any("Riyad" in t for t in titres))        # attentat : pas sur une musique entraînante
        self.assertTrue(all(len(t) <= 84 for t in titres))

    def test_donnees_et_legende(self):
        d = self.a.donnees(self.config, self.numero)
        self.assertEqual(d["numero"], 1)
        self.assertIn("6 Md$", d["plus"])
        self.assertIn("15 brèves", d["plus"])
        self.assertEqual(len(d["cartes"]), len(d["titres"]) + 1)
        texte = self.a.legende(self.config, self.numero, d)
        self.assertIn("lien en bio", texte)
        self.assertIn("Au sommaire", texte)
        self.assertNotIn("; ;", texte)
        self.assertIn("▸ Le loueur Avolon commande 250 avions à Airbus et Boeing", texte)   # titres complets
        g = self.a.donnees(self.config, {"numero": 2, "debut": "2026-10-12", "fin": "2026-10-18"}, generique=True)
        self.assertEqual(g["titres"], self.a.GENERIQUE)
        self.assertEqual(g["periode"], "12 au 18 octobre 2026")

    def test_montage_avec_plans_filmes(self):
        plans = [{"fichier": "p0.mp4", "debut": 0.0, "fin": 4.8}, None, {"fichier": "p2.mp4", "debut": 12.0, "fin": 16.8}]
        cmd = self.a.commande(Path("s.mp4"), True, Path("ciel.jpg"), plans, Path("m.wav"), Path("e.wav"))
        graphe = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("p0.mp4", cmd)
        self.assertIn("overlay", graphe)
        self.assertIn("[4:a]", graphe)          # musique après le calque, le ciel et les deux plans
        dessin = self.a.commande(Path("s.mp4"), False, Path("ciel.jpg"), [None] * 3, Path("m.wav"), Path("e.wav"))
        self.assertIn("0:v", dessin)

    def test_page_shorts(self):
        from revue import construire
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        medias = tmp / "medias"
        medias.mkdir()
        (medias / "2026-10-11-annonce.mp4").write_bytes(b"v")
        (medias / "2026-10-11-annonce.jpg").write_bytes(b"j")
        with mock.patch.object(construire, "DOSSIER_MEDIAS", medias):
            construire.construire(tmp / "_site")
        page = (tmp / "_site" / "shorts" / "index.html").read_text(encoding="utf-8")
        self.assertIn("Annonce de la sortie", page)
        self.assertIn("videos/2026-10-11-annonce.mp4", page)
        self.assertTrue((tmp / "_site" / "videos" / "2026-10-11-annonce.mp4").exists())


class TestErreursClaude(unittest.TestCase):
    def test_messages_clairs(self):
        from revue.claude import ErreurClaude, expliquer
        from revue.http import ErreurHTTP
        credit = ErreurHTTP(400, "Bad Request", '{"error": {"message": "Your credit balance is too low to access the Anthropic API."}}')
        self.assertIn("Crédit Anthropic épuisé", expliquer(credit))
        self.assertIn("ANTHROPIC_API_KEY", expliquer(ErreurHTTP(401, "Unauthorized", "invalid x-api-key")))
        self.assertIn("modele", expliquer(ErreurHTTP(404, "Not Found", '{"error": {"message": "model: x not found"}}')))
        self.assertIn("manquante", expliquer(ErreurClaude("ANTHROPIC_API_KEY manquante (secret GitHub à créer).")))
        self.assertIn("espace de travail", expliquer(ErreurHTTP(400, "Bad Request", "anthropic-workspace-id header is required")))

    def test_espace_de_travail_facultatif(self):
        from revue import claude
        envoye = {}
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k", "ANTHROPIC_WORKSPACE_ID": "wrkspc_1"}), \
             mock.patch.object(claude, "post_json", side_effect=lambda url, charge, entetes=None, **kw: envoye.update(entetes) or {}):
            claude.appeler({"model": "m"})
        self.assertEqual(envoye["anthropic-workspace-id"], "wrkspc_1")

    def test_l_etape_numero_echoue_proprement(self):
        from revue import generer
        from revue.claude import ErreurClaude
        with mock.patch.object(generer, "etape_numero", side_effect=ErreurClaude("ANTHROPIC_API_KEY manquante")):
            self.assertEqual(generer.main(["numero"]), 1)


class TestNewsletter(unittest.TestCase):
    def setUp(self):
        from revue import newsletter
        self.nl = newsletter
        self.config = config_revenus()
        self.numero = lire_json(RACINE / "data" / "numeros" / "2026-10-11.json")

    def test_contenu_de_l_email(self):
        m = self.nl.contenu(self.config, self.numero, verifier_en_ligne=False)
        self.assertTrue(m["sujet"].startswith("N° 1 · "))
        self.assertLessEqual(len(m["sujet"]), 120)
        self.assertIn("https://moi.github.io/hebdo-aero/numeros/1/", m["html"])
        self.assertIn("assets/logo/logo-email.png", m["html"])
        self.assertIn("Publicité · Partenaire de la semaine", m["html"])
        self.assertIn("utm_medium=newsletter", m["html"])
        self.assertIn("Airbus livre 72 avions", m["html"])       # titres des brèves
        self.assertEqual(m["partenaire"], "École Exemple")

    def test_heure_d_envoi(self):
        from datetime import timedelta
        dimanche_tot = datetime(2026, 10, 18, 5, 20, tzinfo=timezone.utc)      # 7 h 20 à Paris
        self.assertEqual(self.nl.heure_envoi(self.config, dimanche_tot), datetime(2026, 10, 18, 6, 30, tzinfo=timezone.utc))
        tard = datetime(2026, 10, 18, 9, 0, tzinfo=timezone.utc)
        self.assertEqual(self.nl.heure_envoi(self.config, tard), tard + timedelta(minutes=5))

    def test_envoi_kit(self):
        envoye = {}

        def faux_post(url, charge, entetes=None, **kw):
            envoye.update(url=url, charge=charge, entetes=entetes, essais=kw.get("essais"))
            return {"broadcast": {"id": 42}}

        with mock.patch.dict(os.environ, {"KIT_API_KEY": "cle"}), \
             mock.patch.object(self.nl, "post_json", side_effect=faux_post), \
             mock.patch.object(self.nl, "_existe_en_ligne", return_value=True):
            r = self.nl.envoyer(self.config, self.numero, datetime(2026, 10, 18, 5, 20, tzinfo=timezone.utc))
        self.assertEqual(r["id"], 42)
        self.assertEqual(envoye["url"], "https://api.kit.com/v4/broadcasts")
        self.assertEqual(envoye["entetes"]["X-Kit-Api-Key"], "cle")
        self.assertEqual(envoye["essais"], 1)                     # jamais de doublon
        self.assertEqual(envoye["charge"]["send_at"], "2026-10-18T06:30:00Z")
        self.assertNotIn("subscriber_filter", envoye["charge"])   # tous les abonnés
        self.assertIn("videos/2026-10-11.jpg", envoye["charge"]["content"])

    def test_une_seule_fois_par_numero(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        appels = []
        with mock.patch.object(self.nl, "DOSSIER_ENVOIS", tmp), \
             mock.patch.object(self.nl, "charger_config", config_revenus), \
             mock.patch.object(self.nl, "envoyer", side_effect=lambda c, n: appels.append(1) or
                               {"id": 1, "envoi_prevu": "x", "sujet": "s", "partenaire": None}), \
             mock.patch.dict(os.environ, {"KIT_API_KEY": "cle"}):
            self.nl.main(["--force"])
            self.nl.main(["--force"])
        self.assertEqual(len(appels), 1)
        self.assertTrue((tmp / "2026-10-11.json").exists())

    def test_sans_cle_rien_n_est_envoye(self):
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(self.nl, "envoyer") as envoi:
            self.assertEqual(self.nl.main([]), 0)
        envoi.assert_not_called()


class TestPartenaireVideo(unittest.TestCase):
    def test_mention_dans_la_video_et_les_legendes(self):
        c = config_revenus()
        numero = lire_json(RACINE / "data" / "numeros" / "2026-10-11.json")
        brut = {"scenes": [{"surtitre": "x", "titre_ecran": "t", "texte_ecran": "f", "narration": "Une phrase."}] * 3,
                "chiffre_narration": "Le chiffre.", "youtube_titre": "Y", "instagram": "I", "facebook": "F",
                "threads": "T " * 300}
        s = reseaux.assembler(c, numero, brut)
        fin = s["video"]["scenes"][-1]
        self.assertIn("École Exemple", fin["narration"])
        self.assertIn("École Exemple", fin["partenaire"])
        self.assertEqual(s["video"]["publicite"], "Collaboration commerciale")
        for cle in ("youtube_description", "instagram", "facebook", "threads"):
            self.assertTrue(s["legendes"][cle].startswith("Collaboration commerciale avec École Exemple."), cle)
        self.assertLessEqual(len(reseaux.remplir_liens(s["legendes"]["threads"], c, 1)), 500)
        c["partenaires"][0]["video"] = False
        s = reseaux.assembler(c, numero, brut)
        self.assertNotIn("partenaire", s["video"]["scenes"][-1])
        self.assertFalse(s["video"]["publicite"])

    def test_youtube_placement_paye_avec_repli(self):
        from revue.http import ErreurHTTP
        from revue.publier import youtube
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        video = tmp / "v.mp4"
        video.write_bytes(b"v")
        urls = []

        def faux_requete(url, **kw):
            urls.append(url)
            if "paidProductPlacementDetails" in url:
                raise ErreurHTTP(400, "Bad Request", "invalid part")
            if "uploadType=resumable" in url:
                return 200, {"Location": "https://upload/session"}, b""
            return 200, {}, b'{"id": "abc"}'

        with mock.patch.object(youtube, "jeton_acces", return_value="t"), \
             mock.patch.object(youtube, "requete", side_effect=faux_requete):
            r = youtube.publier(video, "T", "D", [], placement_paye=True)
        self.assertEqual(r["id"], "abc")
        self.assertIn("paidProductPlacementDetails", urls[0])
        self.assertNotIn("paidProductPlacementDetails", urls[1])


if __name__ == "__main__":
    unittest.main()
