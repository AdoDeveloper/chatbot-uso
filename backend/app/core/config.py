from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=[".env", ".env.production"],
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    APP_NAME: str = "Chatbot RAG API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"

    SECRET_KEY: str = Field(...)
    ENCRYPTION_KEY: str | None = Field(None)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    ALGORITHM: str = "HS256"


    DATABASE_URL: str = Field(...)
    DB_POOL_SIZE: int = 50
    DB_MAX_OVERFLOW: int = 50

    LLM_MAX_CONCURRENCY: int = 30
    LLM_QUEUE_TIMEOUT_SECONDS: float = 45.0

    REDIS_URL: str = "redis://localhost:6379/0"

    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: str | None = None

    UPLOADS_DIR: str = "uploads"
    MAX_SOURCE_UPLOAD_MB: int = 50

    ALLOWED_ORIGINS: list[str] = ["*"]

    # JSON payload size limits
    MAX_JSON_BODY_SIZE_MB: float = 1.0  # 1MB max
    MAX_JSON_DEPTH: int = 100  # Max nesting depth

    WIDGET_BASE_URL: str = "http://localhost:8000"

    FRONTEND_URL: str = "http://localhost:3000"

    RATE_LIMIT_CHAT_PER_SESSION_MIN: int = 20
    RATE_LIMIT_LOGIN_PER_MIN: int = 5
    RATE_LIMIT_REFRESH_PER_MIN: int = 30

    LLM_OLLAMA_BASE: str = "http://localhost:11434/v1"
    LLM_LMSTUDIO_BASE: str = "http://localhost:1234/v1"
    LLM_VLLM_BASE: str = "http://localhost:8000/v1"

    GUARDRAILS_ENABLED: bool = True
    MAX_INPUT_CHARS: int = 4000
    MAX_OUTPUT_TOKENS: int = 800

    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_FROM: str = "noreply@chatbot.local"
    SMTP_TLS: bool = True

    FIRST_ADMIN_EMAIL: str = "admin@example.com"
    FIRST_ADMIN_PASSWORD: str = ""

    @model_validator(mode="after")
    def _check_secrets(self) -> "Settings":
        _insecure = {
            "cambia_esta_clave_secreta_en_produccion",
            "cambia_esta_clave_antes_del_primer_arranque",
            "changeme", "secret", "your-secret-key", "insecure",
        }
        if self.SECRET_KEY in _insecure:
            if self.ENVIRONMENT == "production":
                raise ValueError(
                    "SECRET_KEY must be changed before running in production. "
                    "Generate one with: openssl rand -hex 32"
                )
            import warnings
            warnings.warn(
                "SECRET_KEY is set to an insecure default value. "
                "Run: openssl rand -hex 32  and set the result in .env",
                stacklevel=2,
            )
        if self.ENVIRONMENT == "production" and self.DEBUG:
            raise ValueError(
                "DEBUG must be false in production — it leaks stack traces "
                "and internal details in HTTP responses and logs."
            )
        if self.FIRST_ADMIN_PASSWORD and len(self.FIRST_ADMIN_PASSWORD) < 8:
            raise ValueError(
                "FIRST_ADMIN_PASSWORD es demasiado corta (mínimo 8 caracteres). "
                "Usa una contraseña segura para el primer administrador."
            )
        if not self.FIRST_ADMIN_PASSWORD and self.ENVIRONMENT == "production":
            raise ValueError(
                "FIRST_ADMIN_PASSWORD no puede estar vacía en producción. "
                "Define una contraseña segura en .env"
            )
        if self.ENVIRONMENT == "production" and self.DATABASE_URL.startswith("sqlite"):
            raise ValueError(
                "DATABASE_URL uses SQLite — not supported in production. "
                "Use MySQL: mysql+aiomysql://user:pass@host:3306/dbname"
            )
        if len(self.SECRET_KEY) < 32:
            if self.ENVIRONMENT == "production":
                raise ValueError(
                    "SECRET_KEY is too short for production (min 32 chars). "
                    "Generate one with: openssl rand -hex 32"
                )
            import warnings
            warnings.warn(
                "SECRET_KEY is too short (min 32 chars). "
                "Generate one with: openssl rand -hex 32",
                stacklevel=2,
            )
        return self

    MICROSOFT_CLIENT_ID: str | None = None
    MICROSOFT_CLIENT_SECRET: str | None = None
    MICROSOFT_TENANT_ID: str | None = None
    MICROSOFT_REDIRECT_URI: str | None = None
    GRAPH_MAILBOX: str | None = None

    CHATBOT_CHUNK_PARENT_SIZE: int = 4000
    CHATBOT_CHUNK_CHILD_SIZE: int = 1024
    CHATBOT_CHUNK_PARENT_OVERLAP: int = 400
    CHATBOT_CHUNK_CHILD_OVERLAP: int = 128


@lru_cache
def get_settings() -> Settings:
    return Settings()
