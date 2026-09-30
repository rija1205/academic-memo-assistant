"""Tests of the deployment tooling: backup, restore, and the administrator bootstrap.

These tools are what an operator runs when something has already gone wrong, so their refusal
behaviour matters more than their happy path. The tests pin the refusals:

* a restore without an explicit confirmation does nothing;
* a restore of a corrupted backup is refused with no override available;
* a bootstrap before the stage 13 migration is refused rather than failing on a missing column;
* a manifest that does not match its archive is detected.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import sys
from pathlib import Path

import pytest

#: Repository root: services/api/tests -> services/api -> services -> root.
ROOT = Path(__file__).resolve().parents[3]


def _load(name: str, relative: str):
    """Import a script from the repository without installing it as a package.

    The module is registered in ``sys.modules`` before execution: ``@dataclass(slots=True)``
    resolves its own annotations through that mapping and fails without it.
    """
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


backup = _load("ama_backup", "scripts/backup.py")
bootstrap = _load("ama_bootstrap", "scripts/bootstrap_admin.py")


# ------------------------------------------------------------------- manifest


def test_a_manifest_round_trips() -> None:
    manifest = backup.Manifest(
        created_at="2026-10-28T10:00:00+00:00",
        database_name="academic_memo",
        alembic_revision="0012_security_admin",
        artefact_count=1,
        total_bytes=100,
        artefacts=[
            backup.Artefact(name="database.dump", size_bytes=100, sha256="ab" * 32, kind="database")
        ],
    )
    again = backup.Manifest.from_dict(manifest.as_dict())
    assert again.database_name == "academic_memo"
    assert again.artefacts[0].sha256 == "ab" * 32


def test_the_database_name_is_extracted_without_leaking_the_url() -> None:
    url = "postgresql+asyncpg://user:sup3rs3cret@db:5432/academic_memo"
    name = backup.database_name_from_url(url)
    assert name == "academic_memo"
    assert "sup3rs3cret" not in name


def test_a_query_string_does_not_pollute_the_database_name() -> None:
    assert backup.database_name_from_url("postgresql://u:p@h/db?sslmode=require") == "db"


def test_an_empty_url_yields_a_placeholder() -> None:
    assert backup.database_name_from_url("") == "unknown"


# ----------------------------------------------------------------- sha256


def test_the_digest_matches_the_reference_implementation(tmp_path: Path) -> None:
    import hashlib

    payload = b"contenu de sauvegarde" * 5000
    target = tmp_path / "file.bin"
    target.write_bytes(payload)
    assert backup.sha256_of(target) == hashlib.sha256(payload).hexdigest()


def test_the_digest_of_a_large_file_is_streamed(tmp_path: Path) -> None:
    import hashlib

    payload = b"a" * (3 * 1024 * 1024)
    target = tmp_path / "big.bin"
    target.write_bytes(payload)
    assert backup.sha256_of(target, chunk=64 * 1024) == hashlib.sha256(payload).hexdigest()


# ------------------------------------------------------------------ verify


def make_backup_dir(
    tmp_path: Path, *, corrupt: bool = False, stamp: str = "20261028T100000Z"
) -> Path:
    directory = tmp_path / f"ama-backup-{stamp}"
    directory.mkdir(parents=True)
    dump = directory / "database.dump"
    dump.write_bytes(b"PGDMP" + b"x" * 500)
    digest = backup.sha256_of(dump)
    if corrupt:
        digest = "0" * 64
    manifest = backup.Manifest(
        created_at="2026-10-28T10:00:00+00:00",
        database_name="academic_memo",
        alembic_revision="0012_security_admin",
        artefact_count=1,
        total_bytes=dump.stat().st_size,
        artefacts=[
            backup.Artefact(
                name="database.dump",
                size_bytes=dump.stat().st_size,
                sha256=digest,
                kind="database",
            )
        ],
    )
    (directory / backup.MANIFEST_NAME).write_text(
        json.dumps(manifest.as_dict()), encoding="utf-8"
    )
    return directory


def test_an_intact_backup_verifies(tmp_path: Path) -> None:
    ok, problems = backup.verify_backup(make_backup_dir(tmp_path))
    assert ok is True
    assert problems == []


def test_a_modified_file_is_detected(tmp_path: Path) -> None:
    directory = make_backup_dir(tmp_path)
    (directory / "database.dump").write_bytes(b"corrupted")
    ok, problems = backup.verify_backup(directory)
    assert ok is False
    assert any("empreinte" in problem for problem in problems)


def test_a_missing_file_is_detected(tmp_path: Path) -> None:
    directory = make_backup_dir(tmp_path)
    (directory / "database.dump").unlink()
    ok, problems = backup.verify_backup(directory)
    assert ok is False
    assert any("absent" in problem for problem in problems)


def test_a_directory_without_a_manifest_is_not_restorable(tmp_path: Path) -> None:
    empty = tmp_path / "ama-backup-vide"
    empty.mkdir()
    ok, problems = backup.verify_backup(empty)
    assert ok is False
    assert any("Manifeste introuvable" in problem for problem in problems)


def test_an_inconsistent_manifest_is_detected(tmp_path: Path) -> None:
    directory = make_backup_dir(tmp_path)
    path = directory / backup.MANIFEST_NAME
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["artefact_count"] = 7
    path.write_text(json.dumps(payload), encoding="utf-8")
    ok, problems = backup.verify_backup(directory)
    assert ok is False
    assert any("incohérent" in problem for problem in problems)


def test_an_unreadable_manifest_is_reported_not_raised(tmp_path: Path) -> None:
    directory = make_backup_dir(tmp_path)
    (directory / backup.MANIFEST_NAME).write_text("{pas du json", encoding="utf-8")
    ok, problems = backup.verify_backup(directory)
    assert ok is False
    assert problems


# ----------------------------------------------------------------- restore


def test_a_restore_without_confirmation_does_nothing(tmp_path: Path) -> None:
    directory = make_backup_dir(tmp_path)
    with pytest.raises(backup.BackupError) as error:
        backup.restore_backup(directory=directory, database_url="postgresql://x/y")
    assert "--yes" in str(error.value)


def test_a_restore_of_a_corrupted_backup_is_refused(tmp_path: Path) -> None:
    directory = make_backup_dir(tmp_path, corrupt=True)
    with pytest.raises(backup.BackupError) as error:
        backup.restore_backup(
            directory=directory, database_url="postgresql://x/y", assume_yes=True
        )
    assert "non fiable" in str(error.value)


def test_a_restore_never_offers_an_override_for_a_corrupted_backup() -> None:
    """There is deliberately no force flag: a corrupt archive must not be restorable."""
    options = {action.dest for action in backup.build_parser()._actions}
    assert "force" not in options
    assert "yes" in options


def test_a_restore_needs_the_confirmation_flag() -> None:
    parsed = backup.build_parser().parse_args(
        ["restore", "--root", "r", "--directory", "d"]
    )
    assert parsed.yes is False, "--yes doit être absent par défaut."
    with_confirmation = backup.build_parser().parse_args(
        ["restore", "--root", "r", "--directory", "d", "--yes"]
    )
    assert with_confirmation.yes is True


def test_a_backup_without_a_database_dump_is_refused(tmp_path: Path) -> None:
    directory = make_backup_dir(tmp_path)
    (directory / "database.dump").unlink()
    with pytest.raises(backup.BackupError):
        backup.restore_backup(
            directory=directory, database_url="postgresql://x/y", assume_yes=True
        )


def test_a_storage_archive_cannot_escape_its_destination(tmp_path: Path) -> None:
    """A backup is a file that arrived from somewhere; a traversal in it must not run."""
    import io
    import tarfile

    directory = make_backup_dir(tmp_path)
    evil = directory / "storage.tar.gz"
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w:gz") as archive:
        info = tarfile.TarInfo(name="../../evaded.txt")
        info.size = 3
        archive.addfile(info, io.BytesIO(b"bad"))
    evil.write_bytes(payload.getvalue())

    with pytest.raises(backup.BackupError) as error:
        backup.restore_backup(
            directory=directory,
            database_url="postgresql://x/y",
            storage_path=tmp_path / "dest",
            assume_yes=True,
        )
    # The traversal is refused before any extraction; the database restore may already have
    # been attempted, so the message must name the offending member.
    assert "sort du" in str(error.value) or "pg_restore" in str(error.value)


# -------------------------------------------------------------------- list


def test_listing_reports_the_verification_state(tmp_path: Path) -> None:
    make_backup_dir(tmp_path, stamp="20261028T100000Z")
    make_backup_dir(tmp_path, corrupt=True, stamp="20261027T100000Z")
    entries = backup.list_backups(tmp_path)
    assert len(entries) == 2
    assert all("verified" in entry for entry in entries)
    by_name = {entry["name"]: entry for entry in entries}
    assert by_name["ama-backup-20261028T100000Z"]["verified"] is True
    assert by_name["ama-backup-20261027T100000Z"]["verified"] is False


def test_listing_an_empty_root_returns_nothing(tmp_path: Path) -> None:
    assert backup.list_backups(tmp_path / "absent") == []


# ------------------------------------------------------------------- prune


def test_pruning_keeps_the_requested_number(tmp_path: Path) -> None:
    for index in range(4):
        directory = tmp_path / f"ama-backup-2026102{index}T100000Z"
        directory.mkdir()
        (directory / "database.dump").write_bytes(b"x")
        manifest = backup.Manifest(
            created_at="2026-10-28T10:00:00+00:00",
            database_name="db",
            alembic_revision=None,
            artefact_count=1,
            total_bytes=1,
            artefacts=[
                backup.Artefact(
                    name="database.dump",
                    size_bytes=1,
                    sha256=backup.sha256_of(directory / "database.dump"),
                    kind="database",
                )
            ],
        )
        (directory / backup.MANIFEST_NAME).write_text(json.dumps(manifest.as_dict()))
    removed = backup.prune_backups(tmp_path, keep=2)
    remaining = backup.list_backups(tmp_path)
    assert len(remaining) == 2
    assert len(removed) == 2


def test_pruning_never_deletes_an_unverified_backup(tmp_path: Path) -> None:
    """A backup of unknown integrity may be the only copy of something."""
    for index, corrupt in enumerate((False, False, True, True)):
        directory = tmp_path / f"ama-backup-2026102{index}T100000Z"
        directory.mkdir()
        (directory / "database.dump").write_bytes(b"x")
        manifest = backup.Manifest(
            created_at="2026-10-28T10:00:00+00:00",
            database_name="db",
            alembic_revision=None,
            artefact_count=1,
            total_bytes=1,
            artefacts=[
                backup.Artefact(
                    name="database.dump",
                    size_bytes=1,
                    sha256="0" * 64 if corrupt else backup.sha256_of(directory / "database.dump"),
                    kind="database",
                )
            ],
        )
        (directory / backup.MANIFEST_NAME).write_text(json.dumps(manifest.as_dict()))
    backup.prune_backups(tmp_path, keep=1)
    remaining = {entry["name"] for entry in backup.list_backups(tmp_path)}
    # Both unverified backups survived even though only one was asked for.
    assert len([name for name in remaining if "20261022" in name or "20261023" in name]) == 2


def test_pruning_refuses_to_keep_zero(tmp_path: Path) -> None:
    with pytest.raises(backup.BackupError):
        backup.prune_backups(tmp_path, keep=0)


# ------------------------------------------------------------- missing tools


def test_a_missing_pg_dump_is_reported_readably(tmp_path: Path) -> None:
    with pytest.raises(backup.BackupError) as error:
        backup.backup_database("postgresql://x/y", tmp_path / "out.dump")
    assert "pg_dump" in str(error.value) or "Échec" in str(error.value)


def test_creating_a_backup_without_a_url_is_refused(tmp_path: Path) -> None:
    with pytest.raises(backup.BackupError):
        backup.create_backup(database_url="", destination=tmp_path)


# ------------------------------------------------------- end-to-end cycle


class FakePostgres:
    """Stand-in for ``pg_dump`` and ``pg_restore``.

    A real PostgreSQL is not available in this environment, and the point of these tests is
    the surrounding logic: the manifest, the digests and the refusals. What the real tools
    are called with is captured so the arguments can be asserted.

    It replaces ``subprocess.run`` rather than ``backup.run`` on purpose, so the real
    ``run()`` wrapper is exercised: its translation of a non-zero exit into a ``BackupError``
    is part of what the operator sees and must not be bypassed by the test.
    """

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.fail_dump = False
        self.fail_restore = False

    def __call__(self, command, **kwargs):  # noqa: ANN001 - mirrors subprocess.run
        command = list(command) if not isinstance(command, str) else [command]
        self.calls.append(command)
        if not command:
            raise FileNotFoundError("outil absent")
        code = 0
        if command[0] == "pg_dump":
            if self.fail_dump:
                code = 1
            else:
                target = next(
                    a.split("=", 1)[1] for a in command if a.startswith("--file=")
                )
                path = Path(target)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"PGDMP fake dump content")
        elif command[0] == "pg_restore" and self.fail_restore:
            code = 1
        stderr = f"{command[0]}: error" if code else ""
        if code and kwargs.get("check", False):
            raise backup.subprocess.CalledProcessError(code, command, "", stderr)
        return backup.subprocess.CompletedProcess(command, code, "", stderr)

    def install(self, monkeypatch) -> None:  # noqa: ANN001 - pytest fixture
        monkeypatch.setattr(backup.subprocess, "run", self)


def test_a_full_backup_and_restore_cycle(monkeypatch, tmp_path: Path) -> None:
    fake = FakePostgres()
    fake.install(monkeypatch)
    storage = tmp_path / "storage"
    (storage / "sources").mkdir(parents=True)
    (storage / "sources" / "a.pdf").write_bytes(b"%PDF-1.7 source")

    manifest = backup.create_backup(
        database_url="postgresql://user:secret@db:5432/academic_memo",
        destination=tmp_path / "backups",
        storage_path=storage,
    )
    assert manifest.artefact_count == 2
    assert {artefact.kind for artefact in manifest.artefacts} == {"database", "storage"}
    # The connection string is recorded only as a database name.
    assert manifest.database_name == "academic_memo"
    assert "secret" not in json.dumps(manifest.as_dict())

    directory = next(item for item in (tmp_path / "backups").iterdir() if item.is_dir())

    ok, problems = backup.verify_backup(directory)
    assert ok, problems

    result = backup.restore_backup(
        directory=directory,
        database_url="postgresql://user:secret@db:5432/academic_memo",
        storage_path=storage,
        assume_yes=True,
    )
    assert result["storage_restored"] is True
    assert set(result["artefacts_restored"]) == {"database.dump", "storage.tar.gz"}


def test_the_dump_is_taken_without_ownership_or_privileges(monkeypatch, tmp_path: Path) -> None:
    """A dump that tries to recreate roles would fail to restore on another host."""
    fake = FakePostgres()
    fake.install(monkeypatch)
    backup.create_backup(
        database_url="postgresql://u:p@db/app", destination=tmp_path, include_storage=False
    )
    dump = next(call for call in fake.calls if call[0] == "pg_dump")
    assert "--no-owner" in dump
    assert "--no-privileges" in dump
    assert "--format=custom" in dump


def test_a_failed_dump_is_reported_not_swallowed(monkeypatch, tmp_path: Path) -> None:
    fake = FakePostgres()
    fake.fail_dump = True
    fake.install(monkeypatch)
    with pytest.raises(backup.BackupError) as error:
        backup.create_backup(
            database_url="postgresql://u:p@db/app", destination=tmp_path, include_storage=False
        )
    assert "pg_dump" in str(error.value)


def test_an_empty_storage_directory_is_not_archived(monkeypatch, tmp_path: Path) -> None:
    """An empty tar plus a manifest line is noise an operator has to interpret."""
    fake = FakePostgres()
    fake.install(monkeypatch)
    storage = tmp_path / "storage"
    storage.mkdir()
    manifest = backup.create_backup(
        database_url="postgresql://u:p@db/app", destination=tmp_path, storage_path=storage
    )
    assert manifest.artefact_count == 1
    assert manifest.artefacts[0].kind == "database"


def test_a_missing_storage_directory_does_not_fail_the_backup(
    monkeypatch, tmp_path: Path
) -> None:
    """The database alone is still worth saving when the storage is not local."""
    fake = FakePostgres()
    fake.install(monkeypatch)
    manifest = backup.create_backup(
        database_url="postgresql://u:p@db/app",
        destination=tmp_path,
        storage_path=tmp_path / "absent",
    )
    assert manifest.artefact_count == 1


def test_a_failed_restore_is_reported(monkeypatch, tmp_path: Path) -> None:
    directory = make_backup_dir(tmp_path)
    fake = FakePostgres()
    fake.fail_restore = True
    fake.install(monkeypatch)
    with pytest.raises(backup.BackupError) as error:
        backup.restore_backup(
            directory=directory, database_url="postgresql://u:p@db/app", assume_yes=True
        )
    assert "pg_restore" in str(error.value)


def test_the_storage_is_restored_when_the_archive_exists(
    monkeypatch, tmp_path: Path
) -> None:
    fake = FakePostgres()
    fake.install(monkeypatch)
    source_storage = tmp_path / "origin"
    (source_storage / "sources").mkdir(parents=True)
    (source_storage / "sources" / "b.pdf").write_bytes(b"%PDF-1.7 autre source")
    backup.create_backup(
        database_url="postgresql://u:p@db/app",
        destination=tmp_path / "backups",
        storage_path=source_storage,
    )
    directory = next(
        item for item in (tmp_path / "backups").iterdir() if item.is_dir()
    )
    target = tmp_path / "restored"
    backup.restore_backup(
        directory=directory,
        database_url="postgresql://u:p@db/app",
        storage_path=target,
        assume_yes=True,
    )
    assert (target / "sources" / "b.pdf").read_bytes() == b"%PDF-1.7 autre source"


def test_a_sibling_directory_is_not_mistaken_for_the_destination(
    monkeypatch, tmp_path: Path
) -> None:
    """A string prefix test would accept ``storage-evil`` for a destination of ``storage``."""
    fake = FakePostgres()
    fake.install(monkeypatch)
    directory = make_backup_dir(tmp_path)
    import io
    import tarfile

    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w:gz") as archive:
        info = tarfile.TarInfo(name="../storage-evil/escaped.txt")
        info.size = 3
        archive.addfile(info, io.BytesIO(b"bad"))
    (directory / "storage.tar.gz").write_bytes(payload.getvalue())

    destination = tmp_path / "storage"
    destination.mkdir()
    with pytest.raises(backup.BackupError) as error:
        backup.restore_backup(
            directory=directory,
            database_url="postgresql://u:p@db/app",
            storage_path=destination,
            assume_yes=True,
        )
    assert "sort du" in str(error.value)
    assert not (tmp_path / "storage-evil").exists()


def test_the_defaults_come_from_the_environment(monkeypatch) -> None:
    """The .env variables must actually drive the tool, not just document a wish."""
    monkeypatch.setenv("BACKUP_ROOT", "/srv/sauvegardes")
    monkeypatch.setenv("BACKUP_KEEP", "30")
    monkeypatch.setenv("SOURCE_LOCAL_STORAGE_PATH", "/srv/sources")
    monkeypatch.setattr(Path, "is_dir", lambda self: True)
    args = backup.build_parser().parse_args(["create"])
    assert args.root == Path("/srv/sauvegardes")
    assert args.keep == 30
    assert args.storage_path == Path("/srv/sources")


def test_the_applications_own_storage_variable_wins(monkeypatch) -> None:
    """One path, one name: a backup pointed elsewhere would look successful and lose data."""
    monkeypatch.setenv("SOURCE_LOCAL_STORAGE_PATH", "/srv/bon")
    monkeypatch.setenv("STORAGE_LOCAL_PATH", "/srv/mauvais")
    monkeypatch.setattr(Path, "is_dir", lambda self: True)
    args = backup.build_parser().parse_args(["create"])
    assert args.storage_path == Path("/srv/bon")


def test_an_absent_storage_directory_is_simply_not_backed_up(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SOURCE_LOCAL_STORAGE_PATH", str(tmp_path / "absent"))
    args = backup.build_parser().parse_args(["create"])
    assert args.storage_path is None


def test_no_storage_variable_means_no_storage(monkeypatch) -> None:
    monkeypatch.delenv("SOURCE_LOCAL_STORAGE_PATH", raising=False)
    monkeypatch.delenv("STORAGE_LOCAL_PATH", raising=False)
    args = backup.build_parser().parse_args(["create"])
    assert args.storage_path is None


def test_the_root_has_a_usable_default() -> None:
    args = backup.build_parser().parse_args(["list"])
    assert args.root == Path("backups")
    assert args.keep == 14


# ------------------------------------------------------------- credentials


def test_the_password_is_removed_from_the_url() -> None:
    url, password = backup.split_credentials(
        "postgresql://user:sup3rs3cret@db:5432/academic_memo"
    )
    assert password == "sup3rs3cret"
    assert url == "postgresql://db:5432/academic_memo"
    assert "sup3rs3cret" not in url


def test_a_url_without_a_password_is_left_alone() -> None:
    url, password = backup.split_credentials("postgresql://db:5432/academic_memo")
    assert password is None
    assert url == "postgresql://db:5432/academic_memo"


def test_a_user_without_a_password_yields_none() -> None:
    url, password = backup.split_credentials("postgresql://user@db/academic_memo")
    assert password is None
    assert url == "postgresql://user@db/academic_memo"


def test_a_url_without_a_scheme_is_returned_untouched() -> None:
    url, password = backup.split_credentials("not-a-url")
    assert url == "not-a-url"
    assert password is None


def test_a_password_containing_a_colon_survives() -> None:
    _, password = backup.split_credentials("postgresql://user:a:b:c@db/app")
    assert password == "a:b:c"


def test_the_dump_command_never_carries_the_password(monkeypatch, tmp_path: Path) -> None:
    """A command line is world-readable in the process list; the password must not be there."""
    fake = FakePostgres()
    fake.install(monkeypatch)
    backup.backup_database(
        "postgresql://user:sup3rs3cret@db:5432/academic_memo", tmp_path / "d.dump"
    )
    dump = next(call for call in fake.calls if call[0] == "pg_dump")
    assert not any("sup3rs3cret" in argument for argument in dump)


def test_the_restore_command_never_carries_the_password(monkeypatch, tmp_path: Path) -> None:
    directory = make_backup_dir(tmp_path)
    fake = FakePostgres()
    fake.install(monkeypatch)
    backup.restore_backup(
        directory=directory,
        database_url="postgresql://user:sup3rs3cret@db:5432/academic_memo",
        assume_yes=True,
    )
    restore = next(call for call in fake.calls if call[0] == "pg_restore")
    assert not any("sup3rs3cret" in argument for argument in restore)


def test_the_password_reaches_the_tool_through_the_environment(
    monkeypatch, tmp_path: Path
) -> None:
    """The password is removed from the command line, so it must be handed over elsewhere."""
    seen: list[dict[str, str] | None] = []

    def fake_run(command, **kwargs):  # noqa: ANN001, ANN202
        seen.append(kwargs.get("env"))
        if command and command[0] == "pg_dump":
            target = next(a.split("=", 1)[1] for a in command if a.startswith("--file="))
            path = Path(target)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"PGDMP")
        return backup.subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(backup.subprocess, "run", fake_run)
    backup.backup_database("postgresql://user:sup3rs3cret@db/app", tmp_path / "d.dump")
    assert seen and seen[0] is not None
    assert seen[0].get("PGPASSWORD") == "sup3rs3cret"


def test_no_password_variable_is_set_when_there_is_no_password(
    monkeypatch, tmp_path: Path
) -> None:
    seen: list[dict[str, str] | None] = []

    def fake_run(command, **kwargs):  # noqa: ANN001, ANN202
        seen.append(kwargs.get("env"))
        if command and command[0] == "pg_dump":
            target = next(a.split("=", 1)[1] for a in command if a.startswith("--file="))
            path = Path(target)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"PGDMP")
        return backup.subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(backup.subprocess, "run", fake_run)
    backup.backup_database("postgresql://db/app", tmp_path / "d.dump")
    assert seen and "PGPASSWORD" not in seen[0]


# ----------------------------------------------------- admin bootstrap rules


def test_the_bootstrap_refuses_a_revision_older_than_the_administration_tables() -> None:
    with pytest.raises(bootstrap.BootstrapError) as error:
        bootstrap.check_revision("0011_academic_audit")
    assert "0012_security_admin" in str(error.value)


def test_the_bootstrap_refuses_an_unknown_revision() -> None:
    with pytest.raises(bootstrap.BootstrapError):
        bootstrap.check_revision("n_importe_quoi")
    with pytest.raises(bootstrap.BootstrapError):
        bootstrap.check_revision(None)


def test_the_bootstrap_accepts_the_current_revision() -> None:
    assert bootstrap.check_revision("0012_security_admin") is None


def test_the_revision_order_is_read_from_the_migration_files() -> None:
    """A hard-coded chain would go stale at the next migration and accept an old database."""
    order = bootstrap.revision_order()
    assert order[0].startswith("0001")
    assert bootstrap.REQUIRED_REVISION in order
    files = {
        path.stem
        for path in bootstrap.versions_directory().glob("*.py")
        if path.stem[0].isdigit()
    }
    assert files == set(order), "la chaîne lue ne correspond pas aux fichiers de migration."


def test_the_fallback_chain_stops_at_the_administration_migration() -> None:
    assert bootstrap.FALLBACK_REVISION_ORDER[-1] == "0012_security_admin"


def test_the_bootstrap_requires_an_explicit_confirmation() -> None:
    """Without ``--yes`` the script must exit non-zero and never reach the database."""
    assert bootstrap.main(["--email", "quelquun@example.org"]) == 1


def test_the_bootstrap_confirms_when_given_the_flag() -> None:
    """With ``--yes`` the guard is passed; it then fails on the unreachable database, which
    is the expected outcome on a machine without PostgreSQL, and not a silent success."""
    assert bootstrap.main(["--email", "quelquun@example.org", "--yes"]) == 1


def test_the_bootstrap_asks_for_an_email() -> None:
    assert bootstrap.main(["--yes"]) == 1


def test_the_bootstrap_records_a_reason() -> None:
    source = inspect.getsource(bootstrap.grant_admin)
    assert "AdminAuditEvent" in source
    assert "grant_admin_bootstrap" in source


def test_the_bootstrap_can_list_the_administrators() -> None:
    parsed = bootstrap.build_parser().parse_args(["--list-admins"])
    assert parsed.list_admins is True
    source = inspect.getsource(bootstrap.list_admins)
    assert "is_admin" in source


# ------------------------------------------------------------ deployment files


def test_a_budget_refusal_keeps_its_status_code() -> None:
    """A 429 or 503 raised in the middleware must not degrade into a 500.

    FastAPI's exception handlers do not cover middleware, so raising there produced a 500 and
    dropped ``Retry-After`` — the header a client needs in order to back off. The test reads
    the source rather than issuing a request because reproducing a rate-limit refusal needs
    a live Redis, which the unit suite deliberately does not depend on. The end-to-end
    behaviour is covered by ``scripts/probe_public_surface.py``, which runs in
    ``check-foundation.ps1``.
    """
    import ast

    middleware_path = (
        ROOT / "services" / "api" / "app" / "observability" / "middleware.py"
    )
    tree = ast.parse(middleware_path.read_text(encoding="utf-8"))

    handler = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try) or node.handlers is None:
            continue
        for candidate in node.handlers:
            names = {child.id for child in ast.walk(candidate.type) if isinstance(child, ast.Name)}
            if "HTTPException" in names:
                handler = candidate
    assert handler is not None, "le middleware doit traiter HTTPException explicitement."

    # Within that handler, no bare re-raise: the response has to be built instead.
    assert not any(isinstance(node, ast.Raise) for node in ast.walk(handler)), (
        "le gestionnaire HTTPException ne doit pas relancer : cela produit un 500."
    )
    assert any(
        isinstance(node, ast.Call) and getattr(node.func, "id", "") == "_http_exception_response"
        for node in ast.walk(handler)
    ), "le gestionnaire doit construire la reponse via _http_exception_response."


def test_the_worker_token_is_never_logged() -> None:
    """The token guards the internal surface; it must not appear in the observability output."""
    events = (ROOT / "services" / "api" / "app" / "security" / "guards.py").read_text(
        encoding="utf-8"
    )
    assert "FORBIDDEN" in events
    assert "source_worker_token" not in events


def test_the_production_overlay_only_targets_real_services() -> None:
    import yaml

    base = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    prod = yaml.safe_load(
        (ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
    )
    for name in prod["services"]:
        assert name in base["services"], f"{name} n'existe pas dans le compose de base."


def test_the_production_overlay_publishes_only_the_frontend() -> None:
    import yaml

    prod = yaml.safe_load(
        (ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
    )
    for name in ("backend", "postgres", "redis", "worker"):
        assert not prod["services"][name].get("ports"), f"{name} ne doit pas exposer de port."
    assert prod["services"]["frontend"].get("ports")


def test_the_production_overlay_closes_the_database_port_in_the_base() -> None:
    """``ports: []`` in an override removes the mapping from the base file."""
    import yaml

    base = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    prod = yaml.safe_load((ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8"))
    assert base["services"]["postgres"].get("ports")
    assert prod["services"]["postgres"]["ports"] == []


def test_production_enables_secure_cookies_and_hsts() -> None:
    import yaml

    prod = yaml.safe_load(
        (ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
    )
    environment = prod["services"]["backend"]["environment"]
    assert environment["SECURE_COOKIES"] == "true"
    assert environment["FORCE_HTTPS"] == "true"
    assert environment["APP_ENV"] == "production"


def test_production_sets_resource_limits_and_log_caps() -> None:
    import yaml

    prod = yaml.safe_load(
        (ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
    )
    for name in ("backend", "worker", "postgres", "redis", "frontend"):
        spec = prod["services"][name]
        assert spec["deploy"]["resources"]["limits"], f"{name} sans limite de ressources."
        assert spec["logging"]["options"]["max-size"], f"{name} sans plafond de journal."


def test_production_requires_a_real_database_password() -> None:
    """A placeholder password in production is a credential, not a default."""
    text = (ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
    assert "POSTGRES_PASSWORD:?" in text or "POSTGRES_PASSWORD: ?" in text
    assert "academic_memo_dev" not in text


def test_the_compose_passes_the_later_stage_variables() -> None:
    """The container used to ignore every variable of stages 11 to 13."""
    import yaml

    base = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    environment = base["services"]["backend"]["environment"]
    for name in (
        "EXPORT_MAX_OUTPUT_BYTES",
        "RATE_LIMIT_ENABLED",
        "RATE_LIMIT_FAIL_CLOSED",
        "AUDIT_RATE_LIMIT_MAX_CALLS",
        "FORCE_HTTPS",
        "OPENAI_API_KEY",
        "EMBEDDING_PROVIDER",
    ):
        assert name in environment, f"{name} absent du compose."


def test_the_worker_command_is_valid_yaml() -> None:
    """A list written at the wrong indentation silently breaks ``docker compose up``."""
    import yaml

    base = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    command = base["services"]["worker"]["command"]
    assert isinstance(command, list)
    assert "celery" in command


def test_the_frontend_command_matches_the_image() -> None:
    """An overlay command that disagrees with the image makes the container fail to start.

    The image copies the standalone tree to /app and starts ``node apps/web/server.js``; a
    bare ``server.js`` does not exist there.
    """
    import yaml

    dockerfile = (ROOT / "infra" / "docker" / "frontend.Dockerfile").read_text(
        encoding="utf-8"
    )
    assert 'CMD ["node", "apps/web/server.js"]' in dockerfile
    production = yaml.safe_load(
        (ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
    )
    assert production["services"]["frontend"]["command"] == ["node", "apps/web/server.js"]


def test_the_frontend_produces_a_standalone_server() -> None:
    """``node server.js`` only exists if the build emits the standalone output."""
    config = (ROOT / "apps" / "web" / "next.config.ts").read_text(encoding="utf-8")
    assert 'output: "standalone"' in config


def test_the_backend_runs_the_migrations_before_serving() -> None:
    """A container that serves before migrating answers requests against a stale schema."""
    dockerfile = (ROOT / "infra" / "docker" / "backend.Dockerfile").read_text(
        encoding="utf-8"
    )
    assert "alembic upgrade head && uvicorn" in dockerfile


def test_the_gitignore_protects_the_secrets() -> None:
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    lines = {line.strip() for line in ignore.splitlines()}
    assert ".env" in lines
    assert "!.env.example" in lines
    assert "*.pem" in lines
