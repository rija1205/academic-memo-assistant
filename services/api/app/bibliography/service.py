"""Bibliography service: CRUD, search, duplicates, import and export.

Design decisions:

* A reference is **independent** from an imported source. Linking is optional and never copies
  the source metadata, so the same bibliographic work is not stored twice.
* A missing field stays ``NULL``. Nothing is filled from a language model and nothing is
  guessed from the filename.
* Search is plain SQL over title, author, DOI, journal, keywords and year. It does not use the
  RAG index and does not call a language model.
* Import never deletes and never overwrites silently: a detected duplicate is reported, and
  the author decides.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import String, cast, delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.bibliography.duplicates import (
    DuplicateReport,
    ReferenceSummary,
    find_duplicates,
)
from app.bibliography.parsers import (
    ParsedReference,
    export_bibtex,
    export_ris,
    parse_bibtex,
    parse_ris,
)
from app.bibliography.schemas import (
    AuthorInput,
    AuthorResponse,
    ReferenceCreateRequest,
    ReferenceResponse,
    ReferenceUpdateRequest,
)
from app.core.normalize import normalize_doi, normalize_tag, normalize_url
from app.models.bibliography import (
    BibliographicReference,
    ReferenceAuthor,
    ReferenceTag,
    ReferenceTagLink,
)
from app.models.source import Source

#: Fields shown as "missing" on the detail panel when they are empty.
COMPLETENESS_FIELDS = (
    "title",
    "publication_year",
    "doi",
    "journal",
    "volume",
    "issue",
    "pages",
    "publisher",
    "url",
    "abstract",
    "isbn",
)

_SLUG = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(char for char in text if not unicodedata.combining(char))
    return _SLUG.sub("-", text.casefold()).strip("-")


def build_citation_key(
    *,
    authors: list[AuthorInput],
    publication_year: int | None,
    title: str | None,
    fallback: str = "reference",
) -> str:
    """Derive a readable, stable citation key such as ``dupont2024``.

    This is a key, not metadata: it carries no scholarly meaning and the author may replace it.
    """
    family = ""
    if authors and authors[0].family_name:
        family = slugify(authors[0].family_name)[:40]
    year = str(publication_year) if publication_year else "nd"
    if not family:
        family = slugify(title)[:40] if title else ""
    if not family:
        family = fallback
    return f"{family}{year}"[:200]


async def unique_citation_key(
    db: AsyncSession, *, project_id: UUID, desired: str, exclude_id: UUID | None = None
) -> str:
    """Return ``desired`` or a suffixed variant that is free inside the project."""
    base = desired or "reference"
    candidate = base
    suffix = 2
    while True:
        statement = select(BibliographicReference.id).where(
            BibliographicReference.project_id == project_id,
            BibliographicReference.citation_key == candidate,
        )
        if exclude_id is not None:
            statement = statement.where(BibliographicReference.id != exclude_id)
        if (await db.execute(statement)).scalar_one_or_none() is None:
            return candidate
        candidate = f"{base}{chr(ord('a') + (suffix % 26))}{suffix}"
        suffix += 1


async def _authors_of(
    db: AsyncSession, reference_ids: list[UUID]
) -> dict[UUID, list[ReferenceAuthor]]:
    if not reference_ids:
        return {}
    result = await db.execute(
        select(ReferenceAuthor)
        .where(ReferenceAuthor.reference_id.in_(reference_ids))
        .order_by(ReferenceAuthor.position.asc())
    )
    grouped: dict[UUID, list[ReferenceAuthor]] = {}
    for author in result.scalars().all():
        grouped.setdefault(author.reference_id, []).append(author)
    return grouped


async def _tags_of(
    db: AsyncSession, reference_ids: list[UUID]
) -> dict[UUID, list[str]]:
    if not reference_ids:
        return {}
    result = await db.execute(
        select(ReferenceTagLink.reference_id, ReferenceTag.name)
        .join(ReferenceTag, ReferenceTag.id == ReferenceTagLink.tag_id)
        .where(ReferenceTagLink.reference_id.in_(reference_ids))
        .order_by(ReferenceTag.normalized_name.asc())
    )
    grouped: dict[UUID, list[str]] = {}
    for reference_id, name in result.all():
        grouped.setdefault(reference_id, []).append(name)
    return grouped


async def _sources_of(
    db: AsyncSession, reference_ids: list[UUID]
) -> dict[UUID, tuple[str | None, str]]:
    if not reference_ids:
        return {}
    result = await db.execute(
        select(BibliographicReference.id, Source.title, Source.original_filename).where(
            BibliographicReference.id.in_(reference_ids),
            BibliographicReference.source_id.is_not(None),
        )
    )
    mapping: dict[UUID, tuple[str | None, str]] = {}
    for reference_id, title, filename in result.all():
        mapping[reference_id] = (title, filename)
    return mapping


async def to_response(
    db: AsyncSession, reference: BibliographicReference
) -> ReferenceResponse:
    """Build the API view of a reference, including completeness information."""
    reference_ids = [reference.id]
    authors = (await _authors_of(db, reference_ids)).get(reference.id, [])
    tags = (await _tags_of(db, reference_ids)).get(reference.id, [])
    sources = (await _sources_of(db, reference_ids)).get(reference.id, (None, ""))
    source_title, source_filename = sources
    missing = [
        field_name
        for field_name in COMPLETENESS_FIELDS
        if getattr(reference, field_name, None) in (None, "", [])
    ]
    return ReferenceResponse(
        id=reference.id,
        project_id=reference.project_id,
        citation_key=reference.citation_key,
        reference_type=reference.reference_type,
        entry_type=reference.entry_type,
        title=reference.title,
        subtitle=reference.subtitle,
        authors=[
            AuthorResponse(
                position=author.position,
                given_name=author.given_name,
                family_name=author.family_name,
                orcid=author.orcid,
            )
            for author in authors
        ],
        publication_year=reference.publication_year,
        publication_month=reference.publication_month,
        publication_day=reference.publication_day,
        doi=reference.doi,
        doi_original=reference.doi_original,
        url=reference.url,
        accessed_at=reference.accessed_at,
        journal=reference.journal,
        volume=reference.volume,
        issue=reference.issue,
        pages=reference.pages,
        publisher=reference.publisher,
        publisher_place=reference.publisher_place,
        edition=reference.edition,
        isbn=reference.isbn,
        issn=reference.issn,
        abstract=reference.abstract,
        keywords=list(reference.keywords or []),
        language=reference.language,
        notes=reference.notes,
        extra_fields=dict(reference.extra_fields or {}),
        source_id=reference.source_id,
        source_title=source_title,
        tags=tags,
        has_source=reference.source_id is not None,
        created_at=reference.created_at,
        updated_at=reference.updated_at,
        missing_fields=missing,
    )


async def _replace_authors(
    db: AsyncSession, reference: BibliographicReference, authors: list[AuthorInput]
) -> None:
    await db.execute(
        delete(ReferenceAuthor).where(ReferenceAuthor.reference_id == reference.id)
    )
    for position, author in enumerate(authors, start=1):
        if not author.family_name:
            continue
        db.add(
            ReferenceAuthor(
                reference_id=reference.id,
                position=position,
                given_name=author.given_name,
                family_name=author.family_name,
                orcid=author.orcid,
            )
        )


async def _replace_tags(
    db: AsyncSession, *, project_id: UUID, reference: BibliographicReference, tags: list[str]
) -> None:
    await db.execute(
        delete(ReferenceTagLink).where(ReferenceTagLink.reference_id == reference.id)
    )
    for raw in tags:
        name = raw.strip()
        normalized = normalize_tag(name)
        if not name or len(name) > 80:
            continue
        tag = (
            await db.execute(
                select(ReferenceTag).where(
                    ReferenceTag.project_id == project_id,
                    ReferenceTag.normalized_name == normalized,
                )
            )
        ).scalar_one_or_none()
        if tag is None:
            tag = ReferenceTag(project_id=project_id, name=name, normalized_name=normalized)
            db.add(tag)
            await db.flush()
        db.add(ReferenceTagLink(reference_id=reference.id, tag_id=tag.id))


async def _validate_source(
    db: AsyncSession, *, project_id: UUID, source_id: UUID | None
) -> None:
    if source_id is None:
        return
    found = (
        await db.execute(
            select(Source.id).where(
                Source.id == source_id,
                Source.project_id == project_id,
                Source.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if found is None:
        raise HTTPException(status_code=422, detail="Source introuvable dans ce projet.")


async def create_reference(
    db: AsyncSession,
    *,
    project_id: UUID,
    user_id: UUID,
    payload: ReferenceCreateRequest,
) -> BibliographicReference:
    await _validate_source(db, project_id=project_id, source_id=payload.source_id)
    desired_key = payload.citation_key or build_citation_key(
        authors=payload.authors,
        publication_year=payload.publication_year,
        title=payload.title,
    )
    citation_key = await unique_citation_key(db, project_id=project_id, desired=desired_key)
    reference = BibliographicReference(
        project_id=project_id,
        created_by=user_id,
        citation_key=citation_key,
        reference_type=payload.reference_type,
        entry_type=payload.entry_type,
        title=payload.title,
        subtitle=payload.subtitle,
        publication_year=payload.publication_year,
        publication_month=payload.publication_month,
        publication_day=payload.publication_day,
        doi=normalize_doi(payload.doi),
        doi_original=payload.doi,
        url=normalize_url(payload.url),
        accessed_at=payload.accessed_at,
        journal=payload.journal,
        volume=payload.volume,
        issue=payload.issue,
        pages=payload.pages,
        publisher=payload.publisher,
        publisher_place=payload.publisher_place,
        edition=payload.edition,
        isbn=payload.isbn,
        issn=payload.issn,
        abstract=payload.abstract,
        keywords=payload.keywords,
        language=payload.language,
        notes=payload.notes,
        source_id=payload.source_id,
    )
    db.add(reference)
    await db.flush()
    await _replace_authors(db, reference, payload.authors)
    await _replace_tags(db, project_id=project_id, reference=reference, tags=payload.tags)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Clé de citation déjà utilisée.") from exc
    await db.refresh(reference)
    return reference


async def get_reference(
    db: AsyncSession, *, project_id: UUID, reference_id: UUID
) -> BibliographicReference:
    reference = (
        await db.execute(
            select(BibliographicReference).where(
                BibliographicReference.id == reference_id,
                BibliographicReference.project_id == project_id,
                BibliographicReference.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if reference is None:
        raise HTTPException(status_code=404, detail="Référence introuvable.")
    return reference


async def update_reference(
    db: AsyncSession,
    *,
    project_id: UUID,
    reference: BibliographicReference,
    payload: ReferenceUpdateRequest,
) -> BibliographicReference:
    await _validate_source(db, project_id=project_id, source_id=payload.source_id)
    values = payload.model_dump(exclude_unset=True)
    for field_name, value in values.items():
        if field_name in {"authors", "tags", "doi", "url", "citation_key"}:
            continue
        if field_name == "source_id" and value is None and "source_id" not in values:
            continue
        setattr(reference, field_name, value)
    if "doi" in values:
        reference.doi = normalize_doi(values["doi"])
        reference.doi_original = values["doi"] or None
    if "url" in values:
        reference.url = normalize_url(values["url"])
    if "citation_key" in values and values["citation_key"]:
        reference.citation_key = await unique_citation_key(
            db,
            project_id=project_id,
            desired=values["citation_key"],
            exclude_id=reference.id,
        )
    if "authors" in values:
        await _replace_authors(db, reference, values["authors"] or [])
    if "tags" in values:
        await _replace_tags(
            db, project_id=project_id, reference=reference, tags=values["tags"] or []
        )
    reference.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(reference)
    return reference


async def delete_reference(
    db: AsyncSession, *, project_id: UUID, reference: BibliographicReference
) -> None:
    await db.execute(
        delete(ReferenceTagLink).where(ReferenceTagLink.reference_id == reference.id)
    )
    await db.execute(delete(ReferenceAuthor).where(ReferenceAuthor.reference_id == reference.id))
    reference.deleted_at = datetime.now(UTC)
    await db.commit()


async def list_references(
    db: AsyncSession,
    *,
    project_id: UUID,
    q: str | None = None,
    reference_type: str | None = None,
    year: int | None = None,
    author: str | None = None,
    has_doi: bool | None = None,
    has_source: bool | None = None,
    tag: str | None = None,
    sort: str = "updated_at",
    order: str = "desc",
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[BibliographicReference], int]:
    """List references with plain SQL filters. No RAG, no language model."""
    conditions = [
        BibliographicReference.project_id == project_id,
        BibliographicReference.deleted_at.is_(None),
    ]
    if reference_type:
        conditions.append(BibliographicReference.reference_type == reference_type)
    if year:
        conditions.append(BibliographicReference.publication_year == year)
    if has_doi is True:
        conditions.append(BibliographicReference.doi.is_not(None))
    if has_doi is False:
        conditions.append(BibliographicReference.doi.is_(None))
    if has_source is True:
        conditions.append(BibliographicReference.source_id.is_not(None))
    if has_source is False:
        conditions.append(BibliographicReference.source_id.is_(None))
    if q:
        pattern = f"%{q.strip()}%"
        conditions.append(
            or_(
                BibliographicReference.title.ilike(pattern),
                BibliographicReference.journal.ilike(pattern),
                BibliographicReference.doi.ilike(pattern),
                BibliographicReference.publisher.ilike(pattern),
                BibliographicReference.abstract.ilike(pattern),
                cast(BibliographicReference.keywords, String).ilike(pattern),
                BibliographicReference.citation_key.ilike(pattern),
            )
        )
    if author:
        family = author.strip()
        conditions.append(
            BibliographicReference.id.in_(
                select(ReferenceAuthor.reference_id).where(
                    ReferenceAuthor.family_name.ilike(f"%{family}%")
                )
            )
        )
    if tag:
        conditions.append(
            BibliographicReference.id.in_(
                select(ReferenceTagLink.reference_id)
                .join(ReferenceTag, ReferenceTag.id == ReferenceTagLink.tag_id)
                .where(ReferenceTag.normalized_name == normalize_tag(tag))
            )
        )

    total = int(
        (
            await db.execute(
                select(func.count(BibliographicReference.id)).where(*conditions)
            )
        ).scalar_one()
    )
    sort_column = {
        "updated_at": BibliographicReference.updated_at,
        "created_at": BibliographicReference.created_at,
        "title": BibliographicReference.title,
        "publication_year": BibliographicReference.publication_year,
        "citation_key": BibliographicReference.citation_key,
    }.get(sort, BibliographicReference.updated_at)
    direction = sort_column.asc() if order == "asc" else sort_column.desc()
    result = await db.execute(
        select(BibliographicReference)
        .where(*conditions)
        .order_by(direction, BibliographicReference.id.asc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all()), total


async def reference_summary(
    db: AsyncSession, reference: BibliographicReference
) -> ReferenceSummary:
    authors = (await _authors_of(db, [reference.id])).get(reference.id, [])
    return ReferenceSummary(
        id=reference.id,
        citation_key=reference.citation_key,
        title=reference.title,
        publication_year=reference.publication_year,
        doi=reference.doi,
        author_families=tuple(
            sorted(
                {
                    (author.family_name or "").casefold()
                    for author in authors
                    if author.family_name
                }
            )
        ),
    )


async def duplicates_of(
    db: AsyncSession, *, project_id: UUID, reference: BibliographicReference
) -> DuplicateReport:
    others, _ = await list_references(
        db, project_id=project_id, limit=200, offset=0, sort="created_at"
    )
    summaries = [await reference_summary(db, item) for item in others]
    current = await reference_summary(db, reference)
    return find_duplicates(current, [item for item in summaries if item.id != current.id])


async def reference_stats(db: AsyncSession, *, project_id: UUID) -> dict[str, object]:
    base = [
        BibliographicReference.project_id == project_id,
        BibliographicReference.deleted_at.is_(None),
    ]
    total = int(
        (await db.execute(select(func.count(BibliographicReference.id)).where(*base))).scalar_one()
    )
    type_rows = await db.execute(
        select(BibliographicReference.reference_type, func.count(BibliographicReference.id))
        .where(*base)
        .group_by(BibliographicReference.reference_type)
    )
    year_rows = await db.execute(
        select(BibliographicReference.publication_year, func.count(BibliographicReference.id))
        .where(*base, BibliographicReference.publication_year.is_not(None))
        .group_by(BibliographicReference.publication_year)
        .order_by(BibliographicReference.publication_year.desc())
    )
    async def count_for(extra: Any) -> int:
        return int(
            (
                await db.execute(
                    select(func.count(BibliographicReference.id)).where(*base, extra)
                )
            ).scalar_one()
        )

    return {
        "total": total,
        "by_type": {key: value for key, value in type_rows.all()},
        "by_year": {str(key): value for key, value in year_rows.all() if key},
        "with_doi": await count_for(BibliographicReference.doi.is_not(None)),
        "with_source": await count_for(BibliographicReference.source_id.is_not(None)),
        "with_url": await count_for(BibliographicReference.url.is_not(None)),
        "with_abstract": await count_for(BibliographicReference.abstract.is_not(None)),
    }


# ------------------------------------------------------------------- import/export


async def import_parsed(
    db: AsyncSession,
    *,
    project_id: UUID,
    user_id: UUID,
    parsed: list[ParsedReference],
    skip_duplicates: bool = True,
) -> tuple[list[BibliographicReference], int, int]:
    """Create references from parsed entries. Returns (created, duplicates, skipped)."""
    created: list[BibliographicReference] = []
    duplicates = 0
    for entry in parsed:
        existing = await _existing_duplicate(db, project_id=project_id, doi=entry.doi)
        if existing is None and entry.title and entry.publication_year:
            candidates, _ = await list_references(
                db, project_id=project_id, limit=200, offset=0
            )
            for candidate in candidates:
                if candidate.publication_year != entry.publication_year:
                    continue
                from app.core.normalize import title_similarity

                if title_similarity(candidate.title, entry.title) >= 0.95:
                    existing = candidate
                    break
        if existing is not None:
            duplicates += 1
            if skip_duplicates:
                continue
        request = _to_create_request(entry)
        reference = await create_reference(
            db, project_id=project_id, user_id=user_id, payload=request
        )
        created.append(reference)
    return created, duplicates, 0


async def _existing_duplicate(
    db: AsyncSession, *, project_id: UUID, doi: str | None
) -> BibliographicReference | None:
    if not doi:
        return None
    return (
        await db.execute(
            select(BibliographicReference).where(
                BibliographicReference.project_id == project_id,
                BibliographicReference.doi == doi,
                BibliographicReference.deleted_at.is_(None),
            )
        )
    ).scalars().first()


def _to_create_request(entry: ParsedReference) -> ReferenceCreateRequest:
    return ReferenceCreateRequest(
        citation_key=entry.citation_key,
        reference_type=entry.reference_type,
        entry_type=entry.entry_type,
        title=entry.title,
        subtitle=entry.subtitle,
        authors=[
            AuthorInput(
                given_name=author.given_name,
                family_name=author.family_name or "Auteur non renseigné",
                orcid=author.orcid,
            )
            for author in entry.authors
        ],
        publication_year=entry.publication_year,
        publication_month=entry.publication_month,
        publication_day=entry.publication_day,
        doi=entry.doi_original or entry.doi,
        url=entry.url,
        accessed_at=_parse_date(entry.accessed_at),
        journal=entry.journal,
        volume=entry.volume,
        issue=entry.issue,
        pages=entry.pages,
        publisher=entry.publisher,
        publisher_place=entry.publisher_place,
        edition=entry.edition,
        isbn=entry.isbn,
        issn=entry.issn,
        abstract=entry.abstract,
        keywords=entry.keywords,
        language=entry.language,
        notes=entry.notes,
    )


def _parse_date(value: str | None):  # type: ignore[no-untyped-def]
    from datetime import date

    if not value:
        return None
    match = re.match(r"(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?", value.strip())
    if match is None:
        return None
    try:
        return date(
            int(match.group(1)),
            int(match.group(2) or 1),
            int(match.group(3) or 1),
        )
    except ValueError:
        return None


async def parsed_objects(
    db: AsyncSession, references: list[BibliographicReference]
) -> list[ParsedReference]:
    """Convert stored references back into parser objects, for a faithful export."""
    authors = await _authors_of(db, [reference.id for reference in references])
    tags = await _tags_of(db, [reference.id for reference in references])
    result: list[ParsedReference] = []
    for reference in references:
        result.append(
            ParsedReference(
                reference_type=reference.reference_type,
                citation_key=reference.citation_key,
                entry_type=reference.entry_type,
                title=reference.title,
                subtitle=reference.subtitle,
                authors=list(authors.get(reference.id, [])),
                publication_year=reference.publication_year,
                publication_month=reference.publication_month,
                publication_day=reference.publication_day,
                doi=reference.doi,
                doi_original=reference.doi_original,
                url=reference.url,
                accessed_at=reference.accessed_at.isoformat() if reference.accessed_at else None,
                journal=reference.journal,
                volume=reference.volume,
                issue=reference.issue,
                pages=reference.pages,
                publisher=reference.publisher,
                publisher_place=reference.publisher_place,
                edition=reference.edition,
                isbn=reference.isbn,
                issn=reference.issn,
                abstract=reference.abstract,
                keywords=list(reference.keywords or []),
                language=reference.language,
                notes=reference.notes,
                extra=dict(reference.extra_fields or {}),
            )
        )
        if tags.get(reference.id):
            result[-1].extra.setdefault("note", "")
    return result


def render_export(references: list[ParsedReference], export_format: str) -> str:
    if export_format == "bibtex":
        return export_bibtex(references)
    if export_format == "ris":
        return export_ris(references)
    raise HTTPException(status_code=400, detail="Format d'export non supporté.")


def parse_import(content: str, import_format: str, *, max_entries: int) -> object:
    if import_format == "bibtex":
        return parse_bibtex(content, max_entries=max_entries)
    if import_format == "ris":
        return parse_ris(content, max_entries=max_entries)
    raise HTTPException(status_code=400, detail="Format d'import non supporté.")


async def merge_references(
    db: AsyncSession,
    *,
    project_id: UUID,
    keep: BibliographicReference,
    duplicate: BibliographicReference,
) -> BibliographicReference:
    """Merge a duplicate into ``keep`` without losing any value.

    Fields only the duplicate carries are copied. Authors and tags are moved rather than
    replaced, the notes are concatenated, and the duplicate is soft-deleted so the merge stays
    auditable.
    """
    for field_name in (
        "title", "subtitle", "publication_year", "publication_month", "publication_day",
        "doi", "doi_original", "url", "accessed_at", "journal", "volume", "issue", "pages",
        "publisher", "publisher_place", "edition", "isbn", "issn", "abstract", "language",
        "source_id", "entry_type",
    ):
        if getattr(keep, field_name, None) in (None, "", []):
            value = getattr(duplicate, field_name, None)
            if value not in (None, "", []):
                setattr(keep, field_name, value)
    merged_keywords = list(dict.fromkeys([*(keep.keywords or []), *(duplicate.keywords or [])]))
    keep.keywords = merged_keywords
    if duplicate.notes:
        existing_notes = (keep.notes or "").strip()
        keep.notes = (
            f"{existing_notes}\n\n{duplicate.notes}".strip() if existing_notes else duplicate.notes
        )
    merged_extra = {**(duplicate.extra_fields or {}), **(keep.extra_fields or {})}
    keep.extra_fields = merged_extra

    duplicate_authors = (
        await db.execute(
            select(ReferenceAuthor).where(ReferenceAuthor.reference_id == duplicate.id)
        )
    ).scalars().all()
    offset = int(
        (
            await db.execute(
                select(func.coalesce(func.max(ReferenceAuthor.position), 0)).where(
                    ReferenceAuthor.reference_id == keep.id
                )
            )
        ).scalar_one()
    )
    for author in duplicate_authors:
        db.add(
            ReferenceAuthor(
                reference_id=keep.id,
                position=offset + 1,
                given_name=author.given_name,
                family_name=author.family_name,
                orcid=author.orcid,
            )
        )
        offset += 1

    duplicate_tags = (
        await db.execute(
            select(ReferenceTagLink).where(ReferenceTagLink.reference_id == duplicate.id)
        )
    ).scalars().all()
    for link in duplicate_tags:
        exists = (
            await db.execute(
                select(ReferenceTagLink.id).where(
                    ReferenceTagLink.reference_id == keep.id,
                    ReferenceTagLink.tag_id == link.tag_id,
                )
            )
        ).scalar_one_or_none()
        if exists is None:
            db.add(ReferenceTagLink(reference_id=keep.id, tag_id=link.tag_id))
    await db.execute(
        delete(ReferenceTagLink).where(ReferenceTagLink.reference_id == duplicate.id)
    )
    await db.execute(
        delete(ReferenceAuthor).where(ReferenceAuthor.reference_id == duplicate.id)
    )
    duplicate.deleted_at = datetime.now(UTC)
    keep.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(keep)
    return keep


__all__ = [
    "COMPLETENESS_FIELDS",
    "build_citation_key",
    "create_reference",
    "delete_reference",
    "duplicates_of",
    "get_reference",
    "import_parsed",
    "list_references",
    "merge_references",
    "parse_import",
    "parsed_objects",
    "reference_stats",
    "reference_summary",
    "render_export",
    "slugify",
    "to_response",
    "unique_citation_key",
    "update_reference",
]
