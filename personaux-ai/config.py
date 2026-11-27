"""Central configuration for PersonaUX AI, loaded from environment variables / .env."""
from __future__ import annotations

import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")
# Hosted dev workspaces (e.g. v0) inject project variables into the parent folder.
load_dotenv(BASE_DIR.parent / ".env.development.local")


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


APP_NAME = "PersonaUX AI"
APP_TAGLINE = "Test your website through every user's eyes."

ARTIFACTS_DIR = BASE_DIR / "artifacts"
SCREENSHOTS_DIR = ARTIFACTS_DIR / "screenshots"
REPORTS_DIR = ARTIFACTS_DIR / "reports"
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{(ARTIFACTS_DIR / 'personaux.db').as_posix()}")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
GEMINI_FALLBACK_MODELS = [
    m.strip()
    for m in os.getenv("GEMINI_FALLBACK_MODELS", "gemini-3.5-flash-lite,gemini-3.1-flash-lite").split(",")
    if m.strip()
]
GEMINI_TIMEOUT_SECONDS = _int("GEMINI_TIMEOUT_SECONDS", 60)
GEMINI_MAX_RETRIES = _int("GEMINI_MAX_RETRIES", 5)
GEMINI_SEND_SCREENSHOTS = _bool("GEMINI_SEND_SCREENSHOTS", True)

HEADLESS = _bool("HEADLESS", True)
DEFAULT_MAX_STEPS = _int("DEFAULT_MAX_STEPS", 15)
HARD_MAX_STEPS = _int("HARD_MAX_STEPS", 40)
NAVIGATION_TIMEOUT_MS = _int("NAVIGATION_TIMEOUT_MS", 30000)
ACTION_TIMEOUT_MS = _int("ACTION_TIMEOUT_MS", 8000)
SLOW_PAGE_THRESHOLD_MS = _int("SLOW_PAGE_THRESHOLD_MS", 4000)
MAX_AXE_SCANS_PER_PERSONA = _int("MAX_AXE_SCANS_PER_PERSONA", 5)

# Test identity used whenever a persona fills credentials. Never use real accounts.
TEST_ACCOUNT_EMAIL = os.getenv("TEST_ACCOUNT_EMAIL", "personaux.tester@example.com")
TEST_ACCOUNT_PASSWORD = os.getenv("TEST_ACCOUNT_PASSWORD") or f"PuxTest!{secrets.token_hex(4)}"
TEST_ACCOUNT_NAME = os.getenv("TEST_ACCOUNT_NAME", "Test User")
TEST_ACCOUNT_PHONE = os.getenv("TEST_ACCOUNT_PHONE", "5550100123")

VIEWPORTS = {
    "Desktop": {"width": 1280, "height": 800, "is_mobile": False, "has_touch": False},
    "Mobile": {"width": 390, "height": 844, "is_mobile": True, "has_touch": True},
}
MOBILE_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)


def ensure_dirs() -> None:
    for d in (ARTIFACTS_DIR, SCREENSHOTS_DIR, REPORTS_DIR):
        d.mkdir(parents=True, exist_ok=True)
