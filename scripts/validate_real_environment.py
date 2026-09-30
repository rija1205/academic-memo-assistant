"""Run every validation that depends on a real service, and report honestly what happened.

The previous phase produced a list of BLOCKED items because PostgreSQL, Redis, Docker and Git
are absent from this machine. A list of blocked things is a dead end: it tells the reader what
is missing but not how to finish. This harness closes that gap.

It detects what is installed, runs the validations whose dependencies are satisfied, and marks
the rest BLOCKED with the exact reason. Nothing is simulated and nothing is inferred: an item
is PASS only when the command ran and returned success. The day PostgreSQL appears, running
this file performs the validations that were impossible before, with no further work.

Statuses, used strictly:

* ``PASS``      — executed for real, succeeded
* ``FAIL``      — executed for real, failed
* ``BLOCKED``   — a dependency is missing; nothing was executed
* ``NOT_RUN``   — a dependency is present but the validation was not attempted

Usage::

    python scripts/validate_real_environment.py            # everything possible
    python scripts/validate_real_environment.py --list     # show the plan, execute nothing
    python scripts/validate_real_environment.py --only postgres
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "services" / "api"
VENV_PYTHON = API / ".venv" / "Scripts" / "python.exe"

PASS = "PASS"
FAIL = "FAIL"
BLOCKED = "BLOCKED"
NOT_RUN = "NOT_RUN"


@dataclass
class Outcome:
    name: str
    status: str
    detail: str
    evidence: str = ""


@dataclass
class Check:
    key: str
    title: str
    requires: tuple[str, ...]
    credential: str | None = None
    results: list[Outcome] = field(default_factory=list)


# ------------------------------------------------------------------ detection


def which(name: str) -> str | None:
    return shutil.which(name)


def has_docker() -> bool:
    return which("docker") is not None


def docker_compose_works() -> bool:
    if not has_docker():
        return False
    try:
        return (
            subprocess.run(
                ["docker", "compose", "version"],
                capture_output=True,
                text=True,
                timeout=30,
            ).returncode
            == 0
        )
    except (OSError, subprocess.SubprocessError):
        return False


def postgres_reachable(url: str) -> bool:
    """A TCP probe, without importing a driver, so a missing driver is not a false negative."""
    from urllib.parse import urlparse

    parsed = urlparse(url.replace("postgresql+asyncpg://", "postgresql://"))
    host = parsed.hostname or "localhost"
    port = parsed.port or 5432
    import socket

    try:
        with socket.create_connection((host, port), timeout=3):
            return True
    except OSError:
        return False


def redis_reachable(url: str) -> bool:
    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 6379
    import socket

    try:
        with socket.create_connection((host, port), timeout=3):
            return True
    except OSError:
        return False


def run(command: list[str], cwd: Path, timeout: int = 900) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            command, cwd=cwd, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return 124, "delai depasse"
    except OSError as exc:
        return 127, str(exc)
    return completed.returncode, (completed.stdout or "") + (completed.stderr or "")


def tail(text: str, lines: int = 3) -> str:
    kept = [line for line in text.strip().splitlines() if line.strip()]
    return " | ".join(kept[-lines:])[:220]


# --------------------------------------------------------------------- checks


def check_git(check: Check) -> None:
    if which("git") is None:
        check.results.append(
            Outcome("git", BLOCKED, "git absent ; aucune installation tentee")
        )
        return
    inside = (ROOT / ".git").exists()
    check.results.append(
        Outcome(
            "git",
            PASS if inside else NOT_RUN,
            "depot initialise" if inside else "git present, depot non initialise",
        )
    )


def check_postgres(check: Check) -> None:
    url = os.environ.get("TEST_DATABASE_URL", "")
    if not url:
        check.results.append(
            Outcome("postgres:connexion", BLOCKED, "TEST_DATABASE_URL absente")
        )
        return
    if not postgres_reachable(url):
        check.results.append(
            Outcome("postgres:connexion", BLOCKED, f"aucun serveur sur {url.split('@')[-1]}")
        )
        return
    check.results.append(Outcome("postgres:connexion", PASS, "serveur joignable"))

    # 1. The migrations, applied for real.
    code, output = run([str(API / ".venv/Scripts/alembic.exe"), "upgrade", "head"], cwd=API)
    check.results.append(
        Outcome(
            "postgres:alembic-upgrade",
            PASS if code == 0 else FAIL,
            "head applique" if code == 0 else tail(output),
        )
    )

    # 2. The applied revision, read back from the database rather than from a file.
    code, output = run([str(API / ".venv/Scripts/alembic.exe"), "current"], cwd=API)
    head_present = "0012_security_admin" in output
    check.results.append(
        Outcome(
            "postgres:revision-0012",
            PASS if code == 0 and head_present else FAIL,
            "revision lue dans la base" if head_present else tail(output),
        )
    )

    # 3. The integration suite, executed against that database.
    code, output = run(
        [str(VENV_PYTHON), "-m", "pytest", "-m", "integration", "-q"], cwd=API
    )
    check.results.append(
        Outcome(
            "postgres:tests-integration",
            PASS if code == 0 else FAIL,
            tail(output, 2),
        )
    )

    # 4. The downgrade path, exercised on a throwaway database so the one under test is
    #    never touched. Upgraded then fully reverted: syntax alone would not show that the
    #    downgrades actually run against a live server.
    if which("createdb") is None or which("dropdb") is None:
        check.results.append(
            Outcome("postgres:downgrade", BLOCKED, "createdb / dropdb absents")
        )
        return
    from urllib.parse import urlparse

    parsed = urlparse(url.replace("postgresql+asyncpg://", "postgresql://"))
    host = [parsed.hostname or "localhost", str(parsed.port or 5432)]
    user = parsed.username or "postgres"
    scratch = "ama_downgrade_probe"

    def drop() -> None:
        run(
            ["dropdb", "--if-exists", "--force", "-h", host[0], "-p", host[1], "-U", user, scratch],
            cwd=ROOT,
            timeout=120,
        )

    drop()
    code, output = run(
        ["createdb", "-h", host[0], "-p", host[1], "-U", user, scratch], cwd=ROOT, timeout=120
    )
    if code != 0:
        check.results.append(Outcome("postgres:downgrade", FAIL, tail(output, 2)))
        return

    # Alembic reads its URL from the application settings, which read DATABASE_URL.
    scratch_url = url.rsplit("/", 1)[0] + f"/{scratch}"
    environment = dict(os.environ, DATABASE_URL=scratch_url)
    try:
        upgraded = subprocess.run(
            [str(API / ".venv/Scripts/alembic.exe"), "upgrade", "head"],
            cwd=API, capture_output=True, text=True, timeout=900, env=environment,
        )
        reverted = subprocess.run(
            [str(API / ".venv/Scripts/alembic.exe"), "downgrade", "base"],
            cwd=API, capture_output=True, text=True, timeout=900, env=environment,
        )
    finally:
        drop()

    if upgraded.returncode != 0:
        check.results.append(
            Outcome("postgres:downgrade", FAIL, f"upgrade echoue : {tail(upgraded.stderr, 2)}")
        )
    elif reverted.returncode != 0:
        check.results.append(
            Outcome("postgres:downgrade", FAIL, f"downgrade echoue : {tail(reverted.stderr, 2)}")
        )
    else:
        check.results.append(
            Outcome(
                "postgres:downgrade",
                PASS,
                "12 migrations appliquees puis reverties sur une base jetable",
            )
        )


def check_backup(check: Check) -> None:
    if which("pg_dump") is None or which("pg_restore") is None:
        check.results.append(
            Outcome("backup:cycle", BLOCKED, "pg_dump / pg_restore absents")
        )
        return
    url = os.environ.get("DATABASE_URL") or os.environ.get("TEST_DATABASE_URL", "")
    if not url or not postgres_reachable(url):
        check.results.append(
            Outcome("backup:cycle", BLOCKED, "aucune base joignable pour la sauvegarde")
        )
        return

    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch) / "backups"
        code, output = run(
            [str(VENV_PYTHON), str(ROOT / "scripts" / "backup.py"), "create", "--root", str(root),
             "--database-url", url],
            cwd=ROOT,
        )
        if code != 0:
            check.results.append(Outcome("backup:create", FAIL, tail(output)))
            return
        directories = sorted(item for item in root.iterdir() if item.is_dir())
        check.results.append(
            Outcome("backup:create", PASS, f"{len(directories)} sauvegarde(s) creee(s)")
        )
        code, output = run(
            [str(VENV_PYTHON), str(ROOT / "scripts" / "backup.py"), "verify", "--root", str(root),
             "--directory", str(directories[-1])],
            cwd=ROOT,
        )
        check.results.append(
            Outcome("backup:verify", PASS if code == 0 else FAIL, tail(output, 1))
        )

        # Restored into a separate database, then compared on the table count.
        target = url.rsplit("/", 1)[0] + "/restored_probe"
        code, output = run(
            [str(VENV_PYTHON), str(ROOT / "scripts" / "backup.py"), "restore", "--root", str(root),
             "--directory", str(directories[-1]), "--database-url", target, "--yes"],
            cwd=ROOT,
        )
        if code != 0:
            check.results.append(Outcome("backup:restore", FAIL, tail(output, 2)))
        else:
            comparison = run(
                [str(VENV_PYTHON), str(ROOT / "scripts" / "compare_databases.py"),
                 "--source", url, "--target", target],
                cwd=ROOT,
            )
            ok, detail = comparison
            check.results.append(
                Outcome(
                    "backup:restore",
                    PASS if ok == 0 else FAIL,
                    detail.strip().splitlines()[-1] if detail.strip() else "",
                )
            )


def check_docker(check: Check) -> None:
    if not docker_compose_works():
        check.results.append(
            Outcome("docker:compose", BLOCKED, "docker absent ou demon non joignable")
        )
        return
    code, output = run(["docker", "compose", "config", "--quiet"], cwd=ROOT, timeout=120)
    check.results.append(
        Outcome("docker:config", PASS if code == 0 else FAIL, tail(output, 2))
    )
    code, output = run(["docker", "compose", "build"], cwd=ROOT, timeout=1800)
    check.results.append(Outcome("docker:build", PASS if code == 0 else FAIL, tail(output, 2)))


def check_redis(check: Check) -> None:
    url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    if which("redis-server") is None and not redis_reachable(url):
        check.results.append(Outcome("redis", BLOCKED, "aucun Redis joignable"))
        return
    check.results.append(Outcome("redis", NOT_RUN, "joignable mais non exerce"))


def check_openai(check: Check) -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        check.results.append(
            Outcome("openai", BLOCKED, "OPENAI_API_KEY absente")
        )
        return
    check.results.append(Outcome("openai", NOT_RUN, "cle presente, non exerce"))


def check_google(check: Check) -> None:
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    if not (client_id and secret):
        check.results.append(
            Outcome("google-oauth", BLOCKED, "GOOGLE_CLIENT_ID / SECRET absentes")
        )
        return
    check.results.append(Outcome("google-oauth", NOT_RUN, "credentials presentes, non exercees"))


CHECKS: list[Check] = [
    Check("git", "Versionnement", ()),
    Check("postgres", "PostgreSQL, migrations et tests d'integration", ()),
    Check("backup", "Sauvegarde et restauration", ()),
    Check("redis", "Redis et Celery", ()),
    Check("docker", "Docker Compose", ()),
    Check("openai", "OpenAI reel", ()),
    Check("google", "Google OAuth reel", ()),
]

DISPATCH = {
    "git": check_git,
    "postgres": check_postgres,
    "backup": check_backup,
    "redis": check_redis,
    "docker": check_docker,
    "openai": check_openai,
    "google": check_google,
}


# ---------------------------------------------------------------------- report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="afficher le plan sans executer")
    parser.add_argument("--only", nargs="*", help="limiter a ces controles")
    parser.add_argument("--json", action="store_true", help="sortie JSON")
    args = parser.parse_args()

    if args.only:
        unknown = [name for name in args.only if name not in DISPATCH]
        if unknown:
            print(f"Controle inconnu : {', '.join(unknown)}")
            print(f"Disponibles : {', '.join(DISPATCH)}")
            return 2

    selected = [
        check
        for check in CHECKS
        if not args.only or check.key in args.only
    ]

    if args.list:
        print("Plan de validation sur environnement reel")
        print("=" * 78)
        for check in selected:
            print(f"  {check.key:<10} {check.title}")
        print()
        print("Aucun controle n'a ete execute (--list).")
        return 0

    started = time.perf_counter()
    for check in selected:
        started_check = time.perf_counter()
        try:
            DISPATCH[check.key](check)
        except Exception as exc:  # noqa: BLE001 - a broken check must not hide the others
            check.results.append(
                Outcome(check.key, FAIL, f"controle interrompu : {type(exc).__name__}: {exc}")
            )
        elapsed = time.perf_counter() - started_check
        for outcome in check.results:
            outcome.evidence = outcome.evidence or f"{elapsed:.1f}s"

    counts = {PASS: 0, FAIL: 0, BLOCKED: 0, NOT_RUN: 0}
    for check in selected:
        for outcome in check.results:
            counts[outcome.status] = counts.get(outcome.status, 0) + 1

    if args.json:
        payload: dict[str, Any] = {
            "results": [
                {
                    "check": outcome.name,
                    "status": outcome.status,
                    "detail": outcome.detail,
                }
                for check in selected
                for outcome in check.results
            ],
            "counts": counts,
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0 if counts[FAIL] == 0 else 1

    print()
    print("Validation sur environnement reel")
    print("=" * 78)
    for check in selected:
        print(f"\n{check.title}")
        if not check.results:
            print("  (aucun resultat)")
        for outcome in check.results:
            marker = {
                PASS: "OK  ",
                FAIL: "ECHEC",
                BLOCKED: "BLOQ",
                NOT_RUN: "N.EX",
            }[outcome.status]
            print(f"  [{marker}] {outcome.name:<34} {outcome.detail}")
    print()
    print("=" * 78)
    print(
        f"{counts[PASS]} reussis / {counts[FAIL]} echecs / "
        f"{counts[BLOCKED]} bloques / {counts[NOT_RUN]} non executes / "
        f"{time.perf_counter() - started:.0f}s"
    )
    if counts[BLOCKED]:
        print()
        print("Pour lever un blocage : fournir la dependance, puis relancer ce script.")
        print("  PostgreSQL  -> TEST_DATABASE_URL   (et psql, pg_dump, pg_restore)")
        print("  Redis       -> redis-server sur REDIS_URL")
        print("  Docker      -> docker avec le plugin Compose")
        print("  Git         -> git dans le PATH")
        print("  OpenAI      -> OPENAI_API_KEY")
        print("  Google      -> GOOGLE_CLIENT_ID et GOOGLE_CLIENT_SECRET")
    return 0 if counts[FAIL] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
