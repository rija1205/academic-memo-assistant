from __future__ import annotations

import csv
from dataclasses import dataclass
from io import BytesIO, StringIO
from typing import Protocol

from docx import Document
from openpyxl import load_workbook
from pypdf import PdfReader


class ExtractionError(RuntimeError):
    def __init__(self, message: str, *, technical: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.technical = technical or message


class OcrUnavailableError(ExtractionError):
    pass


class OcrProvider(Protocol):
    def recognize(self, data: bytes, *, mime_type: str) -> list[str]: ...


class NullOcrProvider:
    def recognize(self, data: bytes, *, mime_type: str) -> list[str]:
        raise OcrUnavailableError(
            "OCR non configuré pour ce document.",
            technical="No OCR provider is configured.",
        )


@dataclass(frozen=True, slots=True)
class ExtractedBlock:
    page_number: int
    block_index: int
    block_type: str
    text: str
    position_start: int
    position_end: int


@dataclass(frozen=True, slots=True)
class ExtractedPage:
    page_number: int
    text: str
    blocks: tuple[ExtractedBlock, ...]


@dataclass(frozen=True, slots=True)
class ExtractedMetadata:
    title: str | None = None
    authors: tuple[str, ...] = ()
    page_count: int | None = None
    detected_language: str | None = None


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    pages: tuple[ExtractedPage, ...]
    metadata: ExtractedMetadata
    warnings: tuple[str, ...] = ()
    ocr_used: bool = False
    sheets: tuple[str, ...] = ()

    @property
    def page_count(self) -> int:
        return len(self.pages)


def _clean_text(value: str) -> str:
    normalized = value.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in normalized.split("\n")).strip()


def _blocks_from_text(
    text: str,
    page_number: int,
    *,
    default_type: str = "paragraph",
) -> tuple[ExtractedBlock, ...]:
    normalized = _clean_text(text)
    if not normalized:
        return ()
    raw_blocks = [part.strip() for part in normalized.split("\n\n") if part.strip()]
    blocks: list[ExtractedBlock] = []
    position = 0
    for index, block_text in enumerate(raw_blocks):
        block_type = default_type
        if block_text.startswith("#"):
            block_type = "heading"
        start = normalized.find(block_text, position)
        if start < 0:
            start = position
        end = start + len(block_text)
        blocks.append(
            ExtractedBlock(
                page_number=page_number,
                block_index=index,
                block_type=block_type,
                text=block_text,
                position_start=start,
                position_end=end,
            )
        )
        position = end
    return tuple(blocks)


def _metadata_value(metadata: object, key: str) -> str | None:
    getter = getattr(metadata, "get", None)
    if not callable(getter):
        return None
    value = getter(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _extract_pdf(
    data: bytes,
    *,
    ocr_provider: OcrProvider,
) -> ExtractionResult:
    try:
        reader = PdfReader(BytesIO(data), strict=False)
        if reader.is_encrypted:
            raise ExtractionError("Le PDF est protégé par mot de passe.")
        metadata = reader.metadata
        page_texts: list[str] = []
        for page in reader.pages:
            page_texts.append(_clean_text(page.extract_text() or ""))
    except ExtractionError:
        raise
    except Exception as exc:
        raise ExtractionError(
            "Le PDF ne peut pas être lu.", technical=str(exc)
        ) from exc

    ocr_used = False
    warnings: list[str] = []
    if sum(len(text) for text in page_texts) < max(20, len(page_texts) * 10):
        try:
            ocr_pages = ocr_provider.recognize(data, mime_type="application/pdf")
        except OcrUnavailableError as exc:
            raise OcrUnavailableError(
                "Le PDF semble scanné et aucun fournisseur OCR n'est configuré.",
                technical=exc.technical,
            ) from exc
        if not ocr_pages:
            raise ExtractionError("Aucun texte n'a pu être extrait du PDF.")
        ocr_used = True
        page_texts = [_clean_text(text) for text in ocr_pages]
        warnings.append("OCR utilisé pour ce PDF.")

    pages = tuple(
        ExtractedPage(
            page_number=index,
            text=text,
            blocks=_blocks_from_text(text, index),
        )
        for index, text in enumerate(page_texts, start=1)
    )
    author = _metadata_value(metadata, "/Author")
    return ExtractionResult(
        pages=pages,
        metadata=ExtractedMetadata(
            title=_metadata_value(metadata, "/Title"),
            authors=(author,) if author else (),
            page_count=len(pages),
        ),
        warnings=tuple(warnings),
        ocr_used=ocr_used,
    )


def _extract_docx(data: bytes) -> ExtractionResult:
    try:
        document = Document(BytesIO(data))
    except Exception as exc:
        raise ExtractionError("Le document DOCX est corrompu.", technical=str(exc)) from exc
    blocks: list[ExtractedBlock] = []
    position = 0
    text_parts: list[str] = []
    for paragraph in document.paragraphs:
        text = _clean_text(paragraph.text)
        if not text:
            continue
        start = position
        text_parts.append(text)
        position += len(text) + 2
        style_name = (paragraph.style.name or "").casefold() if paragraph.style else ""
        block_type = "heading" if style_name.startswith("heading") else "paragraph"
        blocks.append(
            ExtractedBlock(1, len(blocks), block_type, text, start, start + len(text))
        )
    for table_index, table in enumerate(document.tables, start=1):
        for row_index, row in enumerate(table.rows, start=1):
            values = [_clean_text(cell.text) for cell in row.cells]
            text = " | ".join(values)
            if not text:
                continue
            start = position
            text_parts.append(text)
            position += len(text) + 2
            blocks.append(
                ExtractedBlock(
                    1,
                    len(blocks),
                    "table_row",
                    text,
                    start,
                    start + len(text),
                )
            )
    full_text = "\n\n".join(text_parts)
    properties = document.core_properties
    author = (properties.author or "").strip() or None
    title = (properties.title or "").strip() or None
    return ExtractionResult(
        pages=(
            ExtractedPage(
                page_number=1,
                text=full_text,
                blocks=tuple(blocks),
            ),
        ),
        metadata=ExtractedMetadata(
            title=title,
            authors=(author,) if author else (),
            page_count=1,
        ),
        warnings=("La pagination DOCX n'est pas disponible.",),
    )


def _extract_plain_text(data: bytes, *, extension: str) -> ExtractionResult:
    try:
        text = _clean_text(data.decode("utf-8-sig"))
    except UnicodeDecodeError as exc:
        raise ExtractionError("Le fichier texte n'est pas encodé en UTF-8.") from exc
    return ExtractionResult(
        pages=(ExtractedPage(1, text, _blocks_from_text(text, 1)),),
        metadata=ExtractedMetadata(page_count=1),
        warnings=(
            ("La pagination TXT/Markdown est synthétique.",)
            if extension != ".csv"
            else ("La pagination CSV est synthétique.",)
        ),
    )


def _extract_csv(data: bytes) -> ExtractionResult:
    try:
        text = data.decode("utf-8-sig")
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except (UnicodeDecodeError, csv.Error):
        text = data.decode("utf-8-sig", errors="strict")
        dialect = csv.excel
    rows = list(csv.reader(StringIO(text), dialect))
    if not rows:
        raise ExtractionError("Le fichier CSV est vide.")
    blocks: list[ExtractedBlock] = []
    position = 0
    rendered_rows: list[str] = []
    for index, row in enumerate(rows):
        rendered = " | ".join(value.strip() for value in row)
        rendered_rows.append(rendered)
        blocks.append(
            ExtractedBlock(
                page_number=1,
                block_index=index,
                block_type="table_header" if index == 0 else "table_row",
                text=rendered,
                position_start=position,
                position_end=position + len(rendered),
            )
        )
        position += len(rendered) + 1
    return ExtractionResult(
        pages=(
            ExtractedPage(1, "\n".join(rendered_rows), tuple(blocks)),
        ),
        metadata=ExtractedMetadata(page_count=1),
        warnings=(f"CSV : {len(rows)} ligne(s), {len(rows[0])} colonne(s) détectée(s).",),
    )


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def _extract_xlsx(data: bytes) -> ExtractionResult:
    try:
        workbook = load_workbook(BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:
        raise ExtractionError("Le classeur XLSX est corrompu.", technical=str(exc)) from exc
    pages: list[ExtractedPage] = []
    blocks: list[ExtractedBlock] = []
    block_index = 0
    for page_number, worksheet in enumerate(workbook.worksheets, start=1):
        rows = list(worksheet.iter_rows(values_only=True))
        rendered_rows: list[str] = []
        page_blocks: list[ExtractedBlock] = []
        position = 0
        for row_index, row in enumerate(rows):
            rendered = " | ".join(_cell_text(value) for value in row)
            rendered_rows.append(rendered)
            page_blocks.append(
                ExtractedBlock(
                    page_number=page_number,
                    block_index=block_index,
                    block_type="table_header" if row_index == 0 else "table_row",
                    text=rendered,
                    position_start=position,
                    position_end=position + len(rendered),
                )
            )
            position += len(rendered) + 1
            block_index += 1
        page_text = "\n".join(rendered_rows)
        pages.append(ExtractedPage(page_number, page_text, tuple(page_blocks)))
        blocks.extend(page_blocks)
    if not pages:
        raise ExtractionError("Le classeur XLSX ne contient aucune feuille.")
    sheet_names = tuple(workbook.sheetnames)
    workbook.close()
    return ExtractionResult(
        pages=tuple(pages),
        metadata=ExtractedMetadata(page_count=len(pages)),
        warnings=(f"XLSX : {len(sheet_names)} feuille(s) détectée(s).",),
        sheets=sheet_names,
    )


def extract_document(
    data: bytes,
    *,
    mime_type: str,
    extension: str,
    ocr_provider: OcrProvider | None = None,
) -> ExtractionResult:
    provider = ocr_provider or NullOcrProvider()
    if mime_type == "application/pdf" or extension == ".pdf":
        return _extract_pdf(data, ocr_provider=provider)
    if mime_type.endswith("wordprocessingml.document") or extension == ".docx":
        return _extract_docx(data)
    if extension in {".txt", ".md", ".markdown"}:
        return _extract_plain_text(data, extension=extension)
    if extension == ".csv":
        return _extract_csv(data)
    if extension == ".xlsx" or mime_type.endswith("spreadsheetml.sheet"):
        return _extract_xlsx(data)
    if extension in {".png", ".jpg", ".jpeg"} or mime_type.startswith("image/"):
        try:
            texts = provider.recognize(data, mime_type=mime_type)
        except OcrUnavailableError as exc:
            raise OcrUnavailableError(
                "L'image nécessite OCR, mais aucun fournisseur n'est configuré.",
                technical=exc.technical,
            ) from exc
        if not texts or not any(text.strip() for text in texts):
            raise ExtractionError("Aucun texte n'a été reconnu dans l'image.")
        pages = tuple(
            ExtractedPage(index, _clean_text(text), _blocks_from_text(text, index))
            for index, text in enumerate(texts, start=1)
        )
        return ExtractionResult(
            pages=pages,
            metadata=ExtractedMetadata(page_count=len(pages)),
            warnings=("OCR utilisé pour l'image.",),
            ocr_used=True,
        )
    raise ExtractionError("Type de document non pris en charge par l'extracteur.")


class DeterministicOcrProvider:
    """Simple test provider; production OCR adapters can implement the same protocol."""

    def __init__(self, pages: list[str] | None = None) -> None:
        self.pages = pages or []

    def recognize(self, data: bytes, *, mime_type: str) -> list[str]:
        return list(self.pages)
