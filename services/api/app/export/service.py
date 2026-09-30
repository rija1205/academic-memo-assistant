"""Build the export document model from the database.

This is the single place that reads the project and turns it into a :class:`DocumentModel`.
Both renderers consume its output, which is what guarantees that the PDF and the DOCX of the
same memoir are identical in content.

Two invariants matter here:

* **citations** come from the stage 10 engine. The function asks
  :func:`app.citations.service.render_citations` for the text of every citation and never
  re-formats one, so exporting can never disagree with the editor;
* **nothing is invented**. A missing author, a missing year or a missing institution stays
  missing, and the model records a warning instead of filling the gap.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.citations.service import (
    orphaned_citations,
    render_citations,
    rendered_bibliography,
)
from app.export.blocks import (
    BibliographyBlock,
    Block,
    BlockKind,
    CoverBlock,
    DocumentModel,
    FigureBlock,
    IndexBlock,
    Span,
    TableBlock,
    TocBlock,
    TocEntry,
)
from app.export.images import image_size, resolve_image
from app.export.options import MAX_SECTIONS, ExportGuard, ExportOptions
from app.export.tiptap import TiptapConverter
from app.models.project import Project
from app.models.workspace import OutlineNode, Section


@dataclass(slots=True)
class SectionPlan:
    """One section of the memoir, in document order."""

    section_id: UUID
    title: str
    level: int
    position: int
    content: dict[str, Any]
    word_count: int
    status: str


@dataclass(slots=True)
class HeadingPlan:
    """A heading with its automatic number, computed once for both renderers."""

    level: int
    text: str
    number: str | None
    anchor: str


ROMAN = (
    "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
    "XI", "XII", "XIII", "XIV", "XV", "XVI", "XVII", "XVIII", "XIX", "XX",
)

#: Section kinds that are annexes rather than body chapters.
ANNEX_MARKERS = ("annexe", "appendix")


async def load_project(db: AsyncSession, project_id: UUID) -> Project:
    project = (
        await db.execute(
            select(Project).where(
                Project.id == project_id, Project.deleted_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if project is None:
        raise LookupError("Mémoire introuvable.")
    return project


async def load_sections(
    db: AsyncSession, *, project_id: UUID, include_annexes: bool = True
) -> list[SectionPlan]:
    """Load the sections in document order, with the outline hierarchy as their level."""
    result = await db.execute(
        select(Section, OutlineNode.parent_id, OutlineNode.position)
        .join(OutlineNode, OutlineNode.id == Section.outline_node_id)
        .where(Section.project_id == project_id)
        .order_by(OutlineNode.position.asc(), Section.created_at.asc())
    )
    rows = result.all()
    if len(rows) > MAX_SECTIONS:
        raise ValueError(
            f"Le mémoire comporte {len(rows)} sections, au-delà de la limite "
            f"de {MAX_SECTIONS} pour un export."
        )
    # Depth is computed from the outline tree so a chapter is level 1 and its sections level 2.
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

    plans: list[SectionPlan] = []
    for section, _parent, position in rows:
        title = section.title.strip()
        is_annex = _is_annex(title, include_annexes)
        level = min(max(depth_of(section.outline_node_id, set()), 1), 6)
        if is_annex:
            level = 1
        plans.append(
            SectionPlan(
                section_id=section.id,
                title=title,
                level=level,
                position=int(position),
                content=section.content if isinstance(section.content, dict) else {},
                word_count=int(section.word_count or 0),
                status=section.status,
            )
        )
    return plans


def _is_annex(title: str, include_annexes: bool) -> bool:
    lowered = title.casefold().strip()
    if not lowered:
        return False
    if lowered.startswith(ANNEX_MARKERS) or f" {ANNEX_MARKERS[0]}" in lowered[:20]:
        return True
    # A title that is only a letter plus punctuation is an annex by convention.
    return bool(lowered.replace(".", "").replace(" ", "").isalpha()) and len(lowered) <= 4


def build_cover(project: Project, options: ExportOptions) -> CoverBlock:
    """The cover page, built only from fields the project actually holds."""
    cover = CoverBlock(kind=BlockKind.COVER)
    cover.title = project.title
    cover.subtitle = project.domain
    cover.author = project.author_name
    cover.institution = project.institution
    cover.level = project.education_level
    cover.academic_year = project.academic_year
    cover.supervisor = project.supervisor_name
    cover.thesis_type = project.thesis_type
    cover.problem_statement = project.problem_statement
    cover.general_objective = project.general_objective
    cover.specific_objectives = tuple(project.specific_objectives or ())
    cover.keywords = tuple(project.keywords or ())
    cover.domain = project.domain
    return cover


def compute_headings(
    plans: list[SectionPlan], *, number: bool, start_index: int = 0
) -> list[HeadingPlan]:
    """Assign a number to each section title, as universities require.

    Level 1 counts with roman numerals, deeper levels with ``1.1``-style numbers. The numbers
    are computed here so the PDF outline and the DOCX numbering are identical.
    """
    counters: dict[int, int] = {}
    headings: list[HeadingPlan] = []
    for offset, plan in enumerate(plans, start=1):
        # A level is clamped here as well as on load, because this function owns the numbering
        # and must not depend on its caller having normalised the level first.
        plan.level = min(max(plan.level, 1), 6)
        counters[plan.level] = counters.get(plan.level, 0) + 1
        for deeper in [key for key in counters if key > plan.level]:
            counters[deeper] = 0
        if not number:
            label = None
        elif plan.level == 1:
            # ``headings`` does not yet contain the current one, so the count is offset by one.
            roman_index = start_index + len(
                [item for item in headings if item.level == 1]
            ) + 1
            label = ROMAN[roman_index - 1] if roman_index <= len(ROMAN) else str(roman_index)
        else:
            # Only the levels that actually have a heading contribute a part, so a section
            # with no numbered parent does not print "0.0.1".
            parts = [
                str(counters[level])
                for level in range(1, plan.level + 1)
                if counters.get(level)
            ]
            if not parts:
                parts = [str(counters.get(plan.level, 1) or 1)]
            label = ".".join(parts)
        headings.append(
            HeadingPlan(
                level=plan.level,
                text=plan.title,
                number=label,
                anchor=f"section-{offset}",
            )
        )
    return headings


async def build_document_model(
    db: AsyncSession,
    *,
    project_id: UUID,
    options: ExportOptions,
) -> DocumentModel:
    """Assemble everything an export needs, in one pass over the database."""
    guard = ExportGuard()
    project = await load_project(db, project_id)
    plans = await load_sections(db, project_id=project_id, include_annexes=options.include_annexes)

    # The citation text always comes from the stage 10 engine, for the whole project so the
    # Vancouver numbering is identical to the one shown in the editor.
    rendered, resolved_style = await render_citations(db, project_id=project_id)
    resolved: dict[str, dict[str, Any]] = {
        item.node_id: {
            "text": item.text,
            "is_orphaned": item.is_orphaned,
            "warnings": item.warnings,
            "reference_ids": item.reference_ids,
            "citation_id": item.citation_id,
        }
        for _citation, item in rendered
    }

    # A node present in a document but unknown to the server has never been saved. Its own
    # text is then the only thing available, and the converter flags the block as pending.
    document_node_ids = _collect_node_ids(plans)
    pending = {node_id for node_id in document_node_ids if node_id not in resolved}

    orphans = await orphaned_citations(db, project_id=project_id)
    bibliography_payload = (
        await rendered_bibliography(db, project_id=project_id)
        if options.include_bibliography
        else None
    )

    model = DocumentModel(
        project_title=project.title,
        project_id=str(project_id),
        style=resolved_style,
        style_label=_style_label(resolved_style),
    )
    if options.include_cover:
        model.cover = build_cover(project, options)
        _check_cover(model.cover, guard)

    headings = compute_headings(plans, number=options.number_headings)
    heading_by_title = {heading.text: heading for heading in headings}
    converter = TiptapConverter(resolved_citations=resolved, pending_citation_ids=pending)

    def section_blocks(plan: SectionPlan) -> list[Block]:
        blocks: list[Block] = []
        heading = heading_by_title.get(plan.title)
        if plan.title:
            label = _heading_text(heading) if heading is not None else plan.title
            blocks.append(
                Block(
                    kind=BlockKind.HEADING,
                    level=plan.level,
                    spans=(Span(label),),
                    plain_text=label,
                    alignment="left",
                    keep_with_next=True,
                )
            )
            guard.add_block(label)
        for block in converter.convert(plan.content):
            guard.add_block(block.text)
            guard.add_text(block.text)
            blocks.append(block)
        return blocks

    body_plans = [plan for plan in plans if not _is_annex(plan.title)]
    annex_plans = [plan for plan in plans if _is_annex(plan.title)]
    if not options.include_annexes:
        annex_plans = []

    body: list[Block] = []
    for plan in body_plans:
        body.extend(section_blocks(plan))
    annexes: list[Block] = []
    for plan in annex_plans:
        annexes.extend(section_blocks(plan))

    figures_index = [
        (f"Figure {block.number}", block.caption or "Sans l?gende")
        for block in body + annexes
        if isinstance(block, FigureBlock) and block.number
    ]
    tables_index = [
        (f"Tableau {block.number}", block.caption or f"Tableau {block.number}")
        for block in body + annexes
        if isinstance(block, TableBlock) and block.number
    ]

    front: list[Block] = []
    toc = _build_toc(plans, heading_by_title, options)
    if options.include_toc and toc is not None:
        front.append(toc)
    if options.include_list_of_figures and figures_index:
        front.append(
            IndexBlock(
                kind=BlockKind.LIST_OF_FIGURES,
                entries=figures_index,
                title=options.list_of_figures_heading,
                plain_text=options.list_of_figures_heading,
            )
        )
    if options.include_list_of_tables and tables_index:
        front.append(
            IndexBlock(
                kind=BlockKind.LIST_OF_TABLES,
                entries=tables_index,
                title=options.list_of_tables_heading,
                plain_text=options.list_of_tables_heading,
            )
        )

    model.blocks.extend(front)
    model.blocks.extend(body)
    if annexes:
        # Annexes come after the bibliography, as universities require. The marker tells the
        # renderer where the body ends, so the bibliography lands in between.
        model.blocks.append(Block(kind=BlockKind.PAGE_BREAK))
        model.annexes = annexes

    if bibliography_payload is not None:
        model.bibliography = BibliographyBlock(
            kind=BlockKind.BIBLIOGRAPHY,
            lines=tuple(entry.text for entry in bibliography_payload["entries"]),
            style=resolved_style,
            style_label=model.style_label,
            incomplete_count=int(bibliography_payload["incomplete_count"]),
            plain_text=options.bibliography_heading,
        )
        model.uncited_count = int(bibliography_payload["uncited_count"])
        model.orphan_count = len(bibliography_payload["orphaned_citations"])

    # Resolve the images once, so both renderers apply the same decision.
    _resolve_figures(
        model.blocks + model.annexes,
        allow_remote=options.embed_remote_images,
        guard=guard,
    )

    model.figure_count = converter.figure_counter
    model.table_count = converter.table_counter
    model.citation_count = converter.citation_counter
    model.section_titles = [plan.title for plan in plans if plan.title]
    model.warnings.extend(guard.warnings)
    if orphans:
        model.warnings.append(
            f"{len(orphans)} citation(s) invalide(s) : reference introuvable."
        )
    return model


def _collect_node_ids(plans: list[SectionPlan]) -> set[str]:
    """Every citation node id present in the documents of the project."""
    from app.citations.service import collect_citation_nodes

    found: set[str] = set()
    for plan in plans:
        for node in collect_citation_nodes(plan.content):
            if node["node_id"]:
                found.add(node["node_id"])
    return found


def _style_label(style_name: str) -> str:
    from app.citations.styles import get_style

    try:
        return get_style(style_name).label
    except Exception:
        return style_name


def _heading_text(heading: HeadingPlan) -> str:
    if heading.number:
        return f"{heading.number}. {heading.text}".strip()
    return heading.text


def _build_toc(
    all_plans: list[SectionPlan],
    heading_by_title: dict[str, HeadingPlan],
    options: ExportOptions,
) -> TocBlock | None:
    """The table of contents, built from the sections that really exist.

    Nothing is invented: a section with no title contributes nothing, and the annexes are
    listed as their own group.
    """
    entries: list[TocEntry] = []
    for plan in all_plans:
        heading = heading_by_title.get(plan.title)
        if heading is None or not plan.title:
            continue
        text = _heading_text(heading)
        entries.append(TocEntry(level=heading.level, text=text, anchor=heading.anchor))
    if not entries:
        return None
    return TocBlock(
        kind=BlockKind.TOC,
        entries=entries,
        title=options.toc_heading,
        plain_text=options.toc_heading,
    )


def _resolve_figures(
    blocks: list[Block], *, allow_remote: bool, guard: ExportGuard
) -> None:
    for block in blocks:
        if isinstance(block, FigureBlock):
            data, content_type, reason = resolve_image(
                block.source_url, allow_remote=allow_remote
            )
            block.data = data
            block.content_type = content_type
            block.unavailable_reason = reason
            if data and image_size(data) is None:
                # The bytes are not a readable image; the renderer will use a fixed box.
                block.unavailable_reason = "Image illisible."
            if not data:
                guard.warn(f"Figure non intégrée : {reason}")


def _check_cover(cover: CoverBlock, guard: ExportGuard) -> None:
    for label, value in (
        ("auteur", cover.author),
        ("établissement", cover.institution),
        ("encadreur", cover.supervisor),
        ("année universitaire", cover.academic_year),
    ):
        if not value:
            guard.warn(f"Page de couverture : {label} non renseigné.")


__all__ = [
    "ANNEX_MARKERS",
    "HeadingPlan",
    "SectionPlan",
    "build_cover",
    "build_document_model",
    "compute_headings",
    "load_project",
    "load_sections",
]
