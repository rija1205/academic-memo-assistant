"""Backup and restore for Academic Memo Assistant.

A thesis is years of work. Losing the database is not an inconvenience, so this tool treats a
backup as something that must be **verifiable**, not merely produced.

What is backed up, and why each part matters:

* the PostgreSQL database — the memoirs, the bibliography, the citations, the audit trails;
* the object storage — the imported source files, without which the provenance chain of a
  citation becomes a promise with nothing behind it;
* a manifest with a SHA-256 per artefact, so a restore can prove the archive was not corrupted.

Design decisions an operator needs to know:

* **format.** A ``pg_dump`` custom-format archive plus a tar of the storage directory. A plain
  SQL dump would work but is slower to restore and cannot be verified as a single object.
* **verification.** ``--verify`` recomputes every digest and reports what it found. A backup
  that was never verified is a hope, not a backup.
* **safety.** A restore refuses to run unless ``--yes`` is given, and it refuses outright when
  the manifest does not match the archive. There is no ``--force`` that skips that check.
* **no secret in the output.** Connection strings are never printed; only the database name.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MANIFEST_NAME = "manifest.json"
ARCHIVE_PREFIX = "ama-backup"


class BackupError(RuntimeError):
    """Raised when a backup or a restore cannot be completed safely."""


@dataclass(slots=True)
class Artefact:
    """One file in the backup, with the digest that proves it is intact."""

    name: str
    size_bytes: int
    sha256: str
    kind: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "kind": self.kind,
        }


@dataclass(slots=True)
class Manifest:
    """What a backup contains, when it was taken, and with which tool versions."""

    created_at: str
    database_name: str
    alembic_revision: str | None
    artefact_count: int
    total_bytes: int
    artefacts: list[Artefact] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "created_at": self.created_at,
            "database_name": self.database_name,
            "alembic_revision": self.alembic_revision,
            "artefact_count": self.artefact_count,
            "total_bytes": self.total_bytes,
            "artefacts": [artefact.as_dict() for artefact in self.artefacts],
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Manifest:
        return cls(
            created_at=str(payload.get("created_at", "")),
            database_name=str(payload.get("database_name", "")),
            alembic_revision=payload.get("alembic_revision"),
            artefact_count=int(payload.get("artefact_count", 0)),
            total_bytes=int(payload.get("total_bytes", 0)),
            artefacts=[
                Artefact(
                    name=str(item.get("name", "")),
                    size_bytes=int(item.get("size_bytes", 0)),
                    sha256=str(item.get("sha256", "")),
                    kind=str(item.get("kind", "")),
                )
                for item in payload.get("artefacts", [])
            ],
            notes=list(payload.get("notes", [])),
        )


def sha256_of(path: Path, chunk: int = 1024 * 1024) -> str:
    """Digest a file without loading it in memory: a source archive can be large."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def run(
    command: list[str],
    *,
    capture: bool = True,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run an external command, turning a failure into a readable error.

    ``env`` exists so a password can be handed to ``pg_dump`` through ``PGPASSWORD`` instead
    of through the command line, where any local user could read it from the process list.
    """
    try:
        return subprocess.run(
            command,
            check=check,
            capture_output=capture,
            text=True,
            env=env,
        )
    except FileNotFoundError as exc:
        raise BackupError(
            f"Outil introuvable : {command[0]}. Installez postgresql-client pour la base."
        ) from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip().splitlines()
        tail = detail[-1] if detail else "aucune sortie"
        raise BackupError(f"Échec de « {command[0]} » : {tail}") from exc


def database_name_from_url(url: str) -> str:
    """Extract only the database name, so a connection string is never printed."""
    without_query = url.split("?", 1)[0]
    name = without_query.rstrip("/").rsplit("/", 1)[-1]
    return name or "unknown"


#: Reads the Alembic marker table in a child interpreter. A subprocess is used because this
#: module is deliberately independent of the application's settings and event loop, and
#: because the backup tool is often run from the repository root where ``alembic.ini`` is not
#: in the working directory.
_REVISION_SNIPPET = """
import asyncio, sys
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

async def main():
    engine = create_async_engine(sys.argv[1])
    try:
        async with engine.connect() as connection:
            row = await connection.execute(text("SELECT version_num FROM alembic_version"))
            return row.first()
    finally:
        await engine.dispose()

row = asyncio.run(main())
print(row[0] if row else "")
"""


def current_revision(database_url: str) -> str | None:
    """The Alembic revision of the live database, recorded so a restore can be checked.

    Returns ``None`` when it cannot be determined. That is recorded as ``null`` in the
    manifest rather than treated as a failure: a backup is worth taking even when the
    revision could not be read, and the operator sees the gap in the manifest.
    """
    url, password = split_credentials(database_url)
    if password is not None:
        # asyncpg reads the password from the URL, so it is put back for the child only.
        url = url.replace("://", f"://:{password}@", 1)
    try:
        result = run(
            [sys.executable, "-c", _REVISION_SNIPPET, url], capture=True, check=False
        )
    except BackupError:
        return None
    if result.returncode != 0:
        return None
    return (result.stdout or "").strip() or None


def split_credentials(database_url: str) -> tuple[str, str | None]:
    """Separate a connection string into a credential-free URL and its password.

    ``pg_dump`` and ``pg_restore`` read the password from ``PGPASSWORD``, so the URL given to
    them must not carry it. Passing the full URL would put the password in the process list
    of the host, where any local user can read it for the lifetime of the command.
    """
    if "://" not in database_url:
        return database_url, None
    scheme, remainder = database_url.split("://", 1)
    if "@" not in remainder:
        return database_url, None
    credentials, host = remainder.split("@", 1)
    if ":" not in credentials:
        # A user with no password: nothing to hide, and nothing for PGPASSWORD to carry.
        return database_url, None
    return f"{scheme}://{host}", credentials.split(":", 1)[1]


def backup_database(database_url: str, destination: Path) -> Path:
    """Dump the database in the custom format, which is restorable and verifiable."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    url, password = split_credentials(database_url)
    env = dict(os.environ)
    if password is not None:
        env["PGPASSWORD"] = password
    run(
        [
            "pg_dump",
            "--format=custom",
            "--no-owner",
            "--no-privileges",
            f"--file={destination}",
            url,
        ],
        capture=True,
        env=env,
    )
    if not destination.exists() or destination.stat().st_size == 0:
        raise BackupError("pg_dump n'a produit aucun fichier.")
    return destination


def backup_storage(storage_path: Path | None, destination: Path) -> Path | None:
    """Archive the object storage when a local provider is in use."""
    if storage_path is None or not storage_path.exists():
        return None
    if not any(storage_path.iterdir()):
        # An empty directory is not worth an archive, and a manifest entry for it would be
        # noise an operator has to interpret.
        return None
    with tarfile.open(destination, "w:gz") as archive:
        for item in sorted(storage_path.iterdir()):
            archive.add(item, arcname=item.name)
    return destination


def create_backup(
    *,
    database_url: str,
    destination: Path,
    storage_path: Path | None = None,
    include_storage: bool = True,
) -> Manifest:
    """Take a complete backup and write its manifest next to the archive."""
    if not database_url:
        raise BackupError("DATABASE_URL est obligatoire.")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    directory = destination / f"{ARCHIVE_PREFIX}-{stamp}"
    directory.mkdir(parents=True, exist_ok=True)

    artefacts: list[Artefact] = []
    database_file = backup_database(database_url, directory / "database.dump")
    artefacts.append(
        Artefact(
            name=database_file.name,
            size_bytes=database_file.stat().st_size,
            sha256=sha256_of(database_file),
            kind="database",
        )
    )

    if include_storage:
        storage_file = backup_storage(storage_path, directory / "storage.tar.gz")
        if storage_file is not None:
            artefacts.append(
                Artefact(
                    name=storage_file.name,
                    size_bytes=storage_file.stat().st_size,
                    sha256=sha256_of(storage_file),
                    kind="storage",
                )
            )

    manifest = Manifest(
        created_at=datetime.now(UTC).isoformat(),
        database_name=database_name_from_url(database_url),
        alembic_revision=current_revision(database_url),
        artefact_count=len(artefacts),
        total_bytes=sum(artefact.size_bytes for artefact in artefacts),
        artefacts=artefacts,
    )
    (directory / MANIFEST_NAME).write_text(
        json.dumps(manifest.as_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return manifest


def read_manifest(directory: Path) -> Manifest:
    path = directory / MANIFEST_NAME
    if not path.exists():
        raise BackupError(
            f"Manifeste introuvable dans {directory}. Un dossier de sauvegarde sans "
            "manifeste ne peut pas être restauré en sécurité."
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BackupError(f"Manifeste illisible : {exc}") from exc
    return Manifest.from_dict(payload)


def verify_backup(directory: Path) -> tuple[bool, list[str]]:
    """Recompute every digest and report what does not match.

    Returns ``(ok, problems)`` rather than raising, so an operator can see the whole picture
    instead of the first problem.
    """
    problems: list[str] = []
    try:
        manifest = read_manifest(directory)
    except BackupError as exc:
        return False, [str(exc)]
    for artefact in manifest.artefacts:
        path = directory / artefact.name
        if not path.exists():
            problems.append(f"{artefact.name} : absent du dossier.")
            continue
        actual_size = path.stat().st_size
        if actual_size != artefact.size_bytes:
            problems.append(
                f"{artefact.name} : taille {actual_size} au lieu de {artefact.size_bytes}."
            )
        actual_digest = sha256_of(path)
        if actual_digest != artefact.sha256:
            problems.append(
                f"{artefact.name} : empreinte {actual_digest[:12]}… au lieu de "
                f"{artefact.sha256[:12]}… — fichier corrompu ou modifié."
            )
    if manifest.artefact_count != len(manifest.artefacts):
        problems.append("Le manifeste annonce un nombre d'artefacts incohérent.")
    return not problems, problems


def restore_backup(
    *,
    directory: Path,
    database_url: str,
    storage_path: Path | None = None,
    assume_yes: bool = False,
) -> dict[str, Any]:
    """Restore a backup after verifying it.

    A restore is irreversible, so it is refused without an explicit confirmation, and it is
    refused outright when verification fails: there is deliberately no override for that.
    """
    ok, problems = verify_backup(directory)
    if not ok:
        raise BackupError(
            "Sauvegarde non fiable, restauration refusée :\n  - "
            + "\n  - ".join(problems)
        )
    if not assume_yes:
        raise BackupError(
            "Restauration annulée. Relancez avec --yes une fois la perte de données "
            "acceptée : la base courante sera écrasée."
        )

    manifest = read_manifest(directory)
    database_file = directory / "database.dump"
    if not database_file.exists():
        raise BackupError("database.dump absent : rien à restaurer.")

    url, password = split_credentials(database_url)
    env = dict(os.environ)
    if password is not None:
        env["PGPASSWORD"] = password
    run(
        [
            "pg_restore",
            "--clean",
            "--if-exists",
            "--no-owner",
            "--no-privileges",
            "--dbname",
            url,
            str(database_file),
        ],
        capture=True,
        env=env,
    )

    storage_restored = False
    storage_file = directory / "storage.tar.gz"
    if storage_file is not None and storage_file.exists() and storage_path is not None:
        storage_path.mkdir(parents=True, exist_ok=True)
        with tarfile.open(storage_file, "r:gz") as archive:
            # Refuse a member that would escape the destination: a backup is still a file
            # that arrived from somewhere, and a path traversal in it must not be executed.
            # ``is_relative_to`` is used rather than a string prefix test, which would accept
            # a sibling directory whose name merely begins with the destination's name.
            root = storage_path.resolve()
            for member in archive.getmembers():
                target = (root / member.name).resolve()
                if not target.is_relative_to(root) or target == root:
                    raise BackupError(
                        f"Archive de stockage refusée : le membre « {member.name} » "
                        "sort du répertoire de destination."
                    )
            # ``filter="data"`` is a second line of defence, applied by the standard library
            # itself: it also rejects absolute paths, links pointing outside and special
            # files, which the traversal check above does not cover. The project targets
            # Python 3.12, the first version providing the parameter, so no fallback is
            # needed and the deprecated behaviour is never reached.
            archive.extractall(storage_path, filter="data")
        storage_restored = True

    return {
        "restored_at": datetime.now(UTC).isoformat(),
        "database": manifest.database_name,
        "alembic_revision": manifest.alembic_revision,
        "artefacts_restored": [artefact.name for artefact in manifest.artefacts],
        "storage_restored": storage_restored,
    }


def list_backups(root: Path) -> list[dict[str, Any]]:
    """Every backup directory under ``root``, newest first, with its verification state."""
    if not root.exists():
        return []
    results: list[dict[str, Any]] = []
    for candidate in sorted(root.iterdir(), reverse=True):
        if not candidate.is_dir() or not candidate.name.startswith(ARCHIVE_PREFIX):
            continue
        ok, problems = verify_backup(candidate)
        size = sum(
            item.stat().st_size for item in candidate.iterdir() if item.is_file()
        )
        results.append(
            {
                "name": candidate.name,
                "path": str(candidate),
                "created_at": datetime.fromtimestamp(
                    candidate.stat().st_mtime, tz=UTC
                ).isoformat(),
                "size_bytes": size,
                "verified": ok,
                "problems": problems,
            }
        )
    return results


def prune_backups(root: Path, keep: int) -> list[str]:
    """Delete the oldest verified backups beyond ``keep``.

    Only **verified** backups are ever deleted: a backup whose integrity is unknown is the
    only copy of something, and removing it on age alone would be reckless.
    """
    if keep < 1:
        raise BackupError("Conservez au moins une sauvegarde.")
    entries = list_backups(root)
    surplus = entries[keep:]
    removed: list[str] = []
    for entry in surplus:
        if not entry["verified"]:
            continue
        path = Path(entry["path"])
        shutil.rmtree(path, ignore_errors=True)
        removed.append(path.name)
    return removed


def _default_storage_path() -> Path | None:
    """Storage directory to include, or ``None`` when there is nothing local to save.

    The application's own variable is used rather than a second one: an operator should not
    have to keep two names for the same directory in step, and a backup pointed at the wrong
    one would look successful while leaving the sources behind.

    A path that does not exist yields ``None`` rather than a missing directory, so the tool
    does not have to be told whether the deployment uses a local or a remote provider.
    """
    configured = os.environ.get("SOURCE_LOCAL_STORAGE_PATH") or os.environ.get(
        "STORAGE_LOCAL_PATH"
    )
    if not configured:
        return None
    candidate = Path(configured)
    return candidate if candidate.is_dir() else None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="backup",
        description="Sauvegarde et restauration de Academic Memo Assistant.",
    )
    parser.add_argument(
        "command",
        choices=("create", "verify", "restore", "list", "prune"),
        help="Opération à effectuer.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(os.environ.get("BACKUP_ROOT", "backups")),
        help="Répertoire des sauvegardes. Par défaut BACKUP_ROOT, sinon « backups ».",
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", ""),
        help="URL de la base. Par défaut la variable DATABASE_URL.",
    )
    parser.add_argument(
        "--storage-path",
        type=Path,
        default=_default_storage_path(),
        help=(
            "Répertoire du stockage local des sources, à sauvegarder aussi. "
            "Par défaut STORAGE_LOCAL_PATH s'il existe, sinon-storage ignoré."
        ),
    )
    parser.add_argument(
        "--directory", type=Path, default=None, help="Dossier d'une sauvegarde existante."
    )
    parser.add_argument(
        "--yes", action="store_true", help="Confirme une restauration destructive."
    )
    parser.add_argument(
        "--keep",
        type=int,
        default=int(os.environ.get("BACKUP_KEEP", "14") or 14),
        help="Nombre de sauvegardes à conserver. Par défaut BACKUP_KEEP.",
    )
    parser.add_argument(
        "--no-storage", action="store_true", help="Ne pas inclure le stockage des sources."
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "create":
            manifest = create_backup(
                database_url=args.database_url,
                destination=args.root,
                storage_path=args.storage_path,
                include_storage=not args.no_storage,
            )
            print(f"Sauvegarde créée : {manifest.artefact_count} artefact(s), "
                  f"{manifest.total_bytes} octets.")
            for artefact in manifest.artefacts:
                print(f"  - {artefact.name} ({artefact.size_bytes} o, "
                      f"{artefact.sha256[:12]}…)")
            return 0
        if args.command == "verify":
            if args.directory is None:
                raise BackupError("--directory est requis pour vérifier.")
            ok, problems = verify_backup(args.directory)
            if ok:
                print("Sauvegarde intacte.")
                return 0
            print("Sauvegarde corrompue :")
            for problem in problems:
                print(f"  - {problem}")
            return 2
        if args.command == "restore":
            if args.directory is None:
                raise BackupError("--directory est requis pour restaurer.")
            result = restore_backup(
                directory=args.directory,
                database_url=args.database_url,
                storage_path=args.storage_path,
                assume_yes=args.yes,
            )
            print("Restauration terminée :", json.dumps(result, indent=2, ensure_ascii=False))
            return 0
        if args.command == "list":
            entries = list_backups(args.root)
            if not entries:
                print("Aucune sauvegarde.")
                return 0
            for entry in entries:
                state = "intacte" if entry["verified"] else "CORROMPUE"
                print(f"{entry['name']}  {entry['size_bytes']} o  {state}")
                for problem in entry["problems"]:
                    print(f"    {problem}")
            return 0
        if args.command == "prune":
            removed = prune_backups(args.root, args.keep)
            print(f"{len(removed)} sauvegarde(s) supprimée(s).")
            for name in removed:
                print(f"  - {name}")
            return 0
    except BackupError as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
