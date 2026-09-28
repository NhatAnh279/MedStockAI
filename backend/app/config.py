from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg2://medstock:medstock@localhost:5432/medstock"
    cors_origins: str = "http://localhost:3000"


settings = Settings()
