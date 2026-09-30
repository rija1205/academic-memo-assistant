# API

La source de vérité est l'application FastAPI. Le frontend appelle l'authentification via son proxy same-origin `/api/backend`, qui relaie les cookies vers l'API. Avec l'API démarrée :

- Swagger UI : http://localhost:8000/docs
- ReDoc : http://localhost:8000/redoc
- OpenAPI JSON : http://localhost:8000/openapi.json

## Santé

| Endpoint | Rôle |
|---|---|
| `GET /` | Métadonnées de l'API |
| `GET /health/live` | Liveness du processus |
| `GET /health/ready` | PostgreSQL et Redis |

## Authentification

| Endpoint | Rôle |
|---|---|
| `GET /api/auth/csrf` | Jeton CSRF et cookie associé |
| `POST /api/auth/register` | Inscription email/mot de passe |
| `POST /api/auth/login` | Connexion email/mot de passe |
| `POST /api/auth/logout` | Déconnexion et révocation |
| `GET /api/auth/me` | Session courante |
| `GET /api/auth/sessions` | Sessions actives de l'utilisateur |
| `DELETE /api/auth/sessions/{session_id}` | Révocation d'une session appartenant à l'utilisateur |
| `PATCH /api/auth/profile` | Profil utilisateur |
| `POST /api/auth/forgot-password` | Demande de reset |
| `POST /api/auth/reset-password` | Reset du mot de passe |
| `GET /api/auth/google/status` | Configuration Google OAuth |
| `POST /api/auth/google/start` | Initialisation OAuth Google |
| `GET /api/auth/google/callback` | Callback OAuth Google, exposé côté frontend via `/api/backend/auth/google/callback` |

## Projets protégés

| Endpoint | Rôle |
|---|---|
| `GET /api/projects` | Projets accessibles à l'utilisateur |
| `GET /api/projects/{project_id}` | Projet accessible, sinon `404` |
| `GET /api/projects/{project_id}/access` | Rôle de l'utilisateur sur le projet |
| `POST /api/projects` | Créer un mémoire |
| `PATCH/DELETE /api/projects/{project_id}` | Modifier ou supprimer un mémoire |
| `GET/POST /api/projects/{project_id}/outline` | Structure des sections |
| `POST /api/projects/{project_id}/outline/reorder` | Réordonner la structure |
| `PATCH/DELETE /api/projects/{project_id}/outline/{node_id}` | Modifier ou supprimer un nœud |
| `POST /api/projects/{project_id}/outline/{node_id}/duplicate` | Dupliquer un nœud et son contenu |
| `GET /api/projects/{project_id}/sections/{section_id}` | Contenu Tiptap d'une section |
| `PUT /api/projects/{project_id}/sections/{section_id}/content` | Autosave Tiptap |
| `GET /api/projects/{project_id}/sections/{section_id}/revisions` | Historique des versions |
| `POST /api/projects/{project_id}/sections/{section_id}/revisions/{revision_id}/restore` | Restaurer une version |
| `POST /api/projects/{project_id}/sources/upload` | Importer une source |
| `GET /api/projects/{project_id}/sources` | Lister et filtrer les sources |
| `GET/PATCH/DELETE /api/projects/{project_id}/sources/{source_id}` | Consulter, modifier ou supprimer une source |
| `GET /api/projects/{project_id}/sources/{source_id}/download` | Télécharger le fichier original |
| `GET /api/projects/{project_id}/sources/{source_id}/preview` | Pages, blocs et provenance |
| `GET /api/projects/{project_id}/sources/search` | Rechercher dans le texte extrait |
| `GET/POST/DELETE /api/projects/{project_id}/sources/folders` | Gérer les dossiers |

Les contrôles de rôle sont effectués côté API. Un `reader` peut consulter l'aperçu et la recherche, mais pas télécharger le binaire ; `editor` et `owner` peuvent télécharger. L'interface ne remplace jamais ces contrôles.
