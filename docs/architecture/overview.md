# Architecture — étapes 2 à 5

## Principe

Academic Memo Assistant est fondé sur un monolithe modulaire : un frontend Next.js, une API FastAPI et un worker Celery, avec PostgreSQL comme source de vérité et Redis pour les files et le cache.

```text
Browser
  ↓
Next.js (apps/web)
  ↓ proxy same-origin /api/backend pour l'authentification
FastAPI (services/api)
  ├── PostgreSQL + pgvector
  ├── Redis / Celery
  ├── Storage objet (étape ultérieure)
  └── Intégrations futures (étapes ultérieures)
```

## Responsabilités

- `apps/web` : interface, proxy same-origin `/api/backend`, authentification, gestion des mémoires, éditeur Tiptap, bibliothèque de sources et proxy de health check.
- `services/api` : configuration, modèles SQLAlchemy, migrations, contrôle d'accès, extraction des sources et health checks.
- `services/worker` : worker Celery de traitement des sources via le callback API protégé.
- `infra/docker` : construction des images et extensions PostgreSQL.
- `packages/contracts` : contrat OpenAPI minimal.

## Modèle de données

La migration `0001_initial_schema` crée les tables de base :

- `users` : identité et état du compte ;
- `projects` : métadonnées académiques de base ;
- `project_members` : rôle d'accès (`owner`, `editor`, `reader`).

La migration `0002_authentication_and_sessions` ajoute :

- `auth_accounts` : méthodes d'authentification par utilisateur ;
- `sessions` : sessions serveur, avec hash du jeton et expiration ;
- `oauth_connections` : connexion Google, sans scope Drive ;
- `password_reset_tokens` : jetons de réinitialisation hachés et à usage unique ;
- les colonnes de vérification et dernière connexion de `users`.

La migration `0003_project_workspace` ajoute :

- les métadonnées académiques du projet ;
- `outline_nodes` : structure hiérarchique des sections ;
- `sections` : documents Tiptap, statut et version courante ;
- `section_revisions` : historique immuable et restaurations.

La migration `0004_source_library` ajoute :

- `sources` : métadonnées académiques, statut et hash ;
- `source_files` : référence du stockage et fichier original ;
- `source_folders` et `source_tags` : organisation de la bibliothèque ;
- `source_pages` et `source_blocks` : texte extrait et provenance ;
- `source_processing_jobs` : pipeline asynchrone et erreurs.

Les tables RAG, documents, références, conversations et jeux de données seront ajoutées dans les étapes correspondantes. Les frontières et le modèle prévu pour l'import de sources sont documentés dans `stage5-sources.md`.

## pgvector

L'image Docker PostgreSQL utilise `pgvector/pgvector:pg16`. Le script d'initialisation active `vector`, `uuid-ossp`, `pg_trgm` et `unaccent`. Le champ de recherche vectorielle n'est pas encore créé : il appartient à l'étape RAG.
