"""Single source of truth for every RAG tunable.

The embedding dimension, the chunking parameters and the retrieval strategy all live in
`app.core.config.Settings`. This module only exposes derived helpers so that models,
migrations, the pipeline and the search layer can never disagree on the vector size.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings, get_settings

#: Semantic meaning of the RAG document states, kept in one place.
RAG_STATUS_PENDING = "pending"
RAG_STATUS_CHUNKING = "chunking"
RAG_STATUS_EMBEDDING = "embedding"
RAG_STATUS_INDEXED = "indexed"
RAG_STATUS_FAILED = "failed"

RAG_STATUSES = (
    RAG_STATUS_PENDING,
    RAG_STATUS_CHUNKING,
    RAG_STATUS_EMBEDDING,
    RAG_STATUS_INDEXED,
    RAG_STATUS_FAILED,
)

#: Strategy identifiers accepted by the search API.
STRATEGY_SEMANTIC = "semantic"
STRATEGY_LEXICAL = "lexical"
STRATEGY_HYBRID = "hybrid"

FUSION_RRF = "rrf"
FUSION_NORMALIZED = "normalized"


@dataclass(frozen=True, slots=True)
class RagTuning:
    """Immutable snapshot of the RAG configuration used by one operation."""

    embedding_provider: str
    embedding_model: str
    embedding_dimension: int
    embedding_batch_size: int
    embedding_version: str
    chunking_version: str
    chunk_max_tokens: int
    chunk_overlap_tokens: int
    chunk_min_tokens: int
    strategy: str
    fusion_method: str
    rrf_k: int
    rrf_weight_vector: float
    rrf_weight_lexical: float
    candidate_multiplier: int
    text_search_config: str
    price_per_million_tokens_usd: float

    @property
    def index_signature(self) -> str:
        """Identity of an index build.

        Two documents may share an index only when every dimension that influences the
        stored vectors or the chunk boundaries is identical.
        """
        return (
            f"{self.embedding_provider}:{self.embedding_model}"
            f":{self.embedding_dimension}:{self.embedding_version}"
            f":{self.chunking_version}:{self.chunk_max_tokens}"
            f":{self.chunk_overlap_tokens}:{self.chunk_min_tokens}"
        )


def rag_tuning(settings: Settings | None = None) -> RagTuning:
    """Build the tuning snapshot from validated settings."""
    resolved = settings or get_settings()
    return RagTuning(
        embedding_provider=resolved.embedding_provider,
        embedding_model=resolved.embedding_model,
        embedding_dimension=resolved.embedding_dimension,
        embedding_batch_size=resolved.embedding_batch_size,
        embedding_version=resolved.embedding_version,
        chunking_version=resolved.chunking_version,
        chunk_max_tokens=resolved.chunk_max_tokens,
        chunk_overlap_tokens=resolved.chunk_overlap_tokens,
        chunk_min_tokens=resolved.chunk_min_tokens,
        strategy=resolved.rag_search_strategy,
        fusion_method=resolved.rag_fusion_method,
        rrf_k=resolved.rag_rrf_k,
        rrf_weight_vector=resolved.rag_rrf_weight_vector,
        rrf_weight_lexical=resolved.rag_rrf_weight_lexical,
        candidate_multiplier=resolved.rag_candidate_multiplier,
        text_search_config=resolved.rag_text_search_config,
        price_per_million_tokens_usd=resolved.embedding_price_per_million_tokens_usd,
    )
