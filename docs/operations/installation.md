# Installation et lancement

Ce document décrit les deux façons de faire tourner l'application, et la manière de vérifier
que l'installation est saine. Il est volontairement concret : chaque commande est celle qui
a été exécutée, pas une intention.

## Choix d'un mode

| | Docker Compose | Développement local |
|---|---|---|
| Pour qui | une démonstration, un poste de travail, un déploiement | le développement quotidien |
| Base de données | conteneur PostgreSQL | PostgreSQL local, ou conteneur |
| Coût de mise en route | le plus faible | plus élevé |
| Ce que l'on peut déboguer | dans les conteneurs | directement dans l'éditeur |

Le mode Docker est celui à utiliser pour **voir l'application fonctionner**. Le mode local
est nécessaire pour travailler sur le code avec un rechargement à chaud.

---

## Mode 1 — Docker Compose

### Prérequis

- Docker Desktop avec le plugin Compose v2 (`docker compose version` doit répondre).
- 4 Go de mémoire disponibles pour Docker.

### Installation

```bash
git clone <url-du-depot> academic-memo-assistant
cd academic-memo-assistant
cp .env.example .env
```

Ouvrir `.env` et au minimum remplacer :

```dotenv
SECRET_KEY=une-cle-longue-generee-aleatoirement
POSTGRES_PASSWORD=un-mot-de-passe-solide
```

Générer une clé correcte plutôt que d'en inventer une :

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Lancer :

```bash
docker compose up -d
```

Suivre le démarrage :

```bash
docker compose logs -f backend
```

Le conteneur `backend` exécute `alembic upgrade head` puis démarre l'API. La base est donc
à jour quand le service répond.

### Vérification

```bash
curl http://localhost:8000/health/ready
```

Une réponse contenant `"status": "ok"` (ou `"ready"`) indique que l'API répond **et** que la
base est joignable. Un service qui répond mais dont la base est injoignable doit être traité
comme indisponible : c'est précisément ce que cette route vérifie.

Puis <http://localhost:3000> pour l'interface.

### Arrêter

```bash
docker compose stop          # conserve les données
docker compose down          # conserve les volumes
docker compose down -v       # SUPPRIME les données : sauvegarde avant
```

---

## Mode 2 — Développement local

### Prérequis

- Python **3.12** (voir `.python-version`)
- Node.js **22** (voir `.nvmrc`)
- PostgreSQL **15 ou plus** accessible
- Redis **7 ou plus** (le worker et le limiteur de débit en dépendent)

### API

```bash
cd services/api
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"   # Windows
# ./.venv/bin/python -m pip install -e ".[dev]"         # Linux et macOS

.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

### Worker

Nécessaire pour l'analyse des sources, les embeddings et le RAG. Le worker n'a pas de
`venv` propre dans ce dépôt ; il utilise l'environnement de l'API et partage ses
dépendances.

```bash
cd services/api
.\.venv\Scripts\python.exe -m celery -A app.worker.celery_app worker --loglevel=INFO --queues=sources,rag,celery
```

### Frontend

```bash
npm install
npm run dev:web
```

L'interface est sur <http://localhost:3000> et relaie l'API via `/api/backend`.

---

## Configuration

Toutes les variables sont documentées dans `.env.example`, section par section, avec le
numéro de l'étape qui les a introduites. Les points qui surprising le plus souvent :

| Variable | Défaut | Effet |
|---|---|---|
| `APP_ENV` | `development` | En `production`, la documentation interactive `/docs` est désactivée. |
| `LLM_PROVIDER` | `mock` | En `production`, `mock` est **refusé** au démarrage. |
| `EMBEDDING_PROVIDER` | `mock` | Idem : la production refuse un fournisseur fictif. |
| `SECURE_COOKIES` | `false` | À mettre à `true` derrière un proxy TLS. |
| `RATE_LIMIT_FAIL_CLOSED` | `true` | Redis injoignable ⇒ `503` plutôt qu'un service ouvert. |
| `EXPORT_ALLOW_REMOTE_IMAGES` | `false` | Les images distantes sont refusées (protection SSRF). |

> **`LLM_PROVIDER=mock` est un choix de développement, pas une économie.** En mode `mock`,
> l'assistant ne contacte aucun modèle : il renvoie des réponses fabriquées. Les
> fonctionnalités d'assistance et de rédaction existent et sont testées, mais leur qualité
> réelle n'est pas évaluée tant qu'aucun appel n'atteint un fournisseur. Voir la section
> « Ce qui n'a pas été vérifié » du rapport final.

---

## Premier administrateur

L'étape 13 a volontairement mis `is_admin` à `false` : aucun compte n'est privilégié par
accident. Il faut donc accorder explicitement le premier privilège.

```bash
# Créer d'abord le compte via /api/auth/register depuis l'interface
python scripts/bootstrap_admin.py --list-admins
python scripts/bootstrap_admin.py --email vous@exemple.org --reason "Amorçage initial" --yes
```

Le script refuse de s'exécuter sans `--yes`, refuse une base antérieure à la migration
`0012_security_admin`, et écrit une trace dans `admin_audit_events`.

Pour les suivants, passer par la console `/admin` : l'opération y est journalisée avec
l'auteur de la décision.

---

## Vérifier l'installation

Le script de contrôle exécute l'ensemble des validations du dépôt :

```powershell
powershell -ExecutionPolicy Bypass -File scripts\check-foundation.ps1
```

`-ExecutionPolicy Bypass` est nécessaire sur Windows : la politique par défaut refuse
d'exécuter un script local, et l'erreur qui en résulte parle de « fichiers de script
désactivés sur ce système », ce qui ne désigne pas la cause. Sous Linux ou macOS :

```bash
pwsh -File scripts/check-foundation.ps1
```

Sous Windows, le `PATH` doit contenir Python **et** Node, sinon `python` résout vers le
stub WindowsApps et le script échoue à tort :

```powershell
$env:PATH = "$env:LOCALAPPDATA\Programs\Python\Python312;$env:PATH"
```

Vérifications manuelles :

```bash
cd services/api
.\.venv\Scripts\python.exe -m pytest -m "not integration"   # tests
.\.venv\Scripts\python.exe -m ruff check .                    # style
.\.venv\Scripts\alembic.exe heads                             # migration courante

npm run typecheck:web
npm run lint:web
npm run test:web
```

---

## Problèmes connus

**`alembic upgrade` échoue sur une base fraîche.** Vérifier que `DATABASE_URL` pointe vers la
base de développement et non vers une base existante : `upgrade` ne recrée pas une base.

**Le frontend ne joint pas l'API.** `BACKEND_INTERNAL_URL` (Docker) ou `NEXT_PUBLIC_API_URL`
(local) doit pointer vers l'API. En local, le relais `/api/backend` est configuré dans
`apps/web/next.config`.

**Le worker ne traite rien.** Vérifier que Redis est joignable et que le worker écoute bien la
file nommée (`--queues=sources,rag,celery`). Une tâche dans une file non consommée reste en
attente sans erreur visible.

**Les tests d'intégration sont ignorés.** Ils exigent `TEST_DATABASE_URL` et une base
PostgreSQL réelle. Sans elle, `pytest -m integration` affiche `skipped`, ce qui est le
comportement attendu et non un échec.
