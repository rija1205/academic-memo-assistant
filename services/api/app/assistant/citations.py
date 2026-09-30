"""Citation validation.

This module is the enforcement point of the anti-hallucination rule. A citation returned by
the model is never trusted: every identifier it claims is checked against the exact set of
passages that were really sent in the prompt, and against the project of the question.

Three outcomes are possible:

* ``accepted``: the identifier exists in the supplied context and belongs to this project;
* ``rejected``: the identifier is unknown, malformed, or points to another project. The
  reference is dropped and recorded, and the answer is flagged as containing unsupported
  references;
* ``missing``: the model made claims without any citation. The answer is flagged so the
  frontend can warn the user.

The validated citation list is what the UI renders, so the model can never make the
application display a source that was not retrieved.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from app.assistant.prompts import CITATION_ID_PATTERN, ContextPassage, extract_citation_ids


class CitationRejectionReason(StrEnum):
    UNKNOWN_IDENTIFIER = "unknown_identifier"
    MALFORMED_IDENTIFIER = "malformed_identifier"
    OTHER_PROJECT = "other_project"


@dataclass(frozen=True, slots=True)
class ValidatedCitation:
    """A citation the application is allowed to display."""

    position: int
    citation_id: str
    chunk_id: UUID
    source_id: UUID
    source_file_id: UUID | None
    provenance_id: UUID
    page: int
    quote: str
    rag_score: float
    source_title: str
    original_filename: str
    authors: tuple[str, ...]
    publication_year: int | None
    project_id: UUID

    def as_dict(self) -> dict[str, object]:
        return {
            "position": self.position,
            "citation_id": self.citation_id,
            "chunk_id": str(self.chunk_id),
            "source_id": str(self.source_id),
            "source_file_id": str(self.source_file_id) if self.source_file_id else None,
            "provenance_id": str(self.provenance_id),
            "page": self.page,
            "quote": self.quote,
            "rag_score": self.rag_score,
            "source_title": self.source_title,
            "original_filename": self.original_filename,
            "authors": list(self.authors),
            "publication_year": self.publication_year,
            "project_id": str(self.project_id),
        }


@dataclass(frozen=True, slots=True)
class RejectedCitation:
    """A reference the model produced that must not be shown to the user."""

    citation_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class CitationValidationResult:
    """Outcome of validating the citations of one answer."""

    accepted: list[ValidatedCitation]
    rejected: list[RejectedCitation]

    @property
    def has_rejected(self) -> bool:
        return bool(self.rejected)

    @property
    def has_citations(self) -> bool:
        return bool(self.accepted)


def validate_citations(
    *,
    answer: str,
    passages: list[ContextPassage],
    project_id: UUID,
) -> CitationValidationResult:
    """Cross-check every citation identifier the model used against the supplied passages."""
    allowed = {passage.citation_id: passage for passage in passages}
    # Passage ids that do not belong to the question's project are refused explicitly, even
    # if a caller managed to place them in the context list.
    accepted: list[ValidatedCitation] = []
    rejected: list[RejectedCitation] = []
    seen: set[str] = set()

    for identifier in extract_citation_ids(answer):
        if identifier in seen:
            continue
        seen.add(identifier)
        if not CITATION_ID_PATTERN.match(identifier):
            rejected.append(
                RejectedCitation(
                    citation_id=identifier,
                    reason=CitationRejectionReason.MALFORMED_IDENTIFIER,
                )
            )
            continue
        passage = allowed.get(identifier)
        if passage is None:
            rejected.append(
                RejectedCitation(
                    citation_id=identifier,
                    reason=CitationRejectionReason.UNKNOWN_IDENTIFIER,
                )
            )
            continue
        chunk = passage.chunk
        if chunk.project_id != project_id:
            rejected.append(
                RejectedCitation(
                    citation_id=identifier,
                    reason=CitationRejectionReason.OTHER_PROJECT,
                )
            )
            continue
        accepted.append(
            ValidatedCitation(
                position=len(accepted) + 1,
                citation_id=identifier,
                chunk_id=chunk.chunk_id,
                source_id=chunk.source.id,
                source_file_id=chunk.source.file_id,
                provenance_id=chunk.provenance_id,
                page=chunk.page_number,
                quote=chunk.text.strip(),
                rag_score=round(chunk.score, 6),
                source_title=chunk.source.display_title(),
                original_filename=chunk.source.original_filename,
                authors=chunk.source.authors,
                publication_year=chunk.source.publication_year,
                project_id=project_id,
            )
        )
    return CitationValidationResult(accepted=accepted, rejected=rejected)


def render_grounding_note(
    *, result: CitationValidationResult, insufficient_sources: bool
) -> str | None:
    """Build the user-visible warning about grounding, or ``None`` when everything is clean."""
    if insufficient_sources:
        return None
    if result.has_rejected:
        return (
            "Certaines references citees par le modele ne correspondent a aucune source "
            "fournie et ont ete retirees de cette reponse."
        )
    if not result.has_citations:
        return (
            "Cette reponse ne comporte aucune citation : le modele n'a pas rattache ses "
            "affirmations aux passages fournis. Verifiez-la avant de l'utiliser."
        )
    return None
