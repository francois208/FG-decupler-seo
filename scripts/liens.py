#!/usr/bin/env python3
"""
liens.py — le profil de liens d'un site (Ubersuggest), trié entre vrais liens
et spam automatique.

Beaucoup de sites reçoivent des centaines de liens de domaines générés en masse
(« seochecker.shop », « backlinkanalyzer.space », pages « Premium PBN & Link
Building »…) : ils gonflent les compteurs sans rien apporter, et Google les
ignore. Le chiffre qui compte est celui des domaines propres, et c'est le seul
que ce script met en avant.

    python3 liens.py resume --cible exemple.com
    python3 liens.py domaines --cible exemple.com
    python3 liens.py domaines --cible exemple.com --json > donnees/liens.json

Un domaine est classé spam si son lien porte le vocabulaire des réseaux de
liens (domaine, titre de la page ou ancre), ou si son score de spam Ubersuggest
atteint --seuil. Le score seul ne suffit pas : Ubersuggest note 7/100 des pages
« Boost your Google rankings with Premium PBN » (relevé d'octobre 2026).

Connexion : `ubersuggest.py connexion`, une fois. Un rapport du quota
quotidien par domaine analysé, quel que soit le nombre de pages lues.
Ubersuggest limite aussi le débit des backlinks, sans le documenter : après
quelques pages de 100 liens enchaînées, ses outils de liens répondent 403
pendant un temps (relevé d'octobre 2026). D'où la pause entre deux pages, et
`resume`, qui passe par domain_overview et n'y est pas soumis.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ubersuggest as U  # noqa: E402
from _projet import charger_env  # noqa: E402

SEUIL_SPAM = 30          # score de spam Ubersuggest (0-100) à partir duquel un domaine est écarté
PAGE = 100               # liens par appel (un par domaine référent)
PAUSE = 10               # secondes entre deux pages : Ubersuggest bride le débit des backlinks

VOCABULAIRE_SPAM = re.compile(
    r"pbn|backlinks?|dofollow|link ?building|seo ?(?:checker|analy[sz]er|tools?|service)|"
    r"rank(?:ing)? (?:first|1st) page|buy (?:links|backlinks)|\bda ?\d{2}\b|\bpa ?\d{2}\b", re.I)


def domaine_de(url: str) -> str:
    h = (url or "").split("//", 1)[-1].split("/", 1)[0].lower()
    return h[4:] if h.startswith("www.") else h


def raison_spam(lien: dict, seuil: int = SEUIL_SPAM) -> str | None:
    """Pourquoi ce lien est du spam, ou None s'il est propre."""
    for champ in ("url_from", "title", "anchor"):
        m = VOCABULAIRE_SPAM.search(domaine_de(lien.get(champ, "")) if champ == "url_from" else lien.get(champ) or "")
        if m:
            return f"« {m.group(0)} » dans {'le domaine' if champ == 'url_from' else 'le titre' if champ == 'title' else 'l’ancre'}"
    if (lien.get("spam_score") or 0) >= seuil:
        return f"score de spam {lien['spam_score']}"
    return None


def classer(liens: list[dict], seuil: int = SEUIL_SPAM) -> dict:
    """Sépare les domaines référents propres du spam (un lien par domaine), et date le spam."""
    propres, spam, mois = [], [], {}
    for l in liens:
        d = {"domaine": domaine_de(l.get("url_from", "")), "autorite": l.get("domain_inlink_rank") or 0,
             "url_from": l.get("url_from"), "url_to": l.get("url_to"), "ancre": l.get("anchor") or "",
             "nofollow": bool(l.get("nofollow")), "spam_score": l.get("spam_score"),
             "vu_le": (l.get("first_seen") or "")[:10]}
        raison = raison_spam(l, seuil)
        if raison:
            spam.append({**d, "raison": raison})
            if d["vu_le"]:
                mois[d["vu_le"][:7]] = mois.get(d["vu_le"][:7], 0) + 1
        else:
            propres.append(d)
    return {"total": len(liens), "propres": propres, "spam": len(spam), "spam_detail": spam,
            "spam_par_mois": dict(sorted(mois.items())),
            "propres_dofollow": sum(1 for d in propres if not d["nofollow"])}


def un_lien_par_domaine(client: U.Client, cible: str, limite: int) -> list[dict]:
    liens, decalage = [], 0
    while len(liens) < limite:
        r = client.appel_complet("backlinks", {"domain": cible, "limit": PAGE, "offset": decalage,
                                              "one_per_domain": True, "order_by": "domain_inlink_rank"})
        lot = r.get("backlinks") or []
        liens += lot
        if len(lot) < PAGE:
            break
        decalage += PAGE
        time.sleep(PAUSE)
    return liens[:limite]


def cmd_resume(a) -> int:
    r = U.Client().appel("domain_overview", {"domain": a.cible})
    resume = {"autorite": r.get("domainAuthority"), "liens": r.get("backlinks"),
              "domaines_referents": r.get("refDomains"), "liens_dofollow": r.get("follow"),
              "liens_nofollow": r.get("noFollow")}
    if a.json:
        print(json.dumps(resume, ensure_ascii=False, indent=1))
        return 0
    print(f"\n  {a.cible} · autorité {resume['autorite']} · {resume['domaines_referents']} domaines référents · "
          f"{resume['liens']} liens")
    print("  Pour séparer les vrais liens du spam : liens.py domaines\n")
    return 0


def cmd_domaines(a) -> int:
    c = classer(un_lien_par_domaine(U.Client(), a.cible, a.limite), a.seuil)
    if a.json:
        print(json.dumps({"cible": a.cible, **c}, ensure_ascii=False, indent=1))
        return 0
    print(f"\n  {a.cible} · {c['total']} domaines référents : {len(c['propres'])} propres "
          f"({c['propres_dofollow']} en dofollow), {c['spam']} de spam")
    if c["spam_par_mois"]:
        print("  Spam par mois d'apparition : " + ", ".join(f"{m} : {n}" for m, n in c["spam_par_mois"].items()))
    print("\n  Domaines propres :")
    for d in c["propres"]:
        print(f"    {d['domaine']:<40} autorité {d['autorite']:>3} · {'nofollow' if d['nofollow'] else 'dofollow'} · "
              f"vu le {d['vu_le']}")
    print()
    return 0


def main() -> int:
    charger_env()
    ap = argparse.ArgumentParser(description="Profil de liens : vrais liens et spam automatique")
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("resume", help="chiffres globaux")
    p.add_argument("--cible", required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(f=cmd_resume)
    p = sp.add_parser("domaines", help="domaines référents, propres d'un côté, spam de l'autre")
    p.add_argument("--cible", required=True)
    p.add_argument("--limite", type=int, default=1000)
    p.add_argument("--seuil", type=int, default=SEUIL_SPAM)
    p.add_argument("--json", action="store_true")
    p.set_defaults(f=cmd_domaines)
    a = ap.parse_args()
    try:
        return a.f(a)
    except U.ErreurUbersuggest as exc:
        print(f"✗ Ubersuggest : {exc}", file=sys.stderr)
        if "403" in str(exc):
            print("  Débit des backlinks bridé par Ubersuggest : réessayez plus tard, ou passez par le "
                  "connecteur claude.ai.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
