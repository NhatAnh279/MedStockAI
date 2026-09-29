from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Reads backend/.env (real environment variables take precedence over it).
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg2://medstock:medstock@localhost:5432/medstock"
    cors_origins: str = "http://localhost:3000"
    # Optional: without a key the LLM service falls back to deterministic templates.
    anthropic_api_key: str | None = None
    llm_model: str = "claude-haiku-4-5-20251001"
    # NL chat and protocol-PDF extraction (tool calling / document reading).
    chat_model: str = "claude-sonnet-4-6"
    # LAN IP for QR codes — "auto" detects at runtime, or set explicitly e.g. "192.168.1.10"
    network_host: str = "auto"


settings = Settings()
