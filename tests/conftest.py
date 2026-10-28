import os
from pathlib import Path

import pytest

# Tests must never call the real Claude API and should not touch the repo's saved model.
os.environ["LLM_PROVIDER"] = "off"
os.environ.setdefault("MODEL_DIR", str(Path(__file__).parent / ".model-cache"))

SAMPLE_RESUME = Path(__file__).resolve().parent.parent / "samples" / "sample_resume.txt"


@pytest.fixture(scope="session")
def resume_text() -> str:
    return SAMPLE_RESUME.read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c
