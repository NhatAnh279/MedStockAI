import pytest

from app.config import settings
from app.services import llm


@pytest.fixture(autouse=True)
def no_llm(monkeypatch):
    """Tests never call the Claude API, even when backend/.env holds a key."""
    monkeypatch.setattr(settings, "anthropic_api_key", None)
    monkeypatch.setattr(llm, "_client", None)
