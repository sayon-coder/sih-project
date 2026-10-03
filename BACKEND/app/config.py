"""
Configuration management for IP-SAKTI Sahayak Backend.
Centralized configuration using environment variables.
"""
from pydantic_settings import BaseSettings
from typing import List
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database
    database_url: str

    # JWT Configuration
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # CORS
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # Demo Mode
    demo_mode: bool = False

    # -------------------------------------------------------
    # LLM Configuration
    # -------------------------------------------------------
    llm_provider: str = "groq"          # groq | openai | gemini
    llm_model: str = "llama-3.3-70b-versatile"  # Groq model name
    groq_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""

    # Sarvam AI fallback (used for normal responses when the primary fails).
    # Empty sarvam_api_key disables the fallback.
    sarvam_api_key: str = ""
    sarvam_model: str = "sarvam-105b-conversations"

    # -------------------------------------------------------
    # Embedding Configuration
    # -------------------------------------------------------
    embedding_provider: str = "sentence-transformers"
    embedding_model: str = "BAAI/bge-m3"
    embedding_dimension: int = 1024     # BGE-M3 dense dimension
    # Optional HuggingFace token, used by sentence-transformers when downloading
    # or accessing a gated model. Left empty when not needed.
    hf_token: str = ""

    # -------------------------------------------------------
    # RAG Configuration
    # -------------------------------------------------------
    rag_chunk_size: int = 800           # tokens per chunk
    rag_chunk_overlap: int = 120        # token overlap between chunks
    rag_top_k_retrieval: int = 20       # candidates from each search arm
    rag_rerank_top_k: int = 6           # final chunks after reranking
    rag_min_similarity: float = 0.30    # minimum cosine similarity threshold

    # -------------------------------------------------------
    # File Upload
    # -------------------------------------------------------
    max_upload_size_mb: int = 25
    upload_dir: str = "data/uploads"

    # -------------------------------------------------------
    # Reports (Phase 8b)
    # -------------------------------------------------------
    reports_dir: str = "data/reports"
    public_base_url: str = "http://localhost:8000"

    # -------------------------------------------------------
    # BHASHINI (Phase 11)
    # -------------------------------------------------------
    bhashini_api_key: str = ""
    bhashini_base_url: str = ""

    # -------------------------------------------------------
    # Privacy / DPDP-aligned retention (privacy layer)
    # -------------------------------------------------------
    # Version stamped on every consent record. Bump this whenever the
    # privacy notice text changes so old consents stay attributable to the
    # notice the data principal actually saw.
    privacy_notice_version: str = "2026-09-1"
    # Retention windows in days. 0 = keep forever (never purge).
    # AUDIT_RETENTION_DAYS defaults to 0 on purpose: the audit trail is
    # evidence, so purging it is an explicit operator decision.
    chat_retention_days: int = 0
    upload_retention_days: int = 0
    audit_retention_days: int = 0
    # Default validity of a granted source permission (paid connectors).
    source_consent_default_days: int = 365
    # Per-dataset cap applied to GET /api/privacy/export.
    export_max_items: int = 50000

    # Developer-only diagnostics. When false (the default, and what
    # production runs with) no debug payload is ever added to responses.
    debug: bool = False

    @property
    def cors_origins_list(self) -> List[str]:
        """Parse CORS origins as a list."""
        return [origin.strip() for origin in self.cors_origins.split(",")]

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """
    Get cached settings instance.
    Uses lru_cache to avoid re-reading environment variables on every call.
    """
    return Settings()
