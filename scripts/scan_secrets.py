"""Repository-wide credential scan.

Run manually during the final audit. It is not part of the test suite: it inspects the
working tree rather than behaviour, and a failure here means a secret was committed, which
is a different kind of problem from a failing test.

The patterns are deliberately specific. A generic ``password = "..."`` rule would match every
test fixture and every example in the documentation, and a scanner that cries wolf gets
ignored; the goal is to find material that would actually work against a real service.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: (label, pattern). Each pattern matches something that would authenticate against a real
#: service, not merely something that looks like a credential.
RULES: list[tuple[str, re.Pattern[str]]] = [
    ("cle OpenAI", re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}")),
    ("cle Google API", re.compile(r"AIza[0-9A-Za-z_-]{30,}")),
    ("JWT signe", re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.")),
    ("identifiants dans une URL", re.compile(r"://[^:/\s]+:[^@/\s]{3,}@")),
    ("token AWS", re.compile(r"AKIA[0-9A-Z]{16}")),
    (
        "cle privee PEM",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"),
    ),
]

#: Values that are placeholders rather than credentials. ``academic_memo_dev`` is the
#: development default in ``alembic.ini``, ``config.py``, the compose file and the CI
#: workflow; it is a placeholder by design, and the production overlay refuses to start
#: without a real one. Excluding the value rather than whole files keeps the exclusion narrow
#: and keeps flagging a real password that happens to sit in a documented file.
PLACEHOLDER_PASSWORDS = {"academic_memo_dev", "mdp", "changeme", "password", "secret"}

#: (file, password) pairs that are synthetic test fixtures. Listed one by one so that adding
#: an exclusion is a visible decision: a new value appearing in a test file is flagged, which
#: is the behaviour that matters.
KNOWN_TEST_PASSWORDS = {
    ("services/api/tests/test_deployment.py", "sup3rs3cret"),
    ("services/api/tests/test_deployment.py", "a:b:c"),
}

SKIP_DIRS = {
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".next",
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
}
SKIP_SUFFIXES = {".pyc", ".png", ".jpg", ".jpeg", ".ico", ".woff", ".woff2", ".zip", ".lock"}


def relative(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def iter_text_files() -> list[Path]:
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in SKIP_SUFFIXES:
            continue
        yield path


def is_placeholder(snippet: str) -> bool:
    """True when the match carries only a development placeholder as its password."""
    for password in PLACEHOLDER_PASSWORDS:
        if password in snippet:
            return True
    return False


def scan() -> list[tuple[str, int, str, str]]:
    findings: list[tuple[str, int, str, str]] = []
    for path in iter_text_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for label, pattern in RULES:
            for match in pattern.finditer(text):
                snippet = match.group(0)
                if label == "identifiants dans une URL":
                    if is_placeholder(snippet):
                        continue
                    if any(
                        password in snippet
                        for path_name, password in KNOWN_TEST_PASSWORDS
                        if path_name == relative(path)
                    ):
                        continue
                line_number = text[: match.start()].count("\n") + 1
                findings.append((relative(path), line_number, label, snippet[:70]))
    return findings


def main() -> int:
    findings = scan()
    checked = sum(1 for _ in iter_text_files())
    print(f"{checked} fichiers analyses.")
    if not findings:
        print(
            "Aucun secret detecte dans le depot. "
            f"({len(PLACEHOLDER_PASSWORDS)} valeurs de developpement ignorees.)"
        )
        return 0

    print(f"{len(findings)} correspondance(s) :")
    for path, line_number, label, snippet in findings:
        print(f"  {path}:{line_number}  [{label}]")
        print(f"      {snippet!r}")
    print("\nCorrespondances a traiter avant toute mise en production.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
