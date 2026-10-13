"""Client Ubersuggest : jetons qui tournent, réponses MCP décodées, erreurs dites telles quelles."""

import io
import json
import os
import sys
import time
import unittest
from contextlib import redirect_stderr

from _outils import SCRIPTS, DossierIsole

sys.path.insert(0, str(SCRIPTS))
import ubersuggest as U  # noqa: E402


class AvecProjet(DossierIsole):
    def setUp(self):
        super().setUp()
        self.env = {k: os.environ.pop(k, None) for k in ("SEO_DECUPLER_PROJET", "UBERSUGGEST_REFRESH_TOKEN")}
        os.environ["SEO_DECUPLER_PROJET"] = str(self.dossier)
        self.origines = (U._post_formulaire, U._rpc)
        self.formulaires = []

        def jeton(url, champs):
            self.formulaires.append(champs)
            n = len(self.formulaires)
            return {"access_token": f"acces-{n}", "expires_in": 172800, "refresh_token": f"renouv-{n}"}
        U._post_formulaire = jeton

    def tearDown(self):
        U._post_formulaire, U._rpc = self.origines
        os.environ.pop("SEO_DECUPLER_PROJET", None)
        os.environ.update({k: v for k, v in self.env.items() if v})
        super().tearDown()


class TestJetons(AvecProjet):
    def test_pas_connecte(self):
        with self.assertRaises(U.ErreurUbersuggest):
            U.jeton_acces()

    def test_renouvellement_garde_le_nouveau_jeton(self):
        U.ecrire_jetons({"access_token": "vieux", "expire_a": time.time() - 1, "refresh_token": "r0"})
        self.assertEqual(U.jeton_acces(), "acces-1")
        self.assertEqual(self.formulaires[0]["refresh_token"], "r0")
        # Ubersuggest refuse un jeton de renouvellement déjà utilisé : seul le dernier doit rester.
        self.assertEqual(U.lire_jetons()["refresh_token"], "renouv-1")
        self.assertEqual(U.jeton_acces(), "acces-1")              # encore valable : pas de nouvel appel
        self.assertEqual(len(self.formulaires), 1)

    def test_jeton_de_routine_perime_signale(self):
        os.environ["UBERSUGGEST_REFRESH_TOKEN"] = "secret-de-routine"
        with redirect_stderr(io.StringIO()) as err:
            self.assertEqual(U.jeton_acces(), "acces-1")
        self.assertIn("UBERSUGGEST_REFRESH_TOKEN est périmé", err.getvalue())
        self.assertTrue(U.fichier_jetons().is_file())


class TestAppels(AvecProjet):
    def setUp(self):
        super().setUp()
        U.ecrire_jetons({"access_token": "a", "expire_a": time.time() + 3600, "refresh_token": "r"})
        self.reponses = []

        def rpc(corps, jeton, session=""):
            if corps["method"] == "initialize":
                return {"protocolVersion": U.VERSION_MCP}, "session-1"
            if corps["method"].startswith("notifications/"):
                return None, session
            self.assertEqual(session, "session-1")
            return self.reponses.pop(0), session
        U._rpc = rpc

    def test_texte_json_decode(self):
        self.reponses = [{"content": [{"type": "text", "text": json.dumps({"search_volume": 720})}]}]
        self.assertEqual(U.Client().appel("keyword_overview", {"keyword": "x"}), {"search_volume": 720})

    def test_erreur_metier(self):
        self.reponses = [{"isError": True, "content": [{"type": "text", "text": "Error: HTTP 403 /backlinks"}]}]
        with self.assertRaises(U.ErreurUbersuggest) as e:
            U.Client().appel("backlinks", {"domain": "a.fr"})
        self.assertIn("403", str(e.exception))

    def test_calcul_en_cours_relance(self):
        texte = lambda d: {"content": [{"type": "text", "text": json.dumps(d)}]}  # noqa: E731
        self.reponses = [texte({"done": False, "backlinks": []}), texte({"done": True, "backlinks": [1]})]
        self.assertEqual(U.Client().appel_complet("backlinks", {}, pause=0)["backlinks"], [1])

    def test_loc_id(self):
        self.assertEqual((U.loc_id("fr"), U.loc_id("US")), (2250, 2840))
        with self.assertRaises(SystemExit):
            U.loc_id("ZZ")


if __name__ == "__main__":
    unittest.main()
