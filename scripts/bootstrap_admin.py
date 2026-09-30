"""Grant the platform administrator flag, deliberately and audibly.

Stage 13 made ``users.is_admin`` default to ``false``, so that no account is privileged by
accident. The cost of that decision is that **somebody has to grant the first flag**. This
script is that path, and it is built so it cannot be run by accident:

* it refuses to run without ``--yes``;
* it refuses to run against a database whose Alembic revision predates stage 13, because the
  column would not exist;
* it writes an ``admin_audit_events`` row, so the first privilege is recorded like every
  later one;
* granting twice is not an error and produces a second, truthful, audit row.

It also offers ``--list-admins``, because an operator who cannot see who is an administrator
has a problem they cannot solve.
"""

from __future__ import annotations

import argparse
import asyncio
import functools
import sys
from pathlib import Path
from typing import Any

#: Revision that introduced ``users.is_admin``. Earlier databases cannot be administered yet.
REQUIRED_REVISION = "0012_security_admin"

#: Used only when the migration files cannot be found, so the guard still has a sane answer
#: instead of accepting anything. The real order is read from ``alembic/versions``.
FALLBACK_REVISION_ORDER = (
    "0001_initial_schema",
    "0002_authentication_and_sessions",
    "0003_project_workspace",
    "0004_source_library",
    "0005_academic_rag",
    "0006_assistant",
    "0007_writing_assistant",
    "0008_bibliography",
    "0009_citations",
    "0010_document_exports",
    "0011_academic_audit",
    "0012_security_admin",
)


class BootstrapError(RuntimeError):
    """Raised when the privilege cannot be granted safely."""


def versions_directory() -> Path:
    return Path(__file__).resolve().parent.parent / "services" / "api" / "alembic" / "versions"


@functools.lru_cache(maxsize=1)
def revision_order() -> tuple[str, ...]:
    """The migration chain, read from the repository rather than hard-coded.

    A hard-coded list would silently go stale at the next migration and let the script accept
    a database that predates the administration tables. The file names carry the order in
    their numeric prefix, which is exactly the chain order.
    """
    directory = versions_directory()
    if not directory.is_dir():
        return FALLBACK_REVISION_ORDER
    revisions = sorted(
        path.stem
        for path in directory.glob("*.py")
        if path.stem != "__init__" and path.stem[0].isdigit()
    )
    return tuple(revisions) or FALLBACK_REVISION_ORDER


def revision_index(revision: str | None) -> int:
    """Position of a revision in the chain, or -1 when it is unknown."""
    if not revision:
        return -1
    order = revision_order()
    return order.index(revision) if revision in order else -1


def check_revision(revision: str | None) -> None:
    """Refuse to touch a database that predates the administration tables."""
    required = revision_index(REQUIRED_REVISION)
    position = revision_index(revision)
    if required < 0:
        # The script itself is out of date relative to the chain; refuse rather than guess.
        raise BootstrapError(
            f"La révision attendue {REQUIRED_REVISION} est absente de la chaîne de "
            "migrations. Lancez le script depuis le dépôt."
        )
    if position < 0:
        raise BootstrapError(
            "Révision Alembic inconnue ou absente. Exécutez « alembic upgrade head » "
            "avant d'accorder un privilège d'administration."
        )
    if position < required:
        raise BootstrapError(
            f"La base est en {revision}, antérieure à {REQUIRED_REVISION}. "
            "Exécutez « alembic upgrade head » d'abord : la colonne users.is_admin "
            "n'existe pas encore."
        )


def _session_factory():  # type: ignore[no-untyped-def]
    """Return the application's own session factory, so the script cannot drift from it.

    The API is importable only with ``services/api`` on the path, which is not the case when
    the script is run from the repository root.
    """
    api_path = Path(__file__).resolve().parent.parent / "services" / "api"
    if str(api_path) not in sys.path:
        sys.path.insert(0, str(api_path))
    from app.db.session import SessionLocal

    return SessionLocal


async def _current_revision() -> str | None:
    """Read the Alembic revision from the ``alembic_version`` table.

    The Alembic command API is deliberately not used here: ``alembic/env.py`` calls
    ``asyncio.run()`` internally, and this script is already inside a running loop, so
    ``command.current()`` returned an un-awaited coroutine and reported an unknown revision
    even against a healthy database. Reading the marker table is both correct in that
    situation and much cheaper.

    ``None`` means the table does not exist, i.e. no migration has ever been applied.
    """
    from sqlalchemy import text

    from app.db.session import SessionLocal

    try:
        async with SessionLocal() as db:
            result = await db.execute(text("SELECT version_num FROM alembic_version"))
            row = result.first()
    except Exception:  # noqa: BLE001 - reported to the operator as an unknown revision
        return None
    return str(row[0]) if row else None


async def grant_admin(email: str, *, reason: str, actor_email: str | None) -> dict[str, Any]:
    """Set the administrator flag on one account and record the decision."""
    session_factory = _session_factory()
    from sqlalchemy import func, select

    from app.models.security import AdminAuditEvent
    from app.models.user import User

    async with session_factory() as db:
        user = (
            await db.execute(
                select(User).where(func.lower(User.email) == email.strip().casefold())
            )
        ).scalar_one_or_none()
        if user is None:
            raise BootstrapError(
                f"Aucun compte n'a l'adresse « {email} ». Créez-le d'abord via "
                "/api/auth/register, ou vérifiez l'orthographe."
            )
        if user.is_suspended:
            raise BootstrapError(
                f"« {email} » est suspendu. Réintégrez le compte avant de l'accorder."
            )
        already = bool(user.is_admin)
        user.is_admin = True
        actor = None
        if actor_email:
            actor = (
                await db.execute(
                    select(User).where(func.lower(User.email) == actor_email.strip().casefold())
                )
            ).scalar_one_or_none()
        db.add(
            AdminAuditEvent(
                actor_id=actor.id if actor else None,
                target_user_id=user.id,
                action="grant_admin_bootstrap",
                target=user.email,
                reason=reason,
            )
        )
        await db.commit()
        return {
            "email": user.email,
            "user_id": str(user.id),
            "was_already_admin": already,
            "is_admin": True,
        }


async def list_admins() -> list[dict[str, Any]]:
    session_factory = _session_factory()
    from sqlalchemy import select

    from app.models.user import User

    async with session_factory() as db:
        users = (
            (
                await db.execute(
                    select(User).where(User.is_admin.is_(True)).order_by(User.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
        return [
            {
                "email": user.email,
                "user_id": str(user.id),
                "created_at": user.created_at.isoformat() if user.created_at else None,
                "suspended": bool(user.is_suspended),
            }
            for user in users
        ]


async def _promote(email: str, *, reason: str, actor_email: str | None) -> dict[str, Any]:
    """Check the revision, then grant the privilege, inside a single event loop.

    Two separate ``asyncio.run`` calls would be able to straddle a migration run, so the
    revision could be checked against one database state and the grant applied to another.
    """
    check_revision(await _current_revision())
    return await grant_admin(email, reason=reason, actor_email=actor_email)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bootstrap_admin",
        description=(
            "Accorde le privilège d'administration à un compte. "
            "L'étape 13 a volontairement laissé is_admin à false : ce script est le chemin "
            "explicite pour accorder le premier."
        ),
    )
    parser.add_argument("--email", help="Adresse du compte à promouvoir.")
    parser.add_argument("--reason", default="Amorçage initial", help="Motif, enregistré.")
    parser.add_argument(
        "--actor-email", default=None, help="Administrateur qui accorde le privilège."
    )
    parser.add_argument(
        "--yes", action="store_true", help="Confirme l'opération."
    )
    parser.add_argument(
        "--list-admins", action="store_true", help="Liste les administrateurs existants."
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if not args.email and not args.list_admins:
            raise BootstrapError("--email est requis.")
        if args.email and not args.yes:
            raise BootstrapError(
                "Refusé sans --yes. Relancez avec --yes une fois vérifié que "
                "l'adresse est la bonne."
            )
        if args.list_admins:
            rows = asyncio.run(list_admins())
            if not rows:
                print("Aucun administrateur. Utilisez --email pour en accorder un.")
                return 0
            for row in rows:
                state = " (suspendu)" if row["suspended"] else ""
                print(f"{row['email']}{state}")
            return 0
        # One event loop for the whole operation: the revision check and the grant must not
        # be able to observe a different database state.
        result = asyncio.run(_promote(args.email, reason=args.reason,
                                      actor_email=args.actor_email))
        if result["was_already_admin"]:
            print(f"{result['email']} était déjà administrateur (aucun changement).")
        else:
            print(f"{result['email']} est maintenant administrateur.")
        print(
            "Pour une durée complète en production, passez par /admin : "
            "l'opération est alors journalisée avec l'auteur de la décision."
        )
        return 0
    except BootstrapError as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - the operator needs a readable failure
        print(f"Erreur inattendue : {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
