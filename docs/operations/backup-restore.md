# Sauvegarde et restauration

Un mémoire représente des années de travail. Traiter la sauvegarde comme une formalité est
la seule manière de découvrir qu'elle ne fonctionnait pas au moment où l'on en a besoin.
Ce document décrit ce que l'outil garantit, et ce qu'il refuse de faire.

## Ce qui est sauvegardé

| Artefact | Contenu | Sans lui |
|---|---|---|
| `database.dump` | mémoires, sources, extraits, bibliographie, citations, exports, audit, traces d'administration | le mémoire |
| `storage.tar.gz` | fichiers sources importés, en stockage local | la provenance d'une citation n'est plus vérifiable |
| `manifest.json` | horodatage, nom de la base, révision Alembic, SHA-256 de chaque artefact | aucune preuve d'intégrité |

Le format est `pg_dump --format=custom` : un objet unique, vérifiable et restaurable
directement, contrairement à un vidage SQL plat.

## Emplacement

Par défaut, les sauvegardes vont dans `backups/`, hors du dépôt. Ce choix est volontaire :
un dossier de sauvegarde versionné devient vite un dépôt lourd, et un secrets dans un dépôt
git est un secret compromis.

## Créer une sauvegarde

```bash
# Base et stockage local
python scripts/backup.py create --root backups \
  --database-url "postgresql://user:mdp@hote:5432/academic_memo" \
  --storage-path storage/uploads

# Les valeurs par défaut viennent de l'environnement
python scripts/backup.py create --root backups
```

Sans `--root`, `--database-url` ni `--storage-path`, l'outil lit `BACKUP_ROOT`,
`DATABASE_URL` et `SOURCE_LOCAL_STORAGE_PATH` : la sauvegarde suit donc la configuration de
l'application, sans qu'il faille la redéclarer.

En Docker, où la base est dans un conteneur :

```bash
docker compose exec -T postgres pg_dump -U academic_memo -Fc academic_memo > database.dump
```

Préférer pour un conteneur : l'outil Python suppose un `pg_dump` local.

Sortie typique :

```
Sauvegarde créée : 2 artefact(s), 4821190 octets.
  - database.dump (4711234 o, 9f2a1c8e4b73…)
  - storage.tar.gz (109956 o, 4c7d0e1a2b85…)
```

## Vérifier une sauvegarde

**À faire systématiquement.** Une sauvegarde jamais vérifiée est un espoir, pas une
sauvegarde.

```bash
python scripts/backup.py verify --root backups --directory backups/ama-backup-20260927T021500Z
```

L'outil recalcule chaque SHA-256 et compare taille et empreinte. Sortie :

- `Sauvegarde intacte.` — les deux cas ;
- `Sauvegarde corrompue :` suivi de la liste des artefacts fautifs.

Lister toutes les sauvegardes avec leur état :

```bash
python scripts/backup.py list --root backups
```

```
ama-backup-20260927T021500Z  4821190 o  intacte
ama-backup-20260926T021500Z  4790112 o  CORROMPUE
    database.dump : empreinte 000000000000… au lieu de 4c7d0e1a2b85… — fichier corrompu ou modifié.
```

## Restaurer

```bash
# Sans --yes, la restauration est refusée. C'est voulu.
python scripts/backup.py restore --root backups \
  --directory backups/ama-backup-20260927T021500Z \
  --storage-path storage/uploads

# Une fois la perte de données acceptée
python scripts/backup.py restore --root backups \
  --directory backups/ama-backup-20260927T021500Z \
  --storage-path storage/uploads --yes
```

Trois refus, sans contournement possible :

1. **Pas de `--yes`** ⇒ rien n'est fait.
2. **Manifeste absent ou Empreintes non concordantes** ⇒ restauration refusée. Il n'existe
   pas d'option `--force` : une archive corrompue ne doit pas pouvoir être restaurée.
3. **Archive de stockage contenant un chemin qui sort du répertoire** ⇒ refus. Une
   sauvegarde reste un fichier venu d'ailleurs ; une traversée de répertoire qu'elle contient
   ne doit pas être exécutée.

Après restauration, la révision Alembic est celle **de la sauvegarde**, pas celle du code.
Si le code a avancé, appliquer les migrations manquantes :

```bash
alembic upgrade head
```

## Rétention

```bash
python scripts/backup.py prune --root backups --keep 14
```

**Seules les sauvegardes vérifiées sont supprimées.** Une sauvegarde dont l'intégrité est
inconnue est peut-être la seule copie de quelque chose : la supprimer pour son âge serait
imprudent. Le résultat est donc parfois « 2 supprimées » pour `--keep 14`, si les plus
anciennes n'ont pas pu être vérifiées.

## Automatisation

Tâche quotidienne sous Windows (Planificateur de tâches) ou cron sous Linux.

```bash
0 3 * * * cd /opt/academic-memo-assistant && \
  python scripts/backup.py create --root /var/backups/ama && \
  python scripts/backup.py prune --root /var/backups/ama --keep 14 && \
  python scripts/backup.py list --root /var/backups/ama
```

La vérification est intégrée : si la sauvegarde du jour est corrompue, `list` l'affiche et le
`prune` ne la supprimera pas.

## Copie hors site

Une sauvegarde sur le même disque que la base ne survit pas à la perte du disque.

```bash
python scripts/backup.py create --root /var/backups/ama
rsync -a --delete /var/backups/ama/ distant:/sauvegardes/ama/
```

À tester régulièrement : une restauration jamais tentée n'est pas une restauration.

## Exercice de reprise

Trimestriellement, sur une machine jetable :

```bash
python scripts/backup.py create --root /tmp/essai
docker run -d --name ama-restore -e POSTGRES_PASSWORD=x -p 55432:5432 postgres:16
# attendre la disponibilité, puis :
python scripts/backup.py restore --root /tmp/essai \
  --directory /tmp/essai/ama-backup-<horodatage> \
  --database-url "postgresql://postgres:x@localhost:55432/postgres" --yes
alembic current   # doit indiquer 0012_security_admin
```

Si cet exercice n'a jamais été fait, la restauration n'est pas prouvée.
