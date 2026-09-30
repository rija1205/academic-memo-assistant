"""The citation style abstraction and the style registry.

Every style implements the same small contract, and the rest of the application asks the
registry for a style by name. No component and no endpoint branches on ``style == "APA"``:
the only place that knows APA's rules is :mod:`app.citations.styles.apa`.

The contract is intentionally narrow:

* :meth:`CitationStyle.format_citation` -- how a citation is displayed in the text;
* :meth:`CitationStyle.format_bibliography_entry` -- one line of the final bibliography;
* :meth:`CitationStyle.sort_bibliography` -- the order of that bibliography;
* :meth:`CitationStyle.assign_year_suffixes` -- the ``2024a`` / ``2024b`` disambiguation.

A style is a pure, deterministic function of the data it receives. It never queries a
database and never calls a language model.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from string import ascii_lowercase

from app.citations.data import (
    LOCATOR_LABELS,
    CitationAuthor,
    CitationData,
    ReferenceCitationData,
    RenderedCitation,
)


@dataclass(slots=True)
class RenderedBibliographyEntry:
    """One line of the final bibliography."""

    reference_id: str
    text: str
    number: int | None = None
    warnings: list[str] = field(default_factory=list)


def format_locator(
    item, labels: dict[str, str], *, page_separator: str = "–"
) -> str:  # type: ignore[no-untyped-def]
    """Render a locator such as ``p. 25`` or ``pp. 25–28``.

    The value is never altered or completed: a locator with no value yields an empty string
    rather than an invented page.
    """
    value = (getattr(item, "locator_value", None) or "").strip()
    if not value:
        return ""
    kind = getattr(item, "locator_type", None) or "other"
    label = labels.get(kind, "")
    # The range is typed by the author ("25-28" or "25–28"); it is reproduced as given and
    # never rebuilt, because guessing the second bound would be inventing a page.
    return f"{label} {value}".strip()


class CitationStyle(ABC):
    """Base class of every bibliographic style."""

    #: Stable identifier stored in ``projects.bibliography_style``.
    name: str = ""
    #: Human label shown in the interface.
    label: str = ""
    #: How a missing year is written. Never a real year.
    date_missing: str = "n.d."
    #: True when the style cites by number rather than by author and year.
    uses_numbers: bool = False
    #: Separator between several references inside one citation.
    item_separator: str = "; "
    #: Characters that open and close a citation.
    open_mark: str = "("
    close_mark: str = ")"

    @property
    def locator_labels(self) -> dict[str, str]:
        return LOCATOR_LABELS.get(self.name, {})

    # ------------------------------------------------------------- citation
    @abstractmethod
    def format_citation(self, citation: CitationData) -> RenderedCitation:
        """Render a citation as it appears in the text."""

    # --------------------------------------------------------- bibliography
    @abstractmethod
    def format_bibliography_entry(
        self,
        reference: ReferenceCitationData,
        *,
        number: int | None = None,
        year_suffix: str | None = None,
    ) -> RenderedBibliographyEntry:
        """Render one line of the final bibliography."""

    def sort_bibliography(
        self, references: list[ReferenceCitationData]
    ) -> list[ReferenceCitationData]:
        """Order the bibliography. Numeric styles keep the citation order."""
        return sorted(references, key=lambda reference: reference.sort_key())

    def assign_year_suffixes(
        self, references: list[ReferenceCitationData]
    ) -> dict[str, str]:
        """Assign ``a``, ``b``, ``c`` to references sharing an author and a year.

        The grouping is sorted by title then citation key, so the assignment only changes when
        the set of references actually changes. That is what makes ``Dupont 2024a`` stable.
        """
        return _assign_letter_suffixes(references)

    def requires_year_suffix(self) -> bool:
        return True

    # ---------------------------------------------------------------- utils
    def format_item_affixes(self, item, base: str) -> str:  # type: ignore[no-untyped-def]
        """Append locator, item prefix and item suffix to an already rendered element."""
        text = base
        locator = format_locator(item, self.locator_labels)
        if locator:
            text = f"{text}, {locator}"
        if getattr(item, "prefix", None):
            text = f"{getattr(item, 'prefix')}{text}"
        if getattr(item, "suffix", None):
            text = f"{text}{getattr(item, 'suffix')}"
        return text

    def _wrap(self, body: str, citation: CitationData) -> str:
        text = body
        if citation.prefix:
            text = _affix(citation.prefix, text, before=True)
        if citation.suffix:
            text = _affix(citation.suffix, text, before=False)
        text = text.strip()
        if citation.mode == "narrative":
            return text
        return f"{self.open_mark}{text}{self.close_mark}"

    def _orphan(self, citation: CitationData) -> RenderedCitation:
        """A citation whose reference is gone must say so, never invent an author."""
        return RenderedCitation(
            text="[Citation invalide : référence introuvable]",
            warnings=["Référence introuvable."],
            is_orphaned=True,
        )

    def _author_warning(self, reference: ReferenceCitationData) -> str | None:
        if reference.has_authors:
            return None
        return "Auteur non renseigné."

    def _year_warning(self, reference: ReferenceCitationData) -> str | None:
        if reference.publication_year:
            return None
        return "Année non renseignée."


def _assign_letter_suffixes(
    references: list[ReferenceCitationData],
) -> dict[str, str]:
    """Group by author+year and letter the collisions."""
    groups: dict[tuple[str, str, int | None], list[ReferenceCitationData]] = {}
    for reference in references:
        author, _ = reference.author_year_key()
        key = (author, reference.year_label or "", reference.publication_year)
        groups.setdefault(key, []).append(reference)
    suffixes: dict[str, str] = {}
    for members in groups.values():
        if len(members) < 2:
            continue
        ordered = sorted(
            members, key=lambda item: ((item.title or "").casefold(), item.citation_key)
        )
        for index, reference in enumerate(ordered):
            if index < len(ascii_lowercase):
                suffixes[reference.reference_id] = ascii_lowercase[index]
    return suffixes


def format_author_list(
    authors: tuple[CitationAuthor, ...],
    *,
    style: str = "full",
    joiner: str = ", ",
    and_word: str = "&",
    serial_comma_two: bool = False,
) -> str:
    """Join authors according to the conventions of the styles.

    ``style='full'``  -> ``Dupont, J. & Martin, P.``  (APA-like reference list)
    ``style='inverted'`` -> ``J. Dupont, P. Martin``
    ``style='short'`` -> ``Dupont & Martin``           (in-text citation)
    ``style='short_amp'`` -> ``Dupont & Martin``
    ``style='plain'`` -> ``Jean Dupont, Marie Rakoto``
    """
    if not authors:
        return ""
    names: list[str] = []
    for author in authors:
        if style == "full":
            names.append(_full_name(author))
        elif style == "inverted":
            names.append(author.display)
        elif style == "short":
            names.append(author.short)
        elif style == "short_amp":
            names.append(author.short)
        else:
            names.append(author.display)
    return _join(names, joiner, and_word, serial_comma_two)


def _full_name(author: CitationAuthor) -> str:
    """``Dupont, J.`` -- an organisation keeps its own spelling."""
    if author.is_organization:
        return author.family_name
    initials = author.initials()
    if not initials:
        return author.family_name
    return f"{author.family_name}, {initials}"


def _join(names: list[str], joiner: str, and_word: str, serial_comma_two: bool = False) -> str:
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if not and_word:
        return joiner.join(names)
    if len(names) == 2:
        # APA writes a serial comma before the ampersand even with two authors
        # ("Dupont, J., & Martin, P."); Harvard does not ("Dupont, J. and Martin, P.").
        # The joiner already carries its own trailing space, so it is used as is.
        comma = joiner if serial_comma_two else " "
        return f"{names[0]}{comma}{and_word} {names[1]}"
    return f"{joiner.join(names[:-1])}, {and_word} {names[-1]}"


#: Characters after which a space must not be inserted.
_NO_SPACE_AFTER = (" ", "\t", "\n", ",", ";", ".", ":", ")", "]", "(", "[")


def _affix(affix: str, text: str, *, before: bool) -> str:
    """Join an affix to the rendered text without adding or removing a separator.

    The author types ``prefix="Voir "`` and ``suffix=", p. 25"`` including the punctuation they
    want, so a space is only inserted when the affix does not already supply one. This keeps
    ``(Voir Dupont, 2024, p. 25)`` free of the doubled and dangling spaces a naive join adds.
    """
    clean = affix.strip()
    if not clean:
        return text
    if before:
        needs_space = not clean.endswith(_NO_SPACE_AFTER) and not text.startswith((" ", "("))
        return f"{clean} {text}" if needs_space else f"{clean}{text}"
    needs_space = not clean.startswith(_NO_SPACE_AFTER)
    return f"{text} {clean}" if needs_space else f"{text}{clean}"


__all__ = [
    "CitationStyle",
    "RenderedBibliographyEntry",
    "format_author_list",
    "format_locator",
]
