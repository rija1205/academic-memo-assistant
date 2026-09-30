"""BibTeX and RIS import/export.

Design rules that matter for an academic bibliography:

* **Parsing is pure text handling.** No entry is ever evaluated, executed, resolved through a
  shell or interpreted. A BibTeX file is untrusted user input; this module only reads it.
* **Nothing is invented.** A field absent from the file stays ``None``. An unrecognised type
  becomes ``other`` and the original entry type is preserved, so the information is not lost.
* **Round-trip fidelity.** A reference imported from BibTeX or RIS and exported again keeps
  every field this application models. Unknown fields are preserved so a re-import is stable.
* **Bounded work.** Callers pass the payload through a size limit and the parser stops after a
  maximum number of entries, so a hostile file cannot exhaust memory or time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.bibliography.authors import (
    ParsedAuthor,
    format_author_list,
    parse_authors,
    parse_ris_authors,
)
from app.core.normalize import normalize_doi, normalize_url

#: BibTeX entry types mapped to the application's reference types.
BIBTEX_TYPE_MAP = {
    "article": "article",
    "book": "book",
    "inbook": "book",
    "incollection": "book_chapter",
    "inproceedings": "conference",
    "conference": "conference",
    "phdthesis": "thesis",
    "mastersthesis": "thesis",
    "thesis": "thesis",
    "techreport": "report",
    "report": "report",
    "misc": "other",
    "online": "webpage",
    "electronic": "webpage",
    "www": "webpage",
    "dataset": "dataset",
    "patent": "patent",
    "software": "other",
}

#: RIS type codes mapped to the application's reference types.
RIS_TYPE_MAP = {
    "JOUR": "article",
    "JFULL": "article",
    "ABST": "article",
    "BOOK": "book",
    "EBOOK": "book",
    "CHAP": "book_chapter",
    "ECHAP": "book_chapter",
    "THES": "thesis",
    "RPRT": "report",
    "CONF": "conference",
    "CPAPER": "conference",
    "ELEC": "webpage",
    "WWW": "webpage",
    "DATA": "dataset",
    "DBASE": "dataset",
    "PAT": "patent",
    "GEN": "other",
    "MGZN": "other",
    "NEWS": "other",
    "SER": "other",
}

REFERENCE_TYPES = (
    "article",
    "book",
    "book_chapter",
    "thesis",
    "report",
    "conference",
    "webpage",
    "dataset",
    "patent",
    "other",
)

_ENTRY_HEADER = re.compile(r"@(?P<type>[A-Za-z]+)\s*[{(]\s*(?P<key>[^,}\s]*)\s*,")


@dataclass(slots=True)
class ParsedReference:
    """One reference read from an import file. ``None`` means "not provided"."""

    reference_type: str
    citation_key: str | None = None
    entry_type: str | None = None
    title: str | None = None
    subtitle: str | None = None
    authors: list[ParsedAuthor] = field(default_factory=list)
    publication_year: int | None = None
    publication_month: str | None = None
    publication_day: str | None = None
    doi: str | None = None
    doi_original: str | None = None
    url: str | None = None
    accessed_at: str | None = None
    journal: str | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    publisher: str | None = None
    publisher_place: str | None = None
    edition: str | None = None
    isbn: str | None = None
    issn: str | None = None
    abstract: str | None = None
    keywords: list[str] = field(default_factory=list)
    language: str | None = None
    notes: str | None = None
    extra: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def has_content(self) -> bool:
        return bool(self.title or self.authors or self.doi or self.publication_year)


@dataclass(slots=True)
class ImportResult:
    references: list[ParsedReference] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    skipped: int = 0

    @property
    def total_seen(self) -> int:
        return len(self.references) + self.skipped


# --------------------------------------------------------------------- BibTeX


def _strip_braces(value: str) -> str:
    text = value.strip()
    while len(text) >= 2 and text[0] == "{" and text[-1] == "}":
        depth = 0
        balanced = True
        for index, char in enumerate(text):
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0 and index != len(text) - 1:
                    balanced = False
                    break
        if balanced:
            text = text[1:-1].strip()
        else:
            break
    return re.sub(r"\s+", " ", text).strip()


def _unquote(value: str) -> str:
    text = value.strip()
    if text.startswith("{") and text.endswith("}"):
        return _strip_braces(text)
    if text.startswith('"') and text.endswith('"'):
        return text[1:-1].strip()
    return text.strip()


def _unescape_latex(value: str) -> str:
    replacements = {
        r"\\&": "&",
        r"\%": "%",
        r"\$": "$",
        r"\#": "#",
        r"\_": "_",
        r"{\'e}": "é",
        r"{\`e}": "è",
        r"{\^e}": "ê",
        r"{\"e}": "ë",
        r"{\c c}": "ç",
        r"{\o}": "ø",
    }
    text = value
    for source, target in replacements.items():
        text = text.replace(source, target)
    return re.sub(r"\\[a-zA-Z]+", "", text)


def parse_bibtex(content: str, *, max_entries: int = 2000) -> ImportResult:
    """Parse a BibTeX file into references. Unknown fields are preserved in ``extra``."""
    result = ImportResult()
    if not content or not content.strip():
        result.errors.append("Fichier BibTeX vide.")
        return result
    position = 0
    while True:
        match = _ENTRY_HEADER.search(content, position)
        if match is None:
            break
        body_start = match.end()
        body_end, position = _find_entry_end(content, body_start)
        if body_end is None:
            result.errors.append(
                f"Entr?e ? {match.group('key') or match.group('type')} ? ignor?e : accolades non "
                "?quilibr?es."
            )
            break
        entry_type = match.group("type").casefold()
        citation_key = match.group("key").strip() or None
        fields = _parse_bibtex_fields(content[body_start:body_end])
        reference = _bibtex_to_reference(entry_type, citation_key, fields)
        if reference.has_content:
            result.references.append(reference)
        else:
            result.skipped += 1
            result.errors.append(
                f"Entr?e {citation_key or entry_type} ignor?e : aucun champ reconnu."
            )
        if len(result.references) >= max_entries:
            result.errors.append(
                f"Limite atteinte : seules les {max_entries} premi?res entr?es ont ?t? lues."
            )
            break
    if not result.references and not result.errors:
        result.errors.append("Aucune entr?e BibTeX reconnue dans le fichier.")
    return result


def _find_entry_end(content: str, start: int) -> tuple[int | None, int]:
    """Return the index of the closing brace of an entry and the next scan position.

    Brace matching is done explicitly so that braces inside a field value, an abstract or a
    nested BibTeX command do not terminate the entry early.
    """
    depth = 1
    index = start
    length = len(content)
    while index < length:
        char = content[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index, index + 1
        index += 1
    return None, length


def _parse_bibtex_fields(body: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    index = 0
    length = len(body)
    while index < length:
        name_match = re.search(r"([A-Za-z_][A-Za-z0-9_-]*)\s*=\s*", body[index:])
        if name_match is None:
            break
        name = name_match.group(1).casefold()
        start = index + name_match.end()
        if start >= length:
            break
        char = body[start]
        if char in "{\"":
            closer = "}" if char == "{" else '"'
            depth = 1
            cursor = start + 1
            while cursor < length:
                current = body[cursor]
                if current == char and char == "{":
                    depth += 1
                elif current == closer:
                    depth -= 1
                    if depth == 0:
                        break
                cursor += 1
            fields[name] = _unescape_latex(_unquote(body[start : cursor + 1]))
            index = cursor + 1
        else:
            end = start
            while end < length and body[end] not in ",}\n":
                end += 1
            fields[name] = _unescape_latex(body[start:end].strip())
            index = end
        # A comma separates fields, and also separates two entries written on one line. It is
        # consumed as a field separator only when the next non-space token is a field name.
        while index < length and body[index] in ", \t":
            lookahead = index + 1
            while lookahead < length and body[lookahead] in " \t":
                lookahead += 1
            if lookahead < length and body[lookahead] == "{":
                break
            index += 1
        while index < length and body[index] in "\n\r":
            index += 1
    return fields


def _bibtex_to_reference(
    entry_type: str, citation_key: str | None, fields: dict[str, str]
) -> ParsedReference:
    known = {
        "title",
        "subtitle",
        "author",
        "year",
        "month",
        "day",
        "doi",
        "url",
        "urldate",
        "journal",
        "journaltitle",
        "volume",
        "number",
        "pages",
        "publisher",
        "location",
        "address",
        "edition",
        "isbn",
        "issn",
        "abstract",
        "keywords",
        "language",
        "langid",
        "note",
        "howpublished",
    }
    reference = ParsedReference(
        reference_type=BIBTEX_TYPE_MAP.get(entry_type, "other"),
        citation_key=citation_key,
        entry_type=entry_type,
        title=fields.get("title") or None,
        subtitle=fields.get("subtitle") or None,
        authors=parse_authors(fields.get("author")),
        publication_year=_int_or_none(fields.get("year")),
        publication_month=fields.get("month") or None,
        publication_day=fields.get("day") or None,
        doi_original=fields.get("doi") or None,
        url=normalize_url(fields.get("url")),
        accessed_at=fields.get("urldate") or None,
        journal=fields.get("journal") or fields.get("journaltitle") or None,
        volume=fields.get("volume") or None,
        issue=fields.get("number") or None,
        pages=fields.get("pages") or None,
        publisher=fields.get("publisher") or None,
        publisher_place=fields.get("location") or fields.get("address") or None,
        edition=fields.get("edition") or None,
        isbn=fields.get("isbn") or None,
        issn=fields.get("issn") or None,
        abstract=fields.get("abstract") or None,
        keywords=_split_keywords(fields.get("keywords")),
        language=fields.get("language") or fields.get("langid") or None,
        notes=fields.get("note") or None,
    )
    reference.doi = normalize_doi(fields.get("doi"))
    reference.extra = {key: value for key, value in fields.items() if key not in known and value}
    if entry_type not in BIBTEX_TYPE_MAP:
        reference.errors.append(
            f"Type BibTeX « {entry_type} » inconnu : enregistré comme « other »."
        )
    return reference


def _int_or_none(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"\d{4}", value)
    if match is None:
        return None
    return int(match.group(0))


def _split_keywords(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in re.split(r"[;,]", value) if item.strip()]


# ------------------------------------------------------------------------- RIS


def parse_ris(content: str, *, max_entries: int = 2000) -> ImportResult:
    """Parse a RIS file. The type code comes from ``TY``; absent fields stay ``None``."""
    result = ImportResult()
    if not content or not content.strip():
        result.errors.append("Fichier RIS vide.")
        return result
    records: list[list[tuple[str, str]]] = []
    current: list[tuple[str, str]] = []
    for raw_line in content.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        match = re.match(r"^([A-Z][A-Z0-9])\s{0,2}-\s?(.*)$", raw_line)
        if match is None:
            continue
        tag = match.group(1)
        value = match.group(2).strip()
        if tag == "TY":
            if current:
                records.append(current)
            current = [(tag, value)]
            continue
        if tag == "ER":
            if current:
                records.append(current)
            current = []
            continue
        if current:
            current.append((tag, value))
    if current:
        records.append(current)

    for record in records:
        reference = _ris_to_reference(record)
        if reference.has_content:
            result.references.append(reference)
        else:
            result.skipped += 1
            result.errors.append("Enregistrement RIS ignoré : aucun champ reconnu.")
        if len(result.references) >= max_entries:
            result.errors.append(
                f"Limite atteinte : seules les {max_entries} premières entrées ont été lues."
            )
            break
    if not result.references and not result.errors:
        result.errors.append("Aucun enregistrement RIS reconnu dans le fichier.")
    return result


def _isbn_from_sn(value: str | None) -> str | None:
    """Extract an ISBN from a RIS ``SN`` line such as ``ISBN 978-2-1234-5678-9``."""
    if not value:
        return None
    text = value.strip()
    if not text.upper().startswith("ISBN"):
        return None
    return text.split(None, 1)[1].strip() if len(text.split(None, 1)) > 1 else None


def _issn_from_sn(value: str | None) -> str | None:
    """Extract an ISSN from a RIS ``SN`` line such as ``ISSN 1234-5678``."""
    if not value:
        return None
    text = value.strip()
    if not text.upper().startswith("ISSN"):
        return None
    return text.split(None, 1)[1].strip() if len(text.split(None, 1)) > 1 else None


def _date_part(value: str | None, index: int) -> str | None:
    """Return one component of a RIS ``DA`` date such as ``2024-03-17``."""
    if not value:
        return None
    parts = value.split("-")
    if len(parts) <= index:
        return None
    component = parts[index].strip()
    return component or None


def _ris_to_reference(record: list[tuple[str, str]]) -> ParsedReference:
    grouped: dict[str, list[str]] = {}
    for tag, value in record:
        grouped.setdefault(tag, []).append(value)

    def first(*tags: str) -> str | None:
        for tag in tags:
            values = grouped.get(tag)
            if values and values[0]:
                return values[0]
        return None

    type_code = (first("TY") or "GEN").upper()
    start_page = first("SP")
    end_page = first("EP")
    pages = None
    if start_page and end_page:
        pages = f"{start_page}-{end_page}"
    elif start_page:
        pages = start_page

    reference = ParsedReference(
        reference_type=RIS_TYPE_MAP.get(type_code, "other"),
        entry_type=type_code,
        citation_key=first("ID") or first("AN") or None,
        title=first("TI", "T1", "ST"),
        subtitle=first("T2"),
        authors=parse_ris_authors(grouped.get("AU", []) or grouped.get("A1", [])),
        publication_year=_int_or_none(first("PY", "Y1")),
        publication_month=_date_part(first("DA"), 1),
        publication_day=_date_part(first("DA"), 2),
        doi_original=first("DO"),
        url=normalize_url(first("UR", "L1")),
        accessed_at=first("Y2"),
        journal=first("JO", "JF", "T2"),
        volume=first("VL"),
        issue=first("IS"),
        pages=pages,
        publisher=first("PB"),
        publisher_place=first("CY", "PP"),
        edition=first("ET"),
        isbn=_isbn_from_sn(first("SN")),
        issn=_issn_from_sn(first("SN")),
        abstract=first("AB", "N2"),
        keywords=[value for value in grouped.get("KW", []) if value],
        language=first("LA"),
        notes=first("N1"),
    )
    reference.doi = normalize_doi(reference.doi_original)
    return reference


# ----------------------------------------------------------------------- export


def _escape_bibtex(value: str) -> str:
    return (
        value.replace("\\", r"\textbackslash{}")
        .replace("&", r"\&")
        .replace("%", r"\%")
        .replace("$", r"\$")
        .replace("#", r"\#")
        .replace("_", r"\_")
        .replace("{", r"\{")
        .replace("}", r"\}")
    )


def _wrap_bibtex(value: str) -> str:
    return "{" + _escape_bibtex(value) + "}"


def to_bibtex(reference, *, fallback_key: str = "reference") -> str:  # type: ignore[no-untyped-def]
    """Serialise one reference as a BibTeX entry.

    Only the fields that actually hold a value are written, which is what keeps a re-import
    from inventing a field the user never provided.
    """
    entry_type = BIBTEX_TYPE_REVERSE.get(reference.reference_type, "misc")
    key = _safe_key(reference.citation_key or fallback_key)
    lines = [f"@{entry_type}{{{key},"]
    values: list[tuple[str, str | None]] = [
        ("title", reference.title),
        ("subtitle", reference.subtitle),
        ("author", format_author_list(list(reference.authors), bibtex=True) or None),
        ("year", str(reference.publication_year) if reference.publication_year else None),
        ("month", reference.publication_month),
        ("day", reference.publication_day),
        ("journal", reference.journal),
        ("volume", reference.volume),
        ("number", reference.issue),
        ("pages", reference.pages),
        ("publisher", reference.publisher),
        ("location", reference.publisher_place),
        ("edition", reference.edition),
        ("doi", reference.doi),
        ("url", reference.url),
        ("urldate", reference.accessed_at),
        ("isbn", reference.isbn),
        ("issn", reference.issn),
        ("abstract", reference.abstract),
        ("keywords", ", ".join(reference.keywords) if reference.keywords else None),
        ("language", reference.language),
        ("note", reference.notes),
    ]
    for name, value in values:
        if value:
            lines.append(f"  {name} = {_wrap_bibtex(value)},")
    for name, value in (reference.extra or {}).items():
        lines.append(f"  {name} = {_wrap_bibtex(value)},")
    lines.append("}")
    return "\n".join(lines)


BIBTEX_TYPE_REVERSE = {
    "article": "article",
    "book": "book",
    "book_chapter": "incollection",
    "thesis": "phdthesis",
    "report": "techreport",
    "conference": "inproceedings",
    "webpage": "misc",
    "dataset": "misc",
    "patent": "misc",
    "other": "misc",
}


def _safe_key(value: str) -> str:
    key = re.sub(r"[^A-Za-z0-9_:-]", "", (value or "").strip())
    return key or "reference"


def export_bibtex(references: list, *, fallback_prefix: str = "ref") -> str:  # type: ignore[no-untyped-def]
    """Serialise a list of references as a BibTeX file."""
    entries = [
        to_bibtex(reference, fallback_key=f"{fallback_prefix}{index}")
        for index, reference in enumerate(references, start=1)
    ]
    return "\n\n".join(entries) + ("\n" if entries else "")


RIS_TYPE_REVERSE = {
    "article": "JOUR",
    "book": "BOOK",
    "book_chapter": "CHAP",
    "thesis": "THES",
    "report": "RPRT",
    "conference": "CONF",
    "webpage": "ELEC",
    "dataset": "DATA",
    "patent": "PAT",
    "other": "GEN",
}


def to_ris(reference) -> str:  # type: ignore[no-untyped-def]
    """Serialise one reference as a RIS record."""
    lines = [f"TY  - {RIS_TYPE_REVERSE.get(reference.reference_type, 'GEN')}"]
    for author in reference.authors:
        lines.append(f"AU  - {author.display}")
    if reference.title:
        lines.append(f"TI  - {reference.title}")
    if reference.subtitle:
        lines.append(f"T2  - {reference.subtitle}")
    if reference.journal:
        lines.append(f"JO  - {reference.journal}")
    if reference.publication_year:
        date_parts = [f"{reference.publication_year:04d}"]
        if reference.publication_month:
            date_parts.append(str(reference.publication_month).zfill(2))
        if reference.publication_day:
            date_parts.append(str(reference.publication_day).zfill(2))
        lines.append(f"PY  - {date_parts[0]}")
        if len(date_parts) > 1:
            lines.append(f"DA  - {'-'.join(date_parts)}")
    if reference.volume:
        lines.append(f"VL  - {reference.volume}")
    if reference.issue:
        lines.append(f"IS  - {reference.issue}")
    if reference.pages:
        start, _, end = reference.pages.partition("-")
        lines.append(f"SP  - {start}")
        if end:
            lines.append(f"EP  - {end}")
    if reference.publisher:
        lines.append(f"PB  - {reference.publisher}")
    if reference.publisher_place:
        lines.append(f"CY  - {reference.publisher_place}")
    if reference.edition:
        lines.append(f"ET  - {reference.edition}")
    if reference.doi:
        lines.append(f"DO  - {reference.doi}")
    if reference.url:
        lines.append(f"UR  - {reference.url}")
    if reference.accessed_at:
        lines.append(f"Y2  - {reference.accessed_at}")
    if reference.isbn:
        lines.append(f"SN  - ISBN {reference.isbn}")
    if reference.issn:
        lines.append(f"SN  - ISSN {reference.issn}")
    if reference.abstract:
        lines.append(f"AB  - {reference.abstract}")
    for keyword in reference.keywords:
        lines.append(f"KW  - {keyword}")
    if reference.language:
        lines.append(f"LA  - {reference.language}")
    if reference.notes:
        lines.append(f"N1  - {reference.notes}")
    if reference.citation_key:
        lines.append(f"ID  - {reference.citation_key}")
    lines.append("ER  -")
    return "\n".join(lines) + "\n"


def export_ris(references: list) -> str:  # type: ignore[no-untyped-def]
    return "".join(to_ris(reference) for reference in references)


__all__ = [
    "BIBTEX_TYPE_MAP",
    "REFERENCE_TYPES",
    "RIS_TYPE_MAP",
    "ImportResult",
    "ParsedReference",
    "export_bibtex",
    "export_ris",
    "parse_bibtex",
    "parse_ris",
    "to_bibtex",
    "to_ris",
]
