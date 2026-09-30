"""Academic assistant built on the stage-6 RAG retrieval engine.

The assistant retrieves passages, gives them to a language model, and validates every citation
the model produced. It never invents a source and never answers without retrieved context.
"""

from app.assistant.llm import (
    LlmCompletion,
    LlmError,
    LlmMessage,
    LlmProvider,
    MockLlmProvider,
    OpenAiLlmProvider,
    build_llm_provider,
)

__all__ = [
    "LlmCompletion",
    "LlmError",
    "LlmMessage",
    "LlmProvider",
    "MockLlmProvider",
    "OpenAiLlmProvider",
    "build_llm_provider",
]
