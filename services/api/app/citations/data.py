"""Input data of the citation rendering engine.

These dataclasses are the *only* thing the style engine knows about. They are deliberately
independent from SQLAlchemy so that:

* the rendering can be tested without a database, and
* the same engine can later serve Tiptap HTML, PDF, DOCX and plain text (stage 12/13) without
  being rewritten.

The engine never receives an ORM object and never touches the database. It is a pure function
of the data below plus the chosen style.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

LocatorType = Literal["page", "pages", "chapter", "figure", "table", "section", "other"]
CitationMode = Literal["parenthetical", "narrative"]

#: Locator labels per style, used to build "p. 25", "pp. 25–28", "chap. 3"…
LOCATOR_LABELS: dict[str, dict[str, str]] = {
    "apa7": {
        "page": "p.",
        "pages": "pp.",
        "chapter": "chap.",
        "figure": "fig.",
        "table": "tableau",
        "section": "sec.",
        "other": "",
    },
    "harvard": {
        "page": "p.",
        "pages": "pp.",
        "chapter": "chap.",
        "figure": "fig.",
        "table": "table",
        "section": "section",
        "other": "",
    },
    "vancouver": {
        "page": "p.",
        "pages": "pp.",
        "chapter": "chap.",
        "figure": "fig.",
        "table": "table",
        "section": "sect",
        "other": "",
    },
    "iso690": {
        "page": "p.",
        "pages": "pp.",
        "chapter": "chap.",
        "figure": "fig.",
        "table": "tab.",
        "section": "sect.",
        "other": "",
    },
}


@dataclass(frozen=True, slots=True)
class CitationAuthor:
    """One author of a reference, in the order given by stage 9.

    ``is_organization`` distinguishes ``FAO`` from a person named ``Faou``. It is an explicit
    flag and never inferred from the spelling: a surname that happens to be capitalised is
    still a person, because guessing is exactly what this project must not do.
    """

    family_name: str
    given_name: str | None = None
    orcid: str | None = None
    is_organization: bool = False

    @property
    def display(self) -> str:
        """``Jean Dupont`` for a person, ``FAO`` for an organisation."""
        if self.is_organization or not self.given_name:
            return self.family_name
        return f"{self.given_name} {self.family_name}"

    @property
    def inverted(self) -> str:
        """``Dupont, Jean`` for a person, ``FAO`` for an organisation."""
        if self.is_organization or not self.given_name:
            return self.family_name
        return f"{self.family_name}, {self.given_name}"

    @property
    def short(self) -> str:
        """Form used inside a citation: ``Dupont`` or ``FAO``."""
        return self.family_name or self.display

    @property
    def sort_key(self) -> str:
        return (self.family_name or "").casefold()

    def initials(self) -> str:
        """``J.`` for ``Jean``, ``J. P.`` for ``Jean Paul``.

        An organisation has no initials, and a person with no given name is rendered with the
        family name alone rather than with an invented initial.
        """
        if self.is_organization or not self.given_name:
            return ""
        parts = [part for part in self.given_name.replace("-", " ").split() if part]
        if not parts:
            return ""
        return " ".join(f"{part[0].upper()}." for part in parts if part)


@dataclass(frozen=True, slots=True)
class ReferenceCitationData:
    """The bibliographic facts a style is allowed to use.

    Every field is optional because stage 9 refuses to invent metadata. A style must render
    what is present and report what is missing.
    """

    reference_id: str
    citation_key: str
    reference_type: str
    title: str | None = None
    authors: tuple[CitationAuthor, ...] = ()
    publication_year: int | None = None
    journal: str | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    publisher: str | None = None
    publisher_place: str | None = None
    edition: str | None = None
    doi: str | None = None
    url: str | None = None
    isbn: str | None = None
    issn: str | None = None
    language: str | None = None
    accessed_at: str | None = None

    @property
    def has_authors(self) -> bool:
        return bool(self.authors)

    @property
    def first_author(self) -> CitationAuthor | None:
        return self.authors[0] if self.authors else None

    @property
    def year_label(self) -> str | None:
        return str(self.publication_year) if self.publication_year else None

    def sort_key(self) -> tuple[str, str, str]:
        """Alphabetical key: author, then year, then title.

        A reference with no author sorts under its title, which is the convention of APA and
        ISO 690. The year becomes a high sentinel so a dateless reference follows the dated
        ones of the same author instead of jumping to the top.
        """
        if self.authors:
            author = f"{self.authors[0].sort_key} {self.authors[0].initials()}"
        else:
            author = (self.title or self.citation_key).casefold()
        year = f"{self.publication_year:04d}" if self.publication_year else "9999"
        return (author, year, (self.title or "").casefold())

    def author_year_key(self) -> tuple[str, str]:
        """Key used to detect same-author same-year collisions (Dupont 2024a / 2024b)."""
        if self.authors:
            return (self.authors[0].sort_key, self.authors[0].initials())
        return ((self.title or self.citation_key).casefold(), "")


@dataclass(frozen=True, slots=True)
class CitationItemData:
    """One reference inside a citation, with its own locator and affixes."""

    reference: ReferenceCitationData
    position: int = 1
    locator_type: str | None = None
    locator_value: str | None = None
    prefix: str | None = None
    suffix: str | None = None
    #: Assigned by the Vancouver numbering pass; ``None`` for other styles.
    number: int | None = None

    def with_number(self, number: int) -> CitationItemData:
        return CitationItemData(
            reference=self.reference,
            position=self.position,
            locator_type=self.locator_type,
            locator_value=self.locator_value,
            prefix=self.prefix,
            suffix=self.suffix,
            number=number,
        )


@dataclass(frozen=True, slots=True)
class CitationData:
    """A whole citation: one node of the document, possibly several references."""

    citation_id: str
    items: tuple[CitationItemData, ...] = ()
    prefix: str | None = None
    suffix: str | None = None
    mode: CitationMode = "parenthetical"
    #: True when a referenced reference was removed; the text is then invalid by construction.
    is_orphaned: bool = False
    #: Frozen rendering captured when the citation was written, used for history only.
    snapshot_text: str | None = None
    snapshot_style: str | None = None

    @property
    def reference_ids(self) -> tuple[str, ...]:
        return tuple(item.reference.reference_id for item in self.items)


@dataclass(slots=True)
class RenderedCitation:
    """The result of rendering a citation, with what could not be honoured."""

    text: str
    warnings: list[str] = field(default_factory=list)
    is_orphaned: bool = False

    @property
    def is_complete(self) -> bool:
        return not self.warnings and not self.is_orphaned


__all__ = [
    "LOCATOR_LABELS",
    "CitationAuthor",
    "CitationData",
    "CitationItemData",
    "CitationMode",
    "LocatorType",
    "ReferenceCitationData",
    "RenderedCitation",
]
