# Passage à Ubersuggest — ce qui a été fait et pourquoi (13 octobre 2026)

Résumé de la session de travail qui a produit la version 3.11.0, pour la
reprendre dans un autre Codespace sans rien perdre.

## La décision

Toute la donnée marché passe par **Ubersuggest** (compte avec plan lifetime,
« tier2 » : 300 rapports par jour, 7 projets). **DataForSEO, Ahrefs et
Semrush sont supprimés** du dépôt : MCP, variables, scripts, skills, docs.
Choix assumé : cette version du plugin est personnelle, elle ne vise pas à
rester compatible avec ces trois outils.

## Ce qu'on a vérifié sur Ubersuggest

| Question | Réponse vérifiée |
|---|---|
| API ? | Pas d'API REST à clé (le centre d'aide le confirme). Le seul accès programmatique est le **serveur MCP officiel** `https://ubersuggest-mcp.neilpatelapi.com/mcp`, en OAuth (client public `ubersuggest-mcp`, PKCE, sans secret). |
| Compris dans un compte lifetime ? | Oui : les appels MCP consomment le même quota que l'application web (un rapport par mot-clé ou domaine distinct et par jour), sans limite propre au MCP. |
| Utilisable depuis un script ? | Oui, testé : `scripts/ubersuggest.py` s'y connecte et appelle les outils. |
| Utilisable dans une routine cloud ? | **Pas par un secret fixe** : le jeton de renouvellement change à chaque usage et l'ancien est refusé (`invalid_grant`). Le jeton d'accès dure 48 h. Dans une routine, c'est le **connecteur claude.ai** qui fait les appels ; les réponses enregistrées passent aux scripts. |
| AI Overview ? | `serp_analysis` dit s'il est présent (`type: ai_overview`), **sans son texte ni ses sources**. L'AI Search Visibility (`brand_prompts`, `brand_visibility_overview`, `provider: google_aio`) mesure la présence de la marque dans ChatGPT, Gemini et les AI Overviews. |
| PAA ? | Présence seulement (`type: people_also_ask`). Les questions viennent de `google_suggestions` (groupe `questions`, autocomplétion Google). |
| Spam score ? | Oui, champ `spam_score` sur chaque backlink, **mais peu discriminant** : 7 (ou vide) sur des pages PBN évidentes, de 2 à 28 sur des articles invités normaux. `liens.py` le combine avec le vocabulaire des réseaux de liens. |
| Liste complète des domaines référents ? | Oui : `backlinks` avec `one_per_domain: true`, paginé par `offset` (328 sur 328 pour le site testé). |
| Limites cachées | Après 4 pages de 100 backlinks enchaînées, les outils de backlinks répondent **403** au script pendant plusieurs heures (le connecteur claude.ai, lui, continue). `domain_overview` n'y est pas soumis. |
| Pas de volume en lot | `keyword_overview` mesure un mot-clé par appel, donc un rapport par mot-clé. |

## Ce qui a changé dans le dépôt (version 3.11.0)

- **`scripts/ubersuggest.py`** (nouveau) : `connexion` (OAuth une fois, jeton
  dans `.seo-decupler/ubersuggest.json`, ignoré par git), `statut` (rapports
  restants aujourd'hui), `outils`, `appel <outil> '<json>'`.
- **`demande.py`** : `volumes` (keyword_overview : volume, KD, intention,
  tendance sur un an), `idees` (match_keywords ; `--mode proches` :
  keyword_suggestions), `serp` (présence AI Overview et PAA, questions).
  `--loc-id` remplace `--lieu`.
- **`serp_concurrents.py`** : SERP Ubersuggest (autorité et clics estimés),
  questions de l'autocomplétion. `--serp-json` lit une réponse de
  `serp_analysis` enregistrée ; `--questions` accepte la réponse de
  `google_suggestions`. `--repli-dataforseo` supprimé : une page illisible se
  relève avec Firecrawl (`--pages-json`).
- **`liens.py`** : tous les domaines référents, spam par vocabulaire
  (domaine, titre, ancre) puis par score ; pause de 10 s entre les pages ;
  `resume` passe par `domain_overview`.
- **`cartographie.py mensuel --volumes`** : volume et KD par Ubersuggest.
- **`doctor.py`**, **`.mcp.json`** (13 → 9 MCP), **`config/.env.example`**,
  20 skills, l'agent `seo-data`, la commande `seo-brief`, les SOP, `docs/MCP.md`
  (section Ubersuggest complète), `docs/DEPANNAGE.md`, README.
- **Gabarit de projet** : `routines/contenu.md` prend la SERP par le
  connecteur ; `ROUTINES.md` dit d'inclure le connecteur Ubersuggest.
- Tests : 419, tous verts (`tests/test_ubersuggest.py` nouveau).

## Les dépôts

- `francois208/SEO-Decupler-perso` — **privé, le dépôt de travail désormais.**
- `francois208/FG-decupler-seo` — ancien fork **public** de Décupler, à
  archiver ou supprimer (un fork d'un dépôt public ne peut pas devenir privé).
- `NathanFenina/decupler-seo` — le plugin d'origine. À garder comme remote
  `upstream` pour récupérer ses mises à jour (attendre des conflits sur les
  fichiers modifiés ici) :
  `git remote add upstream https://github.com/NathanFenina/decupler-seo.git`

## À faire dans le nouveau Codespace

1. `git log --oneline -3` : la version 3.11.0 doit être là.
2. `git remote add upstream https://github.com/NathanFenina/decupler-seo.git`
3. Reconnecter les scripts à Ubersuggest :
   `python3 scripts/ubersuggest.py connexion`, ouvrir le lien, copier
   l'adresse `localhost` finale, puis `connexion --retour "<adresse>"`, et
   `python3 scripts/ubersuggest.py statut`.
4. Vérifier que le connecteur claude.ai Ubersuggest est visible dans la
   session (`/mcp`).
5. Essayer en réel `liens.py domaines --cible <domaine>` : la version finale
   n'a pas pu tourner à cause du 403 sur les backlinks (testée seulement par
   les tests unitaires). Idem pour `cartographie.py mensuel --volumes`.

## Remarques sur le compte Ubersuggest

- Deux projets suivis : copeauetbarbotine.fr et fleursdecoeur.fr (France,
  `locId` 2250).
- La marque suivie dans l'AI Search Visibility du projet
  copeauetbarbotine.fr s'appelle « Fleurs de coeur » : probablement une
  erreur de configuration, à corriger dans Ubersuggest.
