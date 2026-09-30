# Configuration

Ce document décrit la configuration de l'application et, surtout, ce qu'elle **refuse**. Une
configuration acceptée au démarrage ne garantit pas un déploiement sûr : la garantie vient des
refus, qui sont listés ici avec leur message exact.

## Fichiers

| Fichier | Rôle |
|---|---|
| `.env.example` | toutes les variables, section par section, avec l'étape qui les a introduites |
| `.env` | configuration réelle — **jamais versionné**, absent de `.gitignore` par construction |
| `docker-compose.yml` | orchestration de développement |
| `docker-compose.prod.yml` | overlay de production |

## Variables structurantes

| Variable | Défaut | Effet |
|---|---|---|
| `APP_ENV` | `development` | En `production`, `/docs`, `/redoc` et `/openapi.json` sont désactivés |
| `SECRET_KEY` | clé de développement | **Refusé en production** si trop court ou si la valeur de développement est laissée |
| `DATABASE_URL` | `postgresql+asyncpg://…@localhost:5432/academic_memo` | Connexion PostgreSQL |
| `LLM_PROVIDER` | `mock` | **Refusé en production** |
| `LLM_API_KEY` | vide | Obligatoire si `LLM_PROVIDER=openai` |
| `EMBEDDING_PROVIDER` | `mock` | **Refusé en production** |
| `EMBEDDING_MODEL` | `mock-hash-1536` | **Refusé** si `EMBEDDING_PROVIDER=openai` : un modèle simulé avec un vrai fournisseur produirait un index incohérent |
| `SECURE_COOKIES` | `false` | Cookies de session en HTTPS uniquement |
| `FORCE_HTTPS` | `false` | En-tête HSTS envoyé, behind proxy TLS |
| `CORS_ORIGINS` | `http://localhost:3000` | **Refusé en production** si non-HTTPS ou si `*` |
| `FRONTEND_URL` | `http://localhost:3000` | **Refusé en production** si non-HTTPS |
| `GOOGLE_REDIRECT_URI` | localhost | **Refusé en production** si non-HTTPS |
| `AUTH_EXPOSE_RESET_TOKEN` | `false` | **Refusé en production** si activé : le jeton de réinitialisation serait renvoyé dans la réponse |
| `AUTH_RATE_LIMIT_ENABLED` | `true` | **Refusé en production** si désactivé |
| `SOURCE_WORKER_TOKEN` | `local-worker-token` | Obligatoire en mode `async` : le worker s'authentifie sur `/api/internal` |
| `RATE_LIMIT_FAIL_CLOSED` | `true` | Redis injoignable ⇒ `503` plutôt qu'un service ouvert |
| `EXPORT_ALLOW_REMOTE_IMAGES` | `false` | Images distantes refusées (SSRF) |

Le refus de `AUTH_RATE_LIMIT_ENABLED` deserve une justification : un déploiement où la
protection par mot de passe est désactivée est un déploiement où une liste d'adresses
autorisées à essayer des mots de passe est la seule barrière.

## Refus vérifiés

Chaque cas ci-dessous a été exécuté. Un refus est un `ValidationError` au démarrage, pas un
comportement observé en production.

| Cas | Verdict |
|---|---|
| configuration de production complète et valide | **acceptée** |
| `SECRET_KEY` de développement | refusée |
| `SECRET_KEY` trop court | refusée |
| `LLM_PROVIDER=mock` en production | refusée |
| `EMBEDDING_PROVIDER=mock` en production | refusée |
| `LLM_PROVIDER=openai` sans clé | refusée |
| `EMBEDDING_MODEL=mock-hash-1536` avec fournisseur `openai` | refusée |
| `CORS_ORIGINS` en HTTP | refusée |
| `CORS_ORIGINS=*` | refusée |
| `FRONTEND_URL` en HTTP | refusée |
| `AUTH_EXPOSE_RESET_TOKEN=true` | refusée |
| `AUTH_RATE_LIMIT_ENABLED=false` | refusée |
| `GOOGLE_REDIRECT_URI` en HTTP | refusée |
| `SOURCE_PROCESSING_MODE=async` sans jeton worker | refusée |

## Écriture et lecture

`scripts/` lit l'environnement, il ne le modifie pas : aucune variable de `.env` n'est
écrite par l'outillage. `backup.py` utilise `BACKUP_ROOT`, `DATABASE_URL` et
`SOURCE_LOCAL_STORAGE_PATH` ; `bootstrap_admin.py` utilise `DATABASE_URL` via la
configuration de l'application, ce qui garantit qu'il vise la base configurée et non une
autre par accident.

## Google OAuth

`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` et `GOOGLE_OAUTH_SCOPES`
(dont `openid email profile` par défaut). **Aucun scope Drive n'est demandé** : l'authentification
permet de se connecter, pas d'accéder aux fichiers de l'utilisateur.

L'implémentation est réelle : PKCE (`code_verifier`), `state`, `nonce`, échange du code contre
un jeton, et **vérification de signature du jeton d'identité** par `google.oauth2.id_token`
avec comparaison du `nonce` en temps constant. Ce n'est ni une URL ni un bouton.

**Non testé en conditions réelles** : aucun `GOOGLE_CLIENT_ID` n'était disponible. Le parcours
complet n'a donc pas été exécuté contre Google.

## Ce qui n'est pas implémenté

Ces intégrations n'apparaissent nulle part dans le dépôt — ni code, ni route, ni dépendance :

- **Google Drive / Google Docs** : aucun appel `docs.googleapis.com`, aucune dépendance Drive.
- **NotebookLM / Notebook** : aucune occurrence.

Une variable `.env` ou un bouton ne constitueraient pas une intégration fonctionnelle ; il n'y
a d'ailleurs pas de variable pour ces deux services.

## Rotation des secrets

Aucune rotation automatique. Changer `SECRET_KEY` invalide toutes les sessions ouvertes : c'est
un acte assumé, à planifier. Pour l'application d'une rotation sans interruption, il faudrait
accepter deux clés pendant une période de transition, ce qui n'est pas implémenté.
