#!/usr/bin/env python3
"""La demande de recherche, par Ubersuggest (serveur MCP officiel, appelé en direct par ubersuggest.py).

    python3 demande.py volumes --mots "création entreprise, expert comptable lyon" --langue fr
    python3 demande.py idees --graines "création entreprise" --langue fr --max 100
    python3 demande.py idees --lexique --langue ar            # graines = thèmes du lexique du projet
    python3 demande.py serp --mot "expert comptable lyon" --langue fr

- `volumes` : volume mensuel, CPC, difficulté et intention de mots-clés donnés.
- `idees`   : mots-clés liés à des graines, avec volume, difficulté et intention.
              Écrit donnees/demande-<langue>-<date>.csv (requete,volume,kd,intention,
              tendance_an_pct,page),
              directement utilisable par opportunites.py --demande.
- `serp`    : top 10 organique, présence d'un AI Overview et d'« Autres questions
              posées », et les questions réelles de l'autocomplétion Google.
              C'est la matière du brief.

Le pays vient de projet.pays_cible (config) ou de --pays, la langue de --langue.
Connexion : `ubersuggest.py connexion`, une fois. Chaque mot-clé ou domaine
distinct consomme un rapport du quota quotidien Ubersuggest (affiché à la
fin). Sans dépendance.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ubersuggest as U  # noqa: E402
from _projet import charger_env, lire_valeur, racine_projet  # noqa: E402
from ubersuggest import ErreurUbersuggest  # noqa: E402,F401 — réexportée pour les autres scripts

NOMS_PAYS = {"FR": "France", "BE": "Belgique", "CH": "Suisse", "CA": "Canada", "LU": "Luxembourg",
             "MA": "Maroc", "TN": "Tunisie", "DZ": "Algérie", "SN": "Sénégal", "CI": "Côte d'Ivoire",
             "SA": "Arabie saoudite", "AE": "Émirats arabes unis", "QA": "Qatar", "KW": "Koweït",
             "EG": "Égypte", "US": "États-Unis", "GB": "Royaume-Uni", "DE": "Allemagne", "ES": "Espagne",
             "IT": "Italie"}

# Intentions Ubersuggest (searchIntent de keyword_suggestions) → libellés de DataForSEO, gardés
# parce qu'opportunites.py et la cartographie les lisent déjà.
INTENTIONS = {1: "informational", 2: "navigational", 3: "commercial", 4: "transactional"}


def marche(a) -> tuple[str, int, str]:
    """(nom du lieu, locId Ubersuggest, langue) depuis --loc-id, --pays ou projet.pays_cible."""
    langue = (a.langue or "fr").lower()
    if getattr(a, "loc_id", None):
        return f"locId {a.loc_id}", int(a.loc_id), langue
    pays = (a.pays or lire_valeur("projet.pays_cible") or "FR").upper()
    if pays not in U.LOC_IDS:
        raise SystemExit(f"✗ pays {pays} sans locId connu : passez --loc-id (cherchez-le avec "
                         f"`ubersuggest.py appel location_suggest '{{\"query\": \"…\"}}'`)")
    return NOMS_PAYS.get(pays, pays), U.LOC_IDS[pays], langue


def intention(brut) -> str:
    """« Transactional », [4, 3] ou None → « transactional » (la première, la dominante)."""
    if isinstance(brut, list):
        brut = INTENTIONS.get(brut[0], "") if brut else ""
    return (brut or "").lower()


def tendance_an(mensuel: list[dict]) -> int | None:
    """Évolution en % du dernier mois face au même mois un an plus tôt (monthly_searches)."""
    par_mois = {m.get("period"): m.get("search_volume") or 0 for m in mensuel or []}
    if not par_mois:
        return None
    dernier = max(par_mois)
    il_y_a_un_an = f"{int(dernier[:4]) - 1}{dernier[4:]}"
    avant = par_mois.get(il_y_a_un_an)
    return round((par_mois[dernier] - avant) * 100 / avant) if avant else None


def ligne_demande(it: dict) -> dict:
    """Une suggestion (match_keywords ou keyword_suggestions) au format de donnees/demande-*.csv."""
    return {"requete": it.get("keyword"), "volume": it.get("volume") or 0, "kd": it.get("sd"),
            "intention": intention(it.get("search_intent") or it.get("searchIntent")),
            "tendance_an_pct": None, "page": ""}


def lire_serp(brut: dict) -> dict:
    """La réponse de serp_analysis réduite à ce que le brief utilise.

    Ubersuggest signale la présence d'un AI Overview, d'« Autres questions posées »
    et des autres blocs, mais n'en renvoie pas le contenu : sources de l'AI
    Overview et questions PAA sont « non renvoyées », pas « absentes ».
    """
    organique, features = [], []
    for it in (brut or {}).get("serpEntries") or []:
        t = it.get("type") or ""
        if t == "organic":
            organique.append({"rang": len(organique) + 1, "position": it.get("position"), "url": it.get("url"),
                              "titre": it.get("title") or "", "autorite": it.get("domainAuthority"),
                              "clics": it.get("clicks")})
        elif t not in features:
            features.append(t)
    return {"organique": organique, "features": features, "ai_overview": "ai_overview" in features,
            "paa": "people_also_ask" in features}


def questions_autocompletion(brut: dict) -> list[str]:
    """Les questions de google_suggestions (groupe « questions »), dédoublonnées."""
    vues = []
    for groupe in ((brut or {}).get("keywords") or {}).values():
        for q in (groupe or {}).get("questions") or []:
            if q not in vues:
                vues.append(q)
    return vues


# ─── Commandes ────────────────────────────────────────────────────

def cmd_volumes(a, client: U.Client) -> dict:
    lieu, loc, langue = marche(a)
    mots = [m.strip() for m in (a.mots or "").split(",") if m.strip()]
    if a.fichier:
        with open(a.fichier, encoding="utf-8-sig") as f:
            mots += [l[0].strip() for l in csv.reader(f) if l and l[0].strip() and l[0].strip().lower() != "requete"]
    mots = list(dict.fromkeys(mots))
    if not mots:
        raise SystemExit("✗ aucun mot-clé : --mots \"a, b\" ou --fichier liste.csv")
    lignes = []
    for mot in mots[:a.max]:
        r = client.appel("keyword_overview", {"keyword": mot, "language": langue, "locId": loc})
        lignes.append({"requete": r.get("keyword") or mot, "volume": r.get("search_volume") or 0,
                       "cpc": r.get("cpc"), "kd": r.get("seo_difficulty"),
                       "intention": intention(r.get("search_intent")),
                       "tendance_an_pct": tendance_an(r.get("monthly_searches"))})
    if len(mots) > a.max:
        print(f"  ! {len(mots) - a.max} mot(s) non mesuré(s) : --max {a.max} (un rapport par mot-clé)",
              file=sys.stderr)
    lignes.sort(key=lambda x: -(x["volume"] or 0))
    return {"lieu": lieu, "langue": langue, "rapports": len(lignes), "lignes": lignes}


def graines_du_lexique() -> list[str]:
    """Une graine lisible par thème : le premier motif sans syntaxe d'expression régulière."""
    chemin = racine_projet() / "memoire" / "lexique.csv"
    if not chemin.is_file():
        raise SystemExit("✗ memoire/lexique.csv absent : passez --graines")
    graines = {}
    with chemin.open(encoding="utf-8") as f:
        for l in csv.DictReader(f):
            motif = (l.get("motif") or "").split("|")[0]
            if not re.search(r"[\\\[\]()?*+^$]", motif) and l.get("theme") not in graines and motif.strip():
                graines[l["theme"]] = motif.strip()
    return list(graines.values())


def cmd_idees(a, client: U.Client) -> dict:
    lieu, loc, langue = marche(a)
    graines = graines_du_lexique() if a.lexique else [g.strip() for g in (a.graines or "").split(",") if g.strip()]
    if not graines:
        raise SystemExit("✗ aucune graine : --graines \"a, b\" ou --lexique")
    # match_keywords garde la graine dans la requête (longue traîne fidèle au sujet) et pagine ;
    # keyword_suggestions, plus court, sert de voisinage sémantique (--mode proches).
    vues: dict[str, dict] = {}
    for graine in graines[:20]:
        if a.mode == "proches":
            r = client.appel("keyword_suggestions", {"keywords": [graine], "language": langue, "locId": loc})
            items = (r.get("searched_keywords") or []) + (r.get("results") or [])
        else:
            r = client.appel("match_keywords", {"keywords": [graine], "language": langue, "locId": loc,
                                                "limit": a.max})
            items = (r.get("searched_keywords") or []) + (r.get("suggestions") or [])
        for it in items:
            kw = it.get("keyword")
            if kw and kw not in vues:
                vues[kw] = ligne_demande(it)
    lignes = sorted(vues.values(), key=lambda x: -(x["volume"] or 0))
    return {"lieu": lieu, "langue": langue, "graines": graines, "rapports": min(len(graines), 20),
            "lignes": lignes}


def cmd_serp(a, client: U.Client) -> dict:
    lieu, loc, langue = marche(a)
    if not a.mot:
        raise SystemExit("✗ --mot requis")
    serp = lire_serp(client.appel("serp_analysis", {"keyword": a.mot, "language": langue, "locId": loc,
                                                   "limit": 20}))
    pays = next((p for p, l in U.LOC_IDS.items() if l == loc), "fr").lower()
    questions = questions_autocompletion(client.appel("google_suggestions", {
        "keywords": [a.mot], "language": langue, "country": pays}))
    return {"lieu": lieu, "langue": langue, "mot": a.mot, "rapports": 2, "ai_overview": serp["ai_overview"],
            "paa": serp["paa"], "features": serp["features"], "organique": serp["organique"][:10],
            "questions": questions}


def main() -> int:
    charger_env()
    ap = argparse.ArgumentParser(description="Demande de recherche par Ubersuggest")
    sp = ap.add_subparsers(dest="cmd", required=True)
    for nom in ("volumes", "idees", "serp"):
        p = sp.add_parser(nom)
        p.add_argument("--langue", help="fr, en, ar…")
        p.add_argument("--pays", help="code ISO, défaut : projet.pays_cible")
        p.add_argument("--loc-id", type=int, help="locId Ubersuggest, pour un pays hors liste ou une ville")
        p.add_argument("--json", action="store_true")
    sp.choices["volumes"].add_argument("--mots")
    sp.choices["volumes"].add_argument("--fichier")
    sp.choices["volumes"].add_argument("--max", type=int, default=100, help="mots-clés mesurés (un rapport chacun)")
    sp.choices["idees"].add_argument("--graines")
    sp.choices["idees"].add_argument("--lexique", action="store_true", help="graines tirées de memoire/lexique.csv")
    sp.choices["idees"].add_argument("--max", type=int, default=100, help="par graine")
    sp.choices["idees"].add_argument("--mode", choices=["suggestions", "proches"], default="suggestions")
    sp.choices["idees"].add_argument("--ecrire", action="store_true", help="écrit donnees/demande-<langue>-<date>.csv")
    sp.choices["serp"].add_argument("--mot")
    a = ap.parse_args()

    try:
        res = {"volumes": cmd_volumes, "idees": cmd_idees, "serp": cmd_serp}[a.cmd](a, U.Client())
    except ErreurUbersuggest as exc:
        print(f"✗ Ubersuggest : {exc}", file=sys.stderr)
        return 1

    if a.cmd == "idees" and a.ecrire:
        cible = racine_projet() / "donnees" / f"demande-{res['langue']}-{dt.date.today().isoformat()}.csv"
        cible.parent.mkdir(parents=True, exist_ok=True)
        with cible.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["requete", "volume", "kd", "intention", "tendance_an_pct", "page"])
            w.writeheader()
            w.writerows(res["lignes"])
        print(f"  ✓ {cible.relative_to(racine_projet())} · {len(res['lignes'])} requêtes", file=sys.stderr)

    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    elif a.cmd == "serp":
        print(f"\n  « {res['mot']} » · {res['lieu']} · {res['langue']} · "
              f"AI Overview : {'oui' if res['ai_overview'] else 'non'} · "
              f"Autres questions posées : {'oui' if res['paa'] else 'non'}\n")
        for o in res["organique"]:
            print(f"  {o['rang']:>2}. {o['titre']}\n      {o['url']}")
        if res["questions"]:
            print("\n  Questions (autocomplétion Google) :")
            for q in res["questions"][:30]:
                print(f"   - {q}")
    else:
        print(f"\n  {res['lieu']} · {res['langue']} · {len(res['lignes'])} requêtes\n")
        for l in res["lignes"][:40]:
            extra = f"  kd {l['kd']}" if l.get("kd") is not None else ""
            extra += f"  {l['intention']}" if l.get("intention") else ""
            print(f"  {l['volume'] or 0:>8}  {l['requete']}{extra}")
    print(f"\n  Ubersuggest : {res['rapports']} rapport(s) du quota quotidien\n", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
