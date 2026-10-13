#!/usr/bin/env python3
"""Ubersuggest sans connecteur — le serveur MCP officiel appelé en direct, donc aussi dans une routine.

    python3 ubersuggest.py connexion                      # affiche le lien de connexion (une fois)
    python3 ubersuggest.py connexion --retour "http://localhost:8765/callback?code=…"
    python3 ubersuggest.py statut                         # compte, plan, rapports restants aujourd'hui
    python3 ubersuggest.py outils                         # les outils du serveur et leurs paramètres
    python3 ubersuggest.py appel keyword_overview '{"keyword": "…", "language": "fr", "locId": 2250}'

Ubersuggest n'a pas d'API REST : son seul accès programmatique est le
serveur MCP officiel (https://ubersuggest-mcp.neilpatelapi.com/mcp), en
OAuth. On s'y connecte une fois dans un navigateur ; le jeton de
renouvellement est ensuite gardé dans .seo-decupler/ubersuggest.json (le
projet, jamais le plugin) ou, pour une routine, dans UBERSUGGEST_REFRESH_TOKEN.

Les appels consomment le quota de l'application web : un rapport par sujet
distinct (mot-clé, domaine) et par jour, quel que soit le nombre d'appels.
Sans dépendance.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _projet import charger_env, dossier_etat  # noqa: E402

SERVEUR = "https://ubersuggest-mcp.neilpatelapi.com"
MCP = f"{SERVEUR}/mcp"
CLIENT_ID = "ubersuggest-mcp"            # client public du serveur, sans secret
RETOUR = "http://localhost:8765/callback"
PORTEES = "profile domain keywords serp backlinks site_audit content projects utility"
VERSION_MCP = "2025-06-18"

# Codes pays ISO → locId Google (ceux d'Ubersuggest). Les marchés courants ;
# location_suggest pour les autres.
LOC_IDS = {"FR": 2250, "BE": 2056, "CH": 2756, "CA": 2124, "LU": 2442, "MA": 2504, "TN": 2788,
           "DZ": 2012, "SN": 2686, "CI": 2384, "SA": 2682, "AE": 2784, "QA": 2634, "KW": 2414,
           "EG": 2818, "US": 2840, "GB": 2826, "DE": 2276, "ES": 2724, "IT": 2380}


class ErreurUbersuggest(RuntimeError):
    pass


# ─── Jetons ───────────────────────────────────────────────────────

def fichier_jetons() -> Path:
    return dossier_etat("ubersuggest.json")


def lire_jetons() -> dict:
    f = fichier_jetons()
    if f.is_file():
        return json.loads(f.read_text(encoding="utf-8"))
    env = os.environ.get("UBERSUGGEST_REFRESH_TOKEN", "").strip()
    return {"refresh_token": env, "source": "env"} if env else {}


def ecrire_jetons(jetons: dict) -> None:
    f = fichier_jetons()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(jetons, indent=2), encoding="utf-8")
    try:
        f.chmod(0o600)
    except OSError:
        pass


def _post_formulaire(url: str, champs: dict) -> dict:
    req = urllib.request.Request(url, data=urllib.parse.urlencode(champs).encode(), method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=30) as rep:
            return json.loads(rep.read())
    except urllib.error.HTTPError as exc:
        corps = exc.read().decode(errors="replace")[:200]
        raise ErreurUbersuggest(f"HTTP {exc.code} sur {url.rsplit('/', 1)[-1]} : {corps}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ErreurUbersuggest(str(exc)[:120]) from None


def _memoriser(reponse: dict, ancien: dict) -> dict:
    jetons = {
        "access_token": reponse["access_token"],
        "expire_a": time.time() + float(reponse.get("expires_in") or 3600) - 60,
        # Le serveur peut renvoyer un nouveau jeton de renouvellement ; sinon l'ancien reste valable.
        "refresh_token": reponse.get("refresh_token") or ancien.get("refresh_token", ""),
    }
    if ancien.get("source") == "env" and jetons["refresh_token"] != ancien.get("refresh_token"):
        print("⚠ Ubersuggest a renouvelé le jeton : UBERSUGGEST_REFRESH_TOKEN est périmé, "
              "le nouveau est dans .seo-decupler/ubersuggest.json", file=sys.stderr)
    ecrire_jetons(jetons)
    return jetons


def jeton_acces() -> str:
    jetons = lire_jetons()
    if jetons.get("access_token") and jetons.get("expire_a", 0) > time.time():
        return jetons["access_token"]
    if not jetons.get("refresh_token"):
        raise ErreurUbersuggest("pas connecté : lancez `ubersuggest.py connexion` "
                                "(ou définissez UBERSUGGEST_REFRESH_TOKEN)")
    rep = _post_formulaire(f"{SERVEUR}/token", {"grant_type": "refresh_token", "client_id": CLIENT_ID,
                                                "refresh_token": jetons["refresh_token"]})
    return _memoriser(rep, jetons)["access_token"]


# ─── MCP en HTTP ──────────────────────────────────────────────────

def _rpc(corps: dict, jeton: str, session: str = "") -> tuple[dict | None, str]:
    entetes = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
               "Authorization": f"Bearer {jeton}", "MCP-Protocol-Version": VERSION_MCP}
    if session:
        entetes["Mcp-Session-Id"] = session
    req = urllib.request.Request(MCP, data=json.dumps(corps).encode(), method="POST", headers=entetes)
    try:
        with urllib.request.urlopen(req, timeout=180) as rep:
            session = rep.headers.get("Mcp-Session-Id") or session
            brut = rep.read().decode("utf-8")
            if "text/event-stream" in (rep.headers.get("Content-Type") or ""):
                donnees = [l[5:].strip() for l in brut.splitlines() if l.startswith("data:")]
                brut = donnees[-1] if donnees else ""
    except urllib.error.HTTPError as exc:
        raise ErreurUbersuggest(f"HTTP {exc.code} : {exc.read().decode(errors='replace')[:200]}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ErreurUbersuggest(str(exc)[:120]) from None
    if not brut.strip():
        return None, session
    message = json.loads(brut)
    if "error" in message:
        raise ErreurUbersuggest(f"{message['error'].get('code')} {message['error'].get('message')}")
    return message.get("result"), session


class Client:
    """Une session MCP : initialisée au premier appel, réutilisée ensuite."""

    def __init__(self):
        self.jeton = ""
        self.session = ""
        self.n = 0

    def _ouvrir(self) -> None:
        if self.session or self.n:
            return
        self.jeton = jeton_acces()
        self.n = 1
        _, self.session = _rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": VERSION_MCP, "capabilities": {},
            "clientInfo": {"name": "decupler-seo", "version": "1"}}}, self.jeton)
        _rpc({"jsonrpc": "2.0", "method": "notifications/initialized"}, self.jeton, self.session)

    def requete(self, methode: str, params: dict) -> dict:
        self._ouvrir()
        self.n += 1
        res, _ = _rpc({"jsonrpc": "2.0", "id": self.n, "method": methode, "params": params},
                      self.jeton, self.session)
        return res or {}

    def outils(self) -> list[dict]:
        return self.requete("tools/list", {}).get("tools", [])

    def appel(self, outil: str, arguments: dict | None = None) -> dict | list:
        """Appelle un outil et renvoie sa réponse JSON décodée.

        Une erreur métier (quota épuisé, compte non connecté, paramètre
        refusé) lève ErreurUbersuggest avec le message du serveur.
        """
        res = self.requete("tools/call", {"name": outil, "arguments": arguments or {}})
        texte = "\n".join(c.get("text", "") for c in res.get("content", []) if c.get("type") == "text")
        if res.get("isError"):
            raise ErreurUbersuggest(f"{outil} : {texte[:300]}")
        if "structuredContent" in res:
            return res["structuredContent"]
        try:
            return json.loads(texte)
        except ValueError:
            return {"texte": texte}

    def appel_complet(self, outil: str, arguments: dict | None = None, essais: int = 6,
                      pause: float = 5.0) -> dict | list:
        """Comme appel(), en relançant tant que le serveur répond `done: false` (calcul en cours)."""
        for i in range(essais):
            rep = self.appel(outil, arguments)
            if not (isinstance(rep, dict) and rep.get("done") is False):
                return rep
            time.sleep(pause * (i + 1))
        raise ErreurUbersuggest(f"{outil} : toujours en cours de calcul, relancez plus tard")


def loc_id(pays: str) -> int:
    pays = (pays or "FR").upper()
    if pays not in LOC_IDS:
        raise SystemExit(f"✗ pays {pays} sans locId connu : cherchez-le avec "
                         f"`ubersuggest.py appel location_suggest '{{\"query\": \"…\"}}'`")
    return LOC_IDS[pays]


# ─── Commandes ────────────────────────────────────────────────────

def cmd_connexion(a) -> int:
    attente = dossier_etat("ubersuggest-connexion.json")
    if not a.retour:
        verificateur = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
        defi = base64.urlsafe_b64encode(hashlib.sha256(verificateur.encode()).digest()).rstrip(b"=").decode()
        etat = secrets.token_urlsafe(16)
        attente.parent.mkdir(parents=True, exist_ok=True)
        attente.write_text(json.dumps({"verificateur": verificateur, "etat": etat}), encoding="utf-8")
        lien = f"{SERVEUR}/authorize?" + urllib.parse.urlencode({
            "response_type": "code", "client_id": CLIENT_ID, "redirect_uri": RETOUR, "scope": PORTEES,
            "state": etat, "code_challenge": defi, "code_challenge_method": "S256"})
        print("1. Ouvrez ce lien et connectez-vous à Ubersuggest :\n")
        print(f"   {lien}\n")
        print("2. Le navigateur finit sur une page localhost qui ne s'affiche pas : c'est normal.")
        print("   Copiez l'adresse complète de cette page, puis :\n")
        print('   python3 ubersuggest.py connexion --retour "<adresse copiée>"')
        return 0
    if not attente.is_file():
        raise SystemExit("✗ aucune connexion en cours : lancez d'abord `ubersuggest.py connexion`")
    en_cours = json.loads(attente.read_text(encoding="utf-8"))
    params = urllib.parse.parse_qs(urllib.parse.urlparse(a.retour).query)
    if params.get("error"):
        raise SystemExit(f"✗ connexion refusée : {params['error'][0]}")
    if params.get("state", [""])[0] != en_cours["etat"]:
        raise SystemExit("✗ adresse d'une autre tentative : relancez `ubersuggest.py connexion`")
    rep = _post_formulaire(f"{SERVEUR}/token", {
        "grant_type": "authorization_code", "client_id": CLIENT_ID, "code": params["code"][0],
        "redirect_uri": RETOUR, "code_verifier": en_cours["verificateur"]})
    _memoriser(rep, {})
    attente.unlink()
    compte = Client().appel("auth_status")
    print(f"✓ connecté : {compte.get('email')} ({compte.get('tier')})")
    print(f"  jeton gardé dans {fichier_jetons()}")
    print("  Pour une routine : copiez son refresh_token dans le secret UBERSUGGEST_REFRESH_TOKEN.")
    return 0


def cmd_statut(a) -> int:
    c = Client()
    compte = c.appel("auth_status")
    limites = c.appel("user_limits")
    rapports = limites.get("usage", {}).get("account", {}).get("reports", {})
    resultat = {"email": compte.get("email"), "plan": compte.get("tier"),
                "rapports_utilises": rapports.get("used"), "rapports_par_jour": rapports.get("limit")}
    if a.json:
        print(json.dumps(resultat, ensure_ascii=False, indent=2))
    else:
        print(f"✓ {resultat['email']} · plan {resultat['plan']} · "
              f"rapports aujourd'hui : {resultat['rapports_utilises']}/{resultat['rapports_par_jour']}")
    return 0


def cmd_outils(a) -> int:
    for o in Client().outils():
        props = o.get("inputSchema", {}).get("properties", {})
        requis = set(o.get("inputSchema", {}).get("required", []))
        params = ", ".join(f"{k}{'*' if k in requis else ''}" for k in props)
        print(f"- {o['name']}({params})")
    return 0


def cmd_appel(a) -> int:
    arguments = json.loads(a.arguments) if a.arguments else {}
    print(json.dumps(Client().appel_complet(a.outil, arguments), ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    charger_env()
    p = argparse.ArgumentParser(description="Ubersuggest par son serveur MCP officiel, sans connecteur.")
    sous = p.add_subparsers(dest="commande", required=True)
    c = sous.add_parser("connexion", help="se connecter une fois (OAuth dans le navigateur)")
    c.add_argument("--retour", help="adresse localhost complète sur laquelle le navigateur a fini")
    c.set_defaults(f=cmd_connexion)
    s = sous.add_parser("statut", help="compte, plan et rapports restants aujourd'hui")
    s.add_argument("--json", action="store_true")
    s.set_defaults(f=cmd_statut)
    sous.add_parser("outils", help="les outils du serveur").set_defaults(f=cmd_outils)
    ap = sous.add_parser("appel", help="appeler un outil avec des arguments JSON")
    ap.add_argument("outil")
    ap.add_argument("arguments", nargs="?", default="")
    ap.set_defaults(f=cmd_appel)
    a = p.parse_args()
    try:
        return a.f(a)
    except ErreurUbersuggest as exc:
        print(f"✗ Ubersuggest : {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
