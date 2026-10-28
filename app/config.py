"""Runtime configuration, read from environment variables (and an optional .env file)."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(__file__).resolve().parent / "data"
MODEL_DIR = Path(os.getenv("MODEL_DIR", BASE_DIR / "models"))
# Static web UI. Vercel serves public/ from its CDN; locally FastAPI serves the same files.
PUBLIC_DIR = BASE_DIR / "public"


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader so the app works without python-dotenv.

    Real environment variables win over values in the file.
    """
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if value and value[0] in "\"'" and value[-1:] == value[0]:
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].strip()  # allow trailing comments
        os.environ.setdefault(key.strip(), value)


_load_dotenv(BASE_DIR / ".env")


def secret(name: str) -> str | None:
    """Return an API key from the environment, treating empty values and placeholders as unset."""
    value = (os.getenv(name) or "").strip()
    if not value or value.lower().startswith(("your", "paste", "replace", "<", "xxx")):
        return None
    return value


# Which AI provider runs the interviewer and resume tailoring:
#   auto   - Gemini if GEMINI_API_KEY is set, else Claude if ANTHROPIC_API_KEY is set, else offline
#   gemini - Gemini only        claude - Claude only        off - offline engine only
# LLM_MODE is the older name of this setting and is still honoured.
LLM_PROVIDER = (os.getenv("LLM_PROVIDER") or os.getenv("LLM_MODE") or "auto").lower()

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
# Text-to-speech for the interviewer's voice. Preview TTS models get renamed, so the app falls
# back to the older ID automatically and finally to the browser's own voice.
GEMINI_TTS_MODEL = os.getenv("GEMINI_TTS_MODEL", "gemini-3.1-flash-tts-preview")
GEMINI_TTS_FALLBACK_MODEL = "gemini-2.5-flash-preview-tts"
GEMINI_TTS_VOICE = os.getenv("GEMINI_TTS_VOICE", "Sulafat")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")
CLAUDE_EFFORT = os.getenv("CLAUDE_EFFORT", "medium")
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "120"))

# Vercel rejects request bodies over 4.5 MB, so keep uploads below that by default.
MAX_UPLOAD_MB = float(os.getenv("MAX_UPLOAD_MB", "4"))
SESSION_TTL_MINUTES = int(os.getenv("SESSION_TTL_MINUTES", "120"))
MAX_SESSIONS = int(os.getenv("MAX_SESSIONS", "1000"))
