"""Vancouver (ICMJE numeric) style.

A Vancouver citation is a number, and the number depends on **the order of the first citation
in the document**, not on the alphabetical order. That is a property of the document, not of
the style, so it is computed by :mod:`app.citations.numbering` and injected into the data
through :meth:`CitationItemData.with_number`. The style itself only formats.

Rendering of several numbers follows the ICMJE convention: consecutive numbers are collapsed
(``[1-3]``) and the rest are listed (``[1,3,5]``). A single number is written ``[1]``.
"""

from __future__ import annotations

from app.citations.data import CitationData, ReferenceCitationData, RenderedCitation
from app.citations.styles.apa import _unique
from app.citations.styles.base import CitationStyle, RenderedBibliographyEntry

MISSING_NUMBER_MARK = "?"


class VancouverStyle(CitationStyle):
    name = "vancouver"
    label = "Vancouver"
    date_missing = ""
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
        body = _format_number_range(numbers)
        if citation.suffix:
            body = f"{body} {citation.suffix.strip()}"
        return RenderedCitation(
            text=f"{self.open_mark}{body}{self.close_mark}",
            warnings=_unique(warnings),
        )

    def sort_bibliography(
        self, references: list[ReferenceCitationData]
    ) -> list[ReferenceCitationData]:
        """A numeric bibliography keeps the order of first citation.

        The order is a property of the document, so the service hands the references over
        already numbered and already in citation order. This method therefore preserves the
        incoming order instead of sorting by anything.
        """
        return list(references)

    def assign_year_suffixes(
        self, references: list[ReferenceCitationData]
    ) -> dict[str, str]:
        """A numeric style does not disambiguate years with a letter suffix."""
        return {}

    def requires_year_suffix(self) -> bool:
        return False

    def format_bibliography_entry(
        self,
        reference: ReferenceCitationData,
        *,
        number: int | None = None,
        year_suffix: str | None = None,
    ) -> RenderedBibliographyEntry:
        warnings: list[str] = []
        if not reference.has_authors:
            warnings.append("Auteur non renseigné.")
        if not reference.publication_year:
            warnings.append("Année non renseignée.")
        if not reference.title:
            warnings.append("Titre non renseigné.")

        authors = ""
        if reference.authors:
            names = [author.short for author in reference.authors[:6]]
            if len(reference.authors) > 6:
                names.append("et al.")
            authors = ", ".join(names) + ". "

        title = (reference.title or "").strip().rstrip(".")
        segments = [f"{authors}{title}." if title else authors.strip()]

        source = reference.journal or reference.publisher
        if source:
            detail = source
            if reference.volume:
                detail = f"{detail}. {reference.volume}"
                if reference.issue:
                    detail = f"{detail}({reference.issue})"
            if reference.pages:
                detail = f"{detail}:{reference.pages}"
            segments.append(f"{detail}.")
        if reference.publication_year:
            segments.append(f"{reference.publication_year}.")
        if reference.doi:
            segments.append(f"doi:{reference.doi}.")

        text = " ".join(segment for segment in segments if segment.strip()).strip()
        prefix = f"{number}. " if number is not None else ""
        return RenderedBibliographyEntry(
            reference_id=reference.reference_id,
            text=f"{prefix}{text}".strip(),
            number=number,
            warnings=_unique(warnings),
        )


def _format_number_range(numbers: list[int]) -> str:
    """``[1,3,5]`` -> ``1-3,5``; ``[1]`` -> ``1``; ``[1,2,3,7]`` -> ``1-3,7``."""
    if not numbers:
        return ""
    if len(numbers) == 1:
        return str(numbers[0])
    parts: list[str] = []
    start = previous = numbers[0]
    for number in numbers[1:]:
        if number == previous + 1:
            previous = number
            continue
        parts.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = number
    parts.append(str(start) if start == previous else f"{start}-{previous}")
    return ",".join(parts)


__all__ = ["MISSING_NUMBER_MARK", "VancouverStyle", "_format_number_range"]
