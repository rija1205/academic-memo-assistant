"""Retrieval primitives for the academic RAG index."""

from app.rag.search.retrieval import (
    LexicalOverlapReranker,
    RagFilters,
    RerankerProvider,
    ScoredChunk,
    SearchOutcome,
    SourceDescriptor,
    build_filter_conditions,
    build_reranker,
    hybrid_search,
    lexical_search,
    normalized_score_fusion,
    reciprocal_rank_fusion,
    semantic_search,
)

__all__ = [
    "LexicalOverlapReranker",
    "RagFilters",
    "RerankerProvider",
    "ScoredChunk",
    "SearchOutcome",
    "SourceDescriptor",
    "build_filter_conditions",
    "build_reranker",
    "hybrid_search",
    "lexical_search",
    "normalized_score_fusion",
    "reciprocal_rank_fusion",
    "semantic_search",
]
