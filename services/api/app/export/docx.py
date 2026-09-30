"""DOCX rendering, with python-docx.

The renderer walks the same neutral blocks as the PDF renderer and reads the same citation
strings, so a memoir exported twice produces two files with the same content. The output is a
real Word document: headings use the built-in ``Heading N`` styles so the navigation pane and
an automatic table of contents work, lists are real lists, tables are real tables, and the
metadata is written into the document properties.

Page numbering, headers and footers are added through the WordprocessingML field codes,
because python-docx has no high-level API for them.
"""

from __future__ import annotations

from io import BytesIO
from typing import Any

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from app.export.blocks import (
    BibliographyBlock,
    Block,
    BlockKind,
    CitationBlock,
    CoverBlock,
    DocumentModel,
    FigureBlock,
    IndexBlock,
    Span,
    TableBlock,
    TocBlock,
)
from app.export.images import image_size
from app.export.options import ExportOptions

ALIGNMENTS = {
    "left": WD_ALIGN_PARAGRAPH.LEFT,
    "center": WD_ALIGN_PARAGRAPH.CENTER,
    "right": WD_ALIGN_PARAGRAPH.RIGHT,
    "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
}

LIST_BULLET = "List Bullet"
LIST_NUMBER = "List Number"

#: Heading level in Word for a block level, clamped to what Word offers.
def _heading_style(level: int) -> str:
    return f"Heading {min(max(level, 1), 9)}"


def _set_cell_background(cell: Any, colour: str) -> None:
    shading = OxmlElement("w:shd")
    shading.set(qn("w:val"), "clear")
    shading.set(qn("w:color"), "auto")
    shading.set(qn("w:fill"), colour.lstrip("#") or "F2F2F2")
    cell._tc.get_or_add_tcPr().append(shading)


def _add_field(paragraph: Any, instruction: str) -> None:
    """Insert a Word field such as ``PAGE`` or ``NUMPAGES``."""
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = instruction
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.append(begin)
    run._r.append(instr)
    run._r.append(end)


def _add_spans(paragraph: Any, spans: tuple[Span, ...], options: ExportOptions) -> None:
    """Write the spans of a block into a paragraph, applying the marks."""
    for span in spans:
        if not span.text:
            continue
        if "\n" in span.text:
            pieces = span.text.split("\n")
            for index, piece in enumerate(pieces):
                if index:
                    paragraph.add_run().add_break()
                _add_run(paragraph, piece, span, options)
            continue
        _add_run(paragraph, span.text, span, options)


def _add_run(paragraph: Any, text: str, span: Span, options: ExportOptions) -> None:
    run = paragraph.add_run(text)
    run.font.name = "Courier New" if span.code else options.docx_font_name
    if span.code:
        run.font.size = Pt(max(options.font_size - 1.5, 7.0))
    run.bold = span.bold
    run.italic = span.italic
    run.underline = span.underline
    if span.strike:
        run.font.strike = True
    if span.superscript:
        run.font.superscript = True
    if span.subscript:
        run.font.subscript = True
    if span.small:
        run.font.size = Pt(max(options.font_size - 2, 7.0))
    if span.href:
        # The relationship is added so the link is clickable, not merely blue text.
        try:
            relation_id = paragraph.part.relate_to(
                span.href,
                "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
                is_external=True,
            )
            element = OxmlElement("w:hyperlink")
            element.set(qn("r:id"), relation_id)
            paragraph._p.append(element)
        except Exception:
            # A relationship failure must not lose the text.
            pass


def _configure_styles(document: Any, options: ExportOptions) -> None:
    """Apply the chosen typography to the Normal and Heading styles."""
    normal = document.styles["Normal"]
    normal.font.name = options.docx_font_name
    normal.font.size = Pt(options.font_size)
    paragraph_format = normal.paragraph_format
    paragraph_format.line_spacing = options.line_spacing
    paragraph_format.alignment = ALIGNMENTS.get(
        options.paragraph_alignment, WD_ALIGN_PARAGRAPH.JUSTIFY
    )
    paragraph_format.first_line_indent = Cm(options.first_line_indent)
    paragraph_format.space_after = Pt(options.paragraph_space_after * 28.35)
    for level in range(1, 7):
        try:
            style = document.styles[f"Heading {level}"]
        except KeyError:
            continue
        style.font.name = options.docx_font_name
        style.font.size = Pt(max(options.font_size + (5 - level) * 1.2, options.font_size))
        style.font.bold = True
        style.font.color.rgb = RGBColor(0x1A, 0x23, 0x2E)
        style.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
        style.paragraph_format.first_line_indent = Cm(0)
        style.paragraph_format.keep_with_next = True


def _configure_page(document: Any, options: ExportOptions) -> None:
    """Page size, orientation and margins."""
    for section in document.sections:
        width, height = options.page_dimensions()
        section.page_width = Pt(width)
        section.page_height = Pt(height)
        if options.orientation == "landscape":
            section.orientation = WD_ORIENT.LANDSCAPE
        section.top_margin = Cm(options.margin_top)
        section.bottom_margin = Cm(options.margin_bottom)
        section.left_margin = Cm(options.margin_left)
        section.right_margin = Cm(options.margin_right)
        # The cover is its own section so it can have no header and no page number.
        section.different_first_page_header_footer = True


def _configure_header_footer(document: Any, options: ExportOptions) -> None:
    """Running head and page number, added as Word field codes."""
    for section in document.sections:
        header = section.header
        paragraph = header.paragraphs[0] if header.paragraphs else header.add_paragraph()
        paragraph.text = options.header_text or ""
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for run in paragraph.runs:
            run.font.size = Pt(9)
            run.font.name = options.docx_font_name
        footer = section.footer
        paragraph = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        if options.include_page_numbers:
            run = paragraph.add_run()
            run.font.size = Pt(9)
            _add_field(paragraph, "PAGE")
        if options.footer_text:
            paragraph.add_run(f"  ·  {options.footer_text}").font.size = Pt(9)


def _add_cover(document: Any, cover: CoverBlock, options: ExportOptions) -> None:
    """The cover, then a page break. Nothing is invented."""
    for _ in range(3):
        document.add_paragraph()
    if cover.logo_data:
        try:
            document.add_picture(BytesIO(cover.logo_data), width=Cm(3.0))
            document.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
        except Exception:
            pass
    _centered(document, cover.institution.upper() if cover.institution else None, 11, bold=False)
    _centered(document, cover.level, 13, bold=True)
    _centered(document, cover.thesis_type, 14, bold=False, italic=True)
    document.add_paragraph()
    _centered(document, cover.title, 20, bold=True)
    _centered(document, cover.subtitle, 13, italic=True)
    document.add_paragraph()
    _centered(document, "Présenté par", 10)
    _centered(document, cover.author, 13, bold=True)
    _centered(document, "Sous la direction de", 10)
    _centered(document, cover.supervisor, 13, bold=True)
    _centered(document, cover.academic_year, 12, bold=True)
    if cover.keywords:
        document.add_paragraph()
        _centered(document, "Mots-clés : " + ", ".join(cover.keywords), 10)
    document.add_page_break()
    if cover.problem_statement or cover.general_objective:
        heading = document.add_paragraph("Problématique", style=_heading_style(1))
        heading.paragraph_format.first_line_indent = Cm(0)
        if cover.problem_statement:
            _body_paragraph(document, Span(cover.problem_statement), options)
        if cover.general_objective:
            _body_paragraph(document, Span("Objectif général", bold=True), options, indent=False)
            _body_paragraph(document, Span(cover.general_objective), options)
        if cover.specific_objectives:
            _body_paragraph(
            document, Span("Objectifs spécifiques", bold=True), options, indent=False
        )
            for objective in cover.specific_objectives:
                paragraph = document.add_paragraph(objective, style=LIST_BULLET)
                paragraph.paragraph_format.first_line_indent = Cm(0)
        document.add_page_break()


def _centered(
    document: Any, text: str | None, size: float, *, bold: bool = False, italic: bool = False
) -> None:
    if not text:
        return
    paragraph = document.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.paragraph_format.first_line_indent = Cm(0)
    run = paragraph.add_run(text)
    run.bold = bold
    run.italic = italic
    run.font.size = Pt(size)


def _body_paragraph(
    document: Any, span: Span, options: ExportOptions, *, indent: bool = True
) -> Any:
    paragraph = document.add_paragraph()
    if not indent:
        paragraph.paragraph_format.first_line_indent = Cm(0)
    _add_spans(paragraph, (span,), options)
    return paragraph


def _add_toc(document: Any, block: TocBlock, options: ExportOptions) -> None:
    """A real Word table of contents, plus a readable fallback listing.

    Word only fills the field when the document is opened and updated, so the section list is
    also written out: the document is readable even before Word refreshes the field.
    """
    heading = document.add_paragraph(block.title, style=_heading_style(1))
    heading.paragraph_format.first_line_indent = Cm(0)
    field_paragraph = document.add_paragraph()
    field_paragraph.paragraph_format.first_line_indent = Cm(0)
    _add_field(field_paragraph, r'TOC \o "1-3" \h \z \u')
    if block.entries:
        document.add_paragraph()
        for entry in block.entries:
            paragraph = document.add_paragraph()
            paragraph.paragraph_format.first_line_indent = Cm(0)
            paragraph.paragraph_format.left_indent = Cm(0.6 * (entry.level - 1))
            run = paragraph.add_run(entry.text)
            run.font.name = options.docx_font_name
            run.bold = entry.level == 1
    document.add_page_break()


def _add_index(document: Any, block: IndexBlock, options: ExportOptions) -> None:
    heading = document.add_paragraph(block.title, style=_heading_style(1))
    heading.paragraph_format.first_line_indent = Cm(0)
    for label, caption in block.entries:
        paragraph = document.add_paragraph()
        paragraph.paragraph_format.first_line_indent = Cm(0)
        run = paragraph.add_run(f"{label} — {caption}")
        run.font.name = options.docx_font_name
    document.add_page_break()


def _add_bibliography(document: Any, block: BibliographyBlock, options: ExportOptions) -> None:
    heading = document.add_paragraph(options.bibliography_heading, style=_heading_style(1))
    heading.paragraph_format.first_line_indent = Cm(0)
    if not block.lines:
        paragraph = document.add_paragraph("Aucune référence citée dans ce document.")
        paragraph.paragraph_format.first_line_indent = Cm(0)
        return
    for line in block.lines:
        paragraph = document.add_paragraph()
        # A hanging indent, as a bibliography requires.
        paragraph.paragraph_format.first_line_indent = Cm(-0.6)
        paragraph.paragraph_format.left_indent = Cm(0.6)
        paragraph.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
        run = paragraph.add_run(line)
        run.font.name = options.docx_font_name
        run.font.size = Pt(options.font_size)


def _add_table(document: Any, block: TableBlock, options: ExportOptions) -> None:
    if block.number:
        caption = document.add_paragraph()
        caption.paragraph_format.first_line_indent = Cm(0)
        run = caption.add_run(f"Tableau {block.number}")
        run.bold = True
        run.font.size = Pt(options.font_size - 1)
    if not block.rows:
        return
    column_count = max(len(row) for row in block.rows)
    table = document.add_table(rows=len(block.rows), cols=column_count)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    for row_index, row in enumerate(block.rows):
        for column_index in range(column_count):
            cell = table.cell(row_index, column_index)
            cell.paragraphs[0].text = ""
            source = row[column_index] if column_index < len(row) else None
            if source is None:
                continue
            for inner in source.blocks:
                if inner.kind == BlockKind.PARAGRAPH and inner.spans:
                    _add_spans(cell.paragraphs[0], inner.spans, options)
                elif inner.text:
                    cell.paragraphs[0].add_run(inner.text)
            if source.is_header:
                for run in cell.paragraphs[0].runs:
                    run.bold = True
                _set_cell_background(cell, "#EFEFEF")
    for row in table.rows:
        for cell in row.cells:
            for paragraph in cell.paragraphs:
                paragraph.paragraph_format.first_line_indent = Cm(0)
                for run in paragraph.runs:
                    run.font.size = Pt(max(options.font_size - 1.5, 7.0))
    document.add_paragraph()


def _add_figure(document: Any, block: FigureBlock, options: ExportOptions) -> None:
    if block.data:
        try:
            size = image_size(block.data)
            width = Cm(block.width_cm) if block.width_cm else Cm(12.0)
            if size and size[0] > 0:
                ratio = size[1] / size[0]
                if width.cm * ratio > 20:
                    width = Cm(20.0 / ratio)
            document.add_picture(BytesIO(block.data), width=width)
            document.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
        except Exception:
            _add_figure_placeholder(document, block, options)
    else:
        _add_figure_placeholder(document, block, options)
    caption = f"Figure {block.number} — {block.caption}" if block.caption else (
        f"Figure {block.number}" if block.number else ""
    )
    if caption:
        paragraph = document.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        paragraph.paragraph_format.first_line_indent = Cm(0)
        run = paragraph.add_run(caption)
        run.italic = True
        run.font.size = Pt(max(options.font_size - 2, 8.0))


def _add_figure_placeholder(document: Any, block: FigureBlock, options: ExportOptions) -> None:
    """A visible note, so a missing image is never confused with an omission."""
    paragraph = document.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.paragraph_format.first_line_indent = Cm(0)
    label = f"Figure {block.number} indisponible"
    reason = block.unavailable_reason or "image non fournie"
    run = paragraph.add_run(f"{label} — {reason}")
    run.italic = True
    run.font.color.rgb = RGBColor(0x66, 0x66, 0x66)
    run.font.size = Pt(max(options.font_size - 2, 8.0))


def _add_citation(document: Any, block: CitationBlock, options: ExportOptions) -> None:
    paragraph = document.add_paragraph()
    paragraph.paragraph_format.first_line_indent = Cm(0)
    _add_spans(paragraph, block.spans, options)
    if block.is_orphaned:
        note = paragraph.add_run(
            "  [Citation invalide : la référence citée a été supprimée.]"
        )
        note.font.color.rgb = RGBColor(0x8C, 0x2F, 0x2F)
        note.font.size = Pt(max(options.font_size - 2, 7.0))
    elif block.warnings:
        note = paragraph.add_run("  [" + " · ".join(block.warnings) + "]")
        note.font.color.rgb = RGBColor(0x8A, 0x5A, 0x00)
        note.font.size = Pt(max(options.font_size - 2, 7.0))
    elif block.is_pending:
        note = paragraph.add_run("  [Citation non enregistrée]")
        note.font.color.rgb = RGBColor(0x8A, 0x5A, 0x00)
        note.font.size = Pt(max(options.font_size - 2, 7.0))


def _add_block(document: Any, block: Block, options: ExportOptions) -> None:
    """Write one block, recursing into the containers."""
    if block.kind in {BlockKind.PAGE_BREAK, BlockKind.HORIZONTAL_RULE}:
        if block.kind == BlockKind.PAGE_BREAK:
            document.add_page_break()
        return
    if block.kind in {BlockKind.HEADING, BlockKind.HEADING_UNNUMBERED}:
        paragraph = document.add_paragraph(style=_heading_style(block.level))
        _add_spans(paragraph, block.spans, options)
        return
    if block.kind == BlockKind.PARAGRAPH:
        paragraph = document.add_paragraph()
        paragraph.alignment = ALIGNMENTS.get(block.alignment, WD_ALIGN_PARAGRAPH.JUSTIFY)
        if block.indent_first_line is not None:
            paragraph.paragraph_format.first_line_indent = Cm(block.indent_first_line)
        if block.indent_left:
            paragraph.paragraph_format.left_indent = Cm(block.indent_left)
        _add_spans(paragraph, block.spans, options)
        return
    if block.kind == BlockKind.CITATION:
        _add_citation(document, block, options)
        return
    if block.kind == BlockKind.EQUATION:
        value = getattr(block, "value", "") or block.text
        number = getattr(block, "number", None)
        paragraph = document.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        paragraph.paragraph_format.first_line_indent = Cm(0)
        run = paragraph.add_run(f"{value} ({number})" if number else value)
        run.italic = True
        return
    if block.kind == BlockKind.FIGURE:
        _add_figure(document, block, options)
        return
    if block.kind == BlockKind.TABLE:
        _add_table(document, block, options)
        return
    if block.kind in {BlockKind.BULLET_LIST, BlockKind.ORDERED_LIST}:
        style = LIST_NUMBER if block.kind == BlockKind.ORDERED_LIST else LIST_BULLET
        for item in getattr(block, "items", []):
            first = True
            for sub in item:
                if sub.kind == BlockKind.PARAGRAPH and sub.spans:
                    paragraph = (
                        document.add_paragraph(style=style)
                        if first
                        else document.add_paragraph()
                    )
                    paragraph.paragraph_format.first_line_indent = Cm(0)
                    _add_spans(paragraph, sub.spans, options)
                    first = False
                else:
                    _add_block(document, sub, options)
        return
    if block.kind == BlockKind.QUOTE:
        for sub in block.inner:
            _add_block(document, sub, options)
        return
    if block.kind == BlockKind.CODE:
        paragraph = document.add_paragraph()
        paragraph.paragraph_format.first_line_indent = Cm(0)
        run = paragraph.add_run(block.text)
        run.font.name = "Courier New"
        run.font.size = Pt(9)
        return
    if block.kind == BlockKind.PLACEHOLDER:
        paragraph = document.add_paragraph()
        _add_spans(paragraph, block.spans, options)
        return
    if block.kind == BlockKind.BIBLIOGRAPHY:
        _add_bibliography(document, block, options)  # type: ignore[arg-type]
        return
    if block.kind == BlockKind.TOC:
        _add_toc(document, block, options)  # type: ignore[arg-type]
        return
    if block.kind in {BlockKind.LIST_OF_FIGURES, BlockKind.LIST_OF_TABLES}:
        _add_index(document, block, options)  # type: ignore[arg-type]
        return
    if block.kind == BlockKind.COVER:
        _add_cover(document, block, options)  # type: ignore[arg-type]
        return
    for sub in block.inner:
        _add_block(document, sub, options)


def _write_metadata(document: Any, model: DocumentModel) -> None:
    """Write the academic metadata into the document properties."""
    properties = document.core_properties
    properties.title = model.project_title
    cover = model.cover
    properties.author = (cover.author if cover else "") or ""
    properties.subject = model.project_title
    properties.comments = f"Export Academic Memo Assistant · style {model.style_label}"
    if cover and cover.keywords:
        properties.keywords = ", ".join(cover.keywords)
    if cover and cover.institution:
        properties.category = cover.institution
    if cover and cover.academic_year:
        properties.comments = (
            f"Annee universitaire {cover.academic_year} · style {model.style_label}"
        )


def render_docx(model: DocumentModel, options: ExportOptions) -> bytes:
    """Render the document model to DOCX bytes."""
    document = Document()
    _configure_styles(document, options)
    _configure_page(document, options)
    _configure_header_footer(document, options)
    _write_metadata(document, model)

    if model.cover is not None:
        _add_cover(document, model.cover, options)

    for block in model.blocks:
        _add_block(document, block, options)

    if model.bibliography is not None:
        document.add_page_break()
        _add_bibliography(document, model.bibliography, options)

    for block in model.annexes:
        _add_block(document, block, options)

    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


__all__ = ["LIST_BULLET", "LIST_NUMBER", "render_docx"]
