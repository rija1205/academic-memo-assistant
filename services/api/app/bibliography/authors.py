"""Author parsing and formatting.

Authors are stored relationally (``reference_authors``) because their **order matters** and
because a first name, a family name and an ORCID are different facts that a single string
cannot carry. This module converts between that structure and the textual forms used by
BibTeX, RIS and the API.

Two conventions are supported on input, because both occur in real files:

* ``Jean Dupont`` (given name first) — the default;
* ``Dupont, Jean`` (BibTeX and RIS style) — detected by the comma.

When a name is ambiguous, the BibTeX ``von Last, First`` rule is applied: the part before the
last comma is the family name. No name is ever invented: a malformed name is stored as the
family name only, never split into a guessed first name.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_TOKEN = re.compile(r"[^,]+")
_CLEAN = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class ParsedAuthor:
    """One author, as stored in ``reference_authors``."""

    position: int
    given_name: str | None
    family_name: str
    orcid: str | None = None

    @property
    def display(self) -> str:
        if self.given_name:
            return f"{self.family_name}, {self.given_name}"
        return self.family_name

    def as_bibtex_name(self) -> str:
        if self.given_name:
            return f"{self.family_name}, {self.given_name}"
        return self.family_name


def clean_name(value: str) -> str:
    return _CLEAN.sub(" ", (value or "").replace("\n", " ")).strip(" ,;")


def parse_author_name(value: str, position: int, orcid: str | None = None) -> ParsedAuthor:
    """Parse one author string into a structured author.

    ``Dupont, Jean`` yields family ``Dupont`` and given ``Jean``. ``Jean Dupont`` yields
    family ``Dupont`` and given ``Jean``. An ambiguous ``Jean Paul Dupont`` keeps the family
    name as ``Dupont`` and records ``Jean Paul`` as the given name, which is the convention
    used by the major styles without a comma marker.
    """
    raw = clean_name(value)
    if not raw:
        return ParsedAuthor(position=position, given_name=None, family_name="", orcid=orcid)
    if "," in raw:
        family, _, given = raw.partition(",")
        family_name = clean_name(family)
        given_name = clean_name(given) or None
        return ParsedAuthor(
            position=position, given_name=given_name, family_name=family_name, orcid=orcid
        )
    parts = [part for part in raw.split(" ") if part]
    if len(parts) == 1:
        return ParsedAuthor(position=position, given_name=None, family_name=parts[0], orcid=orcid)
    return ParsedAuthor(
        position=position,
        given_name=" ".join(parts[:-1]),
        family_name=parts[-1],
        orcid=orcid,
    )


def parse_authors(value: str | None) -> list[ParsedAuthor]:
    """Parse an author list separated by ``and``, ``;`` or newlines.

    BibTeX uses `` and ``, RIS repeats the ``AU`` tag, and a plain list often uses ``;``.
    Positions are assigned from 1, because the order is part of the data.
    """
    if not value:
        return []
    text = value.replace("\r", "\n")
    # A semicolon is only a separator when it is not the BibTeX "von Last, First" comma
    # convention; split on semicolons and " and " first, then on newlines.
    chunks: list[str] = []
    for chunk in re.split(r"\s+and\s+|[;\n]", text):
        cleaned = clean_name(chunk)
        if cleaned:
            chunks.append(cleaned)
    # "Dupont, Jean" must survive as one author: re-join a chunk that starts after a comma
    # split, which the " and " separator already handles. Anything left is a full name.
    return [
        parse_author_name(chunk, position=index)
        for index, chunk in enumerate(chunks, start=1)
    ]


def parse_ris_authors(values: list[str]) -> list[ParsedAuthor]:
    """Parse RIS ``AU`` lines, one author per line, preserving the original order."""
    authors: list[ParsedAuthor] = []
    for index, value in enumerate(values, start=1):
        if clean_name(value):
            authors.append(parse_author_name(value, position=index))
    return authors


def format_author_full(author: ParsedAuthor) -> str:
    """Human form ``Jean Dupont``."""
    if author.given_name:
        return f"{author.given_name} {author.family_name}"
    return author.family_name


def format_author_list(authors: list[ParsedAuthor], *, bibtex: bool = False) -> str:
    """Join authors for display or for a BibTeX ``author`` field."""
    if bibtex:
        return " and ".join(author.as_bibtex_name() for author in authors)
    return ", ".join(format_author_full(author) for author in authors)


def normalize_orcid(value: str | None) -> str | None:
    """Return the bare ORCID, or ``None`` when the value is not usable.

    Only the shape is checked. The ORCID is **not** verified against the public registry,
    because that would be a network call on a metadata field the author typed.
    """
    if not value:
        return None
    candidate = clean_name(value).casefold()
    for prefix in ("https://orcid.org/", "http://orcid.org/", "orcid:"):
        if candidate.startswith(prefix):
            candidate = candidate[len(prefix) :]
    digits = re.sub(r"[^0-9x]", "", candidate)
    if len(digits) != 16 or not digits.startswith("0000"):
        return None
    return digits[:16]


__all__ = [
    "ParsedAuthor",
    "clean_name",
    "format_author_full",
    "format_author_list",
    "normalize_orcid",
    "parse_author_name",
    "parse_authors",
    "parse_ris_authors",
]
