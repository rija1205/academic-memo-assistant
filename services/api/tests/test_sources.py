from io import BytesIO

import pytest
from docx import Document
from openpyxl import Workbook
from pypdf import PdfWriter

from app.sources.extraction import (
    DeterministicOcrProvider,
    OcrUnavailableError,
    extract_document,
)
from app.sources.validation import UploadValidationError, sanitize_filename, validate_upload
from app.storage.base import StorageError
from app.storage.local import LocalStorageProvider


def make_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def make_docx() -> bytes:
    document = Document()
    document.add_heading("Titre", level=1)
    document.add_paragraph("Paragraphe de test.")
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def make_xlsx() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Mesures"
    sheet.append(["colonne", "valeur"])
    sheet.append(["température", 21])
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def test_upload_validation_detects_real_content_and_hash() -> None:
    data = b" Titre\n\nparagraph"
    result = validate_upload(
        filename="notes.md",
        declared_mime="text/markdown",
        data=data,
        max_size_bytes=1024,
    )

    assert result.extension == ".md"
    assert result.mime_type == "text/markdown"
    assert result.size_bytes == len(data)
    assert len(result.sha256) == 64
    assert result.safe_filename == "notes.md"


@pytest.mark.parametrize(
    ("filename", "data", "code"),
    [
        ("payload.exe", b"MZ", "dangerous_extension"),
        ("fake.pdf", b"not a pdf", "corrupt_file"),
        ("large.txt", b"a" * 20, "file_too_large"),
        ("broken.docx", b"not a zip", "corrupt_file"),
    ],
)
def test_upload_validation_rejects_unsafe_files(filename, data, code) -> None:
    with pytest.raises(UploadValidationError) as error:
        validate_upload(
            filename=filename,
            declared_mime=None,
            data=data,
            max_size_bytes=10,
        )
    assert error.value.code == code


def test_upload_validation_rejects_mismatched_declared_mime() -> None:
    with pytest.raises(UploadValidationError) as error:
        validate_upload(
            filename="declared.pdf",
            declared_mime="text/plain",
            data=make_pdf(),
            max_size_bytes=100_000,
        )
    assert error.value.code == "mime_mismatch"


def test_filename_sanitization_removes_path_and_dangerous_characters() -> None:
    assert sanitize_filename("../../My report?.PDF") == "My_report_.PDF"


def test_pdf_scanned_uses_injectable_ocr_provider() -> None:
    result = extract_document(
        make_pdf(),
        mime_type="application/pdf",
        extension=".pdf",
        ocr_provider=DeterministicOcrProvider(["texte de la page"]),
    )

    assert result.ocr_used is True
    assert result.page_count == 1
    assert result.pages[0].text == "texte de la page"
    assert result.pages[0].blocks[0].position_end > result.pages[0].blocks[0].position_start


def test_pdf_without_ocr_provider_fails_explicitly() -> None:
    with pytest.raises(OcrUnavailableError):
        extract_document(make_pdf(), mime_type="application/pdf", extension=".pdf")


def test_docx_txt_csv_and_xlsx_extraction_preserve_text() -> None:
    docx_result = extract_document(
        make_docx(),
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        extension=".docx",
    )
    assert "Paragraphe de test." in docx_result.pages[0].text

    txt_result = extract_document(b"# Titre\n\ncontenu", mime_type="text/markdown", extension=".md")
    assert txt_result.pages[0].blocks[0].block_type == "heading"

    csv_result = extract_document(b"name,value\na,1\nb,2\n", mime_type="text/csv", extension=".csv")
    assert csv_result.pages[0].blocks[0].block_type == "table_header"
    assert "name | value" in csv_result.pages[0].text

    xlsx_result = extract_document(
        make_xlsx(),
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        extension=".xlsx",
    )
    assert xlsx_result.sheets == ("Mesures",)
    assert "colonne | valeur" in xlsx_result.pages[0].text


def test_local_storage_provider_is_scoped_to_its_root(tmp_path) -> None:
    provider = LocalStorageProvider(tmp_path / "sources")
    stored = provider.save("projects/p1/file.txt", b"hello", content_type="text/plain")

    assert provider.exists(stored.key)
    assert provider.read(stored.key) == b"hello"
    provider.delete(stored.key)
    assert not provider.exists(stored.key)
    with pytest.raises(StorageError):
        provider.read("../outside.txt")
