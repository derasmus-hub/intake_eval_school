from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    api_key: str = "your-openai-api-key-here"
    model_name: str = "gpt-4o-mini"
    database_path: str = "intake_eval.db"
    jwt_secret: str = "intake-eval-school-jwt-secret-32"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
