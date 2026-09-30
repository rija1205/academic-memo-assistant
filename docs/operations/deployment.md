# Déploiement en production

Ce document décrit ce que l'overlay de production change, et pourquoi. Il ne décrit pas une
architecture multi-nœuds : le projet est un monolithe modulaire (voir
`docs/architecture/adr/0001-modular-monolith.md`) et son déploiement de référence tient sur un
seul hôte.

## Levier : l'overlay

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

Le fichier `docker-compose.prod.yml` est un **overlay**, pas une réécriture. Le compose de
développement reste utilisable tel quel, ce qui évite deux fichiers à maintenir en parallèle.

## Ce que l'overlay change

| Service | Développement | Production |
|---|---|---|
| `frontend` | port 3000 | port 3000 (seul service publié) |
| `backend` | port 8000 publié | **non publié** |
| `worker` | — | non publié |
| `postgres` | port 5432 publié | **non publié**, mot de passe obligatoire |
| `redis` | port 6379 publié | **non publié** |

Le point le plus important est la fermeture des ports de `postgres` et `redis`. En
développement, exposer 5432 et 6379 sur la machine hôte est pratique. En production, cela
place une base de données et un cache sur Internet, où la seule barrière est le mot de passe
de la base.

Dans l'overlay, `ports: []` supprime l'héritage du fichier de base : c'est le comportement
attendu de Compose, et un test le vérifie.

### Durcissement par service

- **Limites de ressources** sur les cinq services. Sans elles, un export PDF volumineux peut
  affamer PostgreSQL et rendre l'application entière inutilisable.
- **Système de fichiers en lecture seule** (`read_only: true`) pour `backend` et `worker`,
  avec un `tmpfs` sur `/tmp`. Le code ne doit pas pouvoir écrire dans l'image.
- **Plafonds de journaux** (`max-size` / `max-file`). Un journal non borné remplit un disque,
  et emporte avec lui les sauvegardes.
- **`no-new-privileges`** sur `backend` et `worker`.
- **`shm_size: 256mb`** et `max_connections=200` sur PostgreSQL : la configuration par défaut
  d'un conteneur est dimensionnée pour un serveur isolé, pas pour une charge applicative.

### Sécurité applicative activée

```dotenv
APP_ENV=production
SECURE_COOKIES=true
FORCE_HTTPS=true
```

Conséquences réelles :

- `SECURE_COOKIES=true` ⇒ les cookies de session ne transitent qu'en HTTPS. **Cette option
  exige que le proxy termine TLS.** Sans cela, plus aucune session ne peut être créée.
- `FORCE_HTTPS=true` ⇒ en-tête HSTS envoyé, et requêtes HTTP non redirigées en API.
- `APP_ENV=production` ⇒ `/docs`, `/redoc` et `/openapi.json` **désactivés**. Le schéma
  OpenAPI ne doit pas être distribué : il décrit la surface administrative.

## Avant le premier démarrage

```dotenv
# Obligatoire : l'overlay refuse de démarrer avec un mot de passe de développement
POSTGRES_PASSWORD=<mot-de-passe-solide>
SECRET_KEY=<token_urlsafe(64)>

# Refusés en production au démarrage
LLM_PROVIDER=openai
EMBEDDING_PROVIDER=openai
OPENAI_API_KEY=<clé>

# Cohérents avec la configuration
CORS_ORIGINS=https://memo.exemple.org
FRONTEND_URL=https://memo.exemple.org
POSTGRES_USER=academic_memo
POSTGRES_DB=academic_memo
```

`POSTGRES_PASSWORD` est déclaré avec `${POSTGRES_PASSWORD:?...}` : si la variable est absente,
`docker compose up` **échoue** au lieu de démarrer avec un mot de passe dev. Un mot de passe
par défaut n'est pas une commodité, c'est une credential.

## Séquence de démarrage

1. `postgres` démarre et devient sain (`pg_isready`).
2. `redis` démarre et devient sain.
3. `backend` démarre, exécute `alembic upgrade head`, puis sert.
4. `worker` démarre, dépend de `backend` sain et de `redis` sain.
5. `frontend` démarre, dépend de `backend` sain.

Les migrations sont donc appliquées avant que l'API ne réponde, et le frontend n'est servi
qu'une fois l'API prête. L'ordre est garanti par `depends_on: condition: service_healthy`,
pas par l'ordre de lecture du fichier.

## Migration

Les migrations sont appliquées par le `CMD` du conteneur backend au démarrage. En pratique :

- **un seul** conteneur backend doit démarrer à la fois, sinon deux `alembic upgrade head`
  s'exécutent concurremment ;
- pour une mise à jour sans interruption, ne pas redémarrer le backend en boucle : la
  commande est idempotente, mais la fenêtre de verrouillage est réelle.

## Proxy TLS

L'application ne termine pas TLS. Le proxy doit :

- terminer TLS et rediriger `HTTP → HTTPS` ;
- transmettre `X-Forwarded-Proto: https` ;
- **ne pas exposer** les ports 8000, 5432 ni 6379 ;
- autoriser une taille de corps compatible avec les imports de sources
  (`client_max_body_size`).

## Limites à connaître

- **Node unique.** L'overlay ne couvre pas la haute disponibilité. Le frontend utilise un
  serveur standalone, qui n'est pas multi-instance.
- **Restauration non automatisée.** Une reprise après sinistre suppose une intervention
  humaine et une sauvegarde vérifiée. Voir `backup-restore.md`.
- **`LLM_PROVIDER=mock` impossible.** Le refus est volontaire : un déploiement présenté comme
  fonctionnel alors que l'assistant ne contacte aucun modèle serait trompeur.
- **Pas de rotation des secrets.** `SECRET_KEY` et les mots de passe sont à changer manuellement.
  Changer `SECRET_KEY` invalide toutes les sessions : c'est un acte assumé, à planifier.
