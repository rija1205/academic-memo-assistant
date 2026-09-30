# API — Academic Memo Assistant

API FastAPI de l'étape 5 : authentification, gestion des mémoires, éditeur Tiptap, import et traitement des sources, stockage provider, extraction avec provenance et recherche locale. Le frontend Next.js passe par son proxy same-origin `/api/backend` pour conserver les cookies sur le même hôte.

## Commandes

```bash
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload
pytest
python -m ruff check .
```

Endpoints de santé :

- `GET /health/live` : le processus répond.
- `GET /health/ready` : PostgreSQL et Redis répondent.

Endpoints d'authentification :

- `GET /api/auth/csrf` : délivre un jeton CSRF double-submit.
- `POST /api/auth/register` : création d'un compte email/mot de passe.
- `POST /api/auth/login` : connexion email/mot de passe.
- `POST /api/auth/logout` : révocation de la session courante.
- `GET /api/auth/me` : utilisateur de la session courante.
- `PATCH /api/auth/profile` : mise à jour du nom affiché.
- `POST /api/auth/forgot-password` : demande de réinitialisation.
- `POST /api/auth/reset-password` : changement de mot de passe.
- `GET /api/auth/google/status` : état de la configuration Google OAuth.
- `POST /api/auth/google/start` : démarrage OAuth avec state, nonce et PKCE.
- `GET /api/auth/google/callback` : callback OAuth Google (appelé via le proxy same-origin `/api/backend/auth/google/callback` dans le frontend).

Les requêtes modifiantes doivent envoyer le jeton reçu par `/api/auth/csrf` dans l'en-tête `X-CSRF-Token`.

## Projet et espace de travail

- `POST /api/projects` : créer un mémoire et sa structure initiale.
- `GET /api/projects` : lister les mémoires accessibles.
- `GET/PATCH/DELETE /api/projects/{project_id}` : consulter, modifier ou supprimer.
- `POST /api/projects/{project_id}/archive` et `/duplicate`.
- `GET/POST /api/projects/{project_id}/outline` : structure.
- `PATCH/DELETE /api/projects/{project_id}/outline/{node_id}`.
- `POST /api/projects/{project_id}/outline/{node_id}/duplicate`.
- `POST /api/projects/{project_id}/outline/reorder`.
- `GET /api/projects/{project_id}/sections/{section_id}`.
- `PUT /api/projects/{project_id}/sections/{section_id}/content` : autosave Tiptap (paragraphes, titres, listes, tableaux, images, équations, citations, références et sauts de page).
- `GET /api/projects/{project_id}/sections/{section_id}/revisions`.
- `POST /api/projects/{project_id}/sections/{section_id}/revisions/{revision_id}/restore`.

## Sources

- `POST /api/projects/{project_id}/sources/upload` : upload multipart, validation et doublons SHA-256.
- `GET /api/projects/{project_id}/sources` : recherche, filtres, tri et pagination.
- `GET/PATCH/DELETE /api/projects/{project_id}/sources/{source_id}` : métadonnées, statut et suppression.
- `GET /api/projects/{project_id}/sources/{source_id}/download` : téléchargement réservé à editor/owner.
- `GET /api/projects/{project_id}/sources/{source_id}/preview` : pages, blocs et provenance.
- `GET /api/projects/{project_id}/sources/{source_id}/duplicates` : doublons SHA-256/DOI/titre.
- `GET /api/projects/{project_id}/sources/{source_id}/jobs` : historique de traitement.
- `POST /api/projects/{project_id}/sources/{source_id}/reprocess` : relancer l'extraction.
- `GET /api/projects/{project_id}/sources/search` : recherche textuelle locale.
- `GET/POST/DELETE /api/projects/{project_id}/sources/folders` : dossiers.
- `POST /api/internal/sources/{source_id}/process` : callback worker protégé par `X-Worker-Token`.

Pour les tests d'intégration, définir une base PostgreSQL dédiée :

```bash
$env:TEST_DATABASE_URL="postgresql+asyncpg://academic_memo:academic_memo_dev@localhost:5432/academic_memo_test"
pytest
```

La documentation interactive est disponible sur `/docs` lorsque l'API est démarrée.
