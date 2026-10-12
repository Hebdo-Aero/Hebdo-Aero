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
        son.souffles([1.0, 2.0], 3, tmp / "s.wav")
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


class TestPeriode(unittest.TestCase):
    def test_periode_fr(self):
        self.assertEqual(periode_fr("2026-10-05", "2026-10-11"), "5 au 11 octobre 2026")
        self.assertEqual(periode_fr("2026-09-28", "2026-10-04"), "28 septembre au 4 octobre 2026")
        self.assertEqual(periode_fr("2026-12-28", "2027-01-03"), "28 décembre 2026 au 3 janvier 2027")
        self.assertEqual(periode_fr("2026-06-01", "2026-06-07"), "1er au 7 juin 2026")

    def test_semaine_deja_couverte(self):
        config = charger_config()
        dernier = [{"numero": 1, "fin": "2026-10-11"}]
        with mock.patch.object(generer, "lister_numeros", return_value=dernier):
            with mock.patch.object(generer, "aujourdhui", return_value=date(2026, 10, 13)):
                self.assertIsNone(generer.periode_a_couvrir(config, force=False))
                self.assertEqual(generer.periode_a_couvrir(config, force=True),
                                 (2, date(2026, 10, 12), date(2026, 10, 13)))
            with mock.patch.object(generer, "aujourdhui", return_value=date(2026, 10, 18)):
                self.assertEqual(generer.periode_a_couvrir(config, force=False),
                                 (2, date(2026, 10, 12), date(2026, 10, 18)))


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


if __name__ == "__main__":
    unittest.main()
