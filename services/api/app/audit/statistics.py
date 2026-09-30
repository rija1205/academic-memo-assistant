"""Thesis statistics, computed from what the project actually contains.

Every number here is a count or a ratio over stored data. Nothing is estimated, and a section
the student has not written yet is counted as empty rather than extrapolated.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from app.audit.checks import AuditData

#: Rough French academic norms, used only to phrase an observation, never to fail anything.
#: They are reported as context so the student can judge, not as a verdict.
Norms = {
    "words_per_chapter_low": 1500,
    "words_per_chapter_high": 12000,
    "words_per_chapter_typical": 4000,
    "citation_density_low": 8,
    "citation_density_typical": 25,
    "figure_count_typical": 10,
    "table_count_typical": 8,
}


@dataclass(slots=True)
class SectionStat:
    section_id: str
    title: str
    level: int
    word_count: int
    citation_count: int
    figure_count: int
    table_count: int
    status: str
    #: Citations per thousand words; ``None`` when the section is empty.
    citation_density: float | None = None
    read_minutes: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "section_id": self.section_id,
            "title": self.title,
            "level": self.level,
            "word_count": self.word_count,
            "citation_count": self.citation_count,
            "figure_count": self.figure_count,
            "table_count": self.table_count,
            "status": self.status,
            "citation_density": self.citation_density,
            "read_minutes": round(self.read_minutes, 1),
        }


@dataclass(slots=True)
class ThesisStats:
    """The whole statistical picture of a memoir."""

    project_id: str
    title: str

    # structure
    section_count: int = 0
    chapter_count: int = 0
    subsection_count: int = 0
    empty_section_count: int = 0
    completed_section_count: int = 0

    # volume
    word_count: int = 0
    character_count: int = 0
    #: Estimated reading time at 200 words per minute, which is the usual academic rate.
    read_minutes: float = 0.0
    longest_section: str | None = None
    longest_section_words: int = 0
    average_section_words: int = 0

    # citations and bibliography
    citation_count: int = 0
    distinct_cited_references: int = 0
    orphan_citation_count: int = 0
    pending_citation_count: int = 0
    narrative_citation_count: int = 0
    reference_count: int = 0
    uncited_reference_count: int = 0
    references_with_doi: int = 0
    references_with_url: int = 0
    reference_type_counts: dict[str, int] = field(default_factory=dict)
    reference_year_span: tuple[int, int] | None = None
    most_cited_references: list[dict[str, Any]] = field(default_factory=list)
    #: Citations per thousand words, ``None`` when the memoir is empty.
    citation_density: float | None = None
    bibliography_style: str = ""
    #: Reference ids cited in the text that no longer exist in the library.
    dangling_citation_references: int = 0

    # sources
    source_count: int = 0
    indexed_source_count: int = 0
    source_page_count: int = 0
    source_block_count: int = 0

    # visual material
    figure_count: int = 0
    table_count: int = 0
    equation_count: int = 0

    sections: list[SectionStat] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "title": self.title,
            "section_count": self.section_count,
            "chapter_count": self.chapter_count,
            "subsection_count": self.subsection_count,
            "empty_section_count": self.empty_section_count,
            "completed_section_count": self.completed_section_count,
            "word_count": self.word_count,
            "character_count": self.character_count,
            "read_minutes": round(self.read_minutes, 1),
            "longest_section": self.longest_section,
            "longest_section_words": self.longest_section_words,
            "average_section_words": self.average_section_words,
            "citation_count": self.citation_count,
            "distinct_cited_references": self.distinct_cited_references,
            "orphan_citation_count": self.orphan_citation_count,
            "pending_citation_count": self.pending_citation_count,
            "narrative_citation_count": self.narrative_citation_count,
            "reference_count": self.reference_count,
            "uncited_reference_count": self.uncited_reference_count,
            "references_with_doi": self.references_with_doi,
            "references_with_url": self.references_with_url,
            "reference_type_counts": self.reference_type_counts,
            "reference_year_span": (
                list(self.reference_year_span) if self.reference_year_span else None
            ),
            "most_cited_references": self.most_cited_references,
            "citation_density": self.citation_density,
            "bibliography_style": self.bibliography_style,
            "dangling_citation_references": self.dangling_citation_references,
            "source_count": self.source_count,
            "indexed_source_count": self.indexed_source_count,
            "source_page_count": self.source_page_count,
            "source_block_count": self.source_block_count,
            "figure_count": self.figure_count,
            "table_count": self.table_count,
            "equation_count": self.equation_count,
            "sections": [section.as_dict() for section in self.sections],
        }


def compute_stats(data: AuditData) -> ThesisStats:
    """Build the statistics of a memoir from the collected audit data."""
    stats = ThesisStats(project_id=data.project.project_id, title=data.project.title)
    stats.bibliography_style = data.project.bibliography_style

    # --- structure and volume
    stats.section_count = len(data.sections)
    stats.chapter_count = len([section for section in data.sections if section.level == 1])
    stats.subsection_count = len([section for section in data.sections if section.level > 1])
    stats.empty_section_count = len(
        [section for section in data.sections if section.word_count == 0]
    )
    stats.completed_section_count = len(
        [section for section in data.sections if section.status == "complete"]
    )
    stats.word_count = sum(section.word_count for section in data.sections)
    stats.character_count = sum(
        len(section.plain_text) for section in data.sections
    )
    # 200 words per minute is the usual academic reading pace.
    stats.read_minutes = stats.word_count / 200.0
    if data.sections:
        longest = max(data.sections, key=lambda section: section.word_count)
        stats.longest_section = longest.title
        stats.longest_section_words = longest.word_count
        stats.average_section_words = int(stats.word_count / len(data.sections))

    # --- citations
    stats.citation_count = len(data.citations)
    stats.orphan_citation_count = len([c for c in data.citations if c.is_orphaned])
    stats.pending_citation_count = len([c for c in data.citations if c.is_pending])
    stats.narrative_citation_count = len([c for c in data.citations if c.mode == "narrative"])
    # Only identifiers that resolve to a real reference are counted: a citation pointing at a
    # deleted reference must not inflate the number of works actually cited.
    known_ids = {reference.reference_id for reference in data.references}
    per_reference: Counter[str] = Counter()
    for citation in data.citations:
        for reference_id in citation.reference_ids:
            if reference_id in known_ids:
                per_reference[reference_id] += 1
    stats.distinct_cited_references = len(per_reference)
    stats.citation_density = (
        round(stats.citation_count / (stats.word_count / 1000.0), 1)
        if stats.word_count > 0
        else None
    )

    # --- bibliography
    live = [reference for reference in data.references if not reference.is_deleted]
    stats.reference_count = len(live)
    stats.references_with_doi = len([reference for reference in live if reference.has_doi])
    stats.references_with_url = len([reference for reference in live if reference.has_url])
    stats.uncited_reference_count = len(
        [reference for reference in live if reference.reference_id not in per_reference]
    )
    # References cited but absent from the library, which is exactly the orphan situation.
    stats.dangling_citation_references = len(
        {
            reference_id
            for citation in data.citations
            for reference_id in citation.reference_ids
            if reference_id not in known_ids
        }
    )
    stats.reference_type_counts = dict(
        Counter(reference.reference_type for reference in live).most_common()
    )
    years = [
        reference.publication_year for reference in live if reference.publication_year
    ]
    if years:
        stats.reference_year_span = (min(years), max(years))
    by_id = {reference.reference_id: reference for reference in data.references}
    stats.most_cited_references = [
        {
            "reference_id": reference_id,
            "citation_key": by_id[reference_id].citation_key if reference_id in by_id else None,
            "title": by_id[reference_id].title if reference_id in by_id else None,
            "count": count,
        }
        for reference_id, count in per_reference.most_common(10)
    ]

    # --- sources
    stats.source_count = len(data.sources)
    stats.indexed_source_count = len([source for source in data.sources if source.indexed])
    stats.source_page_count = sum(source.page_count for source in data.sources)
    stats.source_block_count = sum(source.block_count for source in data.sources)

    # --- visual material and per-section detail
    for section in data.sections:
        stats.figure_count += section.figure_count
        stats.table_count += section.table_count
        stats.equation_count += section.equation_count
        stats.sections.append(
            SectionStat(
                section_id=section.section_id,
                title=section.title,
                level=section.level,
                word_count=section.word_count,
                citation_count=section.citation_count,
                figure_count=section.figure_count,
                table_count=section.table_count,
                status=section.status,
                citation_density=(
                    round(section.citation_count / (section.word_count / 1000.0), 1)
                    if section.word_count > 0
                    else None
                ),
                read_minutes=section.word_count / 200.0,
            )
        )
    return stats


def volume_observations(stats: ThesisStats) -> list[dict[str, str]]:
    """Neutral observations about the volume, phrased as context rather than as a verdict.

    A thesis has no universal length, so these are comparisons with the recorded norms and
    never a judgement about quality.
    """
    observations: list[dict[str, str]] = []
    if stats.word_count == 0:
        observations.append(
            {
                "code": "volume.vide",
                "label": "Mémoire vide",
                "detail": (
                    "Aucun mot n'est encore enregistré : aucune statistique n'est exploitable."
                ),
            }
        )
        return observations
    if stats.average_section_words:
        average = stats.average_section_words
        if average < Norms["words_per_chapter_low"]:
            observations.append(
                {
                    "code": "volume.court",
                    "label": "Sections courtes",
                    "detail": (
                        f" Moyenne de {average} mots par section, en dessous des "
                        f"{Norms['words_per_chapter_low']} mots souvent retenus. "
                        "Cela convient à un mémoire court ; à vérifier selon l'établissement."
                    ),
                }
            )
        elif average > Norms["words_per_chapter_high"]:
            observations.append(
                {
                    "code": "volume.long",
                    "label": "Sections longues",
                    "detail": (
                        f"Moyenne de {average} mots par section, au-delà des "
                        f"{Norms['words_per_chapter_high']} mots usuels."
                    ),
                }
            )
    if stats.citation_density is not None:
        if stats.citation_density < Norms["citation_density_low"]:
            observations.append(
                {
                    "code": "volume.density_faible",
                    "label": "Densité de citation faible",
                    "detail": (
                        f"{stats.citation_density} citation(s) pour mille mots. "
                        "À vérifier si la discipline exige une appuis sur la littérature."
                    ),
                }
            )
        elif stats.citation_density > Norms["citation_density_typical"] * 2:
            observations.append(
                {
                    "code": "volume.density_forte",
                    "label": "Densité de citation élevée",
                    "detail": (
                        f"{stats.citation_density} citations pour mille mots : vérifier que "
                        "chacune soutient un propos précis et n'est pas redondante."
                    ),
                }
            )
    if stats.figure_count == 0 and stats.table_count == 0 and stats.word_count > 2000:
        observations.append(
            {
                "code": "volume.sans_illustration",
                "label": "Aucune figure ni tableau",
                "detail": (
                    "Un mémoire de plus de 2 000 mots sans figure ni tableau : à vérifier "
                    "selon les exigences de l'établissement."
                ),
            }
        )
    return observations


__all__ = ["Norms", "SectionStat", "ThesisStats", "compute_stats", "volume_observations"]
