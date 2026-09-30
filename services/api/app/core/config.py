from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Academic Memo Assistant API"
    app_env: str = "development"
    version: str = "0.1.0"
    secret_key: str = Field(default="replace-this-development-secret", min_length=16)
    log_level: str = "INFO"
    database_url: str = (
        "postgresql+asyncpg://academic_memo:academic_memo_dev@localhost:5432/academic_memo"
    )
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"
    cors_origins: str = "http://localhost:3000"
    frontend_url: str = "http://localhost:3000"

    session_cookie_name: str = "ama_session"
    csrf_cookie_name: str = "ama_csrf"
    oauth_state_cookie_name: str = "ama_google_oauth"
    session_ttl_days: int = Field(default=30, ge=1, le=365)
    oauth_state_ttl_seconds: int = Field(default=600, ge=60, le=3600)
    secure_cookies: bool = False
    auth_expose_reset_token: bool = False
    auth_rate_limit_enabled: bool = True
    auth_rate_limit_max_attempts: int = Field(default=10, ge=1, le=100)
    auth_rate_limit_window_seconds: int = Field(default=900, ge=60, le=86400)

    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:3000/api/backend/auth/google/callback"
    google_oauth_scopes: str = "openid email profile"

    source_processing_mode: str = "async"
    source_max_upload_bytes: int = Field(default=52_428_800, ge=1_048_576, le=536_870_912)
    source_local_storage_path: str = "./var/source-storage"
    source_storage_provider: str = "local"
    source_worker_token: str = ""
    source_ocr_provider: str = "none"
    s3_endpoint_url: str = ""
    s3_region: str = "us-east-1"
    s3_bucket: str = "academic-memo"
    s3_access_key: str = ""
    s3_secret_key: str = ""

    # Stage 6 - academic RAG (retrieval only; no language-model generation).
    embedding_provider: str = "mock"
    embedding_model: str = "mock-hash-1536"
    embedding_dimension: int = Field(default=1536, ge=64, le=8192)
    embedding_batch_size: int = Field(default=64, ge=1, le=512)
    embedding_api_key: str = ""
    embedding_api_base_url: str = "https://api.openai.com/v1"
    embedding_request_timeout_seconds: int = Field(default=60, ge=5, le=600)
    embedding_max_retries: int = Field(default=2, ge=0, le=10)
    embedding_version: str = "v1"
    embedding_price_per_million_tokens_usd: float = Field(default=0.0, ge=0.0)

    chunking_version: str = "v1"
    chunk_max_tokens: int = Field(default=900, ge=64, le=8000)
    chunk_overlap_tokens: int = Field(default=120, ge=0, le=2000)
    chunk_min_tokens: int = Field(default=40, ge=1, le=2000)

    rag_search_strategy: str = "hybrid"
    rag_fusion_method: str = "rrf"
    rag_rrf_k: int = Field(default=60, ge=1, le=1000)
    rag_default_top_k: int = Field(default=10, ge=1, le=100)
    rag_max_top_k: int = Field(default=50, ge=1, le=200)
    rag_candidate_multiplier: int = Field(default=4, ge=1, le=20)
    rag_text_search_config: str = "simple"
    rag_rrf_weight_vector: float = Field(default=1.0, ge=0.0, le=10.0)
    rag_rrf_weight_lexical: float = Field(default=1.0, ge=0.0, le=10.0)

    reranker_provider: str = "none"
    reranker_model: str = ""
    reranker_api_key: str = ""
    reranker_api_base_url: str = "https://api.openai.com/v1"
    reranker_max_documents: int = Field(default=50, ge=1, le=200)

    # Stage 7 - academic assistant (retrieval-augmented generation, RAG only as context).
    llm_provider: str = "mock"
    llm_model: str = "gpt-4o-mini"
    llm_api_key: str = ""
    llm_api_base_url: str = "https://api.openai.com/v1"
    llm_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    llm_max_output_tokens: int = Field(default=900, ge=64, le=32000)
    llm_timeout_seconds: int = Field(default=90, ge=5, le=600)
    llm_max_retries: int = Field(default=2, ge=0, le=10)
    llm_price_input_per_million_tokens_usd: float = Field(default=0.0, ge=0.0)
    llm_price_output_per_million_tokens_usd: float = Field(default=0.0, ge=0.0)

    assistant_max_input_tokens: int = Field(default=12000, ge=1000, le=200000)
    assistant_max_history_messages: int = Field(default=10, ge=2, le=60)
    assistant_top_k: int = Field(default=8, ge=1, le=30)
    assistant_min_context_score: float = Field(default=0.0, ge=0.0, le=10.0)
    assistant_max_questions_per_minute: int = Field(default=10, ge=1, le=120)
    assistant_max_daily_tokens: int = Field(default=200000, ge=1000, le=10000000)
    assistant_max_question_length: int = Field(default=4000, ge=10, le=20000)
    assistant_rate_limit_enabled: bool = True

    # Stage 8 - assisted writing. The model proposes; the author applies.
    writing_top_k: int = Field(default=8, ge=1, le=30)
    writing_max_selection_chars: int = Field(default=20000, ge=100, le=200000)
    writing_max_section_chars: int = Field(default=60000, ge=1000, le=400000)
    writing_max_instruction_chars: int = Field(default=1000, ge=10, le=10000)

    # Stage 9 - bibliography. Import payloads are untrusted, so they are bounded.
    bibliography_max_import_bytes: int = Field(default=2_097_152, ge=1024, le=52_428_800)
    bibliography_max_import_entries: int = Field(default=2000, ge=1, le=20000)
    bibliography_max_export_references: int = Field(default=1000, ge=1, le=20000)

    # Stage 11 - exports. The size limit protects the API from a memoir that would produce an
    # unreasonably large file; it is checked before the response is streamed.
    export_max_output_bytes: int = Field(default=209_715_200, ge=1_048_576, le=1_073_741_824)
    export_timeout_seconds: int = Field(default=300, ge=10, le=1800)
    # Remote images are never fetched unless this is explicitly enabled, because fetching a
    # URL supplied by an author is a server-side request forgery vector.
    export_allow_remote_images: bool = Field(default=False)

    # Stage 13 - request budgets. Separate from the authentication limiter: this one bounds
    # how much work a caller may ask for on the expensive routes, so a script cannot turn an
    # export endpoint into a denial of service.
    rate_limit_enabled: bool = Field(default=True)
    # When True, an unreachable Redis makes the protected routes answer 503 rather than serve
    # them unprotected. A limiter that silently fails open is not a limiter.
    rate_limit_fail_closed: bool = Field(default=True)
    rate_limit_window_seconds: int = Field(default=60, ge=5, le=3600)
    export_rate_limit_max_calls: int = Field(default=20, ge=1, le=1000)
    rag_rate_limit_max_calls: int = Field(default=60, ge=1, le=5000)
    assistant_rate_limit_max_calls: int = Field(default=30, ge=1, le=1000)
    writing_rate_limit_max_calls: int = Field(default=30, ge=1, le=1000)
    audit_rate_limit_max_calls: int = Field(default=30, ge=1, le=1000)
    import_rate_limit_max_calls: int = Field(default=20, ge=1, le=1000)
    write_rate_limit_max_calls: int = Field(default=180, ge=1, le=10000)
    # Security headers. force_https is for a deployment behind a proxy that terminates TLS.
    force_https: bool = Field(default=False)
    hsts_max_age: int = Field(default=31_536_000, ge=0, le=63_072_000)

    @property
    def cors_origin_list(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.cors_origins.split(",")
            if origin.strip()
        ]

    @property
    def cookie_secure(self) -> bool:
        return self.secure_cookies or self.app_env.casefold() == "production"

    @model_validator(mode="after")
    def validate_settings(self) -> "Settings":
        self._validate_rag_configuration()
        self._validate_llm_configuration()
        if self.app_env.casefold() != "production":
            return self

        if self.secret_key == "replace-this-development-secret" or len(self.secret_key) < 32:
            raise ValueError("A strong SECRET_KEY is required in production.")
        if self.auth_expose_reset_token:
            raise ValueError("AUTH_EXPOSE_RESET_TOKEN must be disabled in production.")
        if not self.auth_rate_limit_enabled:
            raise ValueError("Authentication rate limiting must be enabled in production.")
        if not self.frontend_url.startswith("https://"):
            raise ValueError("FRONTEND_URL must use HTTPS in production.")
        origins = self.cors_origin_list
        if not origins or any(not origin.startswith("https://") for origin in origins):
            raise ValueError("CORS origins must be explicit HTTPS origins in production.")
        if self.google_client_id and not self.google_redirect_uri.startswith("https://"):
            raise ValueError("Google OAuth redirect URI must use HTTPS in production.")
        if self.source_storage_provider not in {"local", "s3"}:
            raise ValueError("SOURCE_STORAGE_PROVIDER must be local or s3.")
        if self.source_processing_mode not in {"async", "sync"}:
            raise ValueError("SOURCE_PROCESSING_MODE must be async or sync.")
        if self.source_processing_mode == "async" and not self.source_worker_token:
            raise ValueError("SOURCE_WORKER_TOKEN is required for asynchronous processing.")
        if self.source_storage_provider == "s3" and not self.s3_endpoint_url:
            raise ValueError("S3_ENDPOINT_URL is required when SOURCE_STORAGE_PROVIDER=s3.")
        return self

    def index_signature_components(self) -> dict[str, object]:
        """Values that define an RAG index build. Any change invalidates existing vectors."""
        return {
            "embedding_provider": self.embedding_provider,
            "embedding_model": self.embedding_model,
            "embedding_dimension": self.embedding_dimension,
            "embedding_version": self.embedding_version,
            "chunking_version": self.chunking_version,
            "chunk_max_tokens": self.chunk_max_tokens,
            "chunk_overlap_tokens": self.chunk_overlap_tokens,
            "chunk_min_tokens": self.chunk_min_tokens,
        }

    def _validate_rag_configuration(self) -> None:
        """Validate RAG settings. The embedding dimension is defined exactly once, here."""
        if self.embedding_provider not in {"mock", "openai"}:
            raise ValueError("EMBEDDING_PROVIDER must be mock or openai.")
        if self.embedding_provider == "openai" and not self.embedding_api_key:
            raise ValueError("EMBEDDING_API_KEY is required when EMBEDDING_PROVIDER=openai.")
        if self.embedding_provider == "openai" and self.embedding_model == "mock-hash-1536":
            raise ValueError("EMBEDDING_MODEL must be a real model when EMBEDDING_PROVIDER=openai.")
        if self.chunk_overlap_tokens >= self.chunk_max_tokens:
            raise ValueError("CHUNK_OVERLAP_TOKENS must be lower than CHUNK_MAX_TOKENS.")
        if self.chunk_min_tokens > self.chunk_max_tokens:
            raise ValueError("CHUNK_MIN_TOKENS must be lower than CHUNK_MAX_TOKENS.")
        if self.rag_search_strategy not in {"semantic", "lexical", "hybrid"}:
            raise ValueError("RAG_SEARCH_STRATEGY must be semantic, lexical or hybrid.")
        if self.rag_fusion_method not in {"rrf", "normalized"}:
            raise ValueError("RAG_FUSION_METHOD must be rrf or normalized.")
        if self.reranker_provider not in {"none", "mock"}:
            raise ValueError("RERANKER_PROVIDER must be none or mock at this stage.")
        if self.rag_default_top_k > self.rag_max_top_k:
            raise ValueError("RAG_DEFAULT_TOP_K must be lower than RAG_MAX_TOP_K.")
        if self.app_env.casefold() == "production" and self.embedding_provider == "mock":
            raise ValueError(
                "A production deployment must use a real EMBEDDING_PROVIDER, not mock."
            )
        if not self.index_signature_components():
            raise ValueError("Index signature components cannot be empty.")

    def _validate_llm_configuration(self) -> None:
        """Validate the assistant configuration. The API key never leaves the backend."""
        if self.llm_provider not in {"openai", "mock"}:
            raise ValueError("LLM_PROVIDER must be openai or mock at this stage.")
        if self.llm_provider == "openai" and not self.llm_api_key:
            raise ValueError("LLM_API_KEY is required when LLM_PROVIDER=openai.")
        if not self.llm_model:
            raise ValueError("LLM_MODEL must not be empty.")
        if self.assistant_min_context_score < 0:
            raise ValueError("ASSISTANT_MIN_CONTEXT_SCORE cannot be negative.")
        if self.assistant_top_k > 30:
            raise ValueError("ASSISTANT_TOP_K must be lower than or equal to 30.")
        if self.llm_max_output_tokens > self.assistant_max_input_tokens:
            raise ValueError(
                "LLM_MAX_OUTPUT_TOKENS must be lower than ASSISTANT_MAX_INPUT_TOKENS."
            )
        if self.app_env.casefold() == "production" and self.llm_provider == "mock":
            raise ValueError(
                "A production deployment must use a real LLM_PROVIDER, not mock."
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
