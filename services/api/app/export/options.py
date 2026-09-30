"""Export options: what the author may configure about a rendering.

Everything here is a presentation choice. The options are validated and clamped here, once,
so both renderers can trust their inputs, and so a hostile request cannot ask for a
thousand-page document or a font size of zero.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Base-14 fonts of the PDF renderer. They ship with every PDF reader, so no font file has to
#: be embedded and the export works on a machine with no font installed.
PDF_FONTS = {
    "times": ("Times-Roman", "Times-Bold", "Times-Italic", "Times-BoldItalic"),
    "helvetica": ("Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Helvetica-BoldOblique"),
    "courier": ("Courier", "Courier-Bold", "Courier-Oblique", "Courier-BoldOblique"),
}

#: Word font names, used by the DOCX renderer.
DOCX_FONTS = {
    "times": "Times New Roman",
    "helvetica": "Arial",
    "courier": "Courier New",
}

#: Page size in points (1 pt = 1/72 inch). A4 is the French academic default.
PAGE_SIZES = {
    "a4": (595.28, 841.89),
    "letter": (612.0, 792.0),
}

ALIGNMENTS = {"left", "center", "right", "justify"}

#: Hard limits. A document beyond these is refused rather than truncated silently.
MAX_SECTIONS = 2000
MAX_BLOCKS = 200_000
MAX_BLOCK_CHARS = 2_000_000


class ExportOptionError(ValueError):
    """Raised when an export option is outside the allowed range."""


def _clamp(value: float, low: float, high: float, name: str) -> float:
    if value < low or value > high:
        raise ExportOptionError(f"{name} doit être compris entre {low} et {high}.")
    return value


@dataclass(slots=True)
class ExportOptions:
    """Validated presentation options for one export."""

    # page
    page_size: str = "a4"
    orientation: str = "portrait"
    margin_top: float = 2.5
    margin_bottom: float = 2.5
    margin_left: float = 3.0
    margin_right: float = 2.5

    # typography
    font_family: str = "times"
    font_size: float = 12.0
    line_spacing: float = 1.5
    first_line_indent: float = 1.25
    paragraph_alignment: str = "justify"
    paragraph_space_after: float = 0.0

    # structure
    include_cover: bool = True
    include_toc: bool = True
    include_list_of_figures: bool = True
    include_list_of_tables: bool = True
    include_bibliography: bool = True
    include_annexes: bool = True
    include_page_numbers: bool = True
    #: Front matter is numbered in roman numerals, the body in arabic, as universities require.
    roman_front_matter: bool = True
    header_text: str | None = None
    footer_text: str | None = None
    show_running_head: bool = True

    # content
    number_headings: bool = True
    number_figures: bool = True
    number_tables: bool = True
    number_equations: bool = True
    embed_remote_images: bool = False
    bibliography_heading: str = "Bibliographie"
    toc_heading: str = "Table des matières"
    list_of_figures_heading: str = "Liste des figures"
    list_of_tables_heading: str = "Liste des tableaux"

    #: Language of the generated headings, used for the French defaults.
    locale: str = "fr"

    @property
    def pdf_font_names(self) -> tuple[str, str, str, str]:
        return PDF_FONTS.get(self.font_family, PDF_FONTS["times"])

    @property
    def docx_font_name(self) -> str:
        return DOCX_FONTS.get(self.font_family, DOCX_FONTS["times"])

    def page_dimensions(self) -> tuple[float, float]:
        base = PAGE_SIZES.get(self.page_size, PAGE_SIZES["a4"])
        if self.orientation == "landscape":
            return base[1], base[0]
        return base


def build_options(payload: dict[str, Any] | None) -> ExportOptions:
    """Validate a raw request into :class:`ExportOptions`.

    Unknown keys are ignored rather than rejected, so a client from a future version still
    works; every recognised key is clamped to a safe range.
    """
    data = payload or {}
    options = ExportOptions()

    page_size = str(data.get("page_size") or options.page_size).lower()
    if page_size not in PAGE_SIZES:
        raise ExportOptionError(f"Format de page inconnu : {page_size}.")
    options.page_size = page_size

    orientation = str(data.get("orientation") or options.orientation).lower()
    if orientation not in {"portrait", "landscape"}:
        raise ExportOptionError("Orientation doit être portrait ou landscape.")
    options.orientation = orientation

    options.margin_top = _clamp(
        float(data.get("margin_top", options.margin_top)), 0.5, 8.0, "Marge haute"
    )
    options.margin_bottom = _clamp(
        float(data.get("margin_bottom", options.margin_bottom)), 0.5, 8.0, "Marge basse"
    )
    options.margin_left = _clamp(
        float(data.get("margin_left", options.margin_left)), 0.5, 8.0, "Marge gauche"
    )
    options.margin_right = _clamp(
        float(data.get("margin_right", options.margin_right)), 0.5, 8.0, "Marge droite"
    )

    font_family = str(data.get("font_family") or options.font_family).lower()
    if font_family not in PDF_FONTS:
        raise ExportOptionError(f"Police inconnue : {font_family}.")
    options.font_family = font_family

    options.font_size = _clamp(
        float(data.get("font_size", options.font_size)), 6.0, 24.0, "Taille de police"
    )
    options.line_spacing = _clamp(
        float(data.get("line_spacing", options.line_spacing)), 1.0, 3.0, "Interligne"
    )
    options.first_line_indent = _clamp(
        float(data.get("first_line_indent", options.first_line_indent)),
        0.0,
        5.0,
        "Retrait de paragraphe",
    )
    options.paragraph_space_after = _clamp(
        float(data.get("paragraph_space_after", options.paragraph_space_after)),
        0.0,
        5.0,
        "Espace après paragraphe",
    )
    alignment = str(data.get("paragraph_alignment") or options.paragraph_alignment).lower()
    if alignment not in ALIGNMENTS:
        raise ExportOptionError(f"Alignement inconnu : {alignment}.")
    options.paragraph_alignment = alignment

    for name in (
        "include_cover",
        "include_toc",
        "include_list_of_figures",
        "include_list_of_tables",
        "include_bibliography",
        "include_annexes",
        "include_page_numbers",
        "roman_front_matter",
        "show_running_head",
        "number_headings",
        "number_figures",
        "number_tables",
        "number_equations",
        "embed_remote_images",
    ):
        if name in data and data[name] is not None:
            setattr(options, name, bool(data[name]))

    # A header or footer may be cleared with an empty string, hence the distinction.
    for name in ("header_text", "footer_text"):
        if name in data and data[name] is not None:
            text = str(data[name]).strip()
            if len(text) > 300:
                raise ExportOptionError(f"{name} est trop long.")
            setattr(options, name, text or None)

    for name in (
        "bibliography_heading",
        "toc_heading",
        "list_of_figures_heading",
        "list_of_tables_heading",
    ):
        if name in data and data[name] is not None:
            text = str(data[name]).strip()
            if len(text) > 300:
                raise ExportOptionError(f"{name} est trop long.")
            if text:
                setattr(options, name, text)

    return options


#: The format catalogue offered to the interface.
EXPORT_FORMATS = {
    "pdf": {"label": "PDF", "extension": "pdf", "media_type": "application/pdf"},
    "docx": {
        "label": "Word (DOCX)",
        "extension": "docx",
        "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    },
}

#: Bound on the size of a generated document, so a pathological memoir cannot exhaust memory.
MAX_OUTPUT_BYTES = 200 * 1024 * 1024


@dataclass(slots=True)
class ExportGuard:
    """Counters enforced while building, so a runaway document fails loudly."""

    blocks: int = 0
    characters: int = 0
    warnings: list[str] = field(default_factory=list)

    def add_block(self, text: str = "") -> None:
        self.blocks += 1
        if self.blocks > MAX_BLOCKS:
            raise ExportOptionError(
                f"Document trop volumineux : plus de {MAX_BLOCKS} blocs."
            )

    def add_text(self, text: str) -> None:
        self.characters += len(text)
        if self.characters > MAX_BLOCK_CHARS:
            raise ExportOptionError(
                f"Document trop volumineux : plus de {MAX_BLOCK_CHARS} caractères."
            )

    def warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)


__all__ = [
    "ALIGNMENTS",
    "DOCX_FONTS",
    "EXPORT_FORMATS",
    "MAX_BLOCKS",
    "MAX_BLOCK_CHARS",
    "MAX_OUTPUT_BYTES",
    "MAX_SECTIONS",
    "PAGE_SIZES",
    "PDF_FONTS",
    "ExportGuard",
    "ExportOptionError",
    "ExportOptions",
    "build_options",
]
