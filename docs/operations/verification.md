# Vérification finale du projet

Ce document décrit **ce qui a été réellement exécuté** et **ce qui ne l'a pas été**. Il est
volontairement précis sur la distinction : un test écrit n'est pas un test réussi, un
mock n'est pas une intégration.

Dates : audit du dépôt 27 septembre 2026 (étape 15) · phase de validation réelle
27–30 septembre 2026.

---

## Phase de validation réelle — ce qui a pu être prouvé sans base de données

PostgreSQL, Redis, Docker et Git sont absents du poste, et l'installation a été refusée à
la demande de l'exploitant. Trois propriétés ont donc été établies **par des moyens de
contournement qui ne simulent pas le service** :

| Propriété | Moyen | Résultat |
|---|---|---|
| Le schéma correspond au code | DDL des migrations comparé aux 35 modèles SQLAlchemy | **35 tables, 447 colonnes, 74 clés étrangères, 102 index concordants** |
| Le worker atteint l'API interne authentifiée | vrai serveur uvicorn + vrai code de tâche Celery | **anonyme → 401, jeton erroné → 401, jeton worker → 200** |
| La tâche worker se comporte correctement | exécution réelle, retry, échec définitif | **4 requêtes par échec, jamais de succès sur un refus** |

Ces trois preuves utilisent `scripts/check_schema_drift.py` et
`scripts/check_worker_api_link.py`, branchés dans `check-foundation.ps1`.

### Ce que ces preuves ne remplacent pas

Le schéma **produit** par les migrations n'a jamais été appliqué à une base. La concordance
modèles/DDL prouve l'absence de dérive entre le code et le DDL ; elle ne prouve pas que
PostgreSQL accepte ce DDL, ni que les requêtes émises par l'application y trouvent les
lignes attendues. C'est la limite exacte de cette substitution, et elle ne se lève qu'avec une
base réelle.

### Index dupliqués dans les modèles (défaut mineur, non corrigé)

Cinq index sont déclarés deux fois dans les modèles, sur la même colonne que l'index créé par
la migration :

| Modèle | Migration |
|---|---|
| `ix_assistant_citations_chunk` | `ix_assistant_citations_chunk_id` |
| `ix_assistant_citations_source` | `ix_assistant_citations_source_id` |
| `ix_rag_chunks_provenance` | `ix_rag_chunks_provenance_id` |
| `ix_writing_citations_generation` | `ix_writing_citations_generation_id` |
| `ix_writing_generations_section` | `ix_writing_generations_section_id` |

**Gravité : faible.** La colonne est indexée en production, donc aucune requête n'est
pénalisée. Une base créée par `create_all` — celle des tests d'intégration — porterait
cependant deux index sur ces colonnes. `alembic revision --autogenerate` produirait un diff
fictif tant que les noms divergent.

**Non corrigé volontairement** : la correction exige de modifier cinq modèles sans pouvoir la
valider contre une base réelle. Le rapport décrit le défaut ; la décision de le corriger
appartient à l'exploitant.

---

## Audit du dépôt — 27 septembre 2026

## Environnement au moment de l'audit

| Outil | État |
|---|---|
| Docker / Compose | **absent** |
| PostgreSQL (`psql`, `pg_dump`, `pg_restore`) | **absent** |
| Redis | **absent** |
| Celery (binaire) | **absent** |
| `pgserver` (PostgreSQL embarqué) | désinstallé — `initdb` échoue sur ce poste |
| `OPENAI_API_KEY` | absente |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | absents |
| `TEST_DATABASE_URL` | absente |
| Git | **absent** |

Aucun service n'écoutait sur 5432, 6379, 8000 ni 3000.

## Tests réellement exécutés et réussis

| Suite | Commande | Résultat |
|---|---|---|
| Backend complet | `pytest` | **715 passés, 3 ignorés** |
| Backend sans intégration | `pytest -m "not integration"` | 712 passés, 3 ignorés |
| Worker | `pytest` (services/worker) | **5 passés** |
| Frontend | `vitest run` | **12 fichiers / 81 tests** |
| lint backend | `ruff check services/api` | propre |
| lint worker | `ruff check services/worker` | propre |
| lint scripts | `ruff check scripts` | propre |
| byte-compilation | `compileall` | OK |
| dépendances Python | `pip check` | aucune incompatibilité |
| TypeScript | `tsc --noEmit` | 0 erreur |
| ESLint | `eslint .` | 0 erreur |
| build frontend | `next build` | exit 0 |
| audit npm | `npm audit --omit=dev` | **0 vulnérabilité** |
| migrations | `alembic upgrade head --sql` | 829 lignes, sans erreur |
| migrations | `alembic downgrade head:base --sql` | 205 lignes, sans erreur |
| Compose | `check-foundation.ps1` | exit 0 |

Répartition des 715 tests backend par domaine :

| Domaine | Fichier | Tests |
|---|---|---|
| Audit académique | `test_academic_audit.py` | 73 |
| Citations (moteur de styles) | `test_citation_styles.py` | 94 |
| Citations (service) | `test_citations_service.py` | 51 |
| Bibliographie | `test_bibliography.py` | 81 |
| Export PDF/DOCX | `test_export_document.py` | 81 |
| Sécurité (étape 13) | `test_security_stage13.py` | 68 |
| Déploiement et sauvegardes | `test_deployment.py` | 71 |
| Assistant (IA simulée) | `test_assistant_llm.py` | 24 |
| Assistant (pipeline) | `test_assistant_pipeline.py` | 19 |
| Assistant (citations RAG) | `test_assistant_citations.py` | 14 |
| RAG (recherche) | `test_rag_search.py` | 18 |
| RAG (embeddings) | `test_rag_embeddings.py` | 16 |
| RAG (configuration) | `test_rag_config.py` | 15 |
| RAG (découpage) | `test_rag_chunking.py` | 12 |
| RAG (idempotence) | `test_rag_idempotence.py` | 10 |
| RAG (qualité) | `test_rag_quality.py` | 8 |
| Rédaction assistée | `test_writing_assistant.py` | 16 |
| Authentification (API) | `test_auth_api.py` | 12 |
| Sources | `test_sources.py` | 11 |
| Sécurité (authentification) | `test_auth_security.py` | 8 |
| Limiteur de connexion | `test_auth_rate_limit.py` | 1 |
| Rôles de projet | `test_project_roles.py` | 1 |
| Projets (service) | `test_project_service.py` | 3 |
| Projets (API) | `test_project_api.py` | 3 |
| Configuration | `test_config.py` | 3 |
| Santé | `test_health.py` | 2 |

## Tests écrits mais NON exécutés

**24 tests** sont écrits et ignorés, tous dans les trois fichiers marqués `integration`. Motif :
`TEST_DATABASE_URL` absente.

| Fichier | Tests écrits | Dont non exécutés |
|---|---|---|
| `test_auth_integration.py` | 10 | 10 |
| `test_rag_integration.py` | 8 | 8 |
| `test_assistant_integration.py` | 6 | 6 |

Parmi eux, et c'est le point important :

- `test_project_isolation_between_users` — **isolation entre deux utilisateurs**
- `test_source_permissions_and_project_isolation` — **isolation des sources entre projets**
- `test_conversation_of_another_user_is_not_found` — **fuite entre utilisateurs (assistant)**
- `test_conversation_of_another_project_is_not_found`
- `test_assistant_cannot_use_another_project_sources`
- `test_semantic_and_lexical_search_never_leak_another_project`
- `test_every_result_carries_a_complete_provenance_chain`
- `test_reader_cannot_edit_but_editor_can` — **rôles reader/editor**
- `test_editor_role_is_required_for_editor_actions`
- `test_project_roles_are_returned_without_leaking_other_projects`

**La hiérarchie des rôles est testée** (`test_project_roles.py`, 1 test, 7 assertions sur
`has_required_role`). **Son application effective à travers HTTP et la base ne l'est pas** :
ces 24 tests n'ont jamais tourné dans cet environnement.

## Tests impossibles à exécuter faute d'environnement

- Les 24 tests d'intégration ci-dessus (PostgreSQL absent).
- `pg_dump` / `pg_restore` réels : la logique autour est testée avec un `subprocess.run`
  simulé, mais **les outils eux-mêmes n'ont jamais été exécutés**.
- Le cycle sauvegarde → vérification → restauration **contre une base réelle** : jamais fait.
- `docker compose up`, construction d'image, healthchecks réels : Docker absent.
- `docker compose config`, qui est la commande qui aurait validé la fusion des deux fichiers
  Compose : Docker absent.

## Tests nécessitant des credentials externes

- **Intégration OpenAI** : aucun appel réel. `LLM_PROVIDER=mock` par défaut, et tous les tests
  utilisent un fournisseur simulé. Le coût, le rate limiting et la qualité des réponses ne sont
  pas validés.
- **OAuth Google** : le code est complet (PKCE, `state`, `nonce`, vérification de signature),
  mais aucun `GOOGLE_CLIENT_ID` n'était disponible. Le parcours n'a pas été exécuté.

## Vérifications de sécurité exécutées

### Surface publique (requêtes réelles, pas lecture de code)

`scripts/probe_public_surface.py` — 15 routes appelées réellement :

- **11 routes refusent** un appel anonyme en `401` : les 5 `/api/internal`, les 4 `/api/admin`,
  `POST /api/observability/metrics/reset`, `GET /api/observability/security-events`.
- **4 routes publiques par conception** répondent `200` : `/api/observability/metrics`,
  `/api/observability/health/details`, `/health/live`, `/`.
- **Contrôle négatif** : un jeton worker valide franchit bien la même porte, ce qui prouve que
  le `401` observé vient de la décision d'autorisation et non d'une panne.

### Secrets

`scripts/scan_secrets.py` — 307 fichiers analysés, **aucun secret détecté**. Le scanner a été
**mis en échec volontairement** (injection d'une fausse clé `sk-proj-…`) pour prouver qu'il
détecte : il l'a signalée, et le dépôt est revenu propre après retrait.

### Durcissement de la configuration (exécuté)

12 cas testés : une configuration de production valide est acceptée, et 11 configurations
dangereuses sont refusées. Voir `configuration.md` pour le détail.

## Nettoyage final

`scripts/audit_dead_code.py` — **aucun travail inachevé détecté** :

| Contrôle | Résultat |
|---|---|
| Fonctions à corps inerte hors `Protocol` | 0 (13 méthodes de `Protocol` légitimement inertes) |
| Routers jamais inclus | 0 (15 modules inclus, 99 chemins exposés) |
| Appels frontend vers une route absente | 0 (78 appels inspectés) |
| Pages sans navigation | 0 (16 pages) |
| Dépendances déclarées inutilisées | 0 (3 usages indirects expliqués) |

L'outil a été **mis en échec volontairement** deux fois (route frontend inexistante,
dépendance fantôme) pour prouver qu'il détecte. Les trois outils d'audit sont branchés dans
`check-foundation.ps1`.

## Corrections issues de cet audit

| Correction | Effet |
|---|---|
| Le middleware interceptait `HTTPException` et la relançait | un `429` ou un `503` devenait un `500` et perdait `Retry-After` |
| `ErrorActionPreference = "Stop"` dans `check-foundation.ps1` | un `DeprecationWarning` sur stderr faisait échouer tout le script |

## Chaîne de migrations

12 migrations, chaîne linéaire vérifiée, aucune révision dupliquée :

```
0001_initial_schema              -> None
0002_authentication_and_sessions -> 0001
0003_project_workspace           -> 0002
0004_source_library              -> 0003
0005_academic_rag                -> 0004
0006_assistant                   -> 0005
0007_writing_assistant           -> 0006
0008_bibliography                -> 0007
0009_citations                   -> 0008
0010_document_exports            -> 0009
0011_academic_audit              -> 0010
0012_security_admin              -> 0011   (head)
```

Symétrie SQL vérifiée : 36 `CREATE TABLE` dans l'upgrade, 35 `DROP TABLE` dans le downgrade
(l'écart de 1 correspond à la table de journal Alembic, qui n'est pas droppée) ; 21 `ALTER
TABLE` de part et d'autre.

## Ce que l'audit n'a pas pu établir

- Que le schéma produit par les migrations correspond à ce que le code exécute : sans base,
  les requêtes n'ont pas été émises.
- Que la hiérarchie des rôles est **appliquée** en HTTP et en base.
- Que l'isolation entre deux utilisateurs résiste réellement à une tentative d'accès.
- Que `pg_dump` produit un archive restaurable, et que `pg_restore` la restaure.
- Que le RAG indexed et interrogé sur des données réelles produit des résultats pertinents.
- Que l'export PDF et DOCX s'ouvre correctement dans un lecteur : les fichiers sont produits
  et vérifiés structurellement, mais pas ouverts par un lecteur humain ou tiers.
