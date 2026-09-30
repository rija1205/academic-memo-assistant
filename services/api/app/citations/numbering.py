"""Document-order numbering for numeric styles (Vancouver, ISO 690).

The number of a reference in a numeric style is **the order in which it is first cited in the
document**, not its alphabetical position and not its identifier. That makes numbering a
property of the document, so it lives here rather than inside a style class.

The rule is simple and total:

* walk the citations in document order (section order, then position in the section);
* the first time a ``reference_id`` is met, it receives the next number;
* a reference cited again keeps the number it already has.

Because the walk is deterministic, deleting the citation of reference B renumbers everything
after it: ``A -> 1, B -> 2, C -> 3`` becomes ``A -> 1, C -> 2``. Nothing is stored, so the
renumbering is not a migration that could be forgotten.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.citations.data import CitationData


@dataclass(frozen=True, slots=True)
class NumberedCitation:
    """A citation and the number each of its references received."""

    citation: CitationData
    numbers: tuple[int | None, ...]

    @property
    def assigned(self) -> tuple[int, ...]:
        return tuple(number for number in self.numbers if number is not None)


def assign_numbers(citations: list[CitationData]) -> list[NumberedCitation]:
    """Number every reference by order of first citation.

    ``citations`` must already be in document order; the service is responsible for that.
    """
    order: dict[str, int] = {}
    result: list[NumberedCitation] = []
    for citation in citations:
        numbers: list[int | None] = []
        for item in citation.items:
            reference_id = item.reference.reference_id
            if not reference_id:
                numbers.append(None)
                continue
            if reference_id not in order:
                order[reference_id] = len(order) + 1
            numbers.append(order[reference_id])
        result.append(NumberedCitation(citation=citation, numbers=tuple(numbers)))
    return result


def number_map(citations: list[CitationData]) -> dict[str, int]:
    """Return ``reference_id -> number`` for the whole document."""
    order: dict[str, int] = {}
    for citation in citations:
        for item in citation.items:
            reference_id = item.reference.reference_id
            if reference_id and reference_id not in order:
                order[reference_id] = len(order) + 1
    return order


def numbered_items(
    citations: list[CitationData],
) -> list[tuple[CitationData, list]]:
    """Return the citations in document order with numbered items, ready for a style.

    The style receives data that already carries its number, so no style ever has to know how
    document order is computed.
    """
    result: list[tuple[CitationData, list]] = []
    for numbered in assign_numbers(citations):
        items = [
            item.with_number(number)
            for item, number in zip(
                numbered.citation.items, numbered.numbers, strict=True
            )
        ]
        result.append((numbered.citation, items))
    return result


__all__ = ["NumberedCitation", "assign_numbers", "number_map", "numbered_items"]
