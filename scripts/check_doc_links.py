"""Check that every internal documentation link resolves.

A link to a document that was renamed or moved reads exactly like a working reference. Nothing
fails, no test breaks, and the broken link is discovered by whoever follows it — usually
someone looking for the answer to a problem they already have.

The check lives in Python rather than in ``check-foundation.ps1`` for one concrete reason: a
regular expression written in single quotes in PowerShell carries its own escaping rules, and
getting them subtly wrong yields a pattern that matches nothing. The check then passes
silently, forever, which is the worst possible failure mode for a check.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: Every Markdown document is checked, discovered rather than listed. A hand-maintained list
#: is the same kind of thing this check exists to catch: it had just omitted
#: ``local-setup.md`` — the one file that actually contained the five broken commands — so a
#: document with a defect in it was silently out of scope.
def discover_documents() -> list[str]:
    found = ["README.md"]
    for path in sorted((ROOT / "docs").rglob("*.md")):
        found.append(str(path.relative_to(ROOT)).replace("\\", "/"))
    return found

#: ``](target)`` and ``](target "title")``, skipping pure anchors and external schemes.
LINK = re.compile(r"\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")

#: ``npm run <script>`` occurrences. A documented command that does not exist is worse than
#: no documentation: the reader gets an error at every step and has no way to tell the
#: document is wrong rather than their setup. This project already shipped five such
#: commands, so the check exists because of a real defect, not a hypothetical one.
NPM_COMMAND = re.compile(r"\bnpm run ([a-zA-Z0-9:_-]+)")

#: ``npm ci`` and ``npm install`` are both valid; they are not looked up in ``scripts``.
NPM_BARE = re.compile(r"\bnpm (ci|install|audit)\b")

#: Documentation the README must link to. A topic that exists but is unreachable from the
#: entry point is effectively absent, and the omission is invisible to a reader.
REQUIRED_FROM_README = [
    "docs/PROJECT-CLOSURE.md",
    "docs/operations/user-guide.md",
    "docs/operations/installation.md",
    "docs/operations/configuration.md",
    "docs/operations/deployment.md",
    "docs/operations/backup-restore.md",
    "docs/operations/verification.md",
]


def links_in(text: str) -> list[str]:
    found: list[str] = []
    for match in LINK.finditer(text):
        target = match.group(1)
        if target.startswith(("#", "http://", "https://", "mailto:")):
            continue
        found.append(target.split("#", 1)[0])
    return found


def main() -> int:
    documents = discover_documents()
    if not documents:
        print("Aucun document a verifier.")
        return 0

    broken: list[str] = []
    checked = 0
    for name in documents:
        path = ROOT / name
        if not path.exists():
            # A document listed here but absent is itself a broken reference.
            broken.append(f"{name} : le document n'existe pas")
            continue
        for target in links_in(path.read_text(encoding="utf-8")):
            checked += 1
            resolved = (path.parent / target).resolve()
            if not resolved.exists():
                broken.append(f"{name} -> {target}")

    readme_targets = {
        target.split("#", 1)[0]
        for target in links_in((ROOT / "README.md").read_text(encoding="utf-8"))
    }
    for required in REQUIRED_FROM_README:
        if required not in readme_targets:
            broken.append(f"README.md : ne renvoie pas vers {required}")

    # Every documented npm script must exist. The monorepo delegates to the apps/web
    # workspace, so the script names carry a ``:web`` suffix that is easy to omit in prose.
    import json

    declared = set(
        json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["scripts"]
    )
    checked_scripts = 0
    for name in documents:
        path = ROOT / name
        if not path.exists():
            continue
        for command in NPM_COMMAND.findall(path.read_text(encoding="utf-8")):
            checked_scripts += 1
            if command not in declared:
                broken.append(f"{name} : commande inexistante : npm run {command}")
    print(f"{checked_scripts} commandes npm documentees verifiees.")

    print(f"{len(documents)} documents, {checked} liens verifies.")
    if broken:
        print(f"{len(broken)} reference(s) cassee(s) :")
        for item in broken:
            print(f"  - {item}")
        return 1
    print("Toutes les references internes sont resolues.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
