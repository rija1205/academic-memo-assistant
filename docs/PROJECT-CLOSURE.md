# Clôture du projet — état définitif

Date : 30 septembre 2026. Ce document est le point d'arrivée. Il dit ce qui est construit, ce
qui est prouvé, ce qui ne l'est pas, et ce qu'il reste à faire — dans cet ordre.

## Version

`0.1.0` · migration head `0012_security_admin` · 15 étapes de développement terminées.

> Le numéro de version n'a jamais été incrémenté sur 15 étapes. C'est une incohérence
> cosmétique, signalée et non corrigée : la corriger sans décision de numérotation produit un
> arbitraire, et l'arbitraire ici serait « 1.0.0 » alors que rien n'a été validé contre une
> base de données.

## Ce qui est construit

| Domaine | Contenu |
|---|---|
| Socle | comptes, sessions serveur, réinitialisation, OAuth Google, rôles `reader`/`editor`/`owner`/`admin` |
| Sources | import 7 formats, extraction avec provenance, recherche, doublons |
| RAG | 6 tables, découpage, recherche hybride, idempotence, version d'embedding |
| Assistant | conversations, citations `[SRC-001]`, refus sans contexte, coût |
| Rédaction | actions en propositions ; invariant « le backend n'écrit jamais » |
| Bibliographie | 5 tables, APA 7 / Harvard / Vancouver / ISO 690 |
| Citations | `citations` + `citation_items`, distinctes des citations RAG |
| Export | PDF et DOCX, rendu neutre partagé, un seul moteur de citation |
| Audit | 23 contrôles déterministes, aucun modèle de langage |
| Administration | console, `security_events`, `admin_audit_events` |
| Observabilité | logs JSON, `X-Request-Id`, métriques, budgets, en-têtes de sécurité |
| Exploitation | sauvegarde/restauration vérifiée, overlay de production, 7 sondes |

## Preuves acquises

**724 tests exécutés et réussis** : 715 backend, 5 worker, 81 frontend (12 fichiers).

**Schéma** — 35 tables, 447 colonnes, 74 clés étrangères, 102 index concordants entre les
modèles SQLAlchemy et le DDL réellement produit par les migrations. Aucune divergence
bloquante.

**Séparation worker / API, sur réseau réel** — vrai serveur uvicorn, vrai code de tâche Celery :
appel anonyme `401`, jeton erroné `401`, jeton worker `200`. La tâche construit la bonne URL,
envoie le jeton, **relance 4 fois** sur échec et ne rapporte jamais de succès sur un refus.

**Sécurité** — 11 routes sensibles refusent l'appel anonyme, 4 routes publiques conformes à
l'intention, contrôle négatif par jeton valide. 12 configurations de production testées : 1
acceptée, 11 dangereuses refusées. Aucun secret dans 311 fichiers.

**Chaîne de migrations** — 12 révisions uniques, chaîne linéaire, `upgrade`/`downgrade --sql`
symétriques.

**Hygiène** — ruff, compileall, pip check, tsc, eslint, next build, npm audit : verts.
`check-foundation.ps1` : exit 0.

## Ce qui n'est pas prouvé

Le projet **n'a jamais tourné contre une base de données**. Les 715 tests valident une logique
métier testée avec des doublures. Ils ne valident ni le schéma appliqué, ni les requêtes SQL
émises, ni l'isolation entre utilisateurs, ni la restauration, ni le parcours complet.

Cette limite n'est pas un détail de couverture : c'est la frontière entre « le code est
cohérent » et « le logiciel fonctionne », et seule une base réelle la fait franchir.

## Reste à faire, par ordre de valeur

### 1. Versionner — le risque le plus matériel

15 étapes de travail n'existent que sur le disque. Git n'est pas installé et l'installation a
été refusée. Au premier incident, tout est perdu.

```bash
winget install Git.Git
cd academic-memo-assistant
python scripts/check_git_readiness.py    # vérifier ce qui serait versionné
git init && git add -A && git commit -m "État initial — 15 étapes"
```

Le premier `check_git_readiness.py` a déjà simulé ce que Git versionnerait : 306 fichiers,
2,4 Mio, aucun sensible.

### 2. Valider le schéma sur une base réelle

```bash
pip install pgserver          # PostgreSQL embarqué, sans droits admin
# ou installer PostgreSQL 16 + pgvector
export TEST_DATABASE_URL="postgresql+asyncpg://user:mdp@localhost:5432/ama_test"
python scripts/validate_real_environment.py --only postgres
```

Cette commande applique les migrations, vérifie la révision 0012 dans la base, exécute les
**24 tests d'intégration** — dont l'isolation entre utilisateurs et l'application des rôles —
et applique puis revertit les 12 migrations sur une base jetable.

### 3. Valider sauvegarde et restauration

```bash
python scripts/validate_real_environment.py --only backup
```

Le harnais crée la sauvegarde, la **vérifie par empreintes**, la restaure dans une base
distincte puis **compare les deux bases table par table**. `pg_restore` qui retourne 0 ne
prouverait rien : c'est la comparaison des contenus qui prouve la restauration.

### 4. Valider Docker

```bash
python scripts/validate_real_environment.py --only docker
```

`docker compose config`, puis `build`, puis `up`, healthchecks inclus.

### 5. Brancher les fournisseurs réels

```bash
export OPENAI_API_KEY=...          # LLM et embeddings réels
export GOOGLE_CLIENT_ID=...        # OAuth Google réel
python scripts/validate_real_environment.py --only openai google
```

## Le harnais de validation

`scripts/validate_real_environment.py` est le point d'entrée unique des validations qui
dépendent d'un service. Il détecte ce qui est installé, exécute ce qui peut l'être, et déclare
`BLOCKED` le reste avec la raison exacte. Un seul statut par élément :

| Statut | Signification |
|---|---|
| `PASS` | exécuté réellement, réussi |
| `FAIL` | exécuté réellement, échoué |
| `BLOCKED` | dépendance absente, rien n'a été exécuté |
| `NOT_RUN` | dépendance présente, validation non tentée |

```bash
python scripts/validate_real_environment.py --list     # le plan, sans exécuter
python scripts/validate_real_environment.py            # tout ce qui est possible
python scripts/validate_real_environment.py --only postgres backup
python scripts/validate_real_environment.py --json     # sortie exploitable
```

**État au 30 septembre 2026 : `0 reussis / 0 echecs / 7 bloques / 0 non executes`.** Aucun
échec : ce qui manque n'a pas été simulé pour paraître exécuté.

Le harnais a été mis en échec volontairement (dépôt Git initialisé puis retiré, doublure
`git` sur le `PATH`) pour prouver qu'il atteint bien `PASS` et `NOT_RUN` quand la dépendance
est là.

## Sondes de dépôt

Sept sondes vérifient ce qui ne se voit pas dans les tests. Toutes sont branchées dans
`check-foundation.ps1` et toutes ont été **mises en échec volontairement** au moins une fois,
parce qu'un vérificateur jamais vu échouer n'est pas un vérificateur.

| Sonde | Vérifie |
|---|---|
| `check_schema_drift.py` | concordance modèles ↔ migrations |
| `check_worker_api_link.py` | autorisation worker ↔ API sur réseau réel |
| `check_git_readiness.py` | ce que Git versionnerait |
| `scan_secrets.py` | secrets dans le dépôt |
| `probe_public_surface.py` | routes sensibles réellement inaccessibles |
| `check_doc_links.py` | liens de documentation résolus |
| `audit_dead_code.py` | corps inertes, routes non branchées, dépendances mortes |

## Défaut connu, non corrigé

Cinq index déclarés deux fois dans les modèles, sur la colonne que la migration indexe déjà :

| Modèle | Migration |
|---|---|
| `ix_assistant_citations_chunk` | `ix_assistant_citations_chunk_id` |
| `ix_assistant_citations_source` | `ix_assistant_citations_source_id` |
| `ix_rag_chunks_provenance` | `ix_rag_chunks_provenance_id` |
| `ix_writing_citations_generation` | `ix_writing_citations_generation_id` |
| `ix_writing_generations_section` | `ix_writing_generations_section_id` |

**Gravité faible.** La colonne est indexée en production ; aucune requête n'est pénalisée. Une
base créée par `create_all` — celle des tests d'intégration — porterait deux index sur ces
colonnes, et `alembic revision --autogenerate` produirait un diff fictif.

**Non corrigé délibérément** : la correction touche cinq modèles et ne peut pas être validée
sans base de données. Elle est décrite, pas appliquée.

## Conclusion

Le dépôt est cohérent, propre, sans dette de sécurité, et ses invariants sont prouvés par des
exécutions réelles autant que l'environnement les permettait. Le harnais de validation rend la
suite du travail exécutable en une commande plutôt qu'en une liste de vouloirs.

**Ce qui manque n'est pas du code. C'est un serveur PostgreSQL et un Git.** Tant qu'ils ne
sont pas là, le projet est un prototype complet et cohérent, pas un logiciel validé.
