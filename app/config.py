import os
import sys
from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    api_key: str = "your-openai-api-key-here"
    model_name: str = "gpt-4o-mini"
    database_path: str = "intake_eval.db"
    # JWT_SECRET must be set via environment variable - no default
    jwt_secret: str = ""
    # Environment: "dev" (default) or "prod"
    env: str = "dev"
    # CORS origins for prod (comma-separated)
    cors_origins: str = ""

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

    return s


settings = _load_settings()
