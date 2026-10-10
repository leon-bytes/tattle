import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # so "import app" works from any directory

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def fixture_kb(monkeypatch):
    """Tests never read the real files under data/."""
    monkeypatch.setenv("KB_PATH", str(FIXTURES / "kb.json"))
    monkeypatch.setenv("KB_OVERRIDES_PATH", str(FIXTURES / "kb_overrides.json"))
    monkeypatch.setenv("AI_CACHE_SEED_PATH", str(FIXTURES / "ai_cache_seed.json"))
    monkeypatch.setenv("LABELS_DIR", str(FIXTURES / "labels"))
    monkeypatch.delenv("AI_MODEL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)  # tests never touch a database unless they ask for one
    monkeypatch.delenv("AI_BASE_URL", raising=False)   # nor a model server
