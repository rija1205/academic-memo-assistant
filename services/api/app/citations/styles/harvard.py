"""Harvard (author-date) style.

Harvard differs from APA on three points that matter here:

* the in-text conjunction is ``and`` rather than ``&``;
* a dateless reference is written ``n.d.``;
* the reference list separates the year with a comma: ``Dupont, J. (2024)`` stays the same,
  but a book is cited as ``Dupont, J. (2024) *Title*. Place: Publisher.``
"""

from __future__ import annotations

from app.citations.data import CitationData, ReferenceCitationData, RenderedCitation
from app.citations.styles.apa import _unique
from app.citations.styles.base import (
    CitationStyle,
    RenderedBibliographyEntry,
    format_author_list,
)

DATE_MISSING = "n.d."


class HarvardStyle(CitationStyle):
    name = "harvard"
    label = "Harvard"
    date_missing = DATE_MISSING
    uses_numbers = False
    item_separator = "; "
    open_mark = "("
    close_mark = ")"

    def _in_text_names(self, reference: ReferenceCitationData) -> str:
        if not reference.authors:
            return (reference.title or reference.citation_key).strip()
        names = [author.short for author in reference.authors]
        if len(names) == 1:
            return names[0]
        if len(names) == 2:
            return f"{names[0]} and {names[1]}"
        if len(names) == 3:
            return f"{names[0]}, {names[1]} and {names[2]}"
        return f"{names[0]} et al."

    def _year(self, reference: ReferenceCitationData, year_suffix: str = "") -> str:
        year = reference.year_label or DATE_MISSING
        return f"{year}{year_suffix}" if year_suffix else year

    def format_citation(self, citation: CitationData) -> RenderedCitation:
        if citation.is_orphaned:
            return self._orphan(citation)
        if not citation.items:
            return RenderedCitation(
                text="[Citation sans référence]",
                warnings=["La citation ne référence aucune entrée de la bibliographie."],
            )
        warnings: list[str] = []
        elements: list[str] = []
        for item in citation.items:
            reference = item.reference
            if not reference.has_authors:
                warnings.append(
                    f"Auteur non renseigné pour « {reference.citation_key} » : le titre est "
                    "utilisé à sa place."
                )
            if not reference.publication_year:
                warnings.append(
                    f"Année non renseignée pour « {reference.citation_key} » : {DATE_MISSING}."
                )
            names = self._in_text_names(reference)
            core = f"{names}, {self._year(reference)}" if names else self._year(reference)
            elements.append(self.format_item_affixes(item, core))

        body = self.item_separator.join(elements)
        if citation.mode == "narrative":
            first = citation.items[0]
            names = self._in_text_names(first.reference)
            text = f"{names} ({self._year(first.reference)})"
            if len(citation.items) > 1:
                text = f"{text}; {self.item_separator.join(elements[1:])}"
            elif citation.suffix:
                text = f"{text}, {citation.suffix.lstrip(', ')}"
            return RenderedCitation(text=text, warnings=_unique(warnings))
        return RenderedCitation(text=self._wrap(body, citation), warnings=_unique(warnings))

    def _author_string(self, reference: ReferenceCitationData) -> str:
        if not reference.authors:
            return ""
        return format_author_list(
            reference.authors, style="full", and_word="and"
        )

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
            warnings.append("Auteur non renseigné : le titre occupe la place de l'auteur.")
        title = (reference.title or "").strip()
        if not title:
            warnings.append("Titre non renseigné.")
        year = self._year(reference, year_suffix or "")

        parts: list[str] = []
        head = f"{author} ({year})" if author else f"{title} ({year})" if title else f"({year})"
        parts.append(head + ".")
        if title and author:
            parts.append(f"{title}.")
        if reference.journal:
            segments = [reference.journal]
            if reference.volume:
                issue = f", {reference.issue}" if reference.issue else ""
                segments.append(f"{reference.volume}{issue}")
            if reference.pages:
                segments.append(f"pp. {reference.pages}")
            parts.append(", ".join(segments) + ".")
        elif reference.publisher:
            segments = []
            if reference.publisher_place:
                segments.append(reference.publisher_place)
            segments.append(reference.publisher)
            if reference.reference_type == "thesis" and reference.edition:
                segments.insert(0, f"{reference.edition} éd.")
            parts.append(": ".join(segments) + ".")
        elif reference.url:
            parts.append(f"Available at: {reference.url}")
        if reference.doi:
            parts.append(f"doi: {reference.doi}")

        text = " ".join(part for part in parts if part).strip()
        return RenderedBibliographyEntry(
            reference_id=reference.reference_id,
            text=text,
            number=number,
            warnings=_unique(warnings),
        )


__all__ = ["DATE_MISSING", "HarvardStyle"]
