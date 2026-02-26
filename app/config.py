import os
import sys
from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    api_key: str = "your-openai-api-key-here"
    model_name: str = "gpt-4o"
    # AI provider: "openai" or "anthropic"
    ai_provider: str = "openai"
    # Anthropic API key (optional, only needed if ai_provider=anthropic)
    anthropic_api_key: str = ""
    # Model overrides per use case (empty = use default model_name)
    lesson_model: str = "gpt-4o"
    assessment_model: str = "gpt-4o"
    cheap_model: str = "gpt-4o-mini"
    # Database path - can be overridden via DATABASE_PATH env var for Docker
    database_path: str = "intake_eval.db"
    # PostgreSQL connection URL (when set, overrides database_path)
    # e.g. postgresql://user:pass@localhost:5432/intake_eval
    database_url: str = ""
    # JWT_SECRET must be set via environment variable - no default
    jwt_secret: str = ""
    # Environment: "dev" (default) or "prod"
    env: str = "dev"
    # CORS origins for prod (comma-separated)
    cors_origins: str = ""
    # Admin secret for protected admin endpoints (teacher invites, etc.)
    admin_secret: str = ""
    # Set to "1" when running in Docker container
    in_docker: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


def _load_settings() -> Settings:
    """Load settings and validate critical security requirements."""
    s = Settings()

    # JWT_SECRET is required - no hardcoded fallback
    if not s.jwt_secret:
        print("ERROR: JWT_SECRET environment variable is required but not set.", file=sys.stderr)
        print("Set JWT_SECRET to a secure random string (at least 32 characters).", file=sys.stderr)
        sys.exit(1)

    if len(s.jwt_secret) < 32:
        print("ERROR: JWT_SECRET must be at least 32 characters.", file=sys.stderr)
        sys.exit(1)

    # ADMIN_SECRET is required for admin endpoints
    if not s.admin_secret:
        print("ERROR: ADMIN_SECRET environment variable is required but not set.", file=sys.stderr)
        print("Set ADMIN_SECRET to a secure random string (at least 16 characters).", file=sys.stderr)
        sys.exit(1)

    if len(s.admin_secret) < 16:
        print("ERROR: ADMIN_SECRET must be at least 16 characters.", file=sys.stderr)
        sys.exit(1)

    # API_KEY is required — reject placeholder or empty value
    if not s.api_key or s.api_key == "your-openai-api-key-here":
        print("ERROR: API_KEY environment variable is required but not set.", file=sys.stderr)
        print("Set API_KEY to a valid OpenAI API key in your .env file.", file=sys.stderr)
        sys.exit(1)

    return s


settings = _load_settings()
