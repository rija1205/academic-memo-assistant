"""APA 7th edition.

Rules implemented, as stated in the APA Publication Manual, 7th ed.:

* in-text, one author ......... ``(Dupont, 2024)``
* in-text, two authors ........ ``(Dupont & Martin, 2024)``
* in-text, three or more ...... ``(Dupont et al., 2024)``
* in-text with a locator ...... ``(Dupont, 2024, p. 25)``
* in-text, several references . ``(Dupont, 2024; Martin, 2023)``
* reference list, one author .. ``Dupont, J. (2024).``
* reference list, two authors . ``Dupont, J., & Martin, P. (2024).``
* reference list, 3 to 20 ...... every author, ``&`` before the last
* reference list, 21 or more ... the first 19, an ellipsis, then the last

Missing data is never filled in: a reference with no year is written ``(s.d.)`` and a
reference with no author falls back to its title, as APA requires, with a warning attached.
"""

from __future__ import annotations

from app.citations.data import CitationData, ReferenceCitationData, RenderedCitation
from app.citations.styles.base import (
    CitationStyle,
    RenderedBibliographyEntry,
    format_author_list,
)

#: APA writes a dateless reference as "s.d." (sans date), not "n.d.".
DATE_MISSING = "s.d."


class Apa7Style(CitationStyle):
    name = "apa7"
    label = "APA 7"
    date_missing = DATE_MISSING
    uses_numbers = False
    item_separator = "; "
    open_mark = "("
    close_mark = ")"

    # ----------------------------------------------------------- in-text form
    def _in_text_names(self, reference: ReferenceCitationData) -> str:
        """``Dupont`` / ``Dupont & Martin`` / ``Dupont et al.`` / title when no author."""
        if not reference.authors:
            return (reference.title or reference.citation_key).strip()
        if len(reference.authors) == 1:
            return reference.authors[0].short
        if len(reference.authors) == 2:
            return f"{reference.authors[0].short} & {reference.authors[1].short}"
        return f"{reference.authors[0].short} et al."

    def _in_text_year(self, reference: ReferenceCitationData, year_suffix: str) -> str:
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
                    "utilisé à sa place, conformément à APA."
                )
            if not reference.publication_year:
                warnings.append(
                    f"Année non renseignée pour « {reference.citation_key} » : "
                    f"{DATE_MISSING} est utilisé."
                )
            names = self._in_text_names(reference)
            year = self._in_text_year(reference, "")
            core = f"{names}, {year}" if names else year
            element = self.format_item_affixes(item, core)
            elements.append(element)

        body = self.item_separator.join(elements)
        if citation.mode == "narrative":
            # APA narrative form: "Dupont (2024) montre que…". The author moves out of the
            # parentheses, and only the first author is named when there are several.
            first = citation.items[0]
            names = self._in_text_names(first.reference)
            year = self._in_text_year(first.reference, "")
            if len(citation.items) == 1:
                text = f"{names} ({year})"
                if citation.suffix:
                    text = f"{text}, {citation.suffix.lstrip(', ')}"
                return RenderedCitation(text=text, warnings=_unique(warnings))
            return RenderedCitation(
                text=f"{names} ({year}; {self.item_separator.join(elements[1:])})",
                warnings=_unique(warnings),
            )
        return RenderedCitation(text=self._wrap(body, citation), warnings=_unique(warnings))

    # --------------------------------------------------------- reference list
    def _author_string(self, reference: ReferenceCitationData) -> str:
        authors = reference.authors
        if not authors:
            return ""
        # APA 7 puts a serial comma before the ampersand in every case, including two
        # authors: "Dupont, J., & Martin, P. (2024)."
        if len(authors) <= 20:
            return format_author_list(authors, style="full", serial_comma_two=True)
        # 21 authors or more: the first 19, an ellipsis, then the final author alone.
        head = format_author_list(authors[:19], style="full", and_word="")
        tail = format_author_list(authors[-1:], style="full")
        return f"{head}, . . . {tail}"

    def _title_sentence(self, reference: ReferenceCitationData) -> str:
        """APA uses a sentence-case title; the author's own capitalisation is kept."""
        return (reference.title or "").strip()

    def _year(self, reference: ReferenceCitationData, year_suffix: str | None) -> str:
        year = reference.year_label or DATE_MISSING
        return f"{year}{year_suffix}" if year_suffix else year

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
        title = self._title_sentence(reference)
        if not title:
            warnings.append("Titre non renseigné.")
        year = self._year(reference, year_suffix)

        parts: list[str] = []
        if author:
            parts.append(f"{author} ({year}).")
        else:
            parts.append(f"{title} ({year})." if title else f"({year}).")
        if title and author:
            parts.append(f"{title}.")
        elif title and not author:
            pass

        source = _apa_source(reference)
        if source:
            parts.append(source)
        if reference.doi:
            parts.append(f"https://doi.org/{reference.doi}")

        text = " ".join(part for part in parts if part).strip()
        return RenderedBibliographyEntry(
            reference_id=reference.reference_id,
            text=text,
            number=number,
            warnings=_unique(warnings),
        )


def _apa_source(reference: ReferenceCitationData) -> str:
    """Journal or publisher description, following the APA element order."""
    if reference.journal:
        segments = [reference.journal]
        if reference.volume:
            issue = f"({reference.issue})" if reference.issue else ""
            segments.append(f"{reference.volume}{issue}")
        if reference.pages:
            segments.append(reference.pages.replace("-", "–"))
        return ", ".join(segments) + "."
    book_like = {"book", "book_chapter", "thesis", "report", "conference"}
    if reference.reference_type in book_like or reference.publisher:
        segments = []
        if reference.edition:
            segments.append(f"{reference.edition} éd.")
        if reference.publisher:
            segments.append(reference.publisher)
        if reference.reference_type == "thesis" and reference.journal is None:
            # A thesis is cited as an unpublished work.
            return ("[" + ". ".join(segments) + "].").replace("[]", "")
        return ". ".join(segments) + "." if segments else ""
    if reference.url:
        return reference.url
    return ""


def _unique(values: list[str]) -> list[str]:
    seen: list[str] = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return seen


__all__ = ["DATE_MISSING", "Apa7Style"]
