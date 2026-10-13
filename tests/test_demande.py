"""Demande de recherche (Ubersuggest) : du brut d'Ubersuggest aux colonnes que lisent opportunites et la cartographie."""

import argparse
import io
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import demande  # noqa: E402


class FauxClient:
    """Rejoue des réponses Ubersuggest enregistrées, et note les appels."""

    def __init__(self, reponses):
        self.reponses, self.appels = reponses, []

    def appel(self, outil, arguments):
        self.appels.append((outil, arguments))
        return self.reponses[outil](arguments)


def args(**kw):
    base = dict(pays="FR", loc_id=None, langue="fr", graines="fleurs ceramique tombe", lexique=False,
                mode="suggestions", max=10, mots=None, fichier=None, mot=None)
    base.update(kw)
    return argparse.Namespace(**base)


class TestMarche(unittest.TestCase):
    def test_pays_et_loc_id(self):
        self.assertEqual(demande.marche(args(pays="be", langue="FR")), ("Belgique", 2056, "fr"))
        self.assertEqual(demande.marche(args(loc_id=1006094)), ("locId 1006094", 1006094, "fr"))
        with self.assertRaises(SystemExit):
            demande.marche(args(pays="ZZ"))


class TestConversions(unittest.TestCase):
    def test_intention(self):
        self.assertEqual(demande.intention("Transactional"), "transactional")
        self.assertEqual(demande.intention([4, 3]), "transactional")
        self.assertEqual((demande.intention(None), demande.intention([])), ("", ""))

    def test_tendance_an(self):
        mensuel = [{"period": "202505", "search_volume": 880}, {"period": "202605", "search_volume": 720},
                   {"period": "202604", "search_volume": 720}]
        self.assertEqual(demande.tendance_an(mensuel), -18)
        self.assertIsNone(demande.tendance_an([{"period": "202605", "search_volume": 720}]))


class TestCommandes(unittest.TestCase):
    def test_idees_dedoublonnees_et_triees(self):
        client = FauxClient({"match_keywords": lambda a: {
            "searched_keywords": [{"keyword": "fleurs ceramique tombe", "volume": 720, "sd": 10,
                                   "search_intent": "Transactional"}],
            "suggestions": [{"keyword": "fleurs ceramique tombe prix", "volume": 260, "sd": 19,
                             "search_intent": None},
                            {"keyword": "fleurs ceramique tombe", "volume": 720, "sd": 10}]}})
        res = demande.cmd_idees(args(), client)
        self.assertEqual([l["requete"] for l in res["lignes"]], ["fleurs ceramique tombe", "fleurs ceramique tombe prix"])
        self.assertEqual((res["lignes"][0]["kd"], res["lignes"][0]["intention"]), (10, "transactional"))
        self.assertEqual(client.appels[0][1]["locId"], 2250)

    def test_volumes_plafonnes(self):
        client = FauxClient({"keyword_overview": lambda a: {"keyword": a["keyword"], "search_volume": 100,
                                                            "seo_difficulty": 12, "search_intent": "Informational"}})
        with redirect_stderr(io.StringIO()) as err:
            res = demande.cmd_volumes(args(mots="a, b, c, a", max=2), client)
        self.assertEqual((len(res["lignes"]), res["rapports"]), (2, 2))
        self.assertIn("1 mot(s) non mesuré(s)", err.getvalue())

    def test_serp(self):
        client = FauxClient({
            "serp_analysis": lambda a: {"serpEntries": [
                {"type": "ai_overview", "url": "http://NODOMAIN"},
                {"type": "organic", "url": "https://a.fr/x", "title": "A", "position": 2, "clicks": 9,
                 "domainAuthority": 30}]},
            "google_suggestions": lambda a: {"keywords": {a["keywords"][0]: {"questions": ["comment faire ?"]}}}})
        res = demande.cmd_serp(args(mot="décorer une tombe"), client)
        self.assertTrue(res["ai_overview"])
        self.assertFalse(res["paa"])
        self.assertEqual(res["organique"][0]["url"], "https://a.fr/x")
        self.assertEqual(res["questions"], ["comment faire ?"])
        self.assertEqual(client.appels[1][1]["country"], "fr")


if __name__ == "__main__":
    unittest.main()
