# Étape 13 — Sécurité, administration et observabilité

## Vulnérabilités des dépendances : analyse et correction

`npm audit --omit=dev` signalait depuis l'étape 5 :

| Paquet | Gravité | Correctif officiel |
|---|---|---|
| `postcss` 8.4.31 | high | `next@16.3.6` (saut majeur) |
| `next` 15.5.0–16.3.0 | moderate | `next@16.3.6` (saut majeur) |

`postcss` n'est **pas** une dépendance directe : il arrive deux fois, en 8.5.28 via vite (déjà
corrigé) et en 8.4.31 via `next@15.5.26`. Le correctif officiel imposait `next@16`, ce que la
consigne interdit sans vérification d'impact.

**Voie retenue** : un `overrides` npm sur la dépendance transitive.

```json
"overrides": { "next": { "postcss": "8.5.28" } }
```

Résultat mesuré : `postcss@8.5.28` dédupliqué partout, `npm audit --omit=dev` → **0 vulnérabilité**,
et la validation complète reste verte (typecheck, eslint, 81 tests vitest, `next build` exit 0).
Aucun saut de version majeure n'a été tenté. La première tentative, `next>postcss`, a été
rejetée par npm (`EINVALIDTAGNAME`) : la forme imbriquée est la seule acceptée.

## Budget de requêtes

Le limiteur existant ne protégeait que la connexion. Les routes coûteuses — un export PDF, une
requête RAG, un appel au modèle, un import, une écriture — étaient sans limite : une boucle
pouvait transformer l'export en déni de service.

`app/security/guards.py` ajoute un budget par catégorie, avec une fenêtre configurable :

| catégorie | routes | limite par défaut |
|---|---|---|
| `export` | `/exports` | 20 / 60 s |
| `rag` | `/rag` | 60 / 60 s |
| `assistant` | `/assistant` | 30 / 60 s |
| `writing` | `/writing` | 30 / 60 s |
| `audit` | `/audit/run` | 30 / 60 s |
| `import` | `/import` | 20 / 60 s |
| `write` | `/sections`, `/citations`, `/bibliography` | 180 / 60 s |

Trois décisions :

* le budget est appliqué **avant** le gestionnaire, dans le middleware, sinon le travail à
  empêcher a déjà été payé ;
* l'identité est **hachée** (SHA-256) avant d'atteindre Redis : ni adresse ni nom de compte
  n'est écrit en clair ;
* un Redis injoignable fait répondre **503** quand `RATE_LIMIT_FAIL_CLOSED` est actif. Un
  limiteur qui échoue en silence n'est pas un limiteur.

La réponse 429 porte `Retry-After`, `X-RateLimit-Limit` et `X-RateLimit-Remaining`.

## En-têtes de sécurité

Ajoutés : `Content-Security-Policy` (`default-src 'none'`, l'API ne sert jamais de HTML),
`Permissions-Policy`, `Cross-Origin-Opener-Policy`, `Cross-Origin-Resource-Policy`,
`Strict-Transport-Security` en HTTPS ou avec `FORCE_HTTPS`, et `Pragma: no-cache` en plus de
`Cache-Control: no-store` sur les routes `/api/admin`.

En production, `/docs`, `/redoc` et `/openapi.json` sont **désactivés** : publier le schéma
revient à remettre une carte de la surface administrative.

## Journal de sécurité

`security_events` enregistre ce qui s'est passé : acteur, ressource, résultat, chemin, et
l'adresse **hachée**. Un incident doit être attribuable sans que la table devienne une liste
lisible de qui a consulté quoi.

Un refus d'accès est désormais journalisé : `authorize_project_access` enregistre l'événement
quand un projet est absent (404) ou quand le rôle est insuffisant (403). L'écriture est
*best effort* — un journal défaillant ne doit jamais masquer le refus que l'appelant va
recevoir.

`admin_audit_events` isole les actions deliberées d'un administrateur, pour répondre à « qu'a
fait un administrateur » en une requête.

Le journal ne peut pas recevoir de secret : `SecurityEventLog.FORBIDDEN_KEYS` liste les clés
interdites et un détail contenant « password », « token », « secret » ou « api_key » est
remplacé par `<detail redacté>`. Un test le vérifie.

## Administration

Séparée des rôles de projet, délibérément : posséder un mémoire n'implique aucun pouvoir de
plateforme.

* `users.is_admin`, défaut **`false`**. Le premier compte créé n'est pas plus privilégié que
  le millième ; un test vérifie la valeur par défaut au niveau de la colonne ;
* `users.is_suspended`, `suspended_at`, `suspended_reason` ;
* un compte suspendu est refusé **même avec une session valide** : la suspension prend effet
  immédiatement, pas à la prochaine connexion ;
* un administrateur ne peut ni se suspendre ni se retirer ses propres privilèges : ce serait un
  déni de service contre la plateforme ;
* la liste des comptes ne contient **aucun contenu de mémoire** — un administrateur gère des
  comptes, il n'ouvre pas les mémoires des autres.

Toutes les routes `/api/admin` passent par une dépendance unique, `require_platform_admin`, et
les mutations exigent CSRF. Un test vérifie route par route que la dépendance est présente.

## Observabilité

* **Logs structurés** : une ligne JSON par événement, avec `X-Request-Id` propagé dans la
  réponse et dans les logs. La fonction de journalisation ne lève **jamais** : un objet dont le
  `repr` explose ne casse pas l'appelant, c'est testé.
* **Métriques** : compteurs par route, latences p50/p95/p99 (réservoir borné, mémoire
  constante), erreurs 5xx, requêtes limitées, événements de sécurité, exports, appels au
  modèle et jetons. Un histogramme garde 512 valeurs au maximum.
* Les métriques déclarent leur **portée** : `scope: "process"` et un avertissement explicite
  qu'un déploiement multi-instance doit les agréger. Un tableau de bord qui montre une vue
  partielle sans le dire est pire que pas de tableau de bord.
* Une route ne produit jamais un identifiant en clair dans une étiquette de métrique : le
  segment d'identifiant est remplacé par `{id}`.

## Migration

`0012_security_admin`, `down_revision = 0011_academic_audit`. Cinq colonnes sur `users`, deux
tables. Les colonnes ont toutes une valeur neutre par défaut : aucun compte n'acquiert de droit
par la mise à niveau. 0001→0011 intactes.

## Limites

* Les métriques sont par processus : un déploiement multi-instance exige un agrégateur.
* Le journal de sécurité n'est pas purgé automatiquement ; une politique de rétention doit être
  décidée par l'exploitant.
* La suspension invalide l'accès mais ne révoque pas explicitement les sessions déjà émises en
  base : elles sont refusées à l'usage, ce qui est suffisant mais laisse des lignes en base.
* `SecurityEvent` n'est pas partitionné : au-delà de quelques millions de lignes, il faudra
  une politique d'archivage.
