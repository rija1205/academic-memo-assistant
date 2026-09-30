"""Academic RAG engine: chunking, embeddings, pgvector retrieval, fusion and provenance.

This package performs retrieval only. It never calls a language model and never generates
text: it returns the passages a later writing assistant will be able to cite.
"""

from app.rag.settings import RagTuning, rag_tuning

__all__ = ["RagTuning", "rag_tuning"]
