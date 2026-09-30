"""Labelled retrieval dataset used by the RAG quality tests.

The corpus, the passages and the expected answers below are the actual test data: the metrics
computed in ``test_rag_quality.py`` are derived from these texts, not from invented numbers.
The topic (the African plant *Parkia biglobosa*, commonly called jacquier) provides a realistic
academic setting with several clearly separable subjects.

Chunk keys are ``"{document_key}:b{first_block_index}"`` so a judgement always points at a
real passage of the chunked corpus.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import NAMESPACE_DNS, uuid5

from app.rag.chunking import AcademicChunker, SourceBlockInput
from app.rag.evaluation import RelevanceJudgement


@dataclass(frozen=True, slots=True)
class Document:
    """One labelled source of the evaluation corpus."""

    key: str
    title: str
    author: str
    year: int
    publication_type: str
    pages: tuple[tuple[int, tuple[tuple[int, str, str], ...]], ...]
    """pages -> tuple of (block_index, block_type, text)"""

    def blocks(self) -> list[SourceBlockInput]:
        namespace = uuid5(NAMESPACE_DNS, f"rag-dataset:{self.key}")
        return [
            SourceBlockInput(
                provenance_id=uuid5(namespace, str(index)),
                page_number=page,
                block_index=index,
                block_type=block_type,
                text=text,
                position_start=index * 10,
                position_end=index * 10 + len(text),
            )
            for page, entries in self.pages
            for index, block_type, text in entries
        ]


CORPUS: tuple[Document, ...] = (
    Document(
        key="jacquier-nutrition",
        title="Composition nutritionnelle du grain de Parkia biglobosa",
        author="A. Nkolo",
        year=2024,
        publication_type="article",
        pages=(
            (
                1,
                (
                    (0, "heading", "Composition nutritionnelle"),
                    (
                        1,
                        "paragraph",
                        "Le grain de jacquier est riche en proteines vegetales. "
                        "La teneur en proteines brutes atteint 15 pour cent de la matiere seche. "
                        "Les lipides representent environ 7 pour cent du poids sec.",
                    ),
                    (
                        2,
                        "paragraph",
                        "La fraction glucidique est constituee principalement d'amidon resistant. "
                        "Les fibres alimentaires totales representent 20 pour cent du grain. "
                        "Ce taux de fibres est comparable a celui du haricot commun.",
                    ),
                ),
            ),
            (
                2,
                (
                    (3, "heading", "Micromineraux"),
                    (
                        4,
                        "paragraph",
                        "Le jacquier est une source notable de fer, de zinc et de magnesium. "
                        "Le fer non heme est faiblement biodisponible pour l organisme humain. "
                        "La vitamine B1 est presente en quantite non negligeable.",
                    ),
                ),
            ),
        ),
    ),
    Document(
        key="stabilisation-urbaine",
        title="Stabilisation urbaine et gouvernance territoriale en Amerique latine",
        author="M. Ribeiro",
        year=2021,
        publication_type="article",
        pages=(
            (
                1,
                (
                    (0, "heading", "Contexte"),
                    (
                        1,
                        "paragraph",
                        "Les politiques de stabilisation urbaine en Amerique latine ont ete "
                        "reformulees depuis les annees 2000. "
                        "Les collectivites ont obtenu des competences elargies.",
                    ),
                    (
                        2,
                        "paragraph",
                        "La gouvernance territoriale repose sur la negociation "
                        "entre acteurs locaux. "
                        "Les budgets participatifs constituent un instrument central de cette "
                        "negociation et sont voted chaque annee.",
                    ),
                ),
            ),
        ),
    ),
    Document(
        key="transformation-jacquier",
        title="Transformation alimentaire du jacquier et valorisation de la graine",
        author="B. Sow",
        year=2023,
        publication_type="conference",
        pages=(
            (
                1,
                (
                    (0, "heading", "Transformation"),
                    (
                        1,
                        "paragraph",
                        "La fermentation du grain de jacquier reduit les facteurs "
                        "antinutritionnels. "
                        "Les produits de fermentation sont utilises dans la production "
                        "de sauces et de boissons pour nourrissons.",
                    ),
                    (
                        2,
                        "paragraph",
                        "Le procede de transformation fait intervenir un melange "
                        "microbien specifique. "
                        "La duree de fermentation influence directement la qualite nutritionnelle "
                        "du produit obtenu.",
                    ),
                ),
            ),
        ),
    ),
)

#: Questions with the passage keys a human would judge relevant.
JUDGEMENTS: tuple[RelevanceJudgement, ...] = (
    RelevanceJudgement(
        question="Quels sont les composants nutritionnels du grain de jacquier ?",
        relevant_keys=frozenset({"jacquier-nutrition:b1"}),
        note="Les macromolecules du grain sont decrites en page 1.",
    ),
    RelevanceJudgement(
        question="Quelle est la teneur en fibres alimentaires du jacquier ?",
        relevant_keys=frozenset({"jacquier-nutrition:b2"}),
        note="Le taux de fibres de 20 pour cent est donne en page 1.",
    ),
    RelevanceJudgement(
        question="Quels micromineraux contient le grain de jacquier ?",
        relevant_keys=frozenset({"jacquier-nutrition:b4"}),
        note="Fer, zinc et magnesium sont traites en page 2.",
    ),
    RelevanceJudgement(
        question="Comment le jacquier est-il transforme pour la consommation ?",
        relevant_keys=frozenset({"transformation-jacquier:b1", "transformation-jacquier:b2"}),
        note="La fermentation et le procede sont decrits en page 1.",
    ),
    RelevanceJudgement(
        question="Comment les budgets participatifs sont-ils utilises en Amerique latine ?",
        relevant_keys=frozenset({"stabilisation-urbaine:b2"}),
        note="Les budgets participatifs apparaissent dans le contexte de gouvernance.",
    ),
)


def build_corpus_chunks(
    *, max_tokens: int = 80, overlap_tokens: int = 15, min_tokens: int = 10
) -> dict[str, list[tuple[str, str]]]:
    """Chunk the corpus and return ``document_key -> [(chunk_key, text), ...]``."""
    chunker = AcademicChunker(
        max_tokens=max_tokens, overlap_tokens=overlap_tokens, min_tokens=min_tokens
    )
    corpus: dict[str, list[tuple[str, str]]] = {}
    for document in CORPUS:
        chunks = chunker.chunk(document.blocks())
        corpus[document.key] = [
            (f"{document.key}:b{chunk.block_start}", chunk.text) for chunk in chunks
        ]
    return corpus


def flat_passages() -> list[tuple[str, str]]:
    """All labelled passages as ``(key, text)`` pairs."""
    return [
        (key, text)
        for passages in build_corpus_chunks().values()
        for key, text in passages
    ]
