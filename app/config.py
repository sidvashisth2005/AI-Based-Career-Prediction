"""Runtime configuration, read from environment variables (and an optional .env file)."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(__file__).resolve().parent / "data"
MODEL_DIR = Path(os.getenv("MODEL_DIR", BASE_DIR / "models"))
FRONTEND_DIR = BASE_DIR / "frontend"


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader so the app works without python-dotenv."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(BASE_DIR / ".env")

# "auto" uses Claude when credentials are available, "off" forces the offline engine.
LLM_MODE = os.getenv("LLM_MODE", "auto").lower()
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")
CLAUDE_EFFORT = os.getenv("CLAUDE_EFFORT", "medium")
MAX_UPLOAD_MB = float(os.getenv("MAX_UPLOAD_MB", "5"))
SESSION_TTL_MINUTES = int(os.getenv("SESSION_TTL_MINUTES", "120"))
