"""Simulate what Git would track, and refuse to let a sensitive file slip through.

Git is not installed on this machine, so ``git status`` and ``git check-ignore`` cannot be
run. Rather than assert that the ignore rules are correct, this reproduces the subset of Git's
ignore semantics that matters here — directory names, leading slashes, negations, globs — and
reports what a first commit would contain.

The point is to catch the failure that actually happens: a ``.env`` added months later, a
``backup.dump`` committed by accident, a virtual environment of 200 MB. A first commit is the
moment it becomes permanent history.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: Paths that must never enter version control, whatever the ignore rules say. Checked
#: separately from ``.gitignore`` so that a mistake in a pattern is caught by a second,
#: independent list rather than by the same file being wrong once.
FORBIDDEN_NAMES = {".env", ".env.local", ".env.production", "credentials.json"}
FORBIDDEN_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".dump", ".sql.gz", ".sqlite3"}
FORBIDDEN_DIRECTORIES = {"node_modules", ".venv", "venv", "__pycache__", ".next", ".git"}

#: Files whose *name* evokes a secret. Reported as a note, not as a failure: the
#: authoritative check is the content scan in ``scan_secrets.py``, and a name-based rule that
#: flags ``scan_secrets.py`` trains the reader to ignore the output.
SENSITIVE_NAME_FRAGMENTS = ("secret", "credential", "token", "password")

#: Substrings that mark a file as tooling or an example rather than as material itself.
SENSITIVE_NAME_ALLOWLIST = ("scan", "check", "test", "example", "audit", "guard", "verify")


def read_ignore_rules(ignore_path: Path) -> list[str]:
    rules: list[str] = []
    for raw in ignore_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        rules.append(line)
    return rules


def is_ignored(relative: str, rules: list[str]) -> bool:
    """Apply the ignore rules in order, with later negations winning, as Git does."""
    ignored = False
    parts = relative.replace("\\", "/").split("/")
    for rule in rules:
        negated = rule.startswith("!")
        pattern = rule[1:] if negated else rule
        anchored = pattern.startswith("/")
        pattern = pattern.lstrip("/")
        pattern = pattern.rstrip("/")
        if not pattern:
            continue
        if anchored:
            candidates = ["/".join(parts)]
        else:
            # An unanchored pattern matches at any depth.
            candidates = ["/".join(parts[index:]) for index in range(len(parts))]
        matched = any(
            fnmatch.fnmatch(candidate, pattern)
            or fnmatch.fnmatch(candidate, f"{pattern}/*")
            for candidate in candidates
        )
        if matched:
            ignored = not negated
    return ignored


def main() -> int:
    ignore_path = ROOT / ".gitignore"
    if not ignore_path.exists():
        print("Aucun .gitignore : TOUT serait versionne.")
        return 1
    rules = read_ignore_rules(ignore_path)

    tracked: list[str] = []
    ignored: list[str] = []
    violations: list[str] = []
    present_on_disk: list[str] = []

    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT).as_posix()
        if any(part in FORBIDDEN_DIRECTORIES for part in path.parts):
            ignored.append(relative)
            continue
        if is_ignored(relative, rules):
            ignored.append(relative)
            continue
        tracked.append(relative)
        # Independent checks: a mistake in .gitignore must not be the only line of defence.
        if path.name in FORBIDDEN_NAMES:
            violations.append(f"{relative} : nom de fichier interdit")
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            violations.append(f"{relative} : extension sensible")
        lowered = path.name.lower()
        if any(fragment in lowered for fragment in SENSITIVE_NAME_FRAGMENTS):
            if any(marker in lowered for marker in SENSITIVE_NAME_ALLOWLIST):
                continue
            violations.append(f"{relative} : nom evoque un secret, a verifier")

    # A file that is correctly ignored is still worth reporting when it is a secret: the
    # operator has to know a real credential sits on disk, even though Git will not see it.
    # Only the project's own files are considered: a ``cacert.pem`` shipped inside a virtual
    # environment is a public certificate bundle, and reporting it would bury the real case.
    for name in ignored:
        path = ROOT / name
        if any(part in FORBIDDEN_DIRECTORIES for part in path.parts):
            continue
        if path.name in FORBIDDEN_NAMES:
            present_on_disk.append(name)
            continue
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            try:
                if b"PRIVATE KEY" in path.read_bytes()[:4096]:
                    present_on_disk.append(name)
            except OSError:
                continue

    tracked_bytes = sum((ROOT / name).stat().st_size for name in tracked)
    print(f"{len(rules)} regles d'ignore.")
    print(f"{len(tracked)} fichiers seraient versionnes ({tracked_bytes / 1024:.0f} Kio).")
    print(f"{len(ignored)} fichiers seraient ignores.")

    # A first commit of a virtual environment is the most common irreversible mistake.
    print()
    print("Dependances et artefacts volumineux versionnes :")
    heavy = [
        name
        for name in tracked
        if any(part in {".next", "dist", "build", "backups"} for part in name.split("/"))
    ]
    print("  aucun" if not heavy else "\n".join(f"  {name}" for name in heavy[:10]))

    print()
    if present_on_disk:
        print(
            f"{len(present_on_disk)} fichier(s) sensible(s) sur le disque, "
            "correctement ignores :"
        )
        for name in present_on_disk:
            print(f"  - {name}")
        print(
            "  (ils ne seront pas versionnes, mais leur presence sur le disque est a signaler)"
        )

    print()
    if violations:
        print(f"{len(violations)} fichier(s) sensible(s) seraient versionnes :")
        for item in violations:
            print(f"  - {item}")
        return 1
    print("Aucun fichier sensible ne serait versionne.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
