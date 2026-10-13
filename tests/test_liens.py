"""Profil de liens : le spam automatique ne doit jamais passer pour de vrais liens."""

import sys
import unittest

from _outils import SCRIPTS

sys.path.insert(0, str(SCRIPTS))
import liens  # noqa: E402

PBN = "high quality dofollow backlinks da 50 pa 40 premium pbn network service rank first page google"


def lien(url, ancre="", titre="", score=5, nofollow=False, vu="2026-09-02"):
    return {"url_from": url, "anchor": ancre, "title": titre, "spam_score": score, "nofollow": nofollow,
            "first_seen": vu, "domain_inlink_rank": 20}


class TestClasser(unittest.TestCase):
    def test_spam_ecarte_et_date(self):
        liens_ = [
            lien("https://www.vrai-media.fr/article", "décoration de tombe", "Décorer une tombe"),
            lien("https://annuaire.fr/x", "fleurs de coeur", nofollow=True),
            # Relevé réel : Ubersuggest note 7 (ou rien) ces pages PBN, c'est leur vocabulaire qui les trahit.
            lien("https://cvillico.com/all/1082/12.html", PBN, "Boost your Google rankings with Premium PBN",
                 score=7, vu="2026-08-17"),
            lien("https://seochecker.shop/x", "exemple.fr", score=None, vu="2026-10-06"),
            lien("https://blog.fr/y", "lire", "Un article", score=45, vu="2026-10-01"),
        ]
        c = liens.classer(liens_)
        self.assertEqual((c["total"], len(c["propres"]), c["spam"], c["propres_dofollow"]), (5, 2, 3, 1))
        self.assertEqual([d["domaine"] for d in c["propres"]], ["vrai-media.fr", "annuaire.fr"])
        self.assertEqual(c["spam_par_mois"], {"2026-08": 1, "2026-10": 2})
        raisons = [d["raison"] for d in c["spam_detail"]]
        self.assertIn("le domaine", raisons[1])
        self.assertEqual(raisons[2], "score de spam 45")

    def test_seuil(self):
        self.assertEqual(len(liens.classer([lien("https://a.fr", score=30)], seuil=31)["propres"]), 1)
        self.assertEqual(len(liens.classer([lien("https://a.fr", score=30)], seuil=30)["propres"]), 0)

    def test_ancre_ordinaire_propre(self):
        for ancre in ("plaque funéraire personnalisée", "https://www.exemple.fr/", "ce site", "liens utiles"):
            self.assertIsNone(liens.raison_spam(lien("https://mes-liens-favoris.net/x", ancre)), ancre)


if __name__ == "__main__":
    unittest.main()
