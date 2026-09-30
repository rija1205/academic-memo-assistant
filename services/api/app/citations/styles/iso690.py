"""ISO 690 style.

**Variant implemented: the English-language numeric form of ISO 690**, i.e. the
``ISO 690:2010`` numeric presentation recommended for scientific and technical documents
(``[1]``, ``[1,3]``), *not* the full ISO 690 author-date form.

This is stated explicitly because ISO 690 has national variants. The French
``NF Z 74-002`` and the Russian GOST variants differ in their punctuation and element order
and are **not** implemented. Only the element set and the numeric presentation below are
covered:

* a numbered reference: ``[1] AUTHOR. Title. Journal, 2024, vol. 10, p. 25-40.``
* in-text: the reference number in square brackets, several numbers comma-separated;
* an author is rendered ``Family, J.`` and an organisation keeps its own name;
* a dateless reference is written ``n.d.``;
* the title is capitalised as the author wrote it, ISO 690 being deliberately
  language-neutral on capitalisation.
"""

from __future__ import annotations

from app.citations.data import CitationData, ReferenceCitationData, RenderedCitation
from app.citations.styles.apa import _unique
from app.citations.styles.base import (
    CitationStyle,
    RenderedBibliographyEntry,
    format_author_list,
)
from app.citations.styles.vancouver import _format_number_range

DATE_MISSING = "n.d."

#: ISO 690 names a handful of document types explicitly.
ISO_TYPE_LABELS: dict[str, str] = {
    "article": "article",
    "book": "monograph",
    "book_chapter": "chapter",
    "thesis": "thesis",
    "report": "report",
    "conference": "conference",
    "webpage": "online",
    "dataset": "dataset",
    "patent": "patent",
    "other": "document",
}


def _terminate(text: str) -> str:
    """End an element with a single period.

    ``Dupont, J.`` already ends with a period because the initials carry one; adding another
    would produce ``Dupont, J..`` in the bibliography.
    """
    stripped = text.rstrip()
    if stripped.endswith("."):
        return stripped
    return f"{stripped}."


class Iso690Style(CitationStyle):
    name = "iso690"
    label = "ISO 690 (numérique)"
    date_missing = DATE_MISSING
    uses_numbers = True
    item_separator = ","
    open_mark = "["
    close_mark = "]"

    def format_citation(self, citation: CitationData) -> RenderedCitation:
        if citation.is_orphaned:
            return self._orphan(citation)
        if not citation.items:
            return RenderedCitation(
                text="[Citation sans référence]",
                warnings=["La citation ne référence aucune entrée de la bibliographie."],
            )
        warnings: list[str] = []
        numbers: list[int] = []
        for item in citation.items:
            if item.number is None:
                warnings.append(
                    f"Numéro non attribué à « {item.reference.citation_key} » : l'ordre de "
                    "citation du document est nécessaire."
                )
                continue
            if item.number not in numbers:
                numbers.append(item.number)
        if not numbers:
            return RenderedCitation(
                text="[Numéro de citation non attribué]",
                warnings=_unique(warnings),
            )
        numbers.sort()
        text = f"{self.open_mark}{_format_number_range(numbers)}{self.close_mark}"
        if citation.prefix:
            text = f"{citation.prefix.strip()} {text}"
        if citation.suffix:
            text = f"{text}, {citation.suffix.strip()}"
        return RenderedCitation(text=text, warnings=_unique(warnings))

    def sort_bibliography(
        self, references: list[ReferenceCitationData]
    ) -> list[ReferenceCitationData]:
        """ISO 690 numeric bibliography is ordered by order of citation."""
        return list(references)

    def assign_year_suffixes(
        self, references: list[ReferenceCitationData]
    ) -> dict[str, str]:
        return {}

    def requires_year_suffix(self) -> bool:
        return False

    def _author_string(self, reference: ReferenceCitationData) -> str:
        if not reference.authors:
            return ""
        return format_author_list(reference.authors, style="full", and_word=",")

    def format_bibliography_entry(
        self,
        reference: ReferenceCitationData,
        *,
        number: int | None = None,
        year_suffix: str | None = None,
    ) -> RenderedBibliographyEntry:
        warnings: list[str] = []
        author = self._author_string(reference)
        if not author:
            warnings.append("Auteur non renseigné.")
        title = (reference.title or "").strip().rstrip(".")
        if not title:
            warnings.append("Titre non renseigné.")
        if not reference.publication_year:
            warnings.append(f"Année non renseignée : {DATE_MISSING} est utilisé.")

        # ISO 690 element order: responsibility, title, edition, place, publisher, date,
        # extent (volume/issue/pages), DOI.
        elements: list[str] = []
        if author:
            elements.append(_terminate(author))
        type_label = ISO_TYPE_LABELS.get(reference.reference_type)
        if type_label and reference.reference_type in {"thesis", "report", "conference"}:
            elements.append(f"[{type_label}]")
        if title:
            elements.append(f"{title}.")
        if reference.edition and reference.reference_type in {"book", "book_chapter"}:
            elements.append(f"{reference.edition} éd.")
        if reference.publisher:
            place = f"{reference.publisher_place}: " if reference.publisher_place else ""
            elements.append(f"{place}{reference.publisher}.")
        if reference.journal:
            journal = reference.journal
            if reference.volume:
                journal = f"{journal}, vol. {reference.volume}"
                if reference.issue:
                    journal = f"{journal}, no {reference.issue}"
            elements.append(f"{journal}.")
        if reference.publication_year:
            elements.append(f"{reference.publication_year}.")
        elif type_label or reference.publisher:
            elements.append(f"{DATE_MISSING}.")
        if reference.pages:
            pages = reference.pages.replace("-", "-")
            elements.append(f"p. {pages}.")
        if reference.doi:
            elements.append(f"DOI: {reference.doi}.")
        elif reference.url:
            elements.append(f"URL: {reference.url}.")

        body = " ".join(element for element in elements if element).strip()
        prefix = f"{number}. " if number is not None else ""
        return RenderedBibliographyEntry(
            reference_id=reference.reference_id,
            text=f"{prefix}{body}".strip(),
            number=number,
            warnings=_unique(warnings),
        )


__all__ = ["DATE_MISSING", "ISO_TYPE_LABELS", "Iso690Style"]
