"""PDF rendering, with reportlab.

The renderer walks the neutral blocks produced by :mod:`app.export.service` and never touches
the database. Nothing is re-derived here: the citation strings, the bibliography lines and the
numbering all arrive already computed by the stage 10 engine, so the PDF and the DOCX cannot
disagree.

Academic conventions implemented, because they are what makes a document usable as a thesis:

* the cover page carries no page number, the front matter uses roman numerals and the body
  arabic ones, restarting at 1 at the first chapter;
* headings are numbered (``I.``, ``1.1``) and appear in the PDF outline so the reader can
  navigate;
* a table of contents is generated from the real sections, with page numbers resolved in a
  second pass;
* figures and tables are captioned and listed;
* a citation whose reference is missing prints an explicit warning instead of a plausible
  looking author.
"""

from __future__ import annotations

from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    KeepTogether,
    ListFlowable,
    ListItem,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    TableStyle,
)
from reportlab.platypus import (
    Image as FlowImage,
)
from reportlab.platypus import (
    Table as FlowTable,
)

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
from app.export.options import ExportOptions

#: Colour of the academic grey used for rules and header text.
GREY = colors.HexColor("#444444")
#: Warning colour, used for a citation whose metadata is incomplete.
AMBER = colors.HexColor("#8A5A00")
LIGHT_GREY = colors.HexColor("#999999")

HEADING_SIZES = {1: 17.0, 2: 15.0, 3: 13.5, 4: 12.5, 5: 12.0, 6: 12.0}


def _style(
    name: str,
    font: str,
    *,
    size: float = 11.0,
    leading: float | None = None,
    align: int = TA_LEFT,
    colour: colors.Color | None = None,
    first_indent: float = 0.0,
    left_indent: float = 0.0,
    before: float = 0.0,
    after: float = 0.0,
    keep: bool = False,
) -> ParagraphStyle:
    """A paragraph style. The parameters are the ones this renderer actually varies."""
    extra: dict[str, Any] = {}
    if colour is not None:
        # reportlab rejects an explicit None for textColor, so it is only set when wanted.
        extra["textColor"] = colour
    return ParagraphStyle(
        name,
        fontName=font,
        fontSize=size,
        leading=leading if leading is not None else size * 1.4,
        alignment=align,
        firstLineIndent=first_indent,
        leftIndent=left_indent,
        spaceBefore=before,
        spaceAfter=after,
        keepWithNext=keep,
        **extra,
    )


def _escape(text: str) -> str:
    """Escape the characters reportlab's mini-HTML parser treats as markup."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _spans_to_markup(spans: tuple[Span, ...], *, allow_links: bool = True) -> str:
    """Convert spans into reportlab inline markup."""
    parts: list[str] = []
    for span in spans:
        text = _escape(span.text)
        if not text:
            continue
        if span.code:
            text = f'<font face="Courier">{text}</font>'
        if span.bold:
            text = f"<b>{text}</b>"
        if span.italic:
            text = f"<i>{text}</i>"
        if span.underline:
            text = f"<u>{text}</u>"
        if span.strike:
            text = f"<strike>{text}</strike>"
        if span.superscript:
            text = f"<super>{text}</super>"
        if span.subscript:
            text = f"<sub>{text}</sub>"
        if span.href and allow_links:
            href = _escape(span.href)
            if href.lower().startswith(("http://", "https://", "mailto:")):
                text = f'<link href="{href}" color="#0B5FA5">{text}</link>'
        if span.citation is not None:
            text = _annotate_citation_markup(text, span.citation)
        parts.append(text)
    return "".join(parts) or "&nbsp;"


def _annotate_citation_markup(text: str, state: Any) -> str:
    """Make a doubtful citation visible without inventing anything about the reference."""
    if state.is_orphaned:
        return f'<font color="#8C2F2F" size="7">{text} [reference introuvable]</font>'
    if state.is_pending:
        return f'<font color="#8A5A00" size="7">{text} [citation non enregistr\u00e9e]</font>'
    if state.warnings:
        notes = _escape(" \u00b7 ".join(state.warnings))
        return f'{text}<font color="#8A5A00" size="7"> [{notes}]</font>'
    return text


def _style_for(block: Block, options: ExportOptions, base_font: str) -> ParagraphStyle:
    """Pick the paragraph style for a block, derived from the validated options."""
    if block.kind == BlockKind.HEADING:
        size = HEADING_SIZES.get(block.level, 12.0)
        return ParagraphStyle(
            f"h{block.level}",
            fontName=base_font,
            fontSize=size,
            leading=size * 1.35,
            spaceBefore=14 if block.level == 1 else 10,
            spaceAfter=8 if block.level == 1 else 6,
            alignment=TA_LEFT,
            keepWithNext=True,
        )
    alignment = {
        "left": TA_LEFT,
        "center": TA_CENTER,
        "right": TA_RIGHT,
        "justify": TA_JUSTIFY,
    }.get(block.alignment or options.paragraph_alignment, TA_JUSTIFY)
    first = (
        block.indent_first_line
        if block.indent_first_line is not None
        else options.first_line_indent
    )
    return ParagraphStyle(
        f"p-{block.kind.value}",
        fontName=base_font,
        fontSize=options.font_size,
        leading=options.font_size * options.line_spacing,
        spaceAfter=options.paragraph_space_after,
        alignment=alignment,
        firstLineIndent=first * cm if first else 0,
        leftIndent=block.indent_left * cm if block.indent_left else 0,
        allowWidows=1,
        allowOrphans=1,
    )


def _table_flowable(
    block: TableBlock, options: ExportOptions, base_font: str, width: float
) -> FlowTable | Paragraph:
    """Render a table, or a readable note when it cannot be laid out."""
    rows: list[list[Any]] = []
    if not block.rows:
        return Paragraph("Tableau vide.", ParagraphStyle("t", fontName=base_font, fontSize=9))
    column_count = max(len(row) for row in block.rows)
    cell_style = ParagraphStyle(
        "cell",
        fontName=base_font,
        fontSize=max(options.font_size - 1.5, 7.0),
        leading=max(options.font_size - 1.5, 7.0) * 1.2,
        alignment=TA_LEFT,
    )
    header_style = ParagraphStyle(
        "cell-head",
        parent=cell_style,
        fontName=base_font,
    )
    for index, row in enumerate(block.rows):
        line: list[Any] = []
        for column in range(column_count):
            cell = row[column] if column < len(row) else None
            if cell is None:
                line.append("")
                continue
            style = header_style if cell.is_header else cell_style
            content = "<br/>".join(
                _spans_to_markup(inner.spans) for inner in cell.blocks if inner.spans
            )
            line.append(Paragraph(content or "&nbsp;", style))
        rows.append(line)
    try:
        table = FlowTable(rows, repeatRows=block.header_rows, hAlign="LEFT")
    except Exception:
        return Paragraph(
            "Tableau non représentable dans le PDF.", ParagraphStyle("t", fontName=base_font)
        )
    commands: list[tuple] = [
        ("GRID", (0, 0), (-1, -1), 0.4, LIGHT_GREY),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    for index, row in enumerate(block.rows):
        if any(cell.background for cell in row):
            commands.append(
                ("BACKGROUND", (index, 0), (index, column_count - 1), colors.HexColor("#F2F2F2"))
            )
    if block.header_rows:
        commands.append(
            ("BACKGROUND", (0, 0), (-1, block.header_rows - 1), colors.HexColor("#EFEFEF"))
        )
    table.setStyle(TableStyle(commands))
    return table


def _figure_flowable(
    block: FigureBlock, options: ExportOptions, text_width: float
) -> list[Any]:
    """Render a figure, or a framed placeholder explaining why it is missing."""
    flowables: list[Any] = []
    available = min(text_width, (block.width_cm * cm) if block.width_cm else text_width)
    if block.data:
        try:
            from reportlab.lib.utils import ImageReader

            reader = ImageReader(BytesIO(block.data))
            intrinsic_width, intrinsic_height = reader.getSize()
            if intrinsic_width <= 0 or intrinsic_height <= 0:
                raise ValueError("dimensions nulles")
            height = available * (intrinsic_height / intrinsic_width)
            # A figure taller than a page would be silently clipped, so it is scaled down.
            max_height = 20 * cm
            if height > max_height:
                available *= max_height / height
                height = max_height
            flowables.append(FlowImage(BytesIO(block.data), width=available, height=height))
        except Exception:
            flowables.append(_figure_placeholder(block, options, available))
    else:
        flowables.append(_figure_placeholder(block, options, available))
    if block.caption or block.number:
        caption = f"Figure {block.number} — {block.caption}" if block.caption else (
            f"Figure {block.number}" if block.number else ""
        )
        style = ParagraphStyle(
            "caption",
            fontName=options.pdf_font_names[2],
            fontSize=max(options.font_size - 2, 8.0),
            leading=max(options.font_size - 2, 8.0) * 1.25,
            alignment=TA_CENTER,
            textColor=GREY,
        )
        flowables.append(Paragraph(_escape(caption), style))
    return flowables


def _figure_placeholder(
    block: FigureBlock, options: ExportOptions, width: float
) -> FlowTable:
    """A visible placeholder, so a missing image is never confused with a blank space."""
    label = f"Figure {block.number} indisponible"
    reason = block.unavailable_reason or "image non fournie"
    cell_style = ParagraphStyle(
        "ph",
        fontName=options.pdf_font_names[2],
        fontSize=max(options.font_size - 2, 8.0),
        leading=max(options.font_size - 2, 8.0) * 1.3,
        alignment=TA_CENTER,
        textColor=GREY,
    )
    table = FlowTable(
        [[Paragraph(f"<b>{_escape(label)}</b><br/>{_escape(reason)}", cell_style)]],
        colWidths=[width],
    )
    table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.5, LIGHT_GREY),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F5F5F5")),
                ("TOPPADDING", (0, 0), (-1, -1), 18),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 18),
            ]
        )
    )
    return table


def _cover_flowables(cover: CoverBlock, options: ExportOptions) -> list[Any]:
    """The cover page. Every line comes from a project field; none is invented."""
    regular, bold, italic, _ = options.pdf_font_names
    title_style = ParagraphStyle(
        "cover-title",
        fontName=bold,
        fontSize=22,
        leading=28,
        alignment=TA_CENTER,
        spaceAfter=18,
    )
    subtitle_style = ParagraphStyle(
        "cover-sub",
        fontName=italic,
        fontSize=14,
        leading=18,
        alignment=TA_CENTER,
        textColor=GREY,
        spaceAfter=10,
    )
    label_style = ParagraphStyle(
        "cover-label",
        fontName=regular,
        fontSize=9,
        leading=12,
        alignment=TA_CENTER,
        textColor=LIGHT_GREY,
        spaceAfter=2,
    )
    value_style = ParagraphStyle(
        "cover-value",
        fontName=bold,
        fontSize=13,
        leading=18,
        alignment=TA_CENTER,
        spaceAfter=12,
    )
    flowables: list[Any] = [Spacer(1, 3.0 * cm)]
    if cover.logo_data:
        try:
            from reportlab.lib.utils import ImageReader

            reader = ImageReader(BytesIO(cover.logo_data))
            width, height = reader.getSize()
            if width > 0:
                target = 3.0 * cm
                flowables.append(
                    FlowImage(
                        BytesIO(cover.logo_data),
                        width=target,
                        height=target * height / width,
                    )
                )
                flowables.append(Spacer(1, 0.6 * cm))
        except Exception:
            pass
    if cover.institution:
        flowables.append(Paragraph(_escape(cover.institution.upper()), label_style))
    if cover.level:
        flowables.append(Paragraph(_escape(cover.level), value_style))
    if cover.thesis_type:
        flowables.append(Paragraph(_escape(cover.thesis_type), subtitle_style))
    flowables.append(Spacer(1, 1.0 * cm))
    flowables.append(Paragraph(_escape(cover.title), title_style))
    if cover.subtitle:
        flowables.append(Paragraph(_escape(cover.subtitle), subtitle_style))
    flowables.append(Spacer(1, 1.2 * cm))
    if cover.author:
        flowables.append(Paragraph("Présenté par", label_style))
        flowables.append(Paragraph(_escape(cover.author), value_style))
    if cover.supervisor:
        flowables.append(Paragraph("Sous la direction de", label_style))
        flowables.append(Paragraph(_escape(cover.supervisor), value_style))
    if cover.academic_year:
        flowables.append(Spacer(1, 0.5 * cm))
        flowables.append(Paragraph(_escape(cover.academic_year), value_style))
    if cover.keywords:
        flowables.append(Spacer(1, 0.8 * cm))
        flowables.append(
            Paragraph(
                "<b>Mots-clés :</b> " + _escape(", ".join(cover.keywords)),
                ParagraphStyle(
                    "kw", fontName=regular, fontSize=10, leading=14, alignment=TA_CENTER
                ),
            )
        )
    if cover.problem_statement or cover.general_objective:
        flowables.append(PageBreak())
        flowables.append(
            Paragraph(
                "Problématique",
                ParagraphStyle("h", fontName=bold, fontSize=14, leading=18, spaceAfter=8),
            )
        )
        if cover.problem_statement:
            flowables.append(
                Paragraph(
                    _escape(cover.problem_statement),
                    _style("cover-p", regular, size=11, leading=16, align=TA_JUSTIFY),
                )
            )
        if cover.general_objective:
            flowables.append(Spacer(1, 0.4 * cm))
            flowables.append(
                Paragraph(
                    "Objectif général",
                    ParagraphStyle("l", fontName=bold, fontSize=11, leading=15, spaceAfter=4),
                )
            )
            flowables.append(
                Paragraph(
                    _escape(cover.general_objective),
                    _style("cover-p", regular, size=11, leading=16, align=TA_JUSTIFY),
                )
            )
        if cover.specific_objectives:
            flowables.append(Spacer(1, 0.4 * cm))
            flowables.append(
                Paragraph(
                    "Objectifs spécifiques",
                    ParagraphStyle("l", fontName=bold, fontSize=11, leading=15, spaceAfter=4),
                )
            )
            flowables.append(
                ListFlowable(
                    [
                        ListItem(
                            Paragraph(
                                _escape(objective),
                                ParagraphStyle("p", fontName=regular, fontSize=11, leading=16),
                            ),
                            bulletText="\u2022",
                        )
                        for objective in cover.specific_objectives
                    ],
                    leftIndent=18,
                )
            )
    # Exactly one page break closes the cover, whether or not it carries the problematics.
    flowables.append(PageBreak())
    return flowables


class _Flowable(Flowable):
    """A zero-size marker whose only effect is to run code at draw time.

    The running head and the start of the body must be known when a page is *drawn*, not when
    the story is assembled: the whole story exists before the first page is laid out, so a
    plain assignment during assembly would leave every page showing the last heading.
    """

    def __init__(self, action: Any) -> None:
        super().__init__()
        self.action = action
        self.width = 0
        self.height = 0

    def wrap(self, *args: Any, **kwargs: Any) -> tuple[float, float]:
        return 0.0, 0.0

    def draw(self) -> None:
        self.action()


def _mark_body_start(state: dict[str, Any]) -> Any:
    """A one-shot marker recording the last front-matter page."""

    def action() -> None:
        if state["body_marked"]:
            return
        state["body_marked"] = True
        state["body_start"] = int(state["page"])

    return action


def render_pdf(model: DocumentModel, options: ExportOptions) -> bytes:
    """Render the document model to PDF bytes."""
    buffer = BytesIO()
    width, height = options.page_dimensions()
    frame = Frame(
        options.margin_left * cm,
        options.margin_bottom * cm,
        width - (options.margin_left + options.margin_right) * cm,
        height - (options.margin_top + options.margin_bottom) * cm,
        id="body",
        leftPadding=0,
        rightPadding=0,
        topPadding=0,
        bottomPadding=0,
    )
    regular, bold, italic, bold_italic = options.pdf_font_names

    # ``body_marked`` makes the start-of-body marker one-shot: a page break inside the body
    # must not move the numbering back to the body, or the restart would happen twice.
    state: dict[str, Any] = {"page": 0, "body_start": 0, "running_head": "", "body_marked": False}

    def on_page(pdf: pdf_canvas.Canvas, _index: int) -> None:
        state["page"] += 1
        pdf.saveState()
        pdf.setFont(regular, 9)
        pdf.setFillColor(LIGHT_GREY)
        text_width = width - (options.margin_left + options.margin_right) * cm
        if options.include_page_numbers and state["page"] > 1:
            label = _page_label(state["page"], state["body_start"], options)
            pdf.drawCentredString(width / 2, options.margin_bottom * cm - 12, label)
        if options.show_running_head and state["page"] > 1 and state["running_head"]:
            pdf.drawString(
                options.margin_left * cm,
                height - options.margin_top * cm + 10,
                _truncate(state["running_head"], regular, pdf, text_width),
            )
        if options.footer_text and state["page"] > 1:
            pdf.drawCentredString(width / 2, options.margin_bottom * cm - 24, options.footer_text)
        pdf.restoreState()

    document = BaseDocTemplate(
        buffer,
        pagesize=(width, height),
        title=model.project_title,
        author=_author_of(model),
        subject=model.project_title,
        leftMargin=options.margin_left * cm,
        rightMargin=options.margin_right * cm,
        topMargin=options.margin_top * cm,
        bottomMargin=options.margin_bottom * cm,
    )
    document.addPageTemplates([PageTemplate(id="thesis", frames=[frame], onPage=on_page)])

    text_width = document.width
    story: list[Any] = []
    if model.cover is not None:
        story.extend(_cover_flowables(model.cover, options))
    story.extend(_front_matter(model, options, regular, text_width, state))
    # The marker sits before the page break, so it draws while the last front-matter page is
    # still being written. The page callback of that page has already run, which is what makes
    # the restart land on the right number.
    story.append(_Flowable(_mark_body_start(state)))
    story.append(PageBreak())
    for block in model.blocks:
        if block.kind == BlockKind.PAGE_BREAK:
            story.append(_Flowable(_mark_body_start(state)))
            story.append(PageBreak())
            continue
        story.extend(_block_flowables(block, options, regular, bold, text_width, state, model))

    if model.bibliography is not None:
        story.append(PageBreak())
        story.extend(
            _bibliography_flowables(model.bibliography, options, regular, bold, text_width)
        )
    for block in model.annexes:
        if block.kind == BlockKind.PAGE_BREAK:
            story.append(PageBreak())
            continue
        story.extend(_block_flowables(block, options, regular, bold, text_width, state, model))

    document.build(story)
    return buffer.getvalue()


def _page_label(page: int, body_start: int, options: ExportOptions) -> str:
    """Front matter in roman numerals, body in arabic starting at 1.

    ``body_start`` is the last page of the front matter, so the first body page is
    ``body_start + 1`` and shows 1.
    """
    if not body_start or page <= body_start:
        return _roman(page) if options.roman_front_matter else str(page)
    return str(page - body_start)


def _roman(number: int) -> str:
    values = (
        (1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"),
        (50, "l"), (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i"),
    )
    result = []
    remaining = max(number, 1)
    for value, symbol in values:
        while remaining >= value:
            result.append(symbol)
            remaining -= value
    return "".join(result)


def _truncate(text: str, font: str, pdf: pdf_canvas.Canvas, max_width: float) -> str:
    if pdf.stringWidth(text, font, 9) <= max_width:
        return text
    trimmed = text
    while trimmed and pdf.stringWidth(trimmed + "…", font, 9) > max_width:
        trimmed = trimmed[:-1]
    return f"{trimmed}…"


def _author_of(model: DocumentModel) -> str:
    return model.cover.author if model.cover and model.cover.author else ""


def _front_matter(
    model: DocumentModel,
    options: ExportOptions,
    regular: str,
    text_width: float,
    state: dict[str, int | str],
) -> list[Any]:
    """The table of contents, the list of figures and the list of tables."""
    flowables: list[Any] = []
    for block in model.blocks:
        if isinstance(block, TocBlock):
            flowables.extend(_toc_flowables(block, options, regular, text_width))
        elif isinstance(block, IndexBlock):
            flowables.extend(_index_flowables(block, options, regular, text_width))
    return flowables


def _toc_flowables(
    block: TocBlock, options: ExportOptions, regular: str, text_width: float
) -> list[Any]:
    flowables: list[Any] = [Spacer(1, 0.5 * cm)]
    flowables.append(
        Paragraph(
            _escape(block.title),
            _style("toc-title", options.pdf_font_names[1], size=16, leading=20, after=14),
        )
    )
    if not block.entries:
        flowables.append(
            Paragraph(
                "Aucune section à présenter.",
                ParagraphStyle("toc-empty", fontName=regular, fontSize=11, textColor=GREY),
            )
        )
        return flowables
    normal = ParagraphStyle("toc", fontName=regular, fontSize=11, leading=17)
    bold_style = _style("toc-b", options.pdf_font_names[1], size=11, leading=17)
    for entry in block.entries:
        style = bold_style if entry.level == 1 else normal
        left = 0.6 * cm * (entry.level - 1)
        flowables.append(
            Paragraph(
                f'<a name="{entry.anchor}"/>{_escape(entry.text)}',
                ParagraphStyle(
                    f"toc-{entry.level}",
                    parent=style,
                    leftIndent=left,
                    firstLineIndent=0,
                ),
            )
        )
    flowables.append(Spacer(1, 0.4 * cm))
    return flowables


def _index_flowables(
    block: IndexBlock, options: ExportOptions, regular: str, text_width: float
) -> list[Any]:
    flowables: list[Any] = [
        Spacer(1, 0.4 * cm),
        Paragraph(
            _escape(block.title),
            _style("ix-title", options.pdf_font_names[1], size=14, leading=18, after=10),
        ),
    ]
    for label, caption in block.entries:
        flowables.append(
            Paragraph(
                f"{_escape(label)} - {_escape(caption)}",
                _style("ix", regular, size=10.5, leading=15),
            )
        )
    # No page break here: the single break that opens the body separates front matter from
    # content, and a second one would leave a blank page.
    return flowables


def _bibliography_flowables(
    bibliography: BibliographyBlock,
    options: ExportOptions,
    regular: str,
    bold: str,
    text_width: float,
) -> list[Any]:
    flowables: list[Any] = [
        Paragraph(
            _escape(options.bibliography_heading),
            ParagraphStyle(
                "bib-title",
                fontName=bold,
                fontSize=17,
                leading=22,
                spaceAfter=12,
                keepWithNext=True,
            ),
        )
    ]
    if not bibliography.lines:
        flowables.append(
            Paragraph(
                "Aucune référence citée dans ce document.",
                ParagraphStyle("bib-empty", fontName=regular, fontSize=11, textColor=GREY),
            )
        )
        return flowables
    entry_style = ParagraphStyle(
        "bib",
        fontName=regular,
        fontSize=options.font_size,
        leading=options.font_size * 1.4,
        firstLineIndent=-0.6 * cm,
        leftIndent=0.6 * cm,
        spaceAfter=6,
        alignment=TA_LEFT,
    )
    for line in bibliography.lines:
        flowables.append(Paragraph(_escape(line), entry_style))
    return flowables


def _block_flowables(
    block: Block,
    options: ExportOptions,
    regular: str,
    bold: str,
    text_width: float,
    state: dict[str, int | str],
    model: DocumentModel,
) -> list[Any]:
    """Turn one block into reportlab flowables."""
    if block.kind in {BlockKind.PAGE_BREAK, BlockKind.HORIZONTAL_RULE}:
        return []
    if block.kind == BlockKind.HEADING:
        # The marker sets the running head when the page is drawn, so each page shows the
        # heading that is actually on it.
        return [
            _Flowable(lambda: state.__setitem__("running_head", block.plain_text)),
            Paragraph(_spans_to_markup(block.spans), _style_for(block, options, bold)),
        ]
    if block.kind == BlockKind.HEADING_UNNUMBERED:
        return [Paragraph(_spans_to_markup(block.spans), _style_for(block, options, bold))]
    if block.kind == BlockKind.PARAGRAPH:
        return [Paragraph(_spans_to_markup(block.spans), _style_for(block, options, regular))]
    if block.kind == BlockKind.CITATION:
        return _citation_flowables(block, options, regular)
    if block.kind == BlockKind.EQUATION:
        return _equation_flowables(block, options, regular)
    if block.kind == BlockKind.FIGURE:
        return _figure_flowable(block, options, text_width)
    if block.kind == BlockKind.TABLE:
        flowables: list[Any] = []
        if block.number:
            flowables.append(
                Paragraph(
                    _escape(f"Tableau {block.number}"),
                    ParagraphStyle(
                        "tab-title",
                        fontName=options.pdf_font_names[1],
                        fontSize=10.5,
                        leading=14,
                        spaceBefore=8,
                        spaceAfter=4,
                    ),
                )
            )
        rendered = _table_flowable(block, options, regular, text_width)
        flowables.append(rendered)
        return flowables
    if block.kind in {BlockKind.BULLET_LIST, BlockKind.ORDERED_LIST}:
        items = getattr(block, "items", [])
        ordered = block.kind == BlockKind.ORDERED_LIST
        rendered: list[Any] = []
        for item in items:
            inner: list[Any] = []
            for sub in item:
                inner.extend(
                    _block_flowables(sub, options, regular, bold, text_width, state, model)
                )
            content = _join_inline(inner) if inner else Spacer(1, 2)
            if ordered:
                # reportlab numbers the items itself for an ordered list.
                rendered.append(ListItem(content, leftIndent=12))
            else:
                # The bullet is given explicitly: reportlab's "bullet" type expects a bullet
                # name, not the start value, and would otherwise try to draw an integer.
                rendered.append(ListItem(content, bulletText="•", leftIndent=12))
        if not rendered:
            return []
        if ordered:
            return [
                ListFlowable(
                    rendered,
                    bulletType="1",
                    start=getattr(block, "start", 1) or 1,
                    leftIndent=18,
                )
            ]
        return [ListFlowable(rendered, leftIndent=18)]
    if block.kind == BlockKind.QUOTE:
        inner_flowables: list[Any] = []
        for sub in block.inner:
            inner_flowables.extend(
                _block_flowables(sub, options, regular, bold, text_width, state, model)
            )
        if not inner_flowables:
            return []
        return [KeepTogether(inner_flowables)]
    if block.kind == BlockKind.CODE:
        return [
            Paragraph(
                f'<font face="Courier">{_escape(block.text)}</font>',
                _style("code", "Courier", size=9, leading=12),
            )
        ]
    if block.kind == BlockKind.PLACEHOLDER:
        return [
            Paragraph(
                _spans_to_markup(block.spans, allow_links=False),
                _style_for(block, options, regular),
            )
        ]
    if block.kind in {BlockKind.TOC, BlockKind.LIST_OF_FIGURES, BlockKind.LIST_OF_TABLES}:
        # Already rendered in the front matter.
        return []
    if block.kind == BlockKind.BIBLIOGRAPHY:
        return _bibliography_flowables(block, options, regular, bold, text_width)
    if block.kind == BlockKind.COVER:
        return _cover_flowables(block, options)
    return []


def _join_inline(flowables: list[Any]) -> Any:
    if not flowables:
        return Spacer(1, 2)
    if len(flowables) == 1:
        return flowables[0]
    from reportlab.platypus import KeepTogether

    return KeepTogether(flowables)


def _citation_flowables(
    block: CitationBlock, options: ExportOptions, regular: str
) -> list[Any]:
    """A citation, plus a visible note when it cannot be trusted."""
    flowables: list[Any] = []
    style = ParagraphStyle(
        "cite",
        fontName=regular,
        fontSize=options.font_size,
        leading=options.font_size * 1.3,
        firstLineIndent=0,
        spaceAfter=4,
    )
    markup = _spans_to_markup(block.spans)
    if block.is_orphaned:
        flowables.append(
            Paragraph(
                f'<font color="#8C2F2F">{markup}</font>',
                style,
            )
        )
        flowables.append(
            Paragraph(
                '<font color="#8C2F2F" size="8">Citation invalide : la référence citée a été '
                "supprimée. La référence n'a pas été reconstituée.</font>",
                _style("cite-warn", regular, size=8, leading=11, colour=colors.HexColor("#8C2F2F")),
            )
        )
        return flowables
    flowables.append(Paragraph(markup, style))
    if block.warnings:
        flowables.append(
            Paragraph(
                '<font color="#8A5A00" size="8">'
                + _escape(" · ".join(block.warnings))
                + "</font>",
                _style(
                    "cite-warn2",
                    regular,
                    size=8,
                    leading=11,
                    colour=AMBER,
                ),
            )
        )
    if block.is_pending:
        flowables.append(
            Paragraph(
                '<font color="#8A5A00" size="8">Citation non encore enregistrée : '
                "enregistrez le document pour rattacher cette citation à la bibliographie.</font>",
                _style(
                    "cite-warn3",
                    regular,
                    size=8,
                    leading=11,
                    colour=AMBER,
                ),
            )
        )
    return flowables


def _equation_flowables(
    block: Block, options: ExportOptions, regular: str
) -> list[Any]:
    value = getattr(block, "value", "") or block.text
    label = f"({getattr(block, 'number', None)})" if getattr(block, "number", None) else ""
    style = ParagraphStyle(
        "eq",
        fontName=options.pdf_font_names[2],
        fontSize=options.font_size,
        leading=options.font_size * 1.4,
        alignment=TA_CENTER,
        spaceBefore=6,
        spaceAfter=6,
    )
    return [Paragraph(f"{_escape(value)} {label}".strip(), style)]


__all__ = ["GREY", "HEADING_SIZES", "render_pdf"]
