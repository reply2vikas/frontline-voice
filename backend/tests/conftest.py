import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def _isolated_db(monkeypatch):
    """Every test writes to its own throwaway database."""
    from app import audit, config

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "t.db")
        monkeypatch.setattr(config.settings, "db_path", path, raising=False)
        monkeypatch.setattr(audit.settings, "db_path", path, raising=False)
        yield


@pytest.fixture(autouse=True)
def _no_api_key(monkeypatch):
    """Tests must never make a network call; the offline engine is the default."""
    from app import config, llm

    monkeypatch.setattr(config.settings, "anthropic_api_key", None, raising=False)
    monkeypatch.setattr(llm.settings, "anthropic_api_key", None, raising=False)


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)
