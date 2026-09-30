# Développement local

Ce document décrit les commandes vérifiées dans ce dépôt. Les scripts npm sont définis à la
racine du monorepo et délèguent à l'espace de travail `apps/web` : **tous les noms de scripts
se terminent par `:web`**. Un script sans ce suffixe n'existe pas.

Pour une installation complète, voir
[`docs/operations/installation.md`](../operations/installation.md). Pour l'état de clôture,
[`docs/PROJECT-CLOSURE.md`](../PROJECT-CLOSURE.md).

## Docker, recommandé

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Vérifications :

- <http://localhost:3000> — interface
- <http://localhost:8000/health/ready> — API et dépendances
- <http://localhost:8000/docs> — documentation interactive (**désactivée** si `APP_ENV=production`)

## Frontend hors Docker

Prérequis : Node.js 22 (`nvm use`).

Depuis la **racine** du dépôt :

```powershell
npm install
npm run dev:web
```

Scripts réellement disponibles à la racine :

| Commande | Effet |
|---|---|
| `npm run dev:web` | serveur de développement |
| `npm run build:web` | build de production |
| `npm run typecheck:web` | `tsc --noEmit` |
| `npm run lint:web` | ESLint |
| `npm run test:web` | Vitest |

Si le backend n'est pas sur le port par défaut, copiez `apps/web/.env.example` vers
`apps/web/.env.local` et ajustez `BACKEND_INTERNAL_URL`.

## Backend hors Docker

Prérequis : Python 3.12 et PostgreSQL/Redis accessibles.

```powershell
cd services/api
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Invoquer les outils par le chemin complet de l'interpréteur évite de dépendre de l'activation
du virtualenv, qui échoue sous la politique d'exécution par défaut de Windows.

### Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -m "not integration"   # tests unitaires
.\.venv\Scripts\python.exe -m pytest -m integration           # tests d'integration
.\.venv\Scripts\python.exe -m ruff check .
```

Les tests d'intégration exigent `TEST_DATABASE_URL` pointant vers une base dédiée ; sans elle,
ils sont ignorés — c'est le comportement attendu, pas un échec.

## Contrôle du dépôt

```powershell
powershell -ExecutionPolicy Bypass -File scripts\check-foundation.ps1
```

Le drapeau `-ExecutionPolicy Bypass` est nécessaire : la politique par défaut refuse
d'exécuter un script local.

## Worker

```powershell
cd services/worker
..\api\.venv\Scripts\python.exe -m celery -A app.worker.celery_app worker --loglevel=INFO --queues=sources,rag,celery
```

Le worker n'a pas de virtualenv propre ; il utilise celui de l'API et partage ses dépendances.
`check-foundation.ps1` affiche un avertissement explicite lorsqu'il fait cette substitution.

## Dépendances et verrouillage

`package-lock.json` est versionné : utilisez `npm ci` pour une installation reproductible. Les
images Docker utilisent volontairement `npm install`, afin de pouvoir démarrer même si le
verrouillage n'a pas été régénéré.

Le bloc `overrides` de `package.json` (`{"next": {"postcss": "8.5.28"}}`) corrige les
vulnérabilités de Next sans saut de version majeure. **Ne pas le supprimer** : `npm audit
--omit=dev` remonterait alors des vulnérabilités.

## Migrations

Elles sont dans `services/api/alembic/versions`. **Ne jamais modifier une migration déjà
appliquée** : créer un nouveau fichier.

```powershell
.\.venv\Scripts\alembic.exe upgrade head     # appliquer
.\.venv\Scripts\alembic.exe downgrade -1     # annuler la dernière
.\.venv\Scripts\alembic.exe current          # révision courante
```

## Stockage et traitement des sources

- `SOURCE_PROCESSING_MODE=async` utilise Celery et Redis ; `sync` convient aux tests unitaires
  et n'exige pas Redis.
- `SOURCE_PROCESSING_MODE=async` **exige** `SOURCE_WORKER_TOKEN` : le démarrage échoue sinon.
- `SOURCE_STORAGE_PROVIDER=local` écrit dans `SOURCE_LOCAL_STORAGE_PATH` ; `s3` utilise
  `S3_ENDPOINT_URL`, `S3_BUCKET`, `S3_ACCESS_KEY` et `S3_SECRET_KEY`, et MinIO peut être
  ciblé via son endpoint S3.
- Le callback worker utilise `SOURCE_WORKER_TOKEN` dans les deux services. En production,
  remplacez impérativement la valeur locale par un secret partagé.

## Variables de l'API

La configuration complète, avec la liste des valeurs que la production **refuse** de démarrer
avec, est dans [`docs/operations/configuration.md`](../operations/configuration.md).
