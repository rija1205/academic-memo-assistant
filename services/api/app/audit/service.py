"""Audit orchestration: collect, run, summarise.

The collection step reads the project and turns it into :class:`AuditData`, the checks run
over that data, and the report assembles findings, statistics and a defence checklist. No
language model is involved at any point, so two runs on the same data produce the same report.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.checks import (
    ALL_CHECKS,
    AuditData,
    CitationView,
    ProjectView,
    ReferenceView,
    SectionView,
    SourceView,
)
from app.audit.findings import (
    INSUFFICIENT_LABEL,
    MISSING_LABEL,
    SEVERITY_LABELS,
    CheckOutcome,
    Finding,
    Severity,
)
from app.audit.statistics import ThesisStats, volume_observations
from app.citations.service import list_citations
from app.models.bibliography import BibliographicReference, ReferenceAuthor
from app.models.citation import CitationItem
from app.models.project import Project
from app.models.source import Source, SourceBlock, SourceFile, SourcePage
from app.models.workspace import OutlineNode, Section

#: Words a reader gets through per minute, used only for a reading-time estimate.
READING_SPEED = 200

#: A section title is compared case-insensitively and without accents.
def _plain(value: str) -> str:
    import unicodedata

    text = unicodedata.normalize("NFKD", value or "")
    return "".join(char for char in text if not unicodedata.combining(char)).casefold()


async def _authors_by_reference(
    db: AsyncSession, ids: list[UUID]
) -> dict[UUID, list[ReferenceAuthor]]:
    if not ids:
        return {}
    result = await db.execute(
        select(ReferenceAuthor)
        .where(ReferenceAuthor.reference_id.in_(ids))
        .order_by(ReferenceAuthor.position.asc())
    )
    grouped: dict[UUID, list[ReferenceAuthor]] = {}
    for author in result.scalars().all():
        grouped.setdefault(author.reference_id, []).append(author)
    return grouped


async def _collect_references(
    db: AsyncSession, project_id: UUID
) -> list[ReferenceView]:
    """Every reference of the project, including the soft-deleted ones.

    A soft-deleted reference is kept in the view because a citation may still point at it, and
    that is precisely the orphan case the audit must report.
    """
    result = await db.execute(
        select(BibliographicReference)
        .where(BibliographicReference.project_id == project_id)
        .order_by(BibliographicReference.citation_key.asc())
    )
    references = list(result.scalars().all())
    authors = await _authors_by_reference(db, [reference.id for reference in references])
    views: list[ReferenceView] = []
    for reference in references:
        rows = authors.get(reference.id, [])
        views.append(
            ReferenceView(
                reference_id=str(reference.id),
                citation_key=reference.citation_key,
                reference_type=reference.reference_type,
                title=reference.title,
                publication_year=reference.publication_year,
                author_count=len([row for row in rows if not row.is_organization]),
                organisation_count=len([row for row in rows if row.is_organization]),
                has_doi=bool(reference.doi),
                has_url=bool(reference.url),
                has_abstract=bool(reference.abstract),
                keyword_count=len(reference.keywords or []),
                is_deleted=reference.deleted_at is not None,
            )
        )
    return views


async def _collect_sources(db: AsyncSession, project_id: UUID) -> list[SourceView]:
    """Sources with their file, page and block counts, which is what provenance rests on."""
    sources = list(
        (
            await db.execute(
                select(Source).where(
                    Source.project_id == project_id, Source.deleted_at.is_(None)
                )
            )
        )
        .scalars()
        .all()
    )
    if not sources:
        return []
    ids = [source.id for source in sources]
    file_counts = dict(
        (
            await db.execute(
                select(SourceFile.source_id, func.count(SourceFile.id))
                .where(SourceFile.source_id.in_(ids))
                .group_by(SourceFile.source_id)
            )
        ).all()
    )
    page_counts = dict(
        (
            await db.execute(
                select(SourcePage.source_id, func.count(SourcePage.id))
                .where(SourcePage.source_id.in_(ids))
                .group_by(SourcePage.source_id)
            )
        ).all()
    )
    block_counts = dict(
        (
            await db.execute(
                select(SourceBlock.source_id, func.count(SourceBlock.id))
                .where(SourceBlock.source_id.in_(ids))
                .group_by(SourceBlock.source_id)
            )
        ).all()
    )
    return [
        SourceView(
            source_id=str(source.id),
            title=source.title,
            original_filename=source.original_filename,
            status=source.status,
            file_count=int(file_counts.get(source.id, 0)),
            page_count=int(page_counts.get(source.id, 0)),
            block_count=int(block_counts.get(source.id, 0)),
            indexed=bool(getattr(source, "indexed", False)),
            # Provenance exists when the extraction produced pages and blocks, which is what
            # lets a reader be sent back to the exact passage.
            has_provenance=int(page_counts.get(source.id, 0)) > 0
            or int(block_counts.get(source.id, 0)) > 0,
        )
        for source in sources
    ]


def _count_nodes(content: dict[str, Any] | None) -> dict[str, int]:
    """Count the interesting nodes of a Tiptap document."""
    counts = {"citation": 0, "image": 0, "table": 0, "equation": 0}
    if not isinstance(content, dict):
        return counts

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for child in node:
                walk(child)
            return
        if not isinstance(node, dict):
            return
        node_type = node.get("type")
        if node_type in counts:
            counts[node_type] += 1
        walk(node.get("content"))

    walk(content.get("content"))
    return counts


async def _collect_sections(
    db: AsyncSession, project_id: UUID
) -> list[SectionView]:
    rows = (
        await db.execute(
            select(Section, OutlineNode.parent_id, OutlineNode.position)
            .join(OutlineNode, OutlineNode.id == Section.outline_node_id)
            .where(Section.project_id == project_id)
            .order_by(OutlineNode.position.asc())
        )
    ).all()
    parents = {row[0].outline_node_id: row[1] for row in rows}
    depths: dict[UUID, int] = {}

    def depth_of(node_id: UUID, seen: set[UUID]) -> int:
        if node_id in depths:
            return depths[node_id]
        parent = parents.get(node_id)
        if parent is None or parent in seen:
            depths[node_id] = 1
            return 1
        value = depth_of(parent, seen | {node_id}) + 1
        depths[node_id] = value
        return value

    sections: list[SectionView] = []
    for section, _parent, _position in rows:
        counts = _count_nodes(section.content)
        sections.append(
            SectionView(
                section_id=str(section.id),
                title=section.title,
                level=min(max(depth_of(section.outline_node_id, set()), 1), 6),
                word_count=int(section.word_count or 0),
                status=section.status,
                plain_text=section.plain_text or "",
                citation_count=counts["citation"],
                figure_count=counts["image"],
                table_count=counts["table"],
                equation_count=counts["equation"],
            )
        )
    return sections


async def _collect_citations(
    db: AsyncSession, project_id: UUID
) -> list[CitationView]:
    """Citations with the text the stage 10 engine produces for them.

    The rendering is obtained from :func:`app.citations.service.render_citations`, the very
    function the editor uses, so the audit reports exactly what a reader will see rather than
    a second, possibly divergent, interpretation.
    """
    from app.citations.service import load_reference_data, render_citations

    pairs = await list_citations(db, project_id=project_id)
    if not pairs:
        return []

    # One query for the section titles rather than one per citation.
    title_rows = (
        await db.execute(
            select(Section.id, Section.title).where(Section.project_id == project_id)
        )
    ).all()
    section_titles = {str(section_id): title for section_id, title in title_rows}

    citation_ids = [citation.id for citation, _ in pairs]
    items_result = await db.execute(
        select(CitationItem)
        .where(CitationItem.citation_id.in_(citation_ids))
        .order_by(CitationItem.position.asc())
    )
    items_map: dict[UUID, list[CitationItem]] = {}
    for item in items_result.scalars().all():
        items_map.setdefault(item.citation_id, []).append(item)
    reference_ids = [item.reference_id for items in items_map.values() for item in items]
    references = await load_reference_data(db, list(dict.fromkeys(reference_ids)))

    # The engine decides the text, the numbering and the orphan state for the whole project.
    rendered_pairs, _style = await render_citations(db, project_id=project_id)
    rendered_by_id = {
        item.citation_id: item for _citation, item in rendered_pairs if item.citation_id
    }
    # A node the engine does not know is a document that was saved before its citation was
    # registered, or a stage 3 placeholder. The audit says so instead of trusting it.
    known_nodes = {item.node_id for item in rendered_by_id.values()}

    views: list[CitationView] = []
    for citation, _position in pairs:
        items = items_map.get(citation.id, [])
        resolved = rendered_by_id.get(str(citation.id))
        dangling = [item.reference_id for item in items if item.reference_id not in references]
        views.append(
            CitationView(
                citation_id=str(citation.id),
                section_id=str(citation.section_id),
                section_title=section_titles.get(str(citation.section_id), "Section"),
                node_id=citation.node_id,
                rendered_text=(
                    resolved.text
                    if resolved is not None
                    else citation.snapshot_text or MISSING_LABEL
                ),
                is_orphaned=bool(
                    (resolved.is_orphaned if resolved is not None else False) or dangling
                ),
                is_pending=bool(citation.node_id) and citation.node_id not in known_nodes,
                mode=citation.mode,
                reference_ids=tuple(str(item.reference_id) for item in items),
            )
        )
    return views


async def _deleted_reference_ids(db: AsyncSession, project_id: UUID) -> set[UUID]:
    rows = (
        await db.execute(
            select(BibliographicReference.id).where(
                BibliographicReference.project_id == project_id,
                BibliographicReference.deleted_at.is_not(None),
            )
        )
    ).all()
    return {row[0] for row in rows}


async def collect_audit_data(
    db: AsyncSession,
    *,
    project_id: UUID,
    current_academic_year: str | None = None,
    expected_section_count: int | None = None,
) -> AuditData:
    """Read the project once and build everything the checks need."""
    project = (
        await db.execute(
            select(Project).where(
                Project.id == project_id, Project.deleted_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if project is None:
        raise LookupError("Mémoire introuvable.")
    return AuditData(
        project=ProjectView(
            project_id=str(project.id),
            title=project.title,
            author_name=project.author_name,
            institution=project.institution,
            education_level=project.education_level,
            academic_year=project.academic_year,
            supervisor_name=project.supervisor_name,
            thesis_type=project.thesis_type,
            problem_statement=project.problem_statement,
            general_objective=project.general_objective,
            specific_objectives=tuple(project.specific_objectives or ()),
            hypotheses=tuple(project.hypotheses or ()),
            keywords=tuple(project.keywords or ()),
            bibliography_style=project.bibliography_style or "",
        ),
        sections=await _collect_sections(db, project_id),
        references=await _collect_references(db, project_id),
        citations=await _collect_citations(db, project_id),
        sources=await _collect_sources(db, project_id),
        expected_section_count=expected_section_count,
        current_academic_year=current_academic_year,
    )


def run_checks(data: AuditData) -> list[CheckOutcome]:
    """Run every check and return the outcomes, in report order."""
    return [check(data) for check in ALL_CHECKS]


def build_defence_checklist(
    findings: list[Finding], stats: ThesisStats, outcomes: list[CheckOutcome]
) -> list[dict[str, Any]]:
    """The list of points to settle before a deposit, in the order a student should work.

    Each entry is a question the author answers, never a change the application performs.
    """
    checklist: list[dict[str, Any]] = []

    def add(priority: int, category: str, question: str, evidence: str | None = None) -> None:
        checklist.append(
            {
                "priority": priority,
                "category": category,
                "question": question,
                "evidence": evidence,
            }
        )

    blockers = [finding for finding in findings if finding.severity == Severity.BLOCKER]
    warnings = [finding for finding in findings if finding.severity == Severity.WARNING]
    informational = [finding for finding in findings if finding.severity == Severity.INFO]

    for finding in blockers:
        add(
            1,
            "Bloquant",
            f"{finding.title} — {finding.location_label or 'projet'}",
            finding.remedy,
        )
    if not blockers:
        add(
            2,
            "Progression",
            "Aucun point bloquant détecté par l'audit automatique.",
            "Cela ne remplace pas votre relecture : l'audit ne lit pas le sens de vos phrases.",
        )
    for finding in warnings[:12]:
        add(
            2,
            "À vérifier",
            f"{finding.title} — {finding.location_label or 'projet'}",
            finding.remedy,
        )
    if informational:
        add(
            3,
            "Information",
            f"{len(informational)} observation(s) sans conséquence bloquante.",
            "Citez notamment les références jamais utilisées et la couverture bibliographique.",
        )

    # Preparation questions, derived from the data rather than from a template.
    if stats.word_count == 0:
        add(
            1,
            "Préparation",
            "Le mémoire ne contient aucun texte.",
            "Rédiger avant toute préparation de soutenance.",
        )
    if stats.citation_density is not None and stats.citation_density < 8:
        add(
            2,
            "Préparation",
            f"Densité de citation faible ({stats.citation_density} pour mille mots).",
            "Prévoyez les questions sur l'ancrage théorique.",
        )
    if stats.orphan_citation_count:
        add(
            1,
            "Préparation",
            f"{stats.orphan_citation_count} citation(s) orpheline(s) seraient "
            "visibles par le jury.",
            "Réparez-les avant la soutenance : une citation non traçable poserait "
            "une question immédiate.",
        )
    if stats.longest_section:
        add(
            3,
            "Préparation",
            f"Section la plus longue : « {stats.longest_section} » "
            f"({stats.longest_section_words} mots).",
            "Prévoyez d'en connaître le détail : c'est là que le jury posera des questions.",
        )
    for outcome in outcomes:
        if outcome.skipped_reason:
            add(
                2,
                INSUFFICIENT_LABEL,
                f"Contrôle « {outcome.code} » non concluant.",
                outcome.skipped_reason,
            )
    return checklist


def build_audit_report(
    data: AuditData,
    outcomes: list[CheckOutcome],
    stats: ThesisStats,
) -> dict[str, Any]:
    """Assemble the full report the student reads."""
    findings = [finding for outcome in outcomes for finding in outcome.findings]
    findings.sort(key=lambda finding: finding.sort_key())
    by_severity = Counter(finding.severity.value for finding in findings)
    by_code = Counter(finding.code for finding in findings)
    observations = volume_observations(stats)
    return {
        "project_id": data.project.project_id,
        "project_title": data.project.title,
        "generated_at": datetime.now(UTC).isoformat(),
        "readiness": _readiness(by_severity),
        "summary": {
            "blockers": by_severity.get("blocker", 0),
            "warnings": by_severity.get("warning", 0),
            "info": by_severity.get("info", 0),
            "checks_run": len(outcomes),
            "checks_inconclusive": len(
                [outcome for outcome in outcomes if outcome.skipped_reason]
            ),
            "labels": SEVERITY_LABELS,
        },
        "findings": [finding.as_dict() for finding in findings],
        "findings_by_code": dict(by_code.most_common()),
        "checks": [
            {
                "code": outcome.code,
                "finding_count": len(outcome.findings),
                "skipped_reason": outcome.skipped_reason,
            }
            for outcome in outcomes
        ],
        "statistics": stats.as_dict(),
        "observations": observations,
        "defence_checklist": build_defence_checklist(findings, stats, outcomes),
        "disclaimer": (
            "Cet audit est déterministe : il compare des données enregistrées et ne "
            "réécrit rien. Il ne remplace pas la relecture ni la validation par l'encadreur. "
            f"Une information absente est notée « {MISSING_LABEL} », jamais reconstituée."
        ),
    }


def _readiness(by_severity: Counter) -> dict[str, Any]:
    """A readiness statement derived from the blockers only.

    No score is invented: a percentage would suggest a precision the checks do not have.
    """
    blockers = by_severity.get("blocker", 0)
    if blockers == 0:
        return {
            "level": "aucun_bloquant",
            "label": "Aucun point bloquant détecté",
            "detail": (
                "L'audit automatique ne relève aucun blocage. Cela ne vaut pas validation : "
                "le sens du texte reste à vérifier par vous et votre encadreur."
            ),
        }
    if blockers <= 2:
        return {
            "level": "corrections_requises",
            "label": f"{blockers} point(s) bloquant(s) à traiter",
            "detail": "Corrigez les points bloquants avant de déposer le mémoire.",
        }
    return {
        "level": "reprise_necessaire",
        "label": f"{blockers} points bloquants à traiter",
        "detail": "Le mémoire nécessite une reprise avant dépôt.",
    }


__all__ = [
    "READING_SPEED",
    "build_audit_report",
    "build_defence_checklist",
    "collect_audit_data",
    "run_checks",
]
