# Academic Memo Assistant

Monorepo d'un assistant de recherche et de rédaction académique fondé sur les sources.

L'application accompagne un mémoire de bout en bout : importer des sources, les interroger,
rédiger avec une assistance qui **propose** sans jamais écrire à la place de l'auteur,
citer selon une norme choisie, exporter en PDF et DOCX, et vérifier la cohérence académique
avant la soutenance.

> **Principe directeur : l'IA propose, l'auteur décide.**
> Aucun texte du modèle n'est écrit directement dans le mémoire. L'export ne contient jamais
> une reformulation non validée. L'audit signale, il ne réécrit pas.

## État du projet

Les 15 étapes du cahier des charges sont terminées. La dernière est un audit : elle a
identifié deux défauts réels, tous deux corrigés, et consigné ce qui n'a pas pu être vérifié.

**Le projet n'est pas déployé en production et n'a jamais été exécuté contre un PostgreSQL
réel.** Ce qui est établi et ce qui ne l'est pas est détaillé sans ambiguïté dans
[`docs/operations/verification.md`](docs/operations/verification.md).

| Étape | Contenu |
|---|---|
| 1–2 | Fondation du monolithe modulaire, authentification, sessions |
| 3 | Mémoires et espace de travail |
| 4 | Bibliothèque de sources |
| 5 | Import et extraction avec provenance |
| 6 | RAG académique |
| 7 | Assistant de recherche |
| 8 | Assistant de rédaction |
| 9 | Bibliographie |
| 10 | Citations académiques (APA 7, Harvard, Vancouver, ISO 690) |
| 11 | Export PDF et DOCX |
| 12 | Audit académique et préparation de soutenance |
| 13 | Sécurité, administration, observabilité |
| 14 | Déploiement, sauvegardes et restauration, documentation |
| 15 | Vérification finale et audit du dépôt |

## Fonctionnalités

**Sources.** Import de PDF, DOCX, TXT, Markdown, CSV, XLSX et images ; extraction avec
provenance traçable jusqu'au fragment de texte d'origine ; recherche locale.

**RAG.** Indexation par fragments, recherche hybride, réponses citées `[SRC-001]` reliées à
leur source. Les citations du RAG (`assistant_citations`) sont distinctes des citations
académiques (`citations`) : les deux notions ne sont jamais confondues.

**Assistant et rédaction.** Actions suggérées, jamais appliquées automatiquement. Les coûts
et les quotas sont partagés entre l'assistant et la rédaction.

**Bibliographie et citations.** Styles APA 7, Harvard, Vancouver et ISO 690 numérique, avec
numérotation par ordre de première citation. Un seul moteur de citation, utilisé aussi bien
par l'interface que par les exports.

**Export.** PDF et DOCX à partir d'un modèle de rendu neutre : couverture, sommaire, listes
des figures et tableaux, pagination romaine puis arabe, en-tête courant, bibliographie puis
annexes. Les images distantes sont refusées par défaut (protection SSRF).

**Audit académique.** 23 contrôles déterministes — **aucun modèle de langage n'est
interrogé** — dont statistiques du mémoire, préparation de soutenance, historique et
tendance. Un audit signale ; il n'invente ni ne réécrit. Étiquettes canoniques :
`Non renseigné`, `À vérifier`, `Source insuffisante`.

**Administration.** Console `/admin`, journal de sécurité, événements d'administration,
suspension de comptes. `is_admin` vaut `false` par défaut : le premier administrateur est
accordé explicitement (voir `docs/operations/installation.md`).

**Observabilité.** Journalisation structurée avec `X-Request-Id`, métriques
`/api/observability/metrics`, budgets de requêtes par catégorie, en-têtes CSP,
Permissions-Policy, COOP, CORP et HSTS.

## Architecture

```
apps/web            Next.js 15, React 19, TypeScript — 16 pages, éditeur Tiptap
services/api        FastAPI, SQLAlchemy, Alembic — 99 routes / 115 opérations
services/worker     Celery — extraction, embeddings, RAG
packages/contracts  contrats API et documentation OpenAPI
infra/docker        images Docker et initialisation PostgreSQL
scripts             outillage d'exploitation (sauvegarde, amorçage admin, contrôles)
docs                architecture, exploitation, sécurité, décisions
```

Un **monolithe modulaire** assumé : une seule application déployable, des modules qui ne se
connaissent pas par l'intérieur. Voir `docs/architecture/adr/0001-modular-monolith.md`.

## Démarrage rapide

Avec Docker :

```bash
cp .env.example .env
# renseigner SECRET_KEY et POSTGRES_PASSWORD
docker compose up -d
curl http://localhost:8000/health/ready
```

Puis <http://localhost:3000>.

Installation détaillée, mode développement, dépannage :
**[`docs/operations/installation.md`](docs/operations/installation.md)**.

## Configuration

Toutes les variables sont décrites dans `.env.example`, section par section, avec l'étape
qui les a introduites. Les plus structurantes :

| Variable | Défaut | Rôle |
|---|---|---|
| `APP_ENV` | `development` | En `production`, `/docs` et `/openapi.json` sont désactivés |
| `LLM_PROVIDER` | `mock` | La production **refuse** `mock` |
| `EMBEDDING_PROVIDER` | `mock` | La production **refuse** `mock` |
| `SECURE_COOKIES` | `false` | `true` derrière un proxy TLS |
| `RATE_LIMIT_FAIL_CLOSED` | `true` | Redis injoignable ⇒ `503` plutôt qu'un service ouvert |
| `EXPORT_ALLOW_REMOTE_IMAGES` | `false` | Les images distantes sont refusées (SSRF) |

## Exploitation

- **Sauvegarde et restauration** — [`docs/operations/backup-restore.md`](docs/operations/backup-restore.md)
- **Déploiement en production** — [`docs/operations/deployment.md`](docs/operations/deployment.md)
- **Contrôles du dépôt** — `powershell -ExecutionPolicy Bypass -File scripts\check-foundation.ps1`

```bash
python scripts/backup.py create --root backups --storage-path storage/uploads
python scripts/backup.py verify --root backups --directory backups/<sauvegarde>
```

Une sauvegarde est accompagnée d'un manifeste de SHA-256. Une restauration refuse de s'exécuter
si la vérification échoue, et il n'existe aucun drapeau pour contourner ce refus.

## Valider sur un environnement réel

Les validations qui dépendent d'un service — PostgreSQL, Redis, Docker, Git, OpenAI, Google —
ont un point d'entrée unique :

```bash
python scripts/validate_real_environment.py --list    # le plan, sans exécuter
python scripts/validate_real_environment.py           # tout ce qui est possible
python scripts/validate_real_environment.py --only postgres backup
```

Le harnais détecte ce qui est installé, exécute ce qui peut l'être, et déclare `BLOCKED` le
reste avec la raison exacte. **Il ne simule rien** : `PASS` signifie que la commande a
réellement tourné. Le jour où un PostgreSQL est disponible, une seule commande applique les
migrations, lit la révision en base, exécute les 24 tests d'intégration, valide un cycle
sauvegarde/restauration comparé table par table, puis applique et revertit les migrations.

État actuel : `0 reussis / 0 echecs / 7 bloques`. Aucun échec — ce qui manque n'a pas été
simulé pour paraître exécuté. Voir
[`docs/PROJECT-CLOSURE.md`](docs/PROJECT-CLOSURE.md).

## Base de données

12 migrations, de `0001_initial_schema` à `0012_security_admin` (head).

```bash
alembic upgrade head      # appliquer
alembic downgrade -1      # annuler la dernière
alembic current           # révision courante
```

Les migrations ne sont jamais modifiées après coup : toute évolution crée un nouveau fichier.

## Développement

```bash
cd services/api
.\.venv\Scripts\python.exe -m pytest -m "not integration"   # tests
.\.venv\Scripts\python.exe -m ruff check .                    # style

npm run typecheck:web     # TypeScript
npm run lint:web          # ESLint
npm run test:web          # Vitest
```

## Vérification : ce qui est établi, et ce qui ne l'est pas

Cette section existe parce qu'un projet honnête dit ce qu'il n'a pas fait. Le détail complet,
avec les chiffres par domaine, est dans
[`docs/operations/verification.md`](docs/operations/verification.md).

### Exécuté et réussi

| Contrôle | Résultat |
|---|---|
| pytest backend | **715 passés, 3 ignorés** |
| pytest worker | **5 passés** |
| vitest | **12 fichiers / 81 tests** |
| ruff (api, worker, scripts) | propre |
| compileall, pip check | OK |
| tsc, eslint, next build | 0 erreur |
| npm audit --omit=dev | **0 vulnérabilité** |
| migrations `upgrade`/`downgrade --sql` | symétriques, head `0012_security_admin` |
| surface publique (requêtes réelles) | 11 routes refusées, 4 publiques conformes |
| scan de secrets (307 fichiers) | aucun secret |
| détection de code mort | aucun travail inachevé |
| check-foundation.ps1 | exit 0 |

### Écrit mais jamais exécuté

**24 tests d'intégration** sont écrits et ignorés (`TEST_DATABASE_URL` absente). Parmi eux, les
tests d'**isolation entre utilisateurs et projets** et d'**application des rôles reader /
editor / owner**. La hiérarchie des rôles est testée comme fonction ; son application effective
à travers HTTP et la base ne l'est pas.

### Non testable dans cet environnement

- **Docker absent** : ni `docker compose up`, ni healthchecks, ni `docker compose config`.
- **PostgreSQL absent** : les 24 tests d'intégration, et tout ce qui touche au schéma réel.
- **`pg_dump` / `pg_restore` jamais exécutés** : la logique autour est testée avec un appel
  système simulé, les outils eux-mêmes non.
- **Restauration jamais éprouvée contre une base réelle.**
- **Aucun appel réel à l'API OpenAI** : le fournisseur par défaut est `mock`, et la production
  **refuse** `mock`. La qualité réelle des réponses n'a pas été évaluée.
- **OAuth Google jamais exécuté** : le code est complet (PKCE, `state`, `nonce`, vérification de
  signature), mais aucun identifiant client n'était disponible.
- **Google Drive/Docs et NotebookLM ne sont pas implémentés** : aucune occurrence dans le dépôt.

### Non versionné

**Git n'est pas installé.** L'intégralité du travail n'existe que sur le disque, sans historique
ni sauvegarde de version.

## Documentation

| Sujet | Document |
|---|---|
| **Clôture du projet** | [`docs/PROJECT-CLOSURE.md`](docs/PROJECT-CLOSURE.md) |
| Utilisation | [`docs/operations/user-guide.md`](docs/operations/user-guide.md) |
| Installation et lancement | [`docs/operations/installation.md`](docs/operations/installation.md) |
| Configuration | [`docs/operations/configuration.md`](docs/operations/configuration.md) |
| Déploiement | [`docs/operations/deployment.md`](docs/operations/deployment.md) |
| Sauvegarde et restauration | [`docs/operations/backup-restore.md`](docs/operations/backup-restore.md) |
| Vérification finale | [`docs/operations/verification.md`](docs/operations/verification.md) |
| Architecture | [`docs/architecture/overview.md`](docs/architecture/overview.md) |
| Sécurité | [`docs/security/authentication.md`](docs/security/authentication.md) |
| Décisions | [`docs/development/decisions.md`](docs/development/decisions.md) |
| Détail par étape | `docs/architecture/stage*.md` |
