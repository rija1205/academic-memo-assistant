"""Retrieval quality tests computed on the real labelled dataset.

These tests measure the quality of the retrieval stage end to end, in memory, with the
deterministic embedding provider. The numbers are computed from the passages that actually
exist in ``rag_dataset`` and from the relevance judgements written in that file. No score is
hard-coded or assumed.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.rag.embeddings import MockEmbeddingProvider, cosine_similarity
from app.rag.evaluation import (
    QualityReport,
    RankedPassage,
    RelevanceJudgement,
    Timer,
    evaluate,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)
from app.rag.search.retrieval import ScoredChunk, SourceDescriptor
from tests.rag_dataset import CORPUS, JUDGEMENTS, build_corpus_chunks

PROJECT_A = uuid4()
PROJECT_B = uuid4()
DIMENSION = 1024


def build_chunks() -> list[ScoredChunk]:
    """Chunk the corpus and embed every passage with the deterministic provider."""
    chunks: list[ScoredChunk] = []
    for document in CORPUS:
        document_id = uuid4()
        source_id = uuid4()
        for position, (key, text) in enumerate(
            build_corpus_chunks()[document.key]
        ):
            chunks.append(
                ScoredChunk(
                    chunk_id=document_id,
                    rag_document_id=document_id,
                    project_id=PROJECT_A,
                    source=SourceDescriptor(
                        id=source_id,
                        original_filename=f"{document.key}.pdf",
                        title=document.title,
                        authors=(document.author,),
                        publication_year=document.year,
                        publication_type=document.publication_type,
                    ),
                    text=text,
                    page_number=1,
                    block_start=position,
                    block_end=position,
                    chunk_index=position,
                    token_count=len(text.split()),
                    provenance_id=uuid4(),
                    vector_score=0.0,
                    metadata={"dataset_key": key},
                )
            )
    return chunks


def _chunks_with_vectors() -> list[tuple[ScoredChunk, list[float]]]:
    provider = MockEmbeddingProvider(dimension=DIMENSION, model="quality-eval")
    raw: list[tuple[ScoredChunk, list[float]]] = []
    for chunk in build_chunks():
        raw.append((chunk, provider.embed_query(chunk.text)))
    return raw


def retrieve_semantic(
    question: str, *, top_k: int, indexed: list[tuple[ScoredChunk, list[float]]]
) -> list[RankedPassage]:
    """Rank the corpus by cosine similarity against the question embedding."""
    provider = MockEmbeddingProvider(dimension=DIMENSION, model="quality-eval")
    query_vector = provider.embed_query(question)
    scored = [
        (chunk, cosine_similarity(query_vector, vector)) for chunk, vector in indexed
    ]
    scored.sort(key=lambda item: (-item[1], item[0].metadata["dataset_key"]))
    return [
        RankedPassage(key=chunk.metadata["dataset_key"], rank=position)
        for position, (chunk, _) in enumerate(scored[:top_k], start=1)
    ]


def test_precision_recall_and_rrf_on_the_labelled_dataset() -> None:
    indexed = _chunks_with_vectors()
    retrievals: dict[str, list[RankedPassage]] = {}
    for judgement in JUDGEMENTS:
        timer = Timer()
        retrievals[judgement.question] = retrieve_semantic(
            judgement.question, top_k=5, indexed=indexed
        )
        assert timer.elapsed_ms >= 0.0

    report = evaluate(JUDGEMENTS, retrievals, k=5)
    assert isinstance(report, QualityReport)
    assert len(report.cases) == len(JUDGEMENTS)
    assert 0.0 <= report.mean_precision_at_k <= 1.0
    assert 0.0 <= report.mean_recall_at_k <= 1.0
    assert 0.0 <= report.mean_reciprocal_rank <= 1.0
    assert 0.0 <= report.mean_ndcg_at_k <= 1.0


def test_semantic_retrieval_finds_every_labelled_answer_in_the_top_three() -> None:
    """The engine must actually retrieve the passages a human labelled as correct."""
    indexed = _chunks_with_vectors()
    for judgement in JUDGEMENTS:
        ranked = retrieve_semantic(judgement.question, top_k=3, indexed=indexed)
        retrieved = {passage.key for passage in ranked}
        assert judgement.relevant_keys & retrieved, (
            f"aucun passage pertinent retrouve pour : {judgement.question}"
        )


def test_quality_metrics_match_the_measured_values() -> None:
    """Assert the metrics actually measured on the labelled dataset.

    The expected values below are the numbers this dataset produces with the deterministic
    provider and a top-3 retrieval. They are not targets chosen in advance: if the chunker,
    the dataset or the retrieval changes, these assertions move with it and must be updated
    deliberately rather than silently.
    """
    indexed = _chunks_with_vectors()
    retrievals = {
        judgement.question: retrieve_semantic(judgement.question, top_k=3, indexed=indexed)
        for judgement in JUDGEMENTS
    }
    report = evaluate(JUDGEMENTS, retrievals, k=3)
    # One labelled question expects two passages and only one fits in the top 3.
    assert report.mean_recall_at_k == pytest.approx(0.9, abs=0.001)
    assert 0.0 < report.mean_precision_at_k < 1.0
    assert report.mean_reciprocal_rank == pytest.approx(0.633, abs=0.01)
    assert 0.0 < report.mean_ndcg_at_k < 1.0


def test_latency_is_measured_per_case() -> None:
    indexed = _chunks_with_vectors()
    judgements = list(JUDGEMENTS)
    retrievals: dict[str, list[RankedPassage]] = {}
    latencies: dict[str, float] = {}
    for judgement in judgements:
        timer = Timer()
        retrievals[judgement.question] = retrieve_semantic(
            judgement.question, top_k=3, indexed=indexed
        )
        latencies[judgement.question] = timer.elapsed_ms
    report = evaluate(JUDGEMENTS, retrievals, k=3, latencies_ms=latencies)
    assert report.max_latency_ms > 0.0
    assert report.mean_latency_ms > 0.0


def test_metric_functions_on_known_rankings() -> None:
    ranked = [
        RankedPassage(key="a", rank=1),
        RankedPassage(key="b", rank=2),
        RankedPassage(key="c", rank=3),
    ]
    relevant = frozenset({"b"})
    assert precision_at_k(ranked, relevant, 2) == 0.5
    assert recall_at_k(ranked, relevant, 3) == 1.0
    assert reciprocal_rank(ranked, relevant) == 0.5
    # The only relevant passage sits at rank 2: DCG = 1/log2(3), IDCG = 1/log2(2).
    assert ndcg_at_k(ranked, relevant, 3) == pytest.approx(0.6309297536, rel=1e-3)


def test_metrics_detect_a_perfect_and_a_failed_run() -> None:
    relevant = frozenset({"target"})
    perfect = [RankedPassage(key="target", rank=1)]
    failed = [RankedPassage(key="other", rank=1)]
    assert precision_at_k(perfect, relevant, 3) == 1.0
    assert recall_at_k(perfect, relevant, 3) == 1.0
    assert reciprocal_rank(perfect, relevant) == 1.0
    assert ndcg_at_k(perfect, relevant, 3) == 1.0
    assert precision_at_k(failed, relevant, 3) == 0.0
    assert recall_at_k(failed, relevant, 3) == 0.0
    assert reciprocal_rank(failed, relevant) == 0.0
    assert ndcg_at_k(failed, relevant, 3) == 0.0


def test_a_judgement_without_retrieval_scores_zero() -> None:
    judgement = RelevanceJudgement(
        question="Question sans resultat", relevant_keys=frozenset({"x"})
    )
    report = evaluate([judgement], {}, k=3)
    assert report.mean_recall_at_k == 0.0
    assert report.mean_precision_at_k == 0.0


def test_dataset_chunks_are_unique_and_non_empty() -> None:
    corpus = build_corpus_chunks()
    all_keys = [key for passages in corpus.values() for key, _ in passages]
    assert len(all_keys) == len(set(all_keys))
    assert all(text.strip() for passages in corpus.values() for _, text in passages)
    assert len(corpus) == len(CORPUS)
