"""The neutral document model of an export.

Both renderers — PDF (reportlab) and DOCX (python-docx) — consume the blocks defined here.
Nothing about reportlab or python-docx leaks into this module, which is what makes it possible
to add a third output (LaTeX, HTML, plain text) without touching the logic that builds the
document.

The model is deliberately flat and explicit. A block knows what it is and carries only the
facts a renderer needs; it never computes anything.

Important for citations: a :class:`CitationBlock` carries the text **already rendered by the
stage 10 style engine**. The export never re-formats a citation, and never reads the string
the editor happened to display, except as a last resort for a node that has not been saved yet
— in which case the block says so through :attr:`CitationBlock.is_pending`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class BlockKind(StrEnum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    BULLET_LIST = "bullet_list"
    ORDERED_LIST = "ordered_list"
    LIST_ITEM = "list_item"
    TABLE = "table"
    FIGURE = "figure"
    CAPTION = "caption"
    CITATION = "citation"
    EQUATION = "equation"
    BIBLIOGRAPHY = "bibliography"
    QUOTE = "quote"
    CODE = "code"
    HORIZONTAL_RULE = "horizontal_rule"
    PAGE_BREAK = "page_break"
    PLACEHOLDER = "placeholder"
    TOC = "toc"
    LIST_OF_FIGURES = "list_of_figures"
    LIST_OF_TABLES = "list_of_tables"
    COVER = "cover"
    HEADING_UNNUMBERED = "heading_unnumbered"


@dataclass(frozen=True, slots=True)
class CitationState:
    """The state of the citation this span displays.

    A citation usually sits inside a paragraph, so it is rendered as a span rather than as a
    block. Carrying its state on the span is what lets the renderers print the orphan or the
    pending note at the exact place it belongs, instead of losing the information.
    """

    node_id: str = ""
    is_orphaned: bool = False
    is_pending: bool = False
    warnings: tuple[str, ...] = ()
    reference_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Span:
    """A run of text with its marks."""

    text: str
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strike: bool = False
    superscript: bool = False
    subscript: bool = False
    code: bool = False
    #: Target of a link, already validated by the caller.
    href: str | None = None
    #: Font size override for a footnote-sized run.
    small: bool = False
    #: Set when the span is the rendering of a citation node.
    citation: CitationState | None = None

    def is_plain(self) -> bool:
        return not (
            self.bold
            or self.italic
            or self.underline
            or self.strike
            or self.superscript
            or self.subscript
            or self.code
            or self.href
            or self.small
        )


@dataclass(slots=True)
class Block:
    """A paragraph-level element of the exported document."""

    kind: BlockKind
    spans: tuple[Span, ...] = ()
    #: Heading depth, 1 for a chapter title, 2 for a section, and so on.
    level: int = 0
    #: Text without marks, used for the table of contents and the search index.
    plain_text: str = ""
    alignment: str = "justify"
    #: First-line indent in centimetres; ``None`` uses the configured default.
    indent_first_line: float | None = None
    indent_left: float = 0.0
    keep_with_next: bool = False
    #: Blocks wrapped by a container block such as a quote.
    inner: list[Block] = field(default_factory=list)

    @property
    def text(self) -> str:
        if self.plain_text:
            return self.plain_text
        return "".join(span.text for span in self.spans)


@dataclass(slots=True)
class Cell:
    """One table cell. A cell holds blocks so a cell may contain a list."""

    blocks: list[Block] = field(default_factory=list)
    is_header: bool = False
    colspan: int = 1
    rowspan: int = 1
    background: str | None = None

    @property
    def text(self) -> str:
        return " ".join(block.text for block in self.blocks if block.text).strip()


@dataclass(slots=True)
class TableBlock(Block):
    rows: list[list[Cell]] = field(default_factory=list)
    column_widths: list[float] | None = None
    caption: str | None = None
    number: int | None = None
    #: How many leading rows are header rows, repeated on each page.
    header_rows: int = 0


@dataclass(slots=True)
class FigureBlock(Block):
    """An image with its caption and its number.

    ``data`` holds the bytes when the image could be resolved locally. When it could not, the
    renderer draws a framed placeholder and the reason is carried in ``unavailable_reason``,
    because silently dropping a figure would be worse than saying it is missing.
    """

    data: bytes | None = None
    content_type: str | None = None
    caption: str | None = None
    number: int | None = None
    alt: str | None = None
    width_cm: float | None = None
    unavailable_reason: str | None = None
    source_url: str | None = None


@dataclass(slots=True)
class CaptionBlock(Block):
    caption: str = ""
    number: int | None = None
    label: str = "Figure"


@dataclass(slots=True)
class CitationBlock(Block):
    """A citation whose text was produced by the stage 10 style engine."""

    node_id: str = ""
    citation_id: str | None = None
    is_orphaned: bool = False
    #: True when the node had not been saved yet and its own text had to be used.
    is_pending: bool = False
    warnings: tuple[str, ...] = ()
    reference_ids: tuple[str, ...] = ()


@dataclass(slots=True)
class EquationBlock(Block):
    value: str = ""
    #: Position of the equation in the document, used for numbering ``(1)``, ``(2)``…
    number: int | None = None
    numbered: bool = True


@dataclass(slots=True)
class BibliographyBlock(Block):
    """The generated bibliography, one entry per line, as produced by stage 10."""

    lines: tuple[str, ...] = ()
    style: str = ""
    style_label: str = ""
    incomplete_count: int = 0


@dataclass(slots=True)
class ListBlock(Block):
    items: list[list[Block]] = field(default_factory=list)
    start: int = 1
    ordered: bool = False


@dataclass(slots=True)
class TocEntry:
    level: int
    text: str
    page: int = 0
    anchor: str = ""


@dataclass(slots=True)
class TocBlock(Block):
    entries: list[TocEntry] = field(default_factory=list)
    title: str = "Table des matières"


@dataclass(slots=True)
class IndexBlock(Block):
    """A list of figures or a list of tables."""

    entries: list[tuple[str, str]] = field(default_factory=list)
    title: str = "Liste des figures"


@dataclass(slots=True)
class CoverBlock(Block):
    """The cover page. Every field comes from the project record; none is invented."""

    title: str = ""
    subtitle: str | None = None
    author: str | None = None
    institution: str | None = None
    level: str | None = None
    academic_year: str | None = None
    supervisor: str | None = None
    thesis_type: str | None = None
    problem_statement: str | None = None
    general_objective: str | None = None
    specific_objectives: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    domain: str | None = None
    logo_data: bytes | None = None
    logo_content_type: str | None = None


@dataclass(slots=True)
class DocumentModel:
    """The whole export, ready to render."""

    cover: CoverBlock | None = None
    #: Front matter and body.
    blocks: list[Block] = field(default_factory=list)
    #: The generated bibliography, rendered after the body and before the annexes.
    bibliography: BibliographyBlock | None = None
    #: Annexes, rendered last.
    annexes: list[Block] = field(default_factory=list)
    #: The bibliography style actually used, as resolved from the project.
    style: str = ""
    style_label: str = ""
    project_title: str = ""
    project_id: str = ""
    #: Section titles in document order, for the page header.
    section_titles: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    figure_count: int = 0
    table_count: int = 0
    citation_count: int = 0
    uncited_count: int = 0
    orphan_count: int = 0

    def ordered_blocks(self) -> list[Block]:
        """Cover, front matter, body, bibliography, then annexes.

        Both renderers walk this single list, which is what keeps the order identical in the
        PDF and in the DOCX.
        """
        blocks: list[Block] = []
        if self.cover is not None:
            blocks.append(self.cover)
        blocks.extend(self.blocks)
        if self.bibliography is not None:
            blocks.append(self.bibliography)
        blocks.extend(self.annexes)
        return blocks


__all__ = [
    "BibliographyBlock",
    "CitationState",
    "Block",
    "BlockKind",
    "CaptionBlock",
    "Cell",
    "CitationBlock",
    "CoverBlock",
    "DocumentModel",
    "EquationBlock",
    "FigureBlock",
    "IndexBlock",
    "ListBlock",
    "Span",
    "TableBlock",
    "TocBlock",
    "TocEntry",
]
