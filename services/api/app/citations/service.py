"""Citation service: storage, live rendering, synchronisation and bibliography.

The central decision of this module is that **a citation stores no rendered text for the
current document**. A row holds the identity of the references it points to, and the text is
produced on demand by the style engine from the live metadata of those references. Three
requirements fall out of that single choice:

* **synchronisation** (change the year of a reference, every citation follows) needs no write
  at all, so it cannot drift;
* **style switching** needs no migration;
* a citation is never *wrong*, it is only rendered from current data.

The only frozen text is ``snapshot_text``, captured when the citation is written, and it is
used exclusively to keep an old revision or a deleted reference readable.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, func, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.citations.data import (
    CitationAuthor,
    CitationData,
    CitationItemData,
    ReferenceCitationData,
)
from app.citations.numbering import number_map
from app.citations.schemas import (
    CitationCreateRequest,
    CitationItemInput,
    CitationUpdateRequest,
    RenderedBibliographyEntryResponse,
    RenderedCitationResponse,
    UncitedReferenceResponse,
)
from app.citations.styles import get_style, normalise_style_name
from app.models.bibliography import BibliographicReference, ReferenceAuthor
from app.models.citation import Citation, CitationItem
from app.models.project import Project
from app.models.workspace import OutlineNode, Section

#: A document is expected to hold far fewer citations than this; the cap protects the
#: numbering pass and the bibliography render from a pathological document.
MAX_CITATIONS_PER_SECTION = 5000
MAX_RENDER_REFERENCES = 1000


async def _references_by_id(
    db: AsyncSession, ids: list[UUID]
) -> dict[UUID, BibliographicReference]:
    if not ids:
        return {}
    result = await db.execute(
        select(BibliographicReference).where(BibliographicReference.id.in_(ids))
    )
    return {reference.id: reference for reference in result.scalars().all()}


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


def to_reference_data(
    reference: BibliographicReference, authors: list[ReferenceAuthor] | None = None
) -> ReferenceCitationData:
    """Convert a stored reference into the engine input, preserving the author order."""
    return ReferenceCitationData(
        reference_id=str(reference.id),
        citation_key=reference.citation_key,
        reference_type=reference.reference_type,
        title=reference.title,
        authors=tuple(
            CitationAuthor(
                family_name=author.family_name,
                given_name=author.given_name,
                orcid=author.orcid,
                is_organization=bool(getattr(author, "is_organization", False)),
            )
            for author in (authors or [])
        ),
        publication_year=reference.publication_year,
        journal=reference.journal,
        volume=reference.volume,
        issue=reference.issue,
        pages=reference.pages,
        publisher=reference.publisher,
        publisher_place=reference.publisher_place,
        edition=reference.edition,
        doi=reference.doi,
        url=reference.url,
        isbn=reference.isbn,
        issn=reference.issn,
        language=reference.language,
        accessed_at=reference.accessed_at.isoformat() if reference.accessed_at else None,
    )


async def load_reference_data(
    db: AsyncSession, reference_ids: list[UUID]
) -> dict[UUID, ReferenceCitationData]:
    """Load references and their authors, keeping the stage 9 author order."""
    references = await _references_by_id(db, reference_ids)
    authors = await _authors_by_reference(db, list(references))
    return {
        reference_id: to_reference_data(reference, authors.get(reference_id, []))
        for reference_id, reference in references.items()
    }


async def _section_of(
    db: AsyncSession, *, project_id: UUID, section_id: UUID
) -> Section:
    section = (
        await db.execute(
            select(Section).where(
                Section.id == section_id,
                Section.project_id == project_id,
            )
        )
    ).scalar_one_or_none()
    if section is None:
        raise HTTPException(status_code=404, detail="Section introuvable.")
    return section


async def _validate_references(
    db: AsyncSession, *, project_id: UUID, items: list[CitationItemInput]
) -> dict[UUID, ReferenceCitationData]:
    """Every item must point at a live reference of this project.

    A reference of another project is not merely rejected with a message: it is reported as
    404, so a caller cannot use this endpoint to discover that it exists.
    """
    ids = list(dict.fromkeys(item.reference_id for item in items))
    if not ids:
        raise HTTPException(status_code=422, detail="La citation doit référencer une référence.")
    references = await _references_by_id(db, ids)
    for reference_id in ids:
        reference = references.get(reference_id)
        if reference is None or reference.project_id != project_id:
            raise HTTPException(status_code=404, detail="Référence introuvable dans ce projet.")
    authors = await _authors_by_reference(db, ids)
    return {
        reference_id: to_reference_data(reference, authors.get(reference_id, []))
        for reference_id, reference in references.items()
    }


# ------------------------------------------------------------------ retrieval


async def get_citation(
    db: AsyncSession, *, project_id: UUID, citation_id: UUID
) -> Citation:
    citation = (
        await db.execute(
            select(Citation).where(
                Citation.id == citation_id,
                Citation.project_id == project_id,
                Citation.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if citation is None:
        raise HTTPException(status_code=404, detail="Citation introuvable.")
    return citation


async def get_citation_by_node(
    db: AsyncSession, *, project_id: UUID, node_id: str
) -> Citation | None:
    return (
        await db.execute(
            select(Citation).where(
                Citation.project_id == project_id,
                Citation.node_id == node_id,
                Citation.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()


async def list_citations(
    db: AsyncSession,
    *,
    project_id: UUID,
    section_id: UUID | None = None,
    include_deleted: bool = False,
) -> list[tuple[Citation, int]]:
    """Return the live citations with their section order, in document order.

    Document order is the section position in the outline, then the position inside the
    section. This is the order a numeric style must follow.
    """
    statement = (
        select(Citation, OutlineNode.position)
        .join(Section, Section.id == Citation.section_id)
        .join(OutlineNode, OutlineNode.id == Section.outline_node_id)
        .where(Citation.project_id == project_id)
    )
    if section_id is not None:
        statement = statement.where(Citation.section_id == section_id)
    if not include_deleted:
        statement = statement.where(Citation.deleted_at.is_(None))
    result = await db.execute(
        statement.order_by(
            OutlineNode.position.asc(),
            Citation.position_in_section.asc(),
            Citation.created_at.asc(),
            Citation.id.asc(),
        )
    )
    return [(citation, int(position)) for citation, position in result.all()]


async def _items_by_citation(
    db: AsyncSession, citation_ids: list[UUID]
) -> dict[UUID, list[CitationItem]]:
    if not citation_ids:
        return {}
    result = await db.execute(
        select(CitationItem)
        .where(CitationItem.citation_id.in_(citation_ids))
        .order_by(CitationItem.position.asc())
    )
    grouped: dict[UUID, list[CitationItem]] = {}
    for item in result.scalars().all():
        grouped.setdefault(item.citation_id, []).append(item)
    return grouped


def _locator_of(item: CitationItem, citation: Citation) -> tuple[str | None, str | None]:
    """An item locator wins over the citation-wide default."""
    locator_type = item.locator_type or citation.locator_type
    locator_value = item.locator_value or citation.locator_value
    return locator_type, locator_value


def _is_orphaned(
    items: list[CitationItem], references: dict[UUID, ReferenceCitationData]
) -> bool:
    """A citation is orphaned as soon as one of its references is gone.

    The reference is considered gone when it was soft-deleted by stage 9 as well as when the
    row disappeared, because a soft-deleted reference can no longer be rendered.
    """
    if not items:
        return False
    return any(
        item.reference_id not in references or references[item.reference_id] is None
        for item in items
    )


def _snapshot_payload(
    items: list[CitationItem], references: dict[UUID, ReferenceCitationData]
) -> dict[str, Any]:
    """Freeze the bibliographic facts behind a citation, for historical rendering."""
    return {
        "items": [
            {
                "reference_id": str(item.reference_id),
                "citation_key": references[item.reference_id].citation_key
                if item.reference_id in references
                else None,
                "title": references[item.reference_id].title
                if item.reference_id in references
                else None,
                "publication_year": references[item.reference_id].publication_year
                if item.reference_id in references
                else None,
            }
            for item in items
        ],
    }


async def render_citations(
    db: AsyncSession,
    *,
    project_id: UUID,
    style_name: str | None = None,
    section_id: UUID | None = None,
) -> tuple[list[tuple[Citation, RenderedCitationResponse]], str]:
    """Render every citation of the project (or of one section) in document order.

    Returns the rendered list together with the resolved style name, so the caller never has
    to resolve the style itself.
    """
    style_value = await resolve_project_style(db, project_id=project_id, override=style_name)
    style = get_style(style_value)
    pairs = await list_citations(db, project_id=project_id, section_id=section_id)
    if not pairs:
        return [], style_value

    citation_ids = [citation.id for citation, _ in pairs]
    items_map = await _items_by_citation(db, citation_ids)
    reference_ids = [
        item.reference_id for items in items_map.values() for item in items
    ]
    references = await load_reference_data(db, list(dict.fromkeys(reference_ids)))

    # Numeric styles need the number of every reference in the document, even when only one
    # section is being rendered, otherwise the numbering would depend on the filter.
    numbering_scope = pairs if section_id is None else await list_citations(
        db, project_id=project_id
    )
    numbers = number_map([_to_engine_citation(citation, items_map.get(citation.id, []), references)
                          for citation, _ in numbering_scope])

    rendered: list[tuple[Citation, RenderedCitationResponse]] = []
    for citation, _ in pairs:
        items = items_map.get(citation.id, [])
        engine = _to_engine_citation(citation, items, references, numbers)
        result = style.format_citation(engine)
        rendered.append(
            (
                citation,
                RenderedCitationResponse(
                    node_id=citation.node_id,
                    citation_id=str(citation.id),
                    text=result.text,
                    is_orphaned=result.is_orphaned,
                    warnings=result.warnings,
                    reference_ids=[str(item.reference_id) for item in items],
                ),
            )
        )
    return rendered, style_value


def _to_engine_citation(
    citation: Citation,
    items: list[CitationItem],
    references: dict[UUID, ReferenceCitationData],
    numbers: dict[str, int] | None = None,
) -> CitationData:
    """Build the engine input, tolerating a reference that no longer exists."""
    engine_items: list[CitationItemData] = []
    missing: list[str] = []
    for item in items:
        reference = references.get(item.reference_id)
        if reference is None:
            missing.append(str(item.reference_id))
            continue
        locator_type, locator_value = _locator_of(item, citation)
        number = numbers.get(str(item.reference_id)) if numbers else None
        engine_items.append(
            CitationItemData(
                reference=reference,
                position=item.position,
                locator_type=locator_type,
                locator_value=locator_value,
                prefix=item.prefix or citation.prefix,
                suffix=item.suffix or citation.suffix,
                number=number,
            )
        )
    return CitationData(
        citation_id=str(citation.id),
        items=tuple(engine_items),
        prefix=citation.prefix,
        suffix=citation.suffix,
        mode=citation.mode,
        is_orphaned=bool(missing) or (not items and bool(citation.snapshot_text)),
        snapshot_text=citation.snapshot_text,
        snapshot_style=citation.snapshot_style,
    )


async def resolve_project_style(
    db: AsyncSession, *, project_id: UUID, override: str | None = None
) -> str:
    """Resolve the style to use, preferring an explicit override over the project setting.

    The project's stored value is never rewritten: an unknown or legacy value such as
    ``"apa"`` is simply resolved to the matching style.
    """
    if override:
        return normalise_style_name(override)
    project = (
        await db.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    return normalise_style_name(project.bibliography_style if project else None)


# -------------------------------------------------------------------- writing


async def upsert_citation(
    db: AsyncSession,
    *,
    project_id: UUID,
    user_id: UUID,
    payload: CitationCreateRequest,
) -> Citation:
    """Create or update the citation attached to a Tiptap node.

    The node is the identity: inserting a citation for a node that already has a row updates
    that row instead of creating a second one, so re-saving a document never duplicates a
    citation.
    """
    await _section_of(db, project_id=project_id, section_id=payload.section_id)
    references = await _validate_references(
        db, project_id=project_id, items=payload.items
    )
    style_value = await resolve_project_style(db, project_id=project_id)
    style = get_style(style_value)

    existing = await get_citation_by_node(
        db, project_id=project_id, node_id=payload.node_id
    )
    if existing is None:
        existing = Citation(
            project_id=project_id,
            section_id=payload.section_id,
            node_id=payload.node_id,
            citation_key=_build_citation_key(payload, references),
            position_in_section=payload.position_in_section,
            prefix=payload.prefix,
            suffix=payload.suffix,
            locator_type=payload.locator_type,
            locator_value=payload.locator_value,
            mode=payload.mode,
            created_by=user_id,
        )
        db.add(existing)
        await db.flush()
    else:
        existing.section_id = payload.section_id
        existing.position_in_section = payload.position_in_section
        existing.prefix = payload.prefix
        existing.suffix = payload.suffix
        existing.locator_type = payload.locator_type
        existing.locator_value = payload.locator_value
        existing.mode = payload.mode
        existing.deleted_at = None

    await db.execute(
        delete(CitationItem).where(CitationItem.citation_id == existing.id)
    )
    items = [
        CitationItem(
            citation_id=existing.id,
            reference_id=item.reference_id,
            position=position,
            locator_type=item.locator_type,
            locator_value=item.locator_value,
            prefix=item.prefix,
            suffix=item.suffix,
        )
        for position, item in enumerate(payload.items, start=1)
    ]
    for item in items:
        db.add(item)
    await db.flush()

    # Freeze what the author actually sees, so an old revision stays readable even if a
    # reference is later removed.
    engine = CitationData(
        citation_id=str(existing.id),
        items=tuple(
            CitationItemData(
                reference=references[item.reference_id],
                position=item.position,
                locator_type=item.locator_type or payload.locator_type,
                locator_value=item.locator_value or payload.locator_value,
                prefix=item.prefix or payload.prefix,
                suffix=item.suffix or payload.suffix,
            )
            for item in items
        ),
        prefix=payload.prefix,
        suffix=payload.suffix,
        mode=payload.mode,
    )
    existing.snapshot_text = style.format_citation(engine).text
    existing.snapshot_style = style_value
    existing.snapshot_data = _snapshot_payload(items, references)
    existing.is_orphaned = False
    existing.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(existing)
    return existing


def _build_citation_key(
    payload: CitationCreateRequest, references: dict[UUID, ReferenceCitationData]
) -> str:
    """A short internal key, derived from the first reference. Never a bibliographic fact."""
    first = payload.items[0].reference_id
    reference = references.get(first)
    if reference is None:
        return f"cit-{first.hex[:8]}"
    return f"{reference.citation_key}-{payload.node_id}"[:120]


async def update_citation(
    db: AsyncSession,
    *,
    project_id: UUID,
    citation: Citation,
    payload: CitationUpdateRequest,
) -> Citation:
    values = payload.model_dump(exclude_unset=True)
    remove_id = values.pop("remove_reference_id", None)
    items_input = values.pop("items", None)

    if items_input is not None:
        await _validate_references(
            db, project_id=project_id, items=list(items_input)
        )

    existing_items = (
        (
            await db.execute(
                select(CitationItem)
                .where(CitationItem.citation_id == citation.id)
                .order_by(CitationItem.position.asc())
            )
        )
        .scalars()
        .all()
    )
    for name, value in values.items():
        if name == "position_in_section" or name == "mode" or name in {
            "prefix",
            "suffix",
            "locator_type",
            "locator_value",
        }:
            setattr(citation, name, value)

    if remove_id is not None or items_input is not None:
        await db.execute(
            delete(CitationItem).where(CitationItem.citation_id == citation.id)
        )
        if items_input is None:
            kept = [item for item in existing_items if item.reference_id != remove_id]
            if kept:
                for position, item in enumerate(kept, start=1):
                    await db.execute(
                        CitationItem.__table__.update()
                        .where(CitationItem.id == item.id)
                        .values(position=position)
                    )
        if items_input is not None:
            for position, item in enumerate(items_input, start=1):
                db.add(
                    CitationItem(
                        citation_id=citation.id,
                        reference_id=item.reference_id,
                        position=position,
                        locator_type=item.locator_type,
                        locator_value=item.locator_value,
                        prefix=item.prefix,
                        suffix=item.suffix,
                    )
                )
    elif not existing_items:
        raise HTTPException(status_code=422, detail="La citation ne référence aucune référence.")

    await db.flush()
    await _refresh_snapshot(db, project_id=project_id, citation=citation)
    await db.commit()
    await db.refresh(citation)
    return citation


async def _refresh_snapshot(
    db: AsyncSession, *, project_id: UUID, citation: Citation
) -> None:
    items = (
        (
            await db.execute(
                select(CitationItem)
                .where(CitationItem.citation_id == citation.id)
                .order_by(CitationItem.position.asc())
            )
        )
        .scalars()
        .all()
    )
    references = await load_reference_data(db, [item.reference_id for item in items])
    style_value = await resolve_project_style(db, project_id=project_id)
    style = get_style(style_value)
    engine = _to_engine_citation(citation, list(items), references)
    citation.snapshot_text = style.format_citation(engine).text
    citation.snapshot_style = style_value
    citation.snapshot_data = _snapshot_payload(list(items), references)
    citation.is_orphaned = _is_orphaned(list(items), references)
    citation.updated_at = datetime.now(UTC)


async def soft_delete_citation(
    db: AsyncSession, *, project_id: UUID, citation: Citation
) -> None:
    """Delete the citation, never the reference it pointed to.

    A soft delete keeps the row so the snapshot stays available: reading an old revision that
    contains the node still resolves, instead of crashing on a missing node.
    """
    citation.deleted_at = datetime.now(UTC)
    citation.updated_at = datetime.now(UTC)
    await db.commit()


# ----------------------------------------------------------------- bibliography


async def rendered_bibliography(
    db: AsyncSession,
    *,
    project_id: UUID,
    style_name: str | None = None,
) -> dict[str, Any]:
    """Build the final bibliography from the references that are actually cited.

    A reference present in the library but never cited is reported separately and stays out of
    the bibliography. A reference cited several times appears once.
    """
    style_value = await resolve_project_style(db, project_id=project_id, override=style_name)
    style = get_style(style_value)

    pairs = await list_citations(db, project_id=project_id)
    items_map = await _items_by_citation(db, [citation.id for citation, _ in pairs])
    reference_ids = [item.reference_id for items in items_map.values() for item in items]
    unique_ids = list(dict.fromkeys(reference_ids))
    references = await load_reference_data(db, unique_ids)

    engines = [
        _to_engine_citation(citation, items_map.get(citation.id, []), references)
        for citation, _ in pairs
    ]
    numbers = number_map(engines)

    # Which reference is cited by which citation key, and how many times.
    cited_by: dict[str, list[str]] = {}
    occurrences: dict[str, int] = {}
    for citation, items in zip(pairs, items_map.values(), strict=False):
        for item in items:
            key = str(item.reference_id)
            cited_by.setdefault(key, []).append(citation.citation_key)
            occurrences[key] = occurrences.get(key, 0) + 1

    # A reference that was soft-deleted by stage 9 is still in the table but can no longer be
    # rendered, so it is excluded here and reported as an orphan by ``orphaned_citations``.
    cited_data = [
        references[reference_id]
        for reference_id in unique_ids
        if reference_id in references
    ]

    ordered = style.sort_bibliography(list(cited_data))
    suffixes = style.assign_year_suffixes(list(cited_data))
    number_position = {reference_id: index for index, reference_id in enumerate(numbers)}

    if style.uses_numbers:
        ordered.sort(key=lambda reference: number_position.get(reference.reference_id, 0))

    entries: list[RenderedBibliographyEntryResponse] = []
    incomplete = 0
    for position, reference in enumerate(ordered, start=1):
        number = (
            numbers.get(reference.reference_id)
            if style.uses_numbers
            else None
        )
        entry = style.format_bibliography_entry(
            reference, number=number, year_suffix=suffixes.get(reference.reference_id)
        )
        if entry.warnings:
            incomplete += 1
        entries.append(
            RenderedBibliographyEntryResponse(
                reference_id=UUID(reference.reference_id),
                number=number,
                text=entry.text,
                warnings=entry.warnings,
                citation_keys=sorted(set(cited_by.get(reference.reference_id, []))),
                is_complete=not entry.warnings,
            )
        )

    orphaned = await orphaned_citations(
        db, project_id=project_id, references=references, items_map=items_map
    )
    uncited = await uncited_references(db, project_id=project_id, cited_ids=unique_ids)

    return {
        "style": style_value,
        "style_label": style.label,
        "entries": entries,
        "cited_count": len(entries),
        "uncited_count": len(uncited),
        "uncited": uncited,
        "orphaned_citations": orphaned,
        "incomplete_count": incomplete,
        "is_truncated": len(entries) > MAX_RENDER_REFERENCES,
    }


async def uncited_references(
    db: AsyncSession, *, project_id: UUID, cited_ids: list[UUID]
) -> list[UncitedReferenceResponse]:
    """References in the library that no citation points to."""
    conditions = [
        BibliographicReference.project_id == project_id,
        BibliographicReference.deleted_at.is_(None),
    ]
    if cited_ids:
        conditions.append(BibliographicReference.id.notin_(cited_ids))
    else:
        # An empty list must not become an "IN ()" clause, which would match nothing and
        # wrongly report the whole library as uncited.
        conditions.append(true())
    result = await db.execute(
        select(BibliographicReference)
        .where(*conditions)
        .order_by(BibliographicReference.citation_key.asc())
        .limit(MAX_RENDER_REFERENCES)
    )
    return [
        UncitedReferenceResponse(
            reference_id=reference.id,
            citation_key=reference.citation_key,
            title=reference.title,
            publication_year=reference.publication_year,
            reference_type=reference.reference_type,
        )
        for reference in result.scalars().all()
    ]


async def orphaned_citations(
    db: AsyncSession,
    *,
    project_id: UUID,
    references: dict[UUID, ReferenceCitationData] | None = None,
    items_map: dict[UUID, list[CitationItem]] | None = None,
) -> list[dict[str, Any]]:
    """Citations whose reference was removed, with the text they used to show.

    An orphaned citation is never rendered as ``(Auteur inconnu, année inconnue)``. The stored
    snapshot is returned instead, and a message asks the author to repair the citation.
    """
    pairs = await list_citations(db, project_id=project_id)
    if not pairs:
        return []
    if items_map is None:
        items_map = await _items_by_citation(db, [citation.id for citation, _ in pairs])
    if references is None:
        reference_ids = [item.reference_id for items in items_map.values() for item in items]
        references = await load_reference_data(db, list(dict.fromkeys(reference_ids)))

    result: list[dict[str, Any]] = []
    for citation, _ in pairs:
        items = items_map.get(citation.id, [])
        missing = [
            str(item.reference_id) for item in items if item.reference_id not in references
        ]
        if not missing:
            continue
        result.append(
            {
                "citation_id": citation.id,
                "node_id": citation.node_id,
                "section_id": citation.section_id,
                "missing_reference_ids": missing,
                "snapshot_text": citation.snapshot_text,
                "snapshot_style": citation.snapshot_style,
                "message": "Citation invalide : référence introuvable.",
            }
        )
    return result


# ------------------------------------------------------- document reconciliation


def collect_citation_nodes(content: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Extract every citation node of a Tiptap document, in document order.

    Walking the JSON is safe on a malformed document: an unknown node shape is ignored rather
    than raising, so a document written by an older version still loads.
    """
    found: list[dict[str, Any]] = []
    if not isinstance(content, dict):
        return found

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for child in node:
                walk(child)
            return
        if not isinstance(node, dict):
            return
        if node.get("type") == "citation":
            attributes = node.get("attrs")
            attributes = attributes if isinstance(attributes, dict) else {}
            reference_ids = attributes.get("referenceIds")
            found.append(
                {
                    "node_id": str(attributes.get("citationId") or attributes.get("nodeId") or ""),
                    "reference_ids": [
                        str(value) for value in reference_ids if value
                    ]
                    if isinstance(reference_ids, list)
                    else [],
                    "legacy_value": attributes.get("legacyValue"),
                    "mode": attributes.get("mode") or "parenthetical",
                }
            )
        walk(node.get("content"))

    walk(content.get("content"))
    return [item for item in found if item["node_id"]]


async def reconcile_section(
    db: AsyncSession,
    *,
    project_id: UUID,
    section_id: UUID,
    user_id: UUID,
    content: dict[str, Any] | None,
) -> dict[str, Any]:
    """Make the citation rows match the citation nodes of a saved document.

    The document is the source of truth for **which** citations exist; the rows hold the
    bibliographic links and the snapshot. Registering a node is idempotent, and a row whose
    node has disappeared is soft-deleted rather than destroyed, so its snapshot survives for
    the history.
    """
    await _section_of(db, project_id=project_id, section_id=section_id)
    nodes = collect_citation_nodes(content)
    existing = {
        citation.node_id: citation
        for citation, _ in await list_citations(
            db, project_id=project_id, section_id=section_id, include_deleted=True
        )
    }

    registered = 0
    unregistered: list[str] = []
    for position, node in enumerate(nodes[:MAX_CITATIONS_PER_SECTION], start=1):
        reference_ids = _parse_reference_ids(node["reference_ids"])
        if not reference_ids:
            # A legacy node, or one whose references were all removed: nothing to register.
            unregistered.append(node["node_id"])
            continue
        await upsert_citation(
            db,
            project_id=project_id,
            user_id=user_id,
            payload=CitationCreateRequest(
                section_id=section_id,
                node_id=node["node_id"],
                items=[CitationItemInput(reference_id=rid) for rid in reference_ids],
                mode="narrative" if node["mode"] == "narrative" else "parenthetical",
                position_in_section=position,
            ),
        )
        registered += 1

    node_ids = {node["node_id"] for node in nodes}
    stale = [
        citation.id
        for node_id, citation in existing.items()
        if node_id not in node_ids and citation.deleted_at is None
    ]
    for citation_id in stale:
        citation = await get_citation(db, project_id=project_id, citation_id=citation_id)
        await soft_delete_citation(db, project_id=project_id, citation=citation)

    rendered, style_value = await render_citations(
        db, project_id=project_id, section_id=section_id
    )
    orphans = [item for item in await orphaned_citations(db, project_id=project_id)]
    orphan_nodes = [item["node_id"] for item in orphans]
    return {
        "section_id": section_id,
        "style": style_value,
        "citations": [rendered_item for _, rendered_item in rendered],
        "unregistered_node_ids": unregistered,
        "stale_citation_ids": stale,
        "orphaned_node_ids": orphan_nodes,
        "synced": registered,
    }


def _parse_reference_ids(values: list[str]) -> list[UUID]:
    parsed: list[UUID] = []
    for value in values:
        try:
            parsed.append(UUID(value))
        except ValueError:
            # A malformed identifier is dropped, never guessed into a random reference.
            continue
    return list(dict.fromkeys(parsed))


async def count_citations(
    db: AsyncSession, *, project_id: UUID, section_id: UUID | None = None
) -> int:
    conditions = [
        Citation.project_id == project_id,
        Citation.deleted_at.is_(None),
    ]
    if section_id is not None:
        conditions.append(Citation.section_id == section_id)
    return int(
        (
            await db.execute(select(func.count(Citation.id)).where(*conditions))
        ).scalar_one()
    )


__all__ = [
    "MAX_CITATIONS_PER_SECTION",
    "MAX_RENDER_REFERENCES",
    "collect_citation_nodes",
    "count_citations",
    "get_citation",
    "get_citation_by_node",
    "list_citations",
    "load_reference_data",
    "orphaned_citations",
    "reconcile_section",
    "render_citations",
    "rendered_bibliography",
    "resolve_project_style",
    "soft_delete_citation",
    "to_reference_data",
    "uncited_references",
    "update_citation",
    "upsert_citation",
]
