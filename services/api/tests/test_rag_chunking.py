"""Unit tests for the academic chunker."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.rag.chunking import (
    AcademicChunker,
    SourceBlockInput,
    estimate_tokens,
    split_sentences,
)


def block(
    index: int,
    text: str,
    *,
    page: int = 1,
    block_type: str = "paragraph",
) -> SourceBlockInput:
    return SourceBlockInput(
        provenance_id=uuid4(),
        page_number=page,
        block_index=index,
        block_type=block_type,
        text=text,
        position_start=index * 100,
        position_end=index * 100 + len(text),
    )


def test_sentence_split_protects_abbreviations_and_decimals() -> None:
    sentences = split_sentences("Le taux est de 3.14 g. Voir fig. 2 p. 5 etc. Fin.")
    assert sentences == ["Le taux est de 3.14 g.", "Voir fig. 2 p. 5 etc.", "Fin."]


def test_small_document_produces_a_single_chunk() -> None:
    chunker = AcademicChunker(max_tokens=200, overlap_tokens=20, min_tokens=10)
    chunks = chunker.chunk([block(0, "Un petit paragraphe academique.")])
    assert len(chunks) == 1
    assert chunks[0].token_count <= 200
    assert chunks[0].page_number == 1


def test_long_document_respects_max_tokens() -> None:
    sentences = " ".join(
        f"La phrase numero {index} contient plusieurs mots academiques." for index in range(120)
    )
    chunker = AcademicChunker(max_tokens=60, overlap_tokens=15, min_tokens=10)
    chunks = chunker.chunk([block(0, sentences)])
    assert len(chunks) > 1
    assert all(chunk.token_count <= 60 for chunk in chunks)
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))


def test_overlap_repeats_content_between_consecutive_chunks() -> None:
    sentences = " ".join(
        f"Sequence deterministe {index} de mots academiques." for index in range(60)
    )
    chunker = AcademicChunker(max_tokens=50, overlap_tokens=25, min_tokens=5)
    chunks = chunker.chunk([block(0, sentences)])
    assert len(chunks) >= 2
    first_tail = set(chunks[0].text.split()[-6:])
    second_head = set(chunks[1].text.split()[:6])
    assert first_tail & second_head, "l'overlap doit partager des mots entre chunks"


def test_chunks_never_cross_page_boundaries() -> None:
    blocks = [
        block(0, "Contenu de la page un.", page=1),
        block(1, "Contenu de la page deux.", page=2),
    ]
    chunker = AcademicChunker(max_tokens=500, overlap_tokens=10, min_tokens=5)
    chunks = chunker.chunk(blocks)
    assert [chunk.page_number for chunk in chunks] == [1, 2]


def test_heading_is_carried_as_context_and_never_forms_a_chunk() -> None:
    blocks = [
        block(0, "Composition nutritionnelle", block_type="heading"),
        block(1, "Le grain contient des fibres."),
    ]
    chunker = AcademicChunker(max_tokens=200, overlap_tokens=10, min_tokens=5)
    chunks = chunker.chunk(blocks)
    assert len(chunks) == 1
    assert chunks[0].heading_path == ("Composition nutritionnelle",)
    assert "Composition nutritionnelle" in chunks[0].text
    assert chunks[0].block_start == 1


def test_heading_can_be_excluded_from_text_but_kept_in_metadata() -> None:
    blocks = [
        block(0, "Composition nutritionnelle", block_type="heading"),
        block(1, "Le grain contient des fibres."),
    ]
    chunker = AcademicChunker(
        max_tokens=200, overlap_tokens=10, min_tokens=5, include_heading_in_text=False
    )
    chunks = chunker.chunk(blocks)
    assert "Composition nutritionnelle" not in chunks[0].text
    assert chunks[0].heading_path == ("Composition nutritionnelle",)


def test_oversized_sentence_is_split_and_flagged() -> None:
    huge = " ".join(["mot"] * 800)
    chunker = AcademicChunker(max_tokens=50, overlap_tokens=5, min_tokens=5)
    chunks = chunker.chunk([block(0, huge)])
    assert len(chunks) > 1
    assert all(chunk.sentence_split for chunk in chunks)
    assert all(chunk.token_count <= 50 for chunk in chunks)


def test_provenance_id_comes_from_the_first_block() -> None:
    first = block(0, "Premier bloc de la page.")
    second = block(1, "Deuxieme bloc de la page.")
    chunker = AcademicChunker(max_tokens=500, overlap_tokens=10, min_tokens=5)
    chunks = chunker.chunk([first, second])
    assert chunks[0].provenance_id == first.provenance_id
    assert chunks[0].block_start == 0
    assert chunks[0].block_end == 1


def test_undersized_trailing_chunk_is_flagged_not_merged() -> None:
    """A too-small tail is flagged, never merged: merging would break a section boundary."""
    long_text = " ".join(f"Phrase complete numero {index}." for index in range(40))
    blocks = [block(0, long_text), block(1, "Mot.")]
    chunker = AcademicChunker(max_tokens=200, overlap_tokens=10, min_tokens=20)
    chunks = chunker.chunk(blocks)
    assert len(chunks) >= 1
    tail = chunks[-1]
    if tail.token_count < 20:
        assert tail.metadata.get("undersized") is True
    else:
        assert "undersized" not in tail.metadata


def test_estimate_tokens_is_deterministic_and_positive() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("a") == 1
    assert estimate_tokens("mots academiques") == estimate_tokens("mots academiques")
    assert estimate_tokens("un deux trois") > 0


def test_invalid_chunk_parameters_are_rejected() -> None:
    with pytest.raises(ValueError):
        AcademicChunker(max_tokens=100, overlap_tokens=100, min_tokens=10)
    with pytest.raises(ValueError):
        AcademicChunker(max_tokens=100, overlap_tokens=10, min_tokens=0)
