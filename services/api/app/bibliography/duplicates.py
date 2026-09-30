"""Duplicate detection for bibliographic references.

Three levels, from certain to possible:

* **exact**   - same canonical DOI;
* **strong**  - same normalised title and same year;
* **possible** - high title similarity and at least one shared author surname.

Nothing is ever deleted automatically. A match produces a report the author acts on, and a
merge is an explicit operation that never loses data (see :func:`plan_merge`).

The comparison is a pure function so it can be tested without a database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.core.normalize import normalize_doi, normalize_title, title_similarity

#: Title similarity above which two entries are reported as a probable duplicate.
PROBABLE_TITLE_THRESHOLD = 0.85


class DuplicateLevel(StrEnum):
    EXACT = "exact"
    STRONG = "strong"
    POSSIBLE = "possible"


@dataclass(frozen=True, slots=True)
class DuplicateMatch:
    """One candidate duplicate, with the reason it was reported."""

    other_id: Any
    other_citation_key: str
    other_title: str | None
    level: DuplicateLevel
    reason: str
    title_similarity: float = 0.0
    shared_authors: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "reference_id": str(self.other_id),
            "citation_key": self.other_citation_key,
            "title": self.other_title,
            "level": self.level.value,
            "reason": self.reason,
            "title_similarity": round(self.title_similarity, 4),
            "shared_authors": list(self.shared_authors),
        }


@dataclass(slots=True)
class DuplicateReport:
    matches: list[DuplicateMatch] = field(default_factory=list)

    @property
    def has_matches(self) -> bool:
        return bool(self.matches)

    @property
    def exact(self) -> list[DuplicateMatch]:
        return [item for item in self.matches if item.level == DuplicateLevel.EXACT]

    @property
    def strong(self) -> list[DuplicateMatch]:
        return [item for item in self.matches if item.level == DuplicateLevel.STRONG]

    @property
    def possible(self) -> list[DuplicateMatch]:
        return [item for item in self.matches if item.level == DuplicateLevel.POSSIBLE]

    def as_dict(self) -> dict[str, object]:
        return {
            "has_duplicates": self.has_matches,
            "exact": [item.as_dict() for item in self.exact],
            "strong": [item.as_dict() for item in self.strong],
            "possible": [item.as_dict() for item in self.possible],
        }


@dataclass(frozen=True, slots=True)
class ReferenceSummary:
    """The subset of a reference needed to compare two entries."""

    id: Any
    citation_key: str
    title: str | None
    publication_year: int | None
    doi: str | None
    author_families: tuple[str, ...] = ()


def _family_names(authors: list[Any]) -> tuple[str, ...]:
    names = {
        normalize_title(getattr(author, "family_name", "")).strip()
        for author in authors
        if getattr(author, "family_name", None)
    }
    return tuple(sorted(name for name in names if name))


def compare(reference: ReferenceSummary, other: ReferenceSummary) -> DuplicateMatch | None:
    """Compare two references and return a match, or ``None`` when they are distinct."""
    if reference.id == other.id:
        return None

    doi = normalize_doi(reference.doi)
    other_doi = normalize_doi(other.doi)
    if doi and other_doi and doi == other_doi:
        return DuplicateMatch(
            other_id=other.id,
            other_citation_key=other.citation_key,
            other_title=other.title,
            level=DuplicateLevel.EXACT,
            reason=f"DOI identique ({doi})",
        )

    reference_title = normalize_title(reference.title)
    other_title = normalize_title(other.title)
    if not reference_title or not other_title:
        return None

    if (
        reference_title == other_title
        and reference.publication_year is not None
        and reference.publication_year == other.publication_year
    ):
        return DuplicateMatch(
            other_id=other.id,
            other_citation_key=other.citation_key,
            other_title=other.title,
            level=DuplicateLevel.STRONG,
            reason="Titre identique et même année",
            title_similarity=1.0,
            shared_authors=_shared_authors(reference, other),
        )

    similarity = title_similarity(reference.title, other.title)
    shared = _shared_authors(reference, other)
    if similarity >= PROBABLE_TITLE_THRESHOLD and shared:
        return DuplicateMatch(
            other_id=other.id,
            other_citation_key=other.citation_key,
            other_title=other.title,
            level=DuplicateLevel.POSSIBLE,
            reason=(
                f"Titre similaire ({similarity:.0%}) et auteur commun : {', '.join(shared)}"
            ),
            title_similarity=similarity,
            shared_authors=shared,
        )
    return None


def _shared_authors(
    reference: ReferenceSummary, other: ReferenceSummary
) -> tuple[str, ...]:
    if not reference.author_families or not other.author_families:
        return ()
    shared = set(reference.author_families) & set(other.author_families)
    return tuple(sorted(shared))


def find_duplicates(
    reference: ReferenceSummary, others: list[ReferenceSummary]
) -> DuplicateReport:
    """Report every candidate duplicate of ``reference`` among ``others``."""
    report = DuplicateReport()
    for other in others:
        if other.id == reference.id:
            continue
        match = compare(reference, other)
        if match is not None:
            report.matches.append(match)
    report.matches.sort(key=lambda item: (item.level.value, item.other_citation_key))
    return report


@dataclass(frozen=True, slots=True)
class MergePlan:
    """What a merge would keep, and which values would be filled from the other entry.

    A merge never deletes a value that only one side holds: missing fields are filled from
    the duplicate, and the two citation keys are joined so neither is silently dropped.
    """

    target_id: Any
    merged_from_id: Any
    fills: dict[str, Any]
    authors_to_move: int
    tags_to_move: int
    notes_appended: bool


def plan_merge(
    *,
    target: Any,
    source: Any,
    target_fields: dict[str, Any],
    source_fields: dict[str, Any],
    source_author_count: int,
    overlapping_tag_count: int,
) -> MergePlan:
    """Describe a merge without performing it, so the caller can show what will happen."""
    fills: dict[str, Any] = {}
    for field_name, value in source_fields.items():
        if value in (None, "", [], {}):
            continue
        current = target_fields.get(field_name)
        if current in (None, "", [], {}):
            fills[field_name] = value
    source_notes = source_fields.get("notes")
    notes_appended = bool(
        source_notes and source_notes not in (target_fields.get("notes") or "")
    )
    return MergePlan(
        target_id=getattr(target, "id", target),
        merged_from_id=getattr(source, "id", source),
        fills=fills,
        authors_to_move=source_author_count,
        tags_to_move=max(0, overlapping_tag_count),
        notes_appended=notes_appended,
    )


__all__ = [
    "PROBABLE_TITLE_THRESHOLD",
    "DuplicateLevel",
    "DuplicateMatch",
    "DuplicateReport",
    "MergePlan",
    "ReferenceSummary",
    "compare",
    "find_duplicates",
    "plan_merge",
]
