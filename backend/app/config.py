from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg2://medstock:medstock@localhost:5432/medstock"
    cors_origins: str = "http://localhost:3000"
    # Optional: without a key the LLM service falls back to deterministic templates.
    anthropic_api_key: str | None = None
    llm_model: str = "claude-haiku-4-5-20251001"


settings = Settings()
