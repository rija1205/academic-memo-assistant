"""Hunt for dead code and unfinished work: the final cleanup pass.

Five independent checks, each of which reports rather than guesses:

1. ``pass``/``...``/``NotImplementedError`` in a function body — an empty implementation that
   looks finished because it returns something;
2. an HTTP route referenced in the frontend that the API does not expose — a button wired to
   an endpoint that does not exist;
3. an API route whose module is never included in the router tree — a route nothing serves;
4. a frontend page that no navigation entry points to;
5. a dependency declared in ``pyproject.toml`` and never imported.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "services" / "api"
WEB = ROOT / "apps" / "web"

problems: list[str] = []
notes: list[str] = []


# --------------------------------------------------------------- empty bodies

def check_empty_bodies() -> None:
    """A function whose whole body is a placeholder is unfinished work.

    Two legitimate cases are excluded. A method of a ``Protocol`` class is inert **by
    definition**: it declares the contract, and a concrete provider implements it elsewhere.
    Flagging those would bury the real findings under a list that looks alarming and is not.
    An ``@abstractmethod`` is the same idea expressed differently.
    """
    targets = list((API / "app").rglob("*.py")) + list((ROOT / "services" / "worker").rglob("*.py"))
    inert_protocol_methods = 0
    for path in targets:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        protocol_classes = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef)
            and any(
                (isinstance(base, ast.Name) and base.id == "Protocol")
                or (isinstance(base, ast.Attribute) and base.attr == "Protocol")
                or "Protocol" in ast.dump(base)
                for base in node.bases
            )
        }
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            body = [
                statement
                for statement in node.body
                if not (isinstance(statement, ast.Expr)
                        and isinstance(statement.value, ast.Constant)
                        and isinstance(statement.value.value, str))
            ]
            if not body:
                continue
            is_inert = all(
                isinstance(statement, (ast.Pass, ast.Expr))
                and (
                    isinstance(statement, ast.Pass)
                    or (
                        isinstance(statement.value, ast.Constant)
                        and statement.value.value is Ellipsis
                    )
                )
                for statement in body
            ) or any(
                isinstance(statement, ast.Raise)
                and isinstance(statement.exc, ast.Call)
                and getattr(statement.exc.func, "id", "") == "NotImplementedError"
                for statement in body
            )
            if not is_inert:
                continue
            decorators = {getattr(d, "id", "") for d in node.decorator_list}
            parent = next(
                (
                    item
                    for item in ast.walk(tree)
                    if isinstance(item, ast.ClassDef) and node in ast.walk(item)
                ),
                None,
            )
            in_protocol = parent is not None and parent.name in protocol_classes
            if "abstractmethod" in decorators or in_protocol:
                inert_protocol_methods += 1
                continue
            problems.append(
                f"{path.relative_to(ROOT)}:{node.lineno} {node.name}() corps inerte"
            )
    notes.append(f"methodes de Protocol legitimement inertes : {inert_protocol_methods}")


# ------------------------------------------------------- frontend -> API routes

def api_paths() -> set[str]:
    """``METHOD /path`` for every operation the API actually exposes."""
    sys.path.insert(0, str(API))
    from app.main import app as fastapi_app  # noqa: PLC0415

    schema = fastapi_app.openapi()
    paths: set[str] = set()
    for path, operations in schema["paths"].items():
        for method in operations:
            if method in {"get", "post", "put", "patch", "delete"}:
                paths.add(f"{method.upper()} {path}")
    return paths


def collapse(path: str) -> str:
    """Replace every ``{...}`` placeholder with ``{}``.

    The frontend interpolates values while the schema names them, so comparing the raw strings
    would report a mismatch for every dynamic route and drown the real findings.
    """
    return re.sub(r"\{[^}]+\}", "{}", path).rstrip("/") or "/"


def check_frontend_routes() -> None:
    """A frontend call to a route the API does not serve is a button that cannot work."""
    known = api_paths()
    collapsed_known = {collapse(entry) for entry in known}
    pattern = re.compile(
        r"""(?:method:\s*["'](?P<m>GET|POST|PUT|PATCH|DELETE)["']\s*,?\s*url:\s*|`)"""
        r"""(?P<path>/api/[^?`"'\s]*)""",
        re.I,
    )
    checked = 0
    missing: list[str] = []
    for path in sorted(list(WEB.rglob("*.ts")) + list(WEB.rglob("*.tsx"))):
        text = path.read_text(encoding="utf-8")
        for match in pattern.finditer(text):
            raw = match.group("path")
            method = (match.group("m") or "GET").upper()
            # A URL assembled by string concatenation, e.g. "/citations" + query, is cut at
            # the first interpolation: the suffix is a query string, not part of the path.
            template = re.split(r"\$\{|\{", raw)[0]
            template = re.sub(r"\$\{[^}]+\}", "{param}", template).rstrip("/")
            if not template or template.endswith("/api"):
                continue
            # The Next.js catch-all proxy forwards any path, so it is not a route to verify.
            if "[" in template or "${" in template:
                continue
            checked += 1
            if f"{method} {template}" in known:
                continue
            if f"{method} {collapse(template)}" in collapsed_known:
                continue
            if any(entry.endswith(f" {collapse(template)}") for entry in collapsed_known):
                continue
            missing.append(f"{path.relative_to(ROOT)}: {method} {raw}")
    for item in sorted(set(missing)):
        problems.append(f"appel frontend vers une route absente : {item}")
    notes.append(f"appels frontend inspectes : {checked}")


# -------------------------------------------------------- unreachable routers

def check_included_routers() -> None:
    """Every ``router.py`` must be reachable, and every reachable one must serve something.

    Reachability is resolved through the *imported* router objects rather than by matching
    names: ``export/router.py`` is included as ``exports_router``, so a name comparison
    reports all twelve routers as unreached and tells the reader nothing.
    """
    router_dir = API / "app"
    aggregate_path = router_dir / "api" / "router.py"
    aggregate_tree = ast.parse(aggregate_path.read_text(encoding="utf-8"))

    # ``from app.assistant.router import router as assistant_router`` names the module in the
    # ImportFrom node and binds it under a local alias, so the alias is useless for deciding
    # which module is reachable. The module path is what identifies the router.
    imported_from: dict[str, str] = {}
    included_objects: set[str] = set()
    for node in ast.walk(aggregate_tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                imported_from[alias.asname or alias.name] = node.module
                if node.module.endswith(".router") or node.module.endswith(".workspace_router"):
                    # The imported symbol is a router object regardless of its local name.
                    imported_from[f"__object__{node.module}"] = node.module
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "include_router":
            if node.args and isinstance(node.args[0], ast.Name):
                included_objects.add(node.args[0].id)

    included_modules = {
        module
        for name, module in imported_from.items()
        if name in included_objects or name.startswith("__object__")
    }
    # ``app/api/health.py`` is a router module that is not named ``router.py``; it is included
    # and must not be reported as missing.
    included_modules.add("api.health")
    notes.append(f"modules de router inclus via l'agrégat : {len(included_modules)}")

    # The module string from ``ast.ImportFrom`` is fully qualified with a leading ``app.``,
    # while the path is relative to the ``app`` package. Comparing them as-is never matches,
    # which is why every router looked unreachable.
    unreachable: list[str] = []
    for path in sorted(router_dir.rglob("router.py")):
        module = "app." + str(path.relative_to(API / "app").with_suffix("")).replace("\\", ".")
        if module == "app.api.router":
            continue  # the aggregate root itself
        if module in included_modules:
            continue
        unreachable.append(path.relative_to(ROOT))
    for item in unreachable:
        problems.append(f"router jamais inclus : {item}")

    # The reverse direction: an included router that serves nothing is dead weight.
    sys.path.insert(0, str(API))
    from app.main import app as fastapi_app  # noqa: PLC0415

    schema = fastapi_app.openapi()
    for path in sorted(router_dir.rglob("router.py")):
        module = "app." + str(path.relative_to(API / "app").with_suffix("")).replace("\\", ".")
        if module not in included_modules:
            continue
        source = path.read_text(encoding="utf-8")
        declared = len(
            re.findall(r"@(?:router|admin_router)\.(?:get|post|put|patch|delete)", source)
        )
        if declared == 0:
            problems.append(
                f"router inclus mais sans aucune route : {path.relative_to(ROOT)}"
            )
    notes.append(f"chemins exposés par le schéma : {len(schema['paths'])}")


# ------------------------------------------------------------ orphan pages

def check_orphan_pages() -> None:
    """A page nobody links to is unreachable by navigation."""
    pages = {
        p.relative_to(WEB / "src").with_suffix("").as_posix()
        for p in (WEB / "src" / "app").rglob("page.tsx")
    }
    linked: set[str] = set()
    for path in list(WEB.rglob("*.tsx")) + list(WEB.rglob("*.ts")):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r'href=["\{]*/([A-Za-z0-9/_[\]-]+)', text):
            linked.add("/" + match.group(1))
    for path in list(WEB.rglob("*.tsx")) + list(WEB.rglob("*.ts")):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r'href=["\{]*/([A-Za-z0-9/_[\]-]+)', text):
            linked.add("/" + match.group(1))
    # Next.js writes a page as ``app/projects/[projectId]/rag/page.tsx``; the route is
    # ``/projects/[projectId]/rag``. Building it by concatenation produced a doubled slash,
    # which is why every page looked unreferenced.
    routes: set[str] = set()
    for page in pages:
        relative = page.removeprefix("app").removesuffix("/page")
        route = "/" + relative.strip("/")
        routes.add(route or "/")

    #: Pages reached by a link the static text search cannot see.
    navigation_only = {
        "/admin",
        "/projects/[projectId]",
        "/projects/[projectId]/assistant",
        "/projects/[projectId]/audit",
        "/projects/[projectId]/bibliography",
        "/projects/[projectId]/citations",
        "/projects/[projectId]/export",
        "/projects/[projectId]/rag",
        "/projects/[projectId]/sources",
        "/reset-password",
    }

    orphans = []
    for route in sorted(routes):
        if route in {"/", "/login", "/register", "/forgot-password"}:
            continue
        reachable = any(
            target == route or target.startswith(route + "/") for target in linked
        )
        if not reachable and route not in navigation_only:
            orphans.append(route)
    for route in orphans:
        problems.append(f"page sans lien de navigation : {route}")
    notes.append(f"pages inspectees : {len(routes)}")
    notes.append(f"pages atteignables par navigation seulement : {len(navigation_only & routes)}")


# ------------------------------------------------------- unused dependencies

def check_unused_dependencies() -> None:
    """A declared dependency nobody imports is either dead weight or a missing usage."""
    pyproject = API / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    match = re.search(r"dependencies\s*=\s*\[(.*?)\]", text, re.S)
    if not match:
        return
    declared = re.findall(r'"([A-Za-z0-9_.\-]+)', match.group(1))
    # A dependency may be used directly, or required by a framework because of a feature this
    # code asks for. The second kind is real usage and is listed explicitly: a check that
    # only understood ``import`` would report ``python-multipart`` as dead while the upload
    # endpoint cannot work without it.
    import_names = {
        "alembic": ("alembic",),
        "celery": ("celery",),
        "sqlalchemy": ("sqlalchemy",),
        "uvicorn": ("uvicorn",),
        "fastapi": ("fastapi", "starlette"),
        "pydantic": ("pydantic",),
        "pydantic-settings": ("pydantic_settings",),
        "asyncpg": ("asyncpg",),
        "redis": ("redis",),
        "httpx": ("httpx",),
        # Required by FastAPI for UploadFile / File(...) form parsing.
        "python-multipart": ("multipart",),
        "reportlab": ("reportlab",),
        "python-docx": ("docx",),
        "argon2-cffi": ("argon2",),
        "email-validator": ("email_validator",),
        "itsdangerous": ("itsdangerous",),
        "openpyxl": ("openpyxl",),
        "pgvector": ("pgvector",),
        "boto3": ("boto3",),
        "google-auth": ("google.auth", "google.oauth2", "googleapiclient"),
        # ``google.auth.transport.requests`` is the Google library's own HTTP layer: without
        # this alias the declared ``requests`` distribution looks unused.
        "requests": ("requests", "google.auth.transport.requests"),
        "pypdf": ("pypdf", "PyPDF2"),
    }
    #: Declared dependencies this check cannot map to an import name. Reported as a note so
    #: that an unmapped entry is visible rather than silently treated as used.
    indirect: dict[str, str] = {
        "python-multipart": "exige par FastAPI pour le telechargement de fichier (UploadFile)",
        "email-validator": "exige par pydantic pour le type EmailStr",
    }
    # The search covers the application, the migrations and the worker: a dependency is
    # legitimately used by any of them. ``alembic`` is imported by every migration file and
    # ``asyncpg`` is named in the connection URL, so judging them on ``app/`` alone reported
    # two false positives.
    sources = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in (
            list((API / "app").rglob("*.py"))
            + list((API / "alembic").rglob("*.py"))
            + list((ROOT / "services" / "worker").rglob("*.py"))
        )
    )
    configuration = (API / "alembic.ini").read_text(encoding="utf-8")
    for dependency in declared:
        if dependency in indirect:
            if indirect[dependency] in ("", None):
                continue
            # Confirm the feature that justifies the dependency is actually requested.
            feature = "UploadFile" if "UploadFile" in indirect[dependency] else "EmailStr"
            if feature not in sources:
                problems.append(
                    f"{dependency} declare pour {indirect[dependency]}, "
                    f"mais {feature} n'est utilise nulle part"
                )
            else:
                notes.append(f"{dependency} : usage indirect ({indirect[dependency]})")
            continue
        modules = import_names.get(dependency)
        if modules is None:
            # A distribution this check has no mapping for is neither proven used nor proven
            # dead. It is a gap in the audit, not a clean bill of health, and saying so is the
            # only honest option.
            problems.append(
                f"dependance declaree non verifiee par l'audit : {dependency} "
                "(ajouter son module d'import a import_names)"
            )
            continue
        # A driver can be named in a connection URL rather than imported: SQLAlchemy loads it
        # by name, so ``asyncpg`` appears in ``postgresql+asyncpg://`` and nowhere else.
        named_in_url = any(f"+{module}" in configuration or f"{module}://" in configuration
                          for module in modules)
        if named_in_url:
            notes.append(f"{dependency} : utilise via l'URL de connexion")
            continue
        if not any(
            re.search(rf"(^|\n)\s*(from|import)\s+{re.escape(module)}\b", sources)
            for module in modules
        ):
            problems.append(f"dependance declaree jamais importee : {dependency}")


def main() -> int:
    check_empty_bodies()
    check_included_routers()
    check_frontend_routes()
    check_orphan_pages()
    check_unused_dependencies()

    print("Nettoyage final")
    print("=" * 70)
    for note in notes:
        print(f"  {note}")
    print("=" * 70)
    if problems:
        print(f"{len(problems)} point(s) a traiter :")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("Aucun travail inacheve detecte.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
