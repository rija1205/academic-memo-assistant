from __future__ import annotations

import hashlib
import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import PurePath

SUPPORTED_EXTENSIONS = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".csv": "text/csv",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}
DANGEROUS_EXTENSIONS = {
    ".apk",
    ".app",
    ".bat",
    ".bin",
    ".cmd",
    ".com",
    ".cpl",
    ".dll",
    ".exe",
    ".hta",
    ".img",
    ".iso",
    ".jar",
    ".js",
    ".jse",
    ".lnk",
    ".msi",
    ".msp",
    ".php",
    ".ps1",
    ".scr",
    ".sh",
    ".vbe",
    ".vbs",
    ".wsf",
}
GENERIC_MIME_TYPES = {
    "",
    "application/octet-stream",
    "binary/octet-stream",
    "application/x-download",
}
TEXT_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


class UploadValidationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class ValidatedUpload:
    original_filename: str
    safe_filename: str
    extension: str
    mime_type: str
    size_bytes: int
    sha256: str
    data: bytes


def sanitize_filename(filename: str | None) -> str:
    raw = PurePath((filename or "").replace("\\", "/")).name.strip()
    normalized = unicodedata.normalize("NFKC", raw)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", normalized).strip("._")
    if not safe:
        raise UploadValidationError("invalid_filename", "Le nom du fichier est invalide.")
    if len(safe) > 240:
        suffix = PurePath(safe).suffix[:16]
        stem = safe[: 240 - len(suffix)]
        safe = f"{stem}{suffix}"
    return safe


def _extension_and_mime(filename: str) -> tuple[str, str]:
    extension = PurePath(filename).suffix.casefold()
    if extension in DANGEROUS_EXTENSIONS:
        raise UploadValidationError(
            "dangerous_extension", "Cette extension de fichier est interdite."
        )
    mime_type = SUPPORTED_EXTENSIONS.get(extension)
    if mime_type is None:
        raise UploadValidationError(
            "unsupported_extension", "Ce type de fichier n'est pas pris en charge."
        )
    return extension, mime_type


def _validate_declared_mime(declared_mime: str | None, expected_mime: str) -> None:
    declared = (declared_mime or "").split(";", 1)[0].strip().casefold()
    if declared in GENERIC_MIME_TYPES:
        return
    compatible = {
        "application/pdf": {"application/pdf", "application/x-pdf"},
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/zip",
        },
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/zip",
        },
        "text/plain": {"text/plain"},
        "text/markdown": {"text/markdown", "text/plain"},
        "text/csv": {"text/csv", "text/plain", "application/csv"},
        "image/png": {"image/png"},
        "image/jpeg": {"image/jpeg", "image/jpg"},
    }
    if declared not in compatible.get(expected_mime, {expected_mime}):
        raise UploadValidationError(
            "mime_mismatch", "Le type MIME déclaré ne correspond pas au fichier."
        )


def _detect_zip_kind(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            if sum(info.file_size for info in infos) > 500_000_000:
                raise UploadValidationError(
                    "archive_too_large", "L'archive Office est trop volumineuse."
                )
            names = set(archive.namelist())
    except (zipfile.BadZipFile, OSError) as exc:
        raise UploadValidationError("corrupt_file", "L'archive DOCX/XLSX est corrompue.") from exc
    if any(name == "word/document.xml" for name in names):
        return "docx"
    if any(name == "xl/workbook.xml" for name in names):
        return "xlsx"
    raise UploadValidationError(
        "unsupported_archive", "L'archive ne contient pas un document DOCX ou XLSX valide."
    )


def _detect_text(data: bytes) -> str:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise UploadValidationError(
            "invalid_text", "Le fichier texte doit être encodé en UTF-8."
        ) from exc
    if "\x00" in text or len(TEXT_CONTROL_CHARACTERS.findall(text)) > max(2, len(text) // 1000):
        raise UploadValidationError("corrupt_file", "Le fichier contient des données binaires.")
    return text


def _validate_real_content(data: bytes, extension: str) -> None:
    if extension == ".pdf":
        if not data.startswith(b"%PDF-") or b"%%EOF" not in data[-4096:]:
            raise UploadValidationError("corrupt_file", "Le PDF est invalide ou corrompu.")
        return
    if extension in {".docx", ".xlsx"}:
        if not data.startswith(b"PK\x03\x04"):
            raise UploadValidationError("corrupt_file", "L'archive Office est invalide.")
        detected = _detect_zip_kind(data)
        if detected != extension.lstrip("."):
            raise UploadValidationError(
                "mime_mismatch", "L'archive ne correspond pas à son extension."
            )
        return
    if extension in {".png"}:
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise UploadValidationError("corrupt_file", "L'image PNG est invalide.")
        return
    if extension in {".jpg", ".jpeg"}:
        if not data.startswith(b"\xff\xd8\xff"):
            raise UploadValidationError("corrupt_file", "L'image JPEG est invalide.")
        return
    if extension in {".txt", ".md", ".markdown", ".csv"}:
        _detect_text(data)
        return
    raise UploadValidationError("unsupported_extension", "Type de fichier non pris en charge.")


def validate_upload(
    *,
    filename: str | None,
    declared_mime: str | None,
    data: bytes,
    max_size_bytes: int,
) -> ValidatedUpload:
    if not data:
        raise UploadValidationError("empty_file", "Le fichier est vide.")
    if len(data) > max_size_bytes:
        raise UploadValidationError(
            "file_too_large",
            f"Le fichier dépasse la limite de {max_size_bytes} octets.",
        )
    safe_filename = sanitize_filename(filename)
    extension, expected_mime = _extension_and_mime(safe_filename)
    _validate_declared_mime(declared_mime, expected_mime)
    _validate_real_content(data, extension)
    return ValidatedUpload(
        original_filename=safe_filename,
        safe_filename=safe_filename,
        extension=extension,
        mime_type=expected_mime,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        data=data,
    )
