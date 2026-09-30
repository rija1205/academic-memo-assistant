"""Tiptap JSON to neutral blocks.

The converter is total: an unknown node is skipped rather than raising, so a document written
by a future version still exports. Nothing here formats a citation; the text comes from
``resolved_citations``, which the caller fills from the stage 10 style engine.
"""

from __future__ import annotations

from typing import Any

from app.export.blocks import (
    Block,
    BlockKind,
    Cell,
    CitationBlock,
    CitationState,
    EquationBlock,
    FigureBlock,
    ListBlock,
    Span,
    TableBlock,
)

#: Marks Tiptap uses, mapped to the flags of a span.
MARK_MAP = {
    "bold": "bold",
    "italic": "italic",
    "underline": "underline",
    "strike": "strike",
    "code": "code",
    "superscript": "superscript",
    "subscript": "subscript",
}

#: Nodes that carry no content of their own.
ATOM_KINDS = {
    "pageBreak": BlockKind.PAGE_BREAK,
    "horizontalRule": BlockKind.HORIZONTAL_RULE,
}


class TiptapConverter:
    """Convert one Tiptap document into blocks.

    ``resolved_citations`` maps a ``citationId`` to the text produced by the stage 10 engine.
    ``pending_citation_ids`` lists the nodes that have no server row yet, which is the only
    case where the node's own text is used.
    """

    def __init__(
        self,
        *,
        resolved_citations: dict[str, dict[str, Any]] | None = None,
        pending_citation_ids: set[str] | None = None,
    ) -> None:
        self.resolved = resolved_citations or {}
        self.pending = pending_citation_ids or set()
        self.figure_counter = 0
        self.table_counter = 0
        self.equation_counter = 0
        self.citation_counter = 0
        #: Figures and tables in order, for the lists of figures and tables.
        self.figures: list[tuple[str, str]] = []
        self.tables: list[tuple[str, str]] = []

    # ------------------------------------------------------------------ entry
    def convert(self, content: dict[str, Any] | None) -> list[Block]:
        blocks: list[Block] = []
        if not isinstance(content, dict):
            return blocks
        children = content.get("content")
        if not isinstance(children, list):
            return blocks
        blocks.extend(self._convert_blocks(children))
        return blocks

    def _convert_blocks(self, nodes: list[Any]) -> list[Block]:
        blocks: list[Block] = []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            block = self._convert_block(node)
            if block is None:
                continue
            if isinstance(block, list):
                blocks.extend(block)
            else:
                blocks.append(block)
        return blocks

    # ----------------------------------------------------------------- blocks
    def _convert_block(self, node: dict[str, Any]) -> Block | list[Block] | None:
        node_type = node.get("type")
        if not isinstance(node_type, str):
            return None
        if node_type in ATOM_KINDS:
            return Block(kind=ATOM_KINDS[node_type])
        if node_type == "paragraph":
            return self._paragraph(node)
        if node_type == "heading":
            return self._heading(node)
        if node_type in {"bulletList", "orderedList"}:
            return self._list(node, ordered=node_type == "orderedList")
        if node_type == "blockquote":
            return Block(
                kind=BlockKind.QUOTE,
                inner=self._convert_blocks(_children(node)),
                indent_left=1.0,
            )
        if node_type == "codeBlock":
            text = self._plain(_children(node))
            return Block(kind=BlockKind.CODE, spans=(Span(text, code=True),), plain_text=text)
        if node_type == "table":
            return self._table(node)
        if node_type == "image":
            return self._figure(node)
        if node_type == "citation":
            return self._citation(node)
        if node_type == "bibliographyBlock":
            return self._bibliography(node)
        if node_type in {"equation", "reference"}:
            return self._placeholder(node)
        # Unknown block: keep its children so no content is silently lost.
        return self._convert_blocks(_children(node))

    def _paragraph(self, node: dict[str, Any]) -> Block:
        spans, text = self._spans(_children(node))
        attributes = node.get("attrs") if isinstance(node.get("attrs"), dict) else {}
        alignment = str(attributes.get("textAlign") or "justify")
        block = Block(kind=BlockKind.PARAGRAPH, spans=tuple(spans), plain_text=text)
        block.alignment = "left" if alignment == "justify" else alignment
        return block

    def _heading(self, node: dict[str, Any]) -> Block:
        spans, text = self._spans(_children(node))
        attributes = node.get("attrs") if isinstance(node.get("attrs"), dict) else {}
        try:
            level = int(attributes.get("level") or 2)
        except (TypeError, ValueError):
            level = 2
        level = max(1, min(level, 6))
        block = Block(kind=BlockKind.HEADING, spans=tuple(spans), level=level, plain_text=text)
        block.alignment = "left"
        block.keep_with_next = True
        return block

    def _list(self, node: dict[str, Any], *, ordered: bool) -> Block:
        items: list[list[Block]] = []
        for child in _children(node):
            if not isinstance(child, dict) or child.get("type") != "listItem":
                continue
            items.append(self._convert_blocks(_children(child)))
        attributes = node.get("attrs") if isinstance(node.get("attrs"), dict) else {}
        try:
            start = int(attributes.get("start") or 1)
        except (TypeError, ValueError):
            start = 1
        return ListBlock(
            kind=BlockKind.ORDERED_LIST if ordered else BlockKind.BULLET_LIST,
            items=items,
            start=start,
            ordered=ordered,
        )

    def _table(self, node: dict[str, Any]) -> Block:
        rows: list[list[Cell]] = []
        header_rows = 0
        for row_node in _children(node):
            if not isinstance(row_node, dict) or row_node.get("type") != "tableRow":
                continue
            row: list[Cell] = []
            for cell_node in _children(row_node):
                if not isinstance(cell_node, dict):
                    continue
                if cell_node.get("type") not in {"tableCell", "tableHeader"}:
                    continue
                is_header = cell_node.get("type") == "tableHeader"
                inner = self._convert_blocks(_children(cell_node))
                if not inner:
                    inner = [Block(kind=BlockKind.PARAGRAPH, alignment="left")]
                attributes = (
                    cell_node.get("attrs") if isinstance(cell_node.get("attrs"), dict) else {}
                )
                row.append(
                    Cell(
                        blocks=inner,
                        is_header=is_header,
                        colspan=_int(attributes.get("colspan"), 1),
                        rowspan=_int(attributes.get("rowspan"), 1),
                        background=_colSpan(attributes),
                    )
                )
            if row:
                rows.append(row)
        # A leading row made only of header cells is the header row.
        if rows and all(cell.is_header for cell in rows[0]):
            header_rows = 1
        self.table_counter += 1
        return TableBlock(
            kind=BlockKind.TABLE, rows=rows, number=self.table_counter, header_rows=header_rows
        )

    def _figure(self, node: dict[str, Any]) -> FigureBlock:
        attributes = node.get("attrs") if isinstance(node.get("attrs"), dict) else {}
        self.figure_counter += 1
        caption = attributes.get("title") or attributes.get("alt")
        figure = FigureBlock(kind=BlockKind.FIGURE, plain_text=caption or "")
        figure.source_url = attributes.get("src")
        figure.alt = attributes.get("alt")
        figure.caption = attributes.get("title") or None
        figure.number = self.figure_counter
        if isinstance(attributes.get("width"), (int, float)):
            figure.width_cm = float(attributes["width"]) / 96.0 * 2.54
        return figure

    def _citation(self, node: dict[str, Any]) -> CitationBlock:
        """Build the rendering of a citation, always from the engine when it is available."""
        attributes = node.get("attrs") if isinstance(node.get("attrs"), dict) else {}
        citation_id = str(attributes.get("citationId") or "")
        legacy = attributes.get("legacyValue")
        resolved = self.resolved.get(citation_id) if citation_id else None

        if resolved is not None:
            text = str(resolved.get("text") or "")
            is_orphaned = bool(resolved.get("is_orphaned"))
            warnings = tuple(str(item) for item in resolved.get("warnings") or ())
            reference_ids = tuple(str(item) for item in resolved.get("reference_ids") or ())
            citation_ref = resolved.get("citation_id")
            # A node the engine knows is registered, so it is not pending.
            is_pending = False
        else:
            # No server row: the node has never been saved, or it is a stage 3 placeholder.
            # The node's own text is the only thing available, and the block records that so
            # the renderers can tell the author instead of presenting it as a real citation.
            text = str(attributes.get("text") or "")
            warnings = tuple(str(item) for item in attributes.get("warnings") or ())
            reference_ids = tuple(str(item) for item in attributes.get("referenceIds") or ())
            is_orphaned = bool(attributes.get("isOrphaned"))
            citation_ref = None
            is_pending = True
            if legacy:
                text = text or f"[{legacy}]"
                warnings = (
                    *warnings,
                    "Citation de l'ancienne version sans reference enregistree : "
                    "a rattacher a une entree de la bibliographie.",
                )
            elif not text:
                text = "[Citation sans reference enregistree]"

        self.citation_counter += 1
        block = CitationBlock(kind=BlockKind.CITATION, spans=(Span(text),), plain_text=text)
        block.node_id = citation_id or f"pending-{self.citation_counter}"
        block.citation_id = citation_ref
        block.is_orphaned = is_orphaned
        block.is_pending = is_pending
        block.warnings = warnings
        block.reference_ids = reference_ids
        return block

    def _bibliography(self, node: dict[str, Any]) -> Block:
        attributes = node.get("attrs") if isinstance(node.get("attrs"), dict) else {}
        lines = tuple(str(line) for line in attributes.get("lines") or ())
        title = str(attributes.get("title") or "Bibliographie")
        blocks: list[Block] = [
            Block(
                kind=BlockKind.HEADING,
                level=1,
                spans=(Span(title),),
                plain_text=title,
                alignment="left",
                keep_with_next=True,
            )
        ]
        for line in lines:
            blocks.append(
                Block(
                    kind=BlockKind.PARAGRAPH,
                    spans=(Span(line),),
                    plain_text=line,
                    alignment="left",
                    indent_left=0.0,
                )
            )
        return blocks

    def _placeholder(self, node: dict[str, Any]) -> Block | list[Block]:
        attributes = node.get("attrs") if isinstance(node.get("attrs"), dict) else {}
        value = str(attributes.get("value") or "")
        if not value:
            return []
        label = "Équation" if node.get("type") == "equation" else "Référence"
        self.equation_counter += 1
        if node.get("type") != "equation":
            text = f"[{label} : {value}]"
            return Block(
                kind=BlockKind.PLACEHOLDER, spans=(Span(text, italic=True),), plain_text=text
            )
        equation = EquationBlock(
            kind=BlockKind.EQUATION, spans=(Span(value),), plain_text=value
        )
        equation.value = value
        equation.number = self.equation_counter
        return equation

    # ------------------------------------------------------------------ spans
    def _spans(self, nodes: list[Any]) -> tuple[list[Span], str]:
        spans: list[Span] = []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            node_type = node.get("type")
            if node_type == "text":
                spans.append(self._span(str(node.get("text") or ""), node.get("marks")))
            elif node_type == "hardBreak":
                spans.append(Span("\n"))
            elif node_type in {"citation", "image", "equation", "reference", "pageBreak"}:
                inner = self._convert_block(node)
                if isinstance(inner, CitationBlock):
                    # The state travels with the span so the renderers can annotate it.
                    spans.append(
                        Span(
                            f" {inner.text} ",
                            citation=CitationState(
                                node_id=inner.node_id,
                                is_orphaned=inner.is_orphaned,
                                is_pending=inner.is_pending,
                                warnings=inner.warnings,
                                reference_ids=inner.reference_ids,
                            ),
                        )
                    )
                elif isinstance(inner, FigureBlock):
                    label = f"[Figure {inner.number}]" if inner.number else "[Figure]"
                    spans.append(Span(f" {label} "))
                elif isinstance(inner, EquationBlock):
                    label = f"({inner.number})" if inner.number else ""
                    spans.append(Span(f" {inner.value} {label} "))
                elif isinstance(inner, Block) and inner.text:
                    spans.append(Span(f" {inner.text} "))
                else:
                    inner = self._convert_block(node)
                    if isinstance(inner, list):
                        for block in inner:
                            if block.text:
                                spans.append(Span(f" {block.text} "))
            else:
                spans.extend(self._spans(_children(node))[0])
        return spans, "".join(span.text for span in spans).strip()

    def _span(self, text: str, marks: Any) -> Span:
        flags: dict[str, bool] = {}
        href: str | None = None
        if isinstance(marks, list):
            for mark in marks:
                if not isinstance(mark, dict):
                    continue
                mark_type = str(mark.get("type") or "")
                attribute = MARK_MAP.get(mark_type)
                if attribute:
                    flags[attribute] = True
                if mark_type == "link":
                    attributes = mark.get("attrs")
                    if isinstance(attributes, dict):
                        href = str(attributes.get("href") or "") or None
        return Span(
            text=text,
            bold=flags.get("bold", False),
            italic=flags.get("italic", False),
            underline=flags.get("underline", False),
            strike=flags.get("strike", False),
            superscript=flags.get("superscript", False),
            subscript=flags.get("subscript", False),
            code=flags.get("code", False),
            href=href,
        )

    @staticmethod
    def _plain(nodes: list[Any]) -> str:
        parts: list[str] = []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            if node.get("type") == "text":
                parts.append(str(node.get("text") or ""))
            else:
                parts.append(TiptapConverter._plain(_children(node)))
        return "".join(parts)


def _children(node: dict[str, Any]) -> list[Any]:
    content = node.get("content")
    return content if isinstance(content, list) else []


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _colSpan(attributes: dict[str, Any]) -> str | None:
    colour = attributes.get("backgroundColor")
    if isinstance(colour, str) and colour.strip():
        return colour.strip()
    return None


__all__ = ["MARK_MAP", "TiptapConverter"]
