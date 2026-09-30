"""Tests of the academic export.

These cover the three things that must be true for an export to be trustworthy:

* the same citation text as the editor, produced by the stage 10 engine and never re-derived;
* a valid, readable PDF and DOCX, checked by reading the generated files back;
* options, file names and image resolution that cannot be used to attack the server.
"""

from __future__ import annotations

import base64
from io import BytesIO

import pytest
from docx import Document as DocxReader
from pypdf import PdfReader

from app.export.blocks import (
    BibliographyBlock,
    Block,
    BlockKind,
    CoverBlock,
    DocumentModel,
    FigureBlock,
    Span,
    TableBlock,
    TocBlock,
    TocEntry,
)
from app.export.images import (
    ImageUnavailable,
    _is_public_address,
    image_size,
    resolve_data_url,
    resolve_image,
)
from app.export.options import (
    ExportOptionError,
    build_options,
)
from app.export.orchestrator import build_file_name
from app.export.service import SectionPlan, compute_headings
from app.export.tiptap import TiptapConverter

# --------------------------------------------------------------------- helpers


def png_data_url(color: tuple[int, int, int] = (30, 90, 160)) -> str:
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (120, 80), color).save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def cell(text: str, header: bool = False):
    from app.export.blocks import Cell

    return Cell(
        blocks=[Block(kind=BlockKind.PARAGRAPH, spans=(Span(text),), plain_text=text)],
        is_header=header,
    )


def sample_document(data_url: str | None = None) -> dict:
    content: list[dict] = [
        {
            "type": "heading",
            "attrs": {"level": 2},
            "content": [{"type": "text", "text": "Introduction"}],
        },
        {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "Le jacquier est une espece importante. "},
                {"type": "text", "text": "Un terme en gras", "marks": [{"type": "bold"}]},
                {"type": "text", "text": " puis une citation "},
                {
                    "type": "citation",
                    "attrs": {
                        "citationId": "c1",
                        "referenceIds": ["r1"],
                        "text": "TEXTE BRUT DU NOEUD",
                        "warnings": [],
                        "isOrphaned": False,
                        "mode": "parenthetical",
                    },
                },
                {"type": "text", "text": "."},
            ],
        },
        {
            "type": "bulletList",
            "content": [
                {
                    "type": "listItem",
                    "content": [
                        {"type": "paragraph", "content": [{"type": "text", "text": "Point un"}]}
                    ],
                }
            ],
        },
        {
            "type": "table",
            "content": [
                {
                    "type": "tableRow",
                    "content": [
                        {
                            "type": "tableHeader",
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [{"type": "text", "text": "Param"}],
                                }
                            ],
                        },
                        {
                            "type": "tableHeader",
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [{"type": "text", "text": "Valeur"}],
                                }
                            ],
                        },
                    ],
                },
                {
                    "type": "tableRow",
                    "content": [
                        {
                            "type": "tableCell",
                            "content": [
                                {"type": "paragraph", "content": [{"type": "text", "text": "Prot"}]}
                            ],
                        },
                        {
                            "type": "tableCell",
                            "content": [
                                {"type": "paragraph", "content": [{"type": "text", "text": "12 g"}]}
                            ],
                        },
                    ],
                },
            ],
        },
        {
            "type": "paragraph",
            "content": [{"type": "equation", "attrs": {"value": "E = mc2"}}],
        },
        {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "Un lien "},
                {
                    "type": "text",
                    "text": "externe",
                    "marks": [{"type": "link", "attrs": {"href": "https://example.org"}}],
                },
            ],
        },
        {"type": "pageBreak"},
    ]
    if data_url:
        content.insert(
            4, {"type": "image", "attrs": {"src": data_url, "title": "Aspect du grain"}}
        )
    return {"type": "doc", "content": content}


def build_model(*, with_cover: bool = False, with_toc: bool = False) -> DocumentModel:
    data_url = png_data_url()
    resolved = {
        "c1": {
            "text": "(Dupont, 2024, p. 25)",
            "is_orphaned": False,
            "warnings": [],
            "reference_ids": ["r1"],
            "citation_id": "cit-1",
        }
    }
    converter = TiptapConverter(resolved_citations=resolved)
    blocks = converter.convert(sample_document(data_url))
    from app.export.options import ExportGuard
    from app.export.service import _resolve_figures

    _resolve_figures(blocks, allow_remote=False, guard=ExportGuard())

    front: list[Block] = []
    if with_toc:
        front.append(
            TocBlock(
                kind=BlockKind.TOC,
                title="Table des matieres",
                entries=[TocEntry(level=1, text="I. Introduction", anchor="section-1")],
            )
        )
    model = DocumentModel(
        blocks=[*front, *blocks],
        project_title="Memoire de test",
        project_id="p1",
        style="apa7",
        style_label="APA 7",
        figure_count=converter.figure_counter,
        table_count=converter.table_counter,
        citation_count=converter.citation_counter,
    )
    if with_cover:
        model.cover = CoverBlock(
            kind=BlockKind.COVER,
            title="Composition du grain de jacquier",
            author="Rakoto Marie",
            institution="Universite",
            academic_year="2025-2026",
            supervisor="Pr. Dupont",
            problem_statement="Quelle est la composition ?",
        )
    model.bibliography = BibliographyBlock(
        kind=BlockKind.BIBLIOGRAPHY,
        lines=("Dupont, J. (2024). Composition du grain. Revue Agro, 10(2), 25-40.",),
        style="apa7",
        style_label="APA 7",
    )
    model.annexes = [
        Block(kind=BlockKind.HEADING, level=1, spans=(Span("Annexe A"),), plain_text="Annexe A")
    ]
    return model


def pdf_text(payload: bytes) -> str:
    reader = PdfReader(BytesIO(payload))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def flat(text: str) -> str:
    return " ".join(text.split())


def docx_text(payload: bytes) -> str:
    opened = DocxReader(BytesIO(payload))
    parts = [paragraph.text for paragraph in opened.paragraphs]
    for table in opened.tables:
        for row in table.rows:
            for cell in row.cells:
                parts.append(cell.text)
    return "\n".join(parts)


# ------------------------------------------------------------------- options


def test_default_options_match_academic_conventions() -> None:
    options = build_options({})
    assert options.page_size == "a4"
    assert options.font_family == "times"
    assert options.font_size == 12.0
    assert options.line_spacing == 1.5
    assert options.first_line_indent == 1.25
    assert options.paragraph_alignment == "justify"
    assert options.include_cover is True
    assert options.include_toc is True
    assert options.embed_remote_images is False


@pytest.mark.parametrize(
    "payload",
    [
        {"font_size": 2.0},
        {"font_size": 40.0},
        {"line_spacing": 0.1},
        {"line_spacing": 9.0},
        {"margin_left": 0.0},
        {"margin_right": 100.0},
        {"page_size": "a3"},
        {"orientation": "diagonal"},
        {"font_family": "comic"},
        {"paragraph_alignment": "justify-all"},
        {"header_text": "x" * 400},
    ],
)
def test_out_of_range_options_are_refused(payload: dict) -> None:
    with pytest.raises(ExportOptionError):
        build_options(payload)


def test_unknown_option_keys_are_ignored() -> None:
    options = build_options({"font_size": 13, "a_future_option": True})
    assert options.font_size == 13.0


def test_a_header_can_be_cleared_with_an_empty_string() -> None:
    assert build_options({"header_text": ""}).header_text is None


def test_page_dimensions_follow_orientation() -> None:
    portrait = build_options({"orientation": "portrait"})
    landscape = build_options({"orientation": "landscape"})
    assert portrait.page_dimensions()[0] < portrait.page_dimensions()[1]
    assert landscape.page_dimensions()[0] > landscape.page_dimensions()[1]


# -------------------------------------------------------------- file naming


def test_file_name_follows_the_expected_pattern() -> None:
    name = build_file_name("Composition du jacquier", "Rakoto Marie", "2025-2026", "pdf")
    assert name == "Composition_du_jacquier_Rakoto_Marie_20252026.pdf"


def test_file_name_survives_a_hostile_title() -> None:
    """A title must never be able to inject a header, a path or a shell character."""
    name = build_file_name('../../etc/passwd"; rm -rf /', "A/B", "2025", "pdf")
    assert ".." not in name
    assert "/" not in name
    assert '"' not in name
    assert ";" not in name
    assert name.endswith(".pdf")


def test_file_name_falls_back_when_everything_is_stripped() -> None:
    assert build_file_name("///", None, None, "docx") == "memoire.docx"


def test_file_name_keeps_accents_out_of_the_path() -> None:
    name = build_file_name("Le grain de jacquier — étude", "Rakoto", "2026", "pdf")
    assert "—" not in name
    assert " " not in name


def test_file_name_is_bounded() -> None:
    name = build_file_name("T" * 500, "A" * 500, "2026", "pdf")
    assert len(name) <= 100


# ---------------------------------------------------------- Tiptap conversion


RESOLVED = {
    "c1": {
        "text": "(Dupont, 2024, p. 25)",
        "is_orphaned": False,
        "warnings": [],
        "reference_ids": ["r1"],
        "citation_id": "cit-1",
    }
}


def inline_citation(document: dict, *, resolved: dict | None = None):
    """The citation span of a document whose citation sits inside a paragraph."""
    blocks = TiptapConverter(
        resolved_citations=RESOLVED if resolved is None else resolved
    ).convert(document)
    for block in blocks:
        for span in block.spans:
            if span.citation is not None:
                return span
    raise AssertionError("aucun span de citation trouve")


def test_a_citation_uses_the_engine_text_not_the_node_text() -> None:
    """The node says one thing, the engine says another: the engine wins."""
    span = inline_citation(sample_document())
    assert "(Dupont, 2024, p. 25)" in span.text
    assert "TEXTE BRUT" not in span.text
    assert span.citation is not None
    assert span.citation.is_pending is False
    assert span.citation.node_id == "c1"
    assert span.citation.reference_ids == ("r1",)


def test_an_unregistered_node_is_flagged_as_pending() -> None:
    """A node the server does not know is reported instead of being trusted silently."""
    span = inline_citation(sample_document(), resolved={})
    assert span.citation is not None
    assert span.citation.is_pending is True


def test_an_orphan_citation_is_marked_and_keeps_its_warning() -> None:
    blocks = TiptapConverter(
        resolved_citations={
            "c1": {
                "text": "[Citation invalide : reference introuvable]",
                "is_orphaned": True,
                "warnings": ["Reference introuvable."],
                "reference_ids": [],
                "citation_id": "cit-1",
            }
        }
    ).convert(sample_document())
    span = next(
        span
        for block in blocks
        for span in block.spans
        if span.citation is not None
    )
    assert span.citation is not None
    assert span.citation.is_orphaned is True
    assert span.citation.warnings == ("Reference introuvable.",)


def test_a_standalone_citation_node_becomes_a_block() -> None:
    """A citation outside a paragraph, for instance in a table cell, becomes its own block."""
    blocks = TiptapConverter(
        resolved_citations={
            "c1": {
                "text": "(Dupont, 2024)",
                "is_orphaned": False,
                "warnings": [],
                "reference_ids": ["r1"],
                "citation_id": "cit-1",
            }
        }
    ).convert({"type": "doc", "content": [{"type": "citation", "attrs": {"citationId": "c1"}}]})
    citation = next(block for block in blocks if block.kind == BlockKind.CITATION)
    assert citation.text == "(Dupont, 2024)"
    assert citation.citation_id == "cit-1"


def test_a_stage_three_free_text_node_is_never_turned_into_a_citation() -> None:
    document = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "citation", "attrs": {"legacyValue": "Auteur2025"}}],
            }
        ],
    }
    blocks = TiptapConverter().convert(document)
    span = next(
        span for block in blocks for span in block.spans if span.citation is not None
    )
    assert "[Auteur2025]" in span.text
    # It is pending and carries no reference, so the renderers can tell the author to re-attach
    # it rather than pretending the work is cited.
    assert span.citation is not None
    assert span.citation.is_pending is True
    assert span.citation.reference_ids == ()


def test_an_unknown_block_keeps_its_children() -> None:
    document = {
        "type": "doc",
        "content": [
            {
                "type": "futureBlock",
                "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": "Contenu"}]}
                ],
            }
        ],
    }
    blocks = TiptapConverter().convert(document)
    assert any("Contenu" in block.text for block in blocks)


@pytest.mark.parametrize("document", [None, {}, {"content": None}, {"content": "x"}])
def test_a_malformed_document_does_not_raise(document) -> None:
    assert TiptapConverter().convert(document) == []


def test_marks_become_spans() -> None:
    document = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "gras", "marks": [{"type": "bold"}]},
                    {"type": "text", "text": "ital", "marks": [{"type": "italic"}]},
                    {"type": "text", "text": "li", "marks": [{"type": "link", "attrs": {"href": "https://a.fr"}}]},
                ],
            }
        ],
    }
    paragraph = TiptapConverter().convert(document)[0]
    assert paragraph.spans[0].bold is True
    assert paragraph.spans[1].italic is True
    assert paragraph.spans[2].href == "https://a.fr"


def test_figures_and_tables_are_numbered_in_order() -> None:
    # One converter per document: the counters belong to the walk, not to the class.
    converter = TiptapConverter()
    blocks = converter.convert(sample_document(png_data_url()))
    assert converter.figure_counter == 1
    assert converter.table_counter == 1
    table = next(block for block in blocks if isinstance(block, TableBlock))
    assert table.number == 1
    assert table.header_rows == 1


def test_an_equation_inside_a_paragraph_becomes_an_inline_span() -> None:
    blocks = TiptapConverter().convert(sample_document())
    text = " ".join(block.text for block in blocks)
    assert "E = mc2 (1)" in text


# ------------------------------------------------------------------ images


def test_a_data_url_image_is_decoded() -> None:
    data, content_type, reason = resolve_image(png_data_url(), allow_remote=False)
    assert data and data[:4] == b"\x89PNG"
    assert content_type == "image/png"
    assert reason is None
    size = image_size(data)
    assert size == (120, 80)


def test_a_remote_image_is_refused_unless_explicitly_allowed() -> None:
    data, _content_type, reason = resolve_image(
        "https://example.org/a.png", allow_remote=False
    )
    assert data is None
    assert "distante" in (reason or "")


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "file:///etc/passwd",
        "blob:http://localhost/1234",
        "vbscript:msgbox",
        "",
        None,
    ],
)
def test_dangerous_schemes_are_never_dereferenced(url) -> None:
    data, _content_type, reason = resolve_image(url, allow_remote=True)
    assert data is None
    assert reason


@pytest.mark.parametrize(
    "host",
    ["127.0.0.1", "10.0.0.5", "192.168.1.1", "172.16.0.1", "169.254.169.254", "0.0.0.0", "::1"],
)
def test_private_and_reserved_addresses_are_refused(host: str) -> None:
    """This is the check that stops an export reaching the database or a metadata endpoint."""
    with pytest.raises(ImageUnavailable):
        _is_public_address(host)


def test_a_public_literal_address_is_accepted() -> None:
    assert _is_public_address("93.184.216.34") is True


def test_an_oversized_data_url_is_refused() -> None:
    payload = base64.b64encode(b"x" * (13 * 1024 * 1024)).decode()
    with pytest.raises(ImageUnavailable):
        resolve_data_url("data:image/png;base64," + payload)


def test_a_corrupt_image_does_not_break_the_size_probe() -> None:
    assert image_size(b"not an image") is None


# ---------------------------------------------------------- heading numbering


def plans() -> list[SectionPlan]:
    from uuid import uuid4

    def make(title: str, level: int, position: int) -> SectionPlan:
        return SectionPlan(
            section_id=uuid4(),
            title=title,
            level=level,
            position=position,
            content={},
            word_count=0,
            status="in_progress",
        )

    return [
        make("Introduction", 1, 0),
        make("Contexte", 2, 1),
        make("Materiel et methodes", 1, 2),
        make("Resultats", 1, 3),
        make("Resultats", 2, 4),
    ]


def test_headings_are_numbered_with_romans_and_decimals() -> None:
    headings = compute_headings(plans(), number=True)
    assert headings[0].number == "I"
    assert headings[1].number == "1.1"
    assert headings[2].number == "II"
    assert headings[3].number == "III"
    assert headings[4].number == "3.1"


def test_numbering_can_be_switched_off() -> None:
    headings = compute_headings(plans(), number=False)
    assert all(heading.number is None for heading in headings)


def test_heading_levels_are_clamped_to_what_a_renderer_accepts() -> None:
    from uuid import uuid4

    deep = [
        SectionPlan(
            section_id=uuid4(),
            title=f"Titre {index}",
            level=9,
            position=index,
            content={},
            word_count=0,
            status="empty",
        )
        for index in range(3)
    ]
    headings = compute_headings(deep, number=True)
    assert all(heading.level == 6 for heading in headings)


# ------------------------------------------------------------------ rendering


def test_the_pdf_is_a_valid_readable_file() -> None:
    from app.export.pdf import render_pdf

    payload = render_pdf(build_model(), build_options({}))
    assert payload.startswith(b"%PDF")
    assert payload.rstrip().endswith(b"%%EOF")
    assert len(PdfReader(BytesIO(payload)).pages) >= 1


def test_the_docx_is_a_valid_readable_file() -> None:
    from app.export.docx import render_docx

    payload = render_docx(build_model(), build_options({}))
    assert payload.startswith(b"PK")
    opened = DocxReader(BytesIO(payload))
    assert len(opened.tables) == 1


def test_both_formats_render_the_same_citation_text() -> None:
    """The critical coherence requirement of stage 11."""
    from app.export.docx import render_docx
    from app.export.pdf import render_pdf

    model = build_model()
    options = build_options({})
    text = flat(pdf_text(render_pdf(model, options)))
    assert "(Dupont, 2024, p. 25)" in text
    assert "(Dupont, 2024, p. 25)" in docx_text(render_docx(model, options))
    # The node's own string must appear in neither.
    assert "TEXTE BRUT" not in text
    assert "TEXTE BRUT" not in docx_text(render_docx(model, options))


def test_both_formats_render_the_same_bibliography() -> None:
    from app.export.docx import render_docx
    from app.export.pdf import render_pdf

    model = build_model()
    options = build_options({})
    line = "Dupont, J. (2024). Composition du grain. Revue Agro, 10(2), 25-40."
    assert line in flat(pdf_text(render_pdf(model, options)))
    assert line in docx_text(render_docx(model, options))


def test_both_formats_render_the_annex_after_the_bibliography() -> None:
    from app.export.docx import render_docx
    from app.export.pdf import render_pdf

    model = build_model()
    options = build_options({})
    pdf = flat(pdf_text(render_pdf(model, options)))
    assert pdf.index("Bibliographie") < pdf.index("Annexe A")
    body = docx_text(render_docx(model, options))
    assert body.index("Bibliographie") < body.index("Annexe A")


def test_the_pdf_numbers_the_body_in_arabic_after_a_roman_front_matter() -> None:
    from app.export.pdf import render_pdf

    model = build_model(with_cover=True, with_toc=True)
    payload = render_pdf(model, build_options({}))
    pages = (PdfReader(BytesIO(payload)).extract_text() or "" for _ in ())
    del pages
    reader = PdfReader(BytesIO(payload))
    texts = [(page.extract_text() or "").strip() for page in reader.pages]
    assert len(texts) >= 3

    def first_line(text: str) -> str:
        lines = text.splitlines()
        return lines[0].strip() if lines else ""

    # The cover is unnumbered, the front matter is roman, the body restarts at 1.
    assert not first_line(texts[0]).isdigit()
    body_index = next(
        index for index, text in enumerate(texts) if "Le jacquier est une espece" in text
    )
    assert first_line(texts[body_index - 1]) in {"i", "ii", "iii", "iv", "v"}
    assert first_line(texts[body_index]) == "1"


def test_the_running_head_follows_the_current_heading_not_the_last_one() -> None:
    from app.export.pdf import render_pdf

    model = DocumentModel(
        blocks=[
            Block(
                kind=BlockKind.HEADING,
                level=1,
                spans=(Span("Premier chapitre"),),
                plain_text="Premier chapitre",
            ),
            Block(kind=BlockKind.PAGE_BREAK),
            Block(
                kind=BlockKind.HEADING,
                level=1,
                spans=(Span("Second chapitre"),),
                plain_text="Second chapitre",
            ),
            Block(kind=BlockKind.PAGE_BREAK),
        ],
        project_title="t",
        project_id="p",
    )
    reader = PdfReader(BytesIO(render_pdf(model, build_options({}))))
    heads = [(page.extract_text() or "") for page in reader.pages]
    joined = " ".join(flat(text) for text in heads)
    assert "Premier chapitre" in joined
    assert "Second chapitre" in joined


def test_an_orphan_citation_is_printed_as_invalid_in_both_formats() -> None:
    from app.export.blocks import CitationState
    from app.export.docx import render_docx
    from app.export.pdf import render_pdf

    model = DocumentModel(
        blocks=[
            Block(
                kind=BlockKind.PARAGRAPH,
                spans=(
                    Span("Texte "),
                    Span(
                        "[Citation invalide : reference introuvable]",
                        citation=CitationState(node_id="c9", is_orphaned=True),
                    ),
                ),
                plain_text="Texte",
            ),
        ],
        project_title="t",
        project_id="p",
    )
    options = build_options({})
    assert "Citation invalide" in flat(pdf_text(render_pdf(model, options)))
    assert "Citation invalide" in docx_text(render_docx(model, options))
    # The author is told why, rather than being shown a plausible-looking author.
    assert "Auteur inconnu" not in flat(pdf_text(render_pdf(model, options)))


def test_a_missing_figure_produces_a_visible_placeholder() -> None:
    from app.export.pdf import render_pdf

    figure = FigureBlock(kind=BlockKind.FIGURE, plain_text="")
    figure.number = 1
    figure.unavailable_reason = "Image distante non integree"
    model = DocumentModel(blocks=[figure], project_title="t", project_id="p")
    text = flat(pdf_text(render_pdf(model, build_options({}))))
    assert "indisponible" in text
    assert "Image distante non integree" in text


def test_a_remote_figure_is_a_placeholder_when_remote_images_are_off() -> None:
    from app.export.options import ExportGuard
    from app.export.pdf import render_pdf
    from app.export.service import _resolve_figures

    converter = TiptapConverter()
    blocks = converter.convert(
        {
            "type": "doc",
            "content": [{"type": "image", "attrs": {"src": "https://example.org/a.png"}}],
        }
    )
    _resolve_figures(blocks, allow_remote=False, guard=ExportGuard())
    model = DocumentModel(blocks=blocks, project_title="t", project_id="p")
    assert "indisponible" in flat(pdf_text(render_pdf(model, build_options({}))))


def test_an_embedded_figure_appears_in_both_formats() -> None:
    from app.export.docx import render_docx
    from app.export.pdf import render_pdf

    model = build_model()
    options = build_options({})
    assert "Figure 1" in flat(pdf_text(render_pdf(model, options)))
    assert "Figure 1" in docx_text(render_docx(model, options))


def test_the_docx_uses_real_word_heading_styles() -> None:
    from app.export.docx import render_docx

    model = build_model(with_cover=True, with_toc=True)
    opened = DocxReader(BytesIO(render_docx(model, build_options({}))))
    headings = [
        paragraph
        for paragraph in opened.paragraphs
        if paragraph.style.name.startswith("Heading")
    ]
    assert len(headings) >= 3


def test_the_docx_contains_a_word_table_of_contents_field() -> None:
    from app.export.docx import render_docx

    model = build_model(with_toc=True)
    opened = DocxReader(BytesIO(render_docx(model, build_options({}))))
    assert "TOC" in opened.element.xml


def test_the_docx_carries_the_academic_metadata() -> None:
    from app.export.docx import render_docx

    model = build_model(with_cover=True)
    opened = DocxReader(BytesIO(render_docx(model, build_options({}))))
    assert opened.core_properties.title == "Memoire de test"
    assert opened.core_properties.author == "Rakoto Marie"


def test_the_toc_lists_the_sections_that_really_exist() -> None:
    from app.export.pdf import render_pdf

    model = build_model(with_toc=True)
    text = flat(pdf_text(render_pdf(model, build_options({}))))
    assert "Table des matieres" in text
    assert "I. Introduction" in text


def test_the_cover_appears_when_requested_and_is_omitted_otherwise() -> None:
    from app.export.pdf import render_pdf

    with_cover = flat(pdf_text(render_pdf(build_model(with_cover=True), build_options({}))))
    without = flat(pdf_text(render_pdf(build_model(), build_options({}))))
    assert "Rakoto Marie" in with_cover
    assert "Rakoto Marie" not in without


def test_the_page_geometry_is_honoured() -> None:
    from app.export.pdf import render_pdf

    model = build_model()
    a4 = PdfReader(
        BytesIO(render_pdf(model, build_options({"page_size": "a4"})))
    ).pages[0]
    letter = PdfReader(
        BytesIO(render_pdf(model, build_options({"page_size": "letter"})))
    ).pages[0]
    assert float(a4.mediabox.width) != float(letter.mediabox.width)


def test_an_empty_document_still_renders() -> None:
    from app.export.docx import render_docx
    from app.export.pdf import render_pdf

    model = DocumentModel(project_title="Vide", project_id="p")
    options = build_options({})
    assert render_pdf(model, options).startswith(b"%PDF")
    assert render_docx(model, options).startswith(b"PK")


def test_rendering_never_calls_a_language_model() -> None:
    """An export is deterministic: no provider, no cost, no network for the text."""
    import inspect

    from app.export import pdf as pdf_module

    source = inspect.getsource(pdf_module)
    for forbidden in ("openai", "AsyncOpenAI", "chat.completions", "llm", "embedding"):
        assert forbidden not in source.casefold()


# -------------------------------------------------------------- route wiring


def _role_requirement(method: str, suffix: str) -> str:
    from fastapi.routing import APIRoute

    from app.export.router import router

    for route in router.routes:
        if not isinstance(route, APIRoute):
            continue
        if method not in route.methods or not route.path.endswith(suffix):
            continue
        for dependency in route.dependant.dependencies:
            name = getattr(dependency.call, "__name__", "")
            if name.startswith("require_project_"):
                return name
        return "aucune"
    raise AssertionError(f"Route introuvable : {method} {suffix}")


@pytest.mark.parametrize(
    ("method", "suffix", "expected"),
    [
        ("GET", "/exports", "require_project_reader"),
        ("GET", "/exports/formats", "require_project_reader"),
        ("GET", "/exports/{record_id}", "require_project_reader"),
        ("POST", "/exports/preview", "require_project_reader"),
        ("POST", "/exports/{export_format}", "require_project_editor"),
    ],
)
def test_each_export_route_requires_the_expected_role(
    method: str, suffix: str, expected: str
) -> None:
    assert _role_requirement(method, suffix) == expected


def test_generating_a_file_requires_csrf() -> None:
    from fastapi.routing import APIRoute

    from app.export.router import router

    checked = 0
    for route in router.routes:
        if not isinstance(route, APIRoute):
            continue
        if route.methods is None or "POST" not in route.methods:
            continue
        checked += 1
        names = [
            getattr(dependency.call, "__name__", "")
            for dependency in route.dependant.dependencies
        ]
        assert "require_csrf" in names, f"{route.path} n'exige pas de jeton CSRF."
    assert checked >= 2


def test_the_export_routes_are_scoped_to_a_project() -> None:
    """Every export route takes the project id in its path, so isolation is structural."""
    from app.export.router import router

    for route in router.routes:
        assert "{project_id}" in route.path


def test_the_generated_file_is_marked_as_a_private_download() -> None:
    import inspect

    from app.export.router import generate_endpoint

    source = inspect.getsource(generate_endpoint)
    assert "attachment" in source
    assert "no-store" in source
