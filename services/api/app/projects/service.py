import json
import re
from copy import deepcopy
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project, ProjectMember
from app.models.source import Source
from app.models.workspace import EMPTY_DOCUMENT, OutlineNode, Section, SectionRevision
from app.projects.schemas import (
    OutlineNodeCreateRequest,
    OutlineNodeResponse,
    OutlineNodeUpdateRequest,
    ProjectCreateRequest,
    ProjectResponse,
    ProjectUpdateRequest,
    SectionContentUpdateRequest,
    SectionResponse,
    SectionRevisionResponse,
)

DEFAULT_OUTLINE = [
    "Introduction",
    "Contexte",
    "Problématique",
    "Objectifs",
    "Hypothèses",
    "Revue de littérature",
    "Matériel et méthodes",
    "Résultats",
    "Discussion",
    "Conclusion",
    "Recommandations",
    "Bibliographie",
    "Annexes",
]
VALID_SECTION_STATUSES = {"empty", "in_progress", "complete"}
VALID_DOCUMENT_NODES = {
    "doc",
    "paragraph",
    "heading",
    "text",
    "bulletList",
    "orderedList",
    "listItem",
    "blockquote",
    "codeBlock",
    "hardBreak",
    "horizontalRule",
    "table",
    "tableRow",
    "tableHeader",
    "tableCell",
    "image",
    "equation",
    "citation",
    "reference",
    "pageBreak",
}


def _required_title(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise HTTPException(status_code=422, detail="Title cannot be empty.")
    return cleaned


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _clean_list(values: list[str] | None) -> list[str] | None:
    if values is None:
        return None
    return [value.strip() for value in values if value.strip()]


def _word_count(value: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", value, flags=re.UNICODE))


def _document_text(node: dict | str) -> str:
    if isinstance(node, str):
        return node
    if node.get("type") == "text":
        return str(node.get("text", ""))
    if node.get("type") == "hardBreak":
        return "\n"
    if node.get("type") in {"equation", "citation", "reference"}:
        attrs = node.get("attrs")
        return str(attrs.get("value", "")) if isinstance(attrs, dict) else ""
    return "".join(_document_text(child) for child in node.get("content", []))


def _validate_document(content: dict) -> None:
    if content.get("type") != "doc" or not isinstance(content.get("content"), list):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Le contenu doit être un document Tiptap valide.",
        )
    try:
        serialized = json.dumps(content, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Le document contient une valeur non sérialisable.",
        ) from exc
    if len(serialized) > 2_000_000:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Le document est trop volumineux.",
        )
    stack: list[tuple[dict, int]] = [(content, 0)]
    node_count = 0
    while stack:
        node, depth = stack.pop()
        node_count += 1
        node_type = node.get("type")
        children = node.get("content", [])
        if (
            depth > 20
            or node_count > 10_000
            or not isinstance(node_type, str)
            or node_type not in VALID_DOCUMENT_NODES
            or not isinstance(children, list)
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Le document est trop profond ou contient un nœud invalide.",
            )
        if any(not isinstance(child, dict) for child in children):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Le document contient un nœud invalide.",
            )
        stack.extend((child, depth + 1) for child in children)


def _section_response(section: Section) -> SectionResponse:
    return SectionResponse(
        id=section.id,
        project_id=section.project_id,
        outline_node_id=section.outline_node_id,
        title=section.title,
        content=deepcopy(section.content),
        plain_text=section.plain_text,
        status=section.status,
        word_count=section.word_count,
        version=section.version,
        last_saved_by=section.last_saved_by,
        created_at=section.created_at,
        updated_at=section.updated_at,
    )


def _revision_response(revision: SectionRevision) -> SectionRevisionResponse:
    return SectionRevisionResponse(
        id=revision.id,
        section_id=revision.section_id,
        project_id=revision.project_id,
        version=revision.version,
        title=revision.title,
        content=deepcopy(revision.content),
        plain_text=revision.plain_text,
        word_count=revision.word_count,
        status=revision.status,
        change_summary=revision.change_summary,
        created_by=revision.created_by,
        restored_from_id=revision.restored_from_id,
        created_at=revision.created_at,
    )


def _outline_response(node: OutlineNode, section: Section) -> OutlineNodeResponse:
    return OutlineNodeResponse(
        id=node.id,
        project_id=node.project_id,
        parent_id=node.parent_id,
        section_id=section.id,
        kind=node.kind,
        title=node.title,
        position=node.position,
        created_at=node.created_at,
        updated_at=node.updated_at,
    )


async def _add_node_and_section(
    db: AsyncSession,
    *,
    project_id: UUID,
    parent_id: UUID | None,
    kind: str,
    title: str,
    position: int,
    created_by: UUID,
    content: dict | None = None,
    plain_text: str = "",
    status_value: str = "empty",
) -> tuple[OutlineNode, Section]:
    node = OutlineNode(
        project_id=project_id,
        parent_id=parent_id,
        kind=kind,
        title=_required_title(title),
        position=position,
    )
    db.add(node)
    await db.flush()
    section = Section(
        project_id=project_id,
        outline_node_id=node.id,
        title=_required_title(title),
        content=deepcopy(content or EMPTY_DOCUMENT),
        plain_text=plain_text,
        status=status_value,
        word_count=_word_count(plain_text),
        version=1,
        last_saved_by=created_by,
    )
    db.add(section)
    await db.flush()
    db.add(
        SectionRevision(
            project_id=project_id,
            section_id=section.id,
            version=1,
            title=section.title,
            content=deepcopy(section.content),
            plain_text=section.plain_text,
            word_count=section.word_count,
            status=section.status,
            change_summary="Création de la section",
            created_by=created_by,
        )
    )
    return node, section


async def _get_project(db: AsyncSession, project_id: UUID) -> Project:
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.deleted_at.is_(None))
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return project


async def _get_node(db: AsyncSession, project_id: UUID, node_id: UUID) -> OutlineNode:
    result = await db.execute(
        select(OutlineNode).where(
            OutlineNode.id == node_id,
            OutlineNode.project_id == project_id,
        )
    )
    node = result.scalar_one_or_none()
    if node is None:
        raise HTTPException(status_code=404, detail="Outline node not found.")
    return node


async def _get_section(
    db: AsyncSession,
    project_id: UUID,
    section_id: UUID,
    *,
    for_update: bool = False,
) -> Section:
    statement = select(Section).where(
        Section.id == section_id,
        Section.project_id == project_id,
    )
    if for_update:
        statement = statement.with_for_update()
    result = await db.execute(statement)
    section = result.scalar_one_or_none()
    if section is None:
        raise HTTPException(status_code=404, detail="Section not found.")
    return section


async def _touch_project(db: AsyncSession, project_id: UUID) -> None:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if project is not None:
        project.updated_at = datetime.now(UTC)


async def _project_sections(db: AsyncSession, project_id: UUID) -> list[Section]:
    result = await db.execute(
        select(Section)
        .where(Section.project_id == project_id)
        .order_by(Section.created_at.asc())
    )
    return list(result.scalars().all())


async def _project_progress(db: AsyncSession, project_id: UUID) -> dict[str, int | float]:
    sections = await _project_sections(db, project_id)
    completed = sum(section.status == "complete" for section in sections)
    in_progress = sum(section.status == "in_progress" for section in sections)
    empty = sum(section.status == "empty" for section in sections)
    total = len(sections)
    progress = round((completed / total) * 100, 1) if total else 0.0
    source_count = int(
        (
            await db.execute(
                select(func.count(Source.id)).where(
                    Source.project_id == project_id,
                    Source.deleted_at.is_(None),
                )
            )
        ).scalar_one()
    )
    return {
        "progress": progress,
        "section_count": total,
        "completed_sections": completed,
        "in_progress_sections": in_progress,
        "empty_sections": empty,
        "word_count": sum(section.word_count for section in sections),
        "source_count": source_count,
        "reference_count": 0,
    }


async def project_response(
    db: AsyncSession,
    project: Project,
    *,
    access_role: str,
) -> ProjectResponse:
    stats = await _project_progress(db, project.id)
    return ProjectResponse(
        id=project.id,
        title=project.title,
        domain=project.domain,
        status=project.status,
        access_role=access_role,
        education_level=project.education_level,
        institution=project.institution,
        author_name=project.author_name,
        supervisor_name=project.supervisor_name,
        academic_year=project.academic_year,
        thesis_type=project.thesis_type,
        bibliography_style=project.bibliography_style,
        problem_statement=project.problem_statement,
        general_objective=project.general_objective,
        specific_objectives=project.specific_objectives or [],
        hypotheses=project.hypotheses or [],
        keywords=project.keywords or [],
        progress=stats["progress"],
        section_count=stats["section_count"],
        completed_sections=stats["completed_sections"],
        in_progress_sections=stats["in_progress_sections"],
        empty_sections=stats["empty_sections"],
        source_count=stats["source_count"],
        reference_count=stats["reference_count"],
        created_at=project.created_at,
        updated_at=project.updated_at,
        archived_at=project.archived_at,
    )


async def create_project(
    db: AsyncSession,
    *,
    owner_id: UUID,
    payload: ProjectCreateRequest,
) -> Project:
    project = Project(
        owner_id=owner_id,
        title=_required_title(payload.title),
        domain=_clean_optional(payload.domain),
        status="draft",
        institution=_clean_optional(payload.institution),
        education_level=payload.education_level,
        author_name=_clean_optional(payload.author_name),
        supervisor_name=_clean_optional(payload.supervisor_name),
        academic_year=_clean_optional(payload.academic_year),
        problem_statement=_clean_optional(payload.problem_statement),
        general_objective=_clean_optional(payload.general_objective),
        specific_objectives=_clean_list(payload.specific_objectives) or [],
        hypotheses=_clean_list(payload.hypotheses) or [],
        keywords=_clean_list(payload.keywords) or [],
        thesis_type=_clean_optional(payload.thesis_type) or "academic",
        bibliography_style=_clean_optional(payload.bibliography_style) or "apa",
    )
    db.add(project)
    try:
        await db.flush()
        db.add(ProjectMember(project_id=project.id, user_id=owner_id, role="owner"))
        for position, title in enumerate(DEFAULT_OUTLINE):
            await _add_node_and_section(
                db,
                project_id=project.id,
                parent_id=None,
                kind="section",
                title=title,
                position=position,
                created_by=owner_id,
            )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Project could not be created.") from exc
    await db.refresh(project)
    return project


async def update_project(
    db: AsyncSession,
    *,
    project: Project,
    payload: ProjectUpdateRequest,
) -> Project:
    values = payload.model_dump(exclude_unset=True)
    for field in (
        "title",
        "domain",
        "institution",
        "author_name",
        "supervisor_name",
        "academic_year",
    ):
        if field in values:
            value = values[field]
            if field == "title" and value is None:
                raise HTTPException(status_code=422, detail="Title cannot be null.")
            if isinstance(value, str):
                value = _required_title(value) if field == "title" else value.strip()
            setattr(project, field, value)
    for field in ("specific_objectives", "hypotheses", "keywords"):
        if field in values:
            setattr(project, field, _clean_list(values[field]) or [])
    for field in ("problem_statement", "general_objective", "thesis_type", "bibliography_style"):
        if field in values:
            value = values[field]
            if field in {"thesis_type", "bibliography_style"} and value is None:
                raise HTTPException(status_code=422, detail=f"{field} cannot be null.")
            setattr(project, field, _clean_optional(value) if isinstance(value, str) else value)
    if "education_level" in values:
        value = values["education_level"]
        if value is None:
            raise HTTPException(status_code=422, detail="education_level cannot be null.")
        project.education_level = value
    if "status" in values:
        value = values["status"]
        if value is None:
            raise HTTPException(status_code=422, detail="status cannot be null.")
        project.status = value
        project.archived_at = datetime.now(UTC) if value == "archived" else None
    project.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(project)
    return project


async def archive_project(db: AsyncSession, *, project: Project) -> Project:
    now = datetime.now(UTC)
    project.status = "archived"
    project.archived_at = now
    project.updated_at = now
    await db.commit()
    await db.refresh(project)
    return project


async def delete_project(db: AsyncSession, *, project: Project) -> None:
    now = datetime.now(UTC)
    project.deleted_at = now
    project.updated_at = now
    await db.commit()


async def duplicate_project(
    db: AsyncSession,
    *,
    project: Project,
    new_owner_id: UUID,
    title: str | None,
) -> Project:
    new_project = Project(
        owner_id=new_owner_id,
        title=_required_title(title or f"{project.title} — copie")[:500],
        domain=project.domain,
        status="draft",
        institution=project.institution,
        education_level=project.education_level,
        author_name=project.author_name,
        supervisor_name=project.supervisor_name,
        academic_year=project.academic_year,
        problem_statement=project.problem_statement,
        general_objective=project.general_objective,
        specific_objectives=deepcopy(project.specific_objectives or []),
        hypotheses=deepcopy(project.hypotheses or []),
        keywords=deepcopy(project.keywords or []),
        thesis_type=project.thesis_type,
        bibliography_style=project.bibliography_style,
    )
    db.add(new_project)
    await db.flush()
    db.add(ProjectMember(project_id=new_project.id, user_id=new_owner_id, role="owner"))

    nodes_result = await db.execute(
        select(OutlineNode, Section)
        .join(Section, Section.outline_node_id == OutlineNode.id)
        .where(OutlineNode.project_id == project.id)
        .order_by(OutlineNode.position.asc(), OutlineNode.created_at.asc())
    )
    node_map: dict[UUID, UUID] = {}
    source_rows = nodes_result.all()
    for old_node, old_section in source_rows:
        new_node = OutlineNode(
            project_id=new_project.id,
            parent_id=None,
            kind=old_node.kind,
            title=old_node.title,
            position=old_node.position,
        )
        db.add(new_node)
        await db.flush()
        node_map[old_node.id] = new_node.id
        new_section = Section(
            project_id=new_project.id,
            outline_node_id=new_node.id,
            title=old_section.title,
            content=deepcopy(old_section.content),
            plain_text=old_section.plain_text,
            status=old_section.status,
            word_count=old_section.word_count,
            version=1,
            last_saved_by=new_owner_id,
        )
        db.add(new_section)
        await db.flush()
        db.add(
            SectionRevision(
                project_id=new_project.id,
                section_id=new_section.id,
                version=1,
                title=new_section.title,
                content=deepcopy(new_section.content),
                plain_text=new_section.plain_text,
                word_count=new_section.word_count,
                status=new_section.status,
                change_summary="Copie du projet",
                created_by=new_owner_id,
            )
        )
    for old_node, _ in source_rows:
        new_node_id = node_map[old_node.id]
        new_parent_id = node_map.get(old_node.parent_id) if old_node.parent_id else None
        new_node = await _get_node(db, new_project.id, new_node_id)
        new_node.parent_id = new_parent_id
    await db.commit()
    await db.refresh(new_project)
    return new_project


async def list_outline(
    db: AsyncSession,
    *,
    project_id: UUID,
) -> list[OutlineNodeResponse]:
    result = await db.execute(
        select(OutlineNode, Section)
        .join(Section, Section.outline_node_id == OutlineNode.id)
        .where(OutlineNode.project_id == project_id)
        .order_by(OutlineNode.position.asc(), OutlineNode.created_at.asc())
    )
    return [_outline_response(node, section) for node, section in result.all()]


async def _validate_parent(
    nodes: list[OutlineNode],
    *,
    node_id: UUID | None,
    parent_id: UUID | None,
    kind: str,
) -> None:
    if kind == "section" and parent_id is not None:
        raise HTTPException(status_code=422, detail="A section must be at the root.")
    if kind == "subsection" and parent_id is None:
        raise HTTPException(status_code=422, detail="A subsection needs a parent section.")
    if parent_id is None:
        return
    if not nodes:
        raise HTTPException(status_code=422, detail="Project outline is empty.")
    parent = next((item for item in nodes if item.id == parent_id), None)
    if parent is None or parent.project_id != nodes[0].project_id:
        raise HTTPException(status_code=422, detail="Parent outline node not found.")
    if parent.kind != "section":
        raise HTTPException(status_code=422, detail="Subsections can only be nested in sections.")
    current = parent
    seen: set[UUID] = set()
    while current is not None:
        if current.id == node_id or current.id in seen:
            raise HTTPException(status_code=422, detail="An outline node cannot contain itself.")
        seen.add(current.id)
        current = next((item for item in nodes if item.id == current.parent_id), None)


async def create_outline_node(
    db: AsyncSession,
    *,
    project_id: UUID,
    created_by: UUID,
    payload: OutlineNodeCreateRequest,
) -> OutlineNodeResponse:
    result = await db.execute(select(OutlineNode).where(OutlineNode.project_id == project_id))
    nodes = list(result.scalars().all())
    await _validate_parent(
        nodes,
        node_id=None,
        parent_id=payload.parent_id,
        kind=payload.kind,
    )
    siblings = [node for node in nodes if node.parent_id == payload.parent_id]
    position = payload.position if payload.position is not None else len(siblings)
    position = max(0, min(position, len(siblings)))
    node, section = await _add_node_and_section(
        db,
        project_id=project_id,
        parent_id=payload.parent_id,
        kind=payload.kind,
        title=payload.title,
        position=position,
        created_by=created_by,
    )
    for sibling in siblings:
        if sibling.position >= position:
            sibling.position += 1
    ordered_siblings = sorted(
        [*siblings, node],
        key=lambda item: item.position,
    )
    for index, sibling in enumerate(ordered_siblings):
        sibling.position = index
    await _touch_project(db, project_id)
    await db.commit()
    await db.refresh(node)
    await db.refresh(section)
    return _outline_response(node, section)


async def update_outline_node(
    db: AsyncSession,
    *,
    project_id: UUID,
    node_id: UUID,
    payload: OutlineNodeUpdateRequest,
) -> OutlineNodeResponse:
    node = await _get_node(db, project_id, node_id)
    section_result = await db.execute(
        select(Section).where(
            Section.outline_node_id == node_id,
            Section.project_id == project_id,
        )
    )
    section = section_result.scalar_one_or_none()
    if section is None:
        raise HTTPException(status_code=404, detail="Section not found.")
    original_parent_id = node.parent_id
    original_kind = node.kind
    if payload.title is not None:
        node.title = _required_title(payload.title)
        section.title = node.title

    hierarchy_changed = (
        payload.kind is not None
        or "parent_id" in payload.model_fields_set
        or payload.position is not None
    )
    if hierarchy_changed:
        result = await db.execute(select(OutlineNode).where(OutlineNode.project_id == project_id))
        nodes = list(result.scalars().all())
        effective_kind = payload.kind or node.kind
        effective_parent_id = (
            payload.parent_id
            if "parent_id" in payload.model_fields_set
            else node.parent_id
        )
        if effective_kind != original_kind:
            children_result = await db.execute(
                select(OutlineNode).where(
                    OutlineNode.project_id == project_id,
                    OutlineNode.parent_id == node.id,
                )
            )
            if children_result.scalars().first() is not None:
                raise HTTPException(
                    status_code=422,
                    detail="Un nœud avec des sous-sections ne peut pas changer de type.",
                )
        await _validate_parent(
            nodes,
            node_id=node.id,
            parent_id=effective_parent_id,
            kind=effective_kind,
        )
        node.kind = effective_kind
        node.parent_id = effective_parent_id
        if payload.position is not None:
            node.position = payload.position
        for parent_id in {original_parent_id, effective_parent_id}:
            siblings = [item for item in nodes if item.parent_id == parent_id]
            siblings.sort(key=lambda item: item.position)
            for index, sibling in enumerate(siblings):
                sibling.position = index
    node.updated_at = datetime.now(UTC)
    section.updated_at = node.updated_at
    await _touch_project(db, project_id)
    await db.commit()
    return _outline_response(node, section)


async def reorder_outline(
    db: AsyncSession,
    *,
    project_id: UUID,
    moves: list,
) -> list[OutlineNodeResponse]:
    result = await db.execute(select(OutlineNode).where(OutlineNode.project_id == project_id))
    nodes = list(result.scalars().all())
    by_id = {node.id: node for node in nodes}
    if len({move.node_id for move in moves}) != len(moves):
        raise HTTPException(status_code=422, detail="Duplicate outline move.")
    for move in moves:
        if move.node_id not in by_id:
            raise HTTPException(status_code=404, detail="Outline node not found.")
        await _validate_parent(
            nodes,
            node_id=move.node_id,
            parent_id=move.parent_id,
            kind=by_id[move.node_id].kind,
        )
    for move in moves:
        node = by_id[move.node_id]
        node.parent_id = move.parent_id
        node.position = move.position
    for node in nodes:
        seen: set[UUID] = set()
        parent_id = node.parent_id
        while parent_id is not None:
            if parent_id in seen or parent_id == node.id:
                raise HTTPException(status_code=422, detail="Outline cycle detected.")
            seen.add(parent_id)
            parent_id = by_id[parent_id].parent_id
    grouped: dict[UUID | None, list[OutlineNode]] = {}
    for node in nodes:
        grouped.setdefault(node.parent_id, []).append(node)
    for siblings in grouped.values():
        siblings.sort(key=lambda item: item.position)
        for index, sibling in enumerate(siblings):
            sibling.position = index
    await _touch_project(db, project_id)
    await db.commit()
    return await list_outline(db, project_id=project_id)


async def delete_outline_node(db: AsyncSession, *, project_id: UUID, node_id: UUID) -> None:
    node = await _get_node(db, project_id, node_id)
    await db.delete(node)
    await _touch_project(db, project_id)
    await db.commit()


async def _duplicate_node_tree(
    db: AsyncSession,
    *,
    project_id: UUID,
    source_node_id: UUID,
    new_parent_id: UUID | None,
    created_by: UUID,
    position: int,
    root: bool = False,
) -> tuple[OutlineNode, Section]:
    source_result = await db.execute(
        select(OutlineNode, Section)
        .join(Section, Section.outline_node_id == OutlineNode.id)
        .where(
            OutlineNode.id == source_node_id,
            OutlineNode.project_id == project_id,
        )
    )
    source_node, source_section = source_result.one()
    new_node, new_section = await _add_node_and_section(
        db,
        project_id=project_id,
        parent_id=new_parent_id,
        kind=source_node.kind,
        title=(f"{source_node.title} (copie)"[:300] if root else source_node.title),
        position=position,
        created_by=created_by,
        content=deepcopy(source_section.content),
        plain_text=source_section.plain_text,
        status_value=source_section.status,
    )
    children_result = await db.execute(
        select(OutlineNode)
        .where(
            OutlineNode.project_id == project_id,
            OutlineNode.parent_id == source_node_id,
        )
        .order_by(OutlineNode.position.asc(), OutlineNode.created_at.asc())
    )
    for child in children_result.scalars().all():
        await _duplicate_node_tree(
            db,
            project_id=project_id,
            source_node_id=child.id,
            new_parent_id=new_node.id,
            created_by=created_by,
            position=child.position,
        )
    return new_node, new_section


async def duplicate_outline_node(
    db: AsyncSession,
    *,
    project_id: UUID,
    node_id: UUID,
    created_by: UUID,
) -> OutlineNodeResponse:
    node = await _get_node(db, project_id, node_id)
    result = await db.execute(
        select(func.max(OutlineNode.position)).where(
            OutlineNode.project_id == project_id,
            OutlineNode.parent_id == node.parent_id,
        )
    )
    position = (result.scalar_one_or_none() or -1) + 1
    new_node, new_section = await _duplicate_node_tree(
        db,
        project_id=project_id,
        source_node_id=node_id,
        new_parent_id=node.parent_id,
        created_by=created_by,
        position=position,
        root=True,
    )
    await _touch_project(db, project_id)
    await db.commit()
    await db.refresh(new_node)
    await db.refresh(new_section)
    return _outline_response(new_node, new_section)


async def get_section_content(
    db: AsyncSession,
    *,
    project_id: UUID,
    section_id: UUID,
) -> SectionResponse:
    section = await _get_section(db, project_id, section_id)
    return _section_response(section)


async def save_section_content(
    db: AsyncSession,
    *,
    project_id: UUID,
    section_id: UUID,
    user_id: UUID,
    payload: SectionContentUpdateRequest,
) -> SectionResponse:
    _validate_document(payload.content)
    section = await _get_section(db, project_id, section_id, for_update=True)
    if payload.expected_version is not None and payload.expected_version != section.version:
        raise HTTPException(
            status_code=409,
            detail="The section changed on another device. Reload before saving.",
        )
    plain_text = _document_text(payload.content).strip()
    word_count = _word_count(plain_text)
    status_value = payload.status or ("empty" if not plain_text else "in_progress")
    if status_value not in VALID_SECTION_STATUSES:
        raise HTTPException(status_code=422, detail="Invalid section status.")
    if status_value == "complete" and not plain_text:
        raise HTTPException(status_code=422, detail="A complete section cannot be empty.")
    if (
        section.content == payload.content
        and section.plain_text == plain_text
        and section.status == status_value
    ):
        return _section_response(section)
    section.content = deepcopy(payload.content)
    section.plain_text = plain_text
    section.status = status_value
    section.word_count = word_count
    section.version += 1
    section.last_saved_by = user_id
    section.updated_at = datetime.now(UTC)
    db.add(
        SectionRevision(
            project_id=project_id,
            section_id=section.id,
            version=section.version,
            title=section.title,
            content=deepcopy(section.content),
            plain_text=section.plain_text,
            word_count=section.word_count,
            status=section.status,
            change_summary=payload.change_summary,
            created_by=user_id,
        )
    )
    await _touch_project(db, project_id)
    await db.commit()
    await db.refresh(section)
    return _section_response(section)


async def list_section_revisions(
    db: AsyncSession,
    *,
    project_id: UUID,
    section_id: UUID,
) -> list[SectionRevisionResponse]:
    await _get_section(db, project_id, section_id)
    result = await db.execute(
        select(SectionRevision)
        .where(
            SectionRevision.project_id == project_id,
            SectionRevision.section_id == section_id,
        )
        .order_by(SectionRevision.version.desc())
    )
    return [_revision_response(revision) for revision in result.scalars().all()]


async def restore_section_revision(
    db: AsyncSession,
    *,
    project_id: UUID,
    section_id: UUID,
    revision_id: UUID,
    user_id: UUID,
    change_summary: str | None,
) -> SectionResponse:
    section = await _get_section(db, project_id, section_id, for_update=True)
    result = await db.execute(
        select(SectionRevision).where(
            SectionRevision.id == revision_id,
            SectionRevision.project_id == project_id,
            SectionRevision.section_id == section_id,
        )
    )
    revision = result.scalar_one_or_none()
    if revision is None:
        raise HTTPException(status_code=404, detail="Revision not found.")
    section.title = revision.title
    outline_node = await _get_node(db, project_id, section.outline_node_id)
    outline_node.title = revision.title
    section.content = deepcopy(revision.content)
    section.plain_text = revision.plain_text
    section.word_count = revision.word_count
    section.status = revision.status or ("in_progress" if revision.word_count else "empty")
    section.version += 1
    section.last_saved_by = user_id
    section.updated_at = datetime.now(UTC)
    outline_node.updated_at = section.updated_at
    db.add(
        SectionRevision(
            project_id=project_id,
            section_id=section.id,
            version=section.version,
            title=section.title,
            content=deepcopy(section.content),
            plain_text=section.plain_text,
            word_count=section.word_count,
            status=section.status,
            change_summary=change_summary or "Restauration d'une version",
            created_by=user_id,
            restored_from_id=revision.id,
        )
    )
    await _touch_project(db, project_id)
    await db.commit()
    await db.refresh(section)
    return _section_response(section)
