# Étape 14 — Déploiement, sauvegardes et documentation d'exploitation

## Ce que l'étape apporte

L'application était fonctionnelle et testée, mais rien ne permettait de la **déployer** de
façon sûre ni de la **restaurer**. Trois manques concrets ont été comblés, et deux bugs
réels ont été trouvés au passage.

## 1. Outillage de sauvegarde et de restauration

`scripts/backup.py` — outil autonome, sans dépendance à l'application.

### Décisions

**Un manifeste, pas un simple fichier.** Chaque sauvegarde produit un `manifest.json`
contenant un SHA-256 par artefact. Sans lui, une restauration ne peut pas prouver que
l'archive est intacte : c'est une hypothèse, pas une vérification.

**Une sauvegarde non vérifiée est un espoir.** `--verify` recalcule chaque empreinte et
rapporte *tous* les problèmes, pas le premier encountered. Un opérateur doit voir l'ensemble
de la situation d'un coup.

**Aucun contournement possible.** Une restauration est refusée si la vérification échoue. Il
n'existe pas de `--force` : la présence d'un tel drapeau aurait pour effet de rendre
utilisable exactement les archives qu'il ne faut pas utiliser. Un test vérifie explicitement
que ce drapeau n'existe pas.

**Une double confirmation est demandée par la conception.** `--yes` est exigé parce qu'une
restauration écrase la base. Mais la vérification précède la confirmation : une archive
corrompue est refusée avant même que l'opérateur ait à confirmer.

**Le stockage des sources est inclus.** Sans les fichiers importés, la chaîne de provenance
d'une citation devient une promesse sans support. Un répertoire de stockage vide n'est pas
archivé : une ligne de manifeste à interpréter pour rien est un bruit.

**La rétention ne supprime que ce qui est vérifié.** Une sauvegarde d'intégrité inconnue est
peut-être la seule copie de quelque chose. `prune` la laisse en place, et dit pourquoi.

### Le mot de passe ne doit pas fuiter

`pg_dump` et `pg_restore` lisent le mot de passe dans `PGPASSWORD`. L'URL leur est donc
transmise **sans ses identifiants** (`split_credentials`), le mot de passe allant par
l'environnement. Passer l'URL complète aurait mis le mot de passe dans la liste des
processus de l'hôte, lisible par tout utilisateur local pendant l'exécution.

## 2. Amorçage du premier administrateur

L'étape 13 a mis `is_admin` à `false` par défaut. C'était la bonne décision, mais elle
avait un coût que l'étape 13 n'avait pas couvert : **personne ne pouvait devenir
administrateur**. `scripts/bootstrap_admin.py` est ce chemin.

- refuse de s'exécuter sans `--yes` ;
- refuse une base antérieure à `0012_security_admin`, où la colonne n'existe pas ;
- écrit une trace `admin_audit_events`, comme toute autre décision d'administration ;
- `--list-admins` répond à la question « qui est administrateur ? », qu'on ne peut pas poser
  autrement.

La chaîne de révisions est **lue depuis les fichiers de migration**, pas recopiée : une liste
codée en dur serait devenue fausse à la migration `0013` et aurait accepté une base trop
ancienne.

## 3. Overlay de production

`docker-compose.prod.yml` est un overlay, pas une réécriture. Le compose de développement
reste utilisable.

- **fermeture des ports** de `backend`, `postgres`, `redis` ; seul `frontend` reste publié ;
- **limites de ressources** sur les cinq services ;
- **système de fichiers en lecture seule** pour `backend` et `worker` ;
- **plafonds de journaux** ;
- **`POSTGRES_PASSWORD` obligatoire** (`${VAR:?message}`) : le démarrage échoue plutôt que de
  produire un mot de passe par défaut.

## Bugs trouvés et corrigés

Ces bugs existaient dans le dépôt avant cette étape. Ils sont listés parce qu'ils sont
révélateurs : aucun n'aurait été détecté sans l'étape 14.

### 1. Le compose ignorait toutes les variables des étapes 11 à 13

Seules les variables des étapes 1 à 9 étaient transmises au conteneur `backend`. Un opérateur
réglant `EXPORT_MAX_OUTPUT_BYTES` ou `RATE_LIMIT_FAIL_CLOSED` dans `.env` croyait configurer
l'application : les valeurs étaient **silencieusement ignorées**, et le conteneur tournait
avec les défauts du code. Le conteneur est précisément le lieu où la configuration doit
s'appliquer.

### 2. Le `command:` du worker était du YAML invalide

```yaml
    command:
    [
      "celery",
```

La liste était indentée au niveau de la clé, et non en dessous. Le document n'était pas
analysable comme attendu et `docker compose up` échouait. Le bug ne se voyait pas à la
lecture : il a fallu valider le YAML pour le trouver.

### 3. Le mot de passe de base fuitait dans la liste des processus

`backup_database` construisait un `PGPASSWORD` dans `env`… et ne transmettait jamais `env` à
`run()`. Le mot de passe passait donc bel et bien dans l'argument de ligne de commande,
exactement ce que le commentaire affirmait éviter. Le commentaire décrivait l'intention, pas
le comportement.

### 4. `bootstrap_admin.py` n'aurait jamais fonctionné

`alembic/env.py` appelle `asyncio.run()` en interne. Appelé depuis une boucle déjà ouverte,
`command.current()` renvoyait une coroutine jamais attendue : la révision était toujours
`None`, et le script refusait donc **toujours** de s'exécuter, y compris sur une base
saine. Le script lisait aussi `session_factory` dans `app.db.session`, où la factory
s'appelle `SessionLocal`. Deux erreurs qui ne se revelóient qu'à l'exécution.

### 5. Le test de confinement d'archive était trop faible

```python
if not str(target).startswith(str(storage_path.resolve())):
```

Accepte un répertoire frère dont le nom commence par celui de la destination :
`/stockage-ennemi` passe le test pour une destination `/stockage`. Remplacé par
`is_relative_to`, et complété par `filter="data"` de la bibliothèque standard, qui rejette
aussi les chemins absolus et les liens sortants.

### 6. L'overlay de production lançait un fichier inexistant

L'overlay définissait `command: ["node", "server.js"]`, alors que l'image copie l'arbre
standalone dans `/app` et démarre `node apps/web/server.js` depuis ce répertoire. Le
conteneur frontend **échouerait au démarrage en production** — un échec qui n'apparaît qu'au
déploiement, sur le service le plus visible. Un test compare désormais la commande de
l'overlay à celle du Dockerfile.

### 7. Le contrôle de structure ignorait silencieusement la vérification Compose

`check-foundation.ps1` cherchait `python` dans le `PATH`. Sur ce poste, l'interpréteur système
n'a pas PyYAML : le contrôle affichait « vérification ignorée » et **continuait**, donc
l'étape paraissait verte. Le script utilise maintenant le virtualenv de l'API, et signale
explicitement l'absence d'interpréteur au lieu de passer sous silence.

## Une erreur de conception corrigée

Le premier jet de `.env.example` introduisait `STORAGE_LOCAL_PATH` pour la sauvegarde, à
côté du `SOURCE_LOCAL_STORAGE_PATH` déjà utilisé par l'application. Deux noms pour un même
répertoire : il fallait les tenir synchronisés, et une sauvegarde pointerait sur le mauvais
silencieusement. L'outil lit désormais la variable de l'application, en priorité.

## Documentation

- `docs/operations/installation.md` — installation, lancement, vérification, premier
  administrateur, dépannage.
- `docs/operations/deployment.md` — overlay de production, séquence de démarrage, proxy TLS,
  limites.
- `docs/operations/backup-restore.md` — sauvegarde, vérification, restauration, rétention,
  exercice de reprise.
- `README.md` réécrit : il décrivait encore l'étape 5 sur un projet arrivé à l'étape 14.

## Tests

69 tests dans `services/api/tests/test_deployment.py`.

Ils pinnent les **refus** autant que les réussites, parce que ce sont les refus qui protègent :

- restauration sans `--yes` : rien ne se passe ;
- restauration d'une sauvegarde corrompue : refusée, sans option de contournement ;
- archive dont un membre sort du répertoire : refusée, répertoire frère inclus ;
- amorçage avant la migration 0012 : refusé ;
- `prune` ne supprime jamais une sauvegarde non vérifiée ;
- le mot de passe n'apparaît dans aucun argument de ligne de commande, et arrive par
  l'environnement ;
- l'overlay ne publie que le frontend, et exige un mot de passe de base réel ;
- le compose transmet bien les variables des étapes 11 à 13.

Le cycle complet sauvegarde → vérification → restauration est couvert de bout en bout, avec
`subprocess.run` simulé : la vraie fonction `run()` reste en place, donc sa traduction d'une
sortie non nulle en `BackupError` est réellement testée.

## Limites

- **Aucun test n'a été exécuté contre un PostgreSQL réel.** `pg_dump`, `pg_restore` et la
  migration sont validés par leurs arguments et par la logique environnante, pas contre un
  serveur. Les 3 tests d'intégration restent ignorés faute de `TEST_DATABASE_URL`.
- **La restauration n'a pas été éprouvée en conditions réelles.** Le cycle est testé avec un
  `pg_dump` simulé. Un exercice de reprise sur une base réelle reste à faire.
- **Le déploiement n'a pas été exécuté.** Docker n'est pas disponible sur ce poste : ni
  `docker compose up`, ni construction d'image, ni healthcheck réel. Les fichiers Compose
  sont validés syntaxiquement et par assertions, pas par un démarrage.
- **`docker compose config` n'a pas pu être exécuté**, qui plus est la commande qui aurait
  validé l'overlay fusionné. La vérification repose sur la lecture des deux fichiers, ce qui
  ne remplace pas la fusion réelle.
