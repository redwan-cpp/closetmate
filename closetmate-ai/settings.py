"""
settings.py — single source of runtime configuration for the ClosetMate backend.

Everything that used to be a hard-coded constant (model IDs, token lifetimes,
quota limits, CORS origins) is read from environment variables here, so a model
retirement or a pricing change is a config change, not a code change.

Nothing in this module reads the environment at import time; call
``get_settings()`` after ``load_env()`` has run (main.py does this first).
"""
from __future__ import annotations

import logging
import os
import pathlib
import secrets
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, Optional, Tuple

log = logging.getLogger(__name__)

_DEV_JWT_SECRET = "dev-insecure-secret-change-me-before-deploying"
_MIN_JWT_SECRET_LEN = 32

# Features that are metered per user per calendar month.
QUOTA_FEATURES = ("chat", "vision", "bgremove", "insights")


# ---------------------------------------------------------------------------
# .env loader (no python-dotenv dependency required)
# ---------------------------------------------------------------------------

def load_env(env_file: Optional[pathlib.Path] = None) -> None:
    """Load KEY=VALUE pairs from .env without overwriting real environment vars."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    path = env_file or pathlib.Path(__file__).parent / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        log.warning("Invalid integer for %s=%r — using default %d", name, raw, default)
        return default


def _csv(name: str, default: Tuple[str, ...]) -> Tuple[str, ...]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    return tuple(p.strip() for p in raw.split(",") if p.strip())


def get_secret(name: str) -> Optional[str]:
    """Return an API key / secret from the environment (never logged)."""
    value = os.getenv(name, "").strip()
    return value or None


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Settings:
    env: str                         # "dev" | "test" | "prod"
    jwt_secret: str
    jwt_issuer: str
    access_token_minutes: int
    refresh_token_days: int

    openai_chat_model: str
    openai_vision_model: str
    openai_vision_detail: str        # "low" | "high" | "auto"
    gemini_models: Tuple[str, ...]   # tried in order; first healthy one wins

    cors_origins: Tuple[str, ...]
    max_upload_bytes: int
    max_image_pixels: int
    trusted_proxy_hops: int          # proxies in front of us whose X-Forwarded-For entry we trust

    studio_model: str                # rembg model for studio-shot cutouts (quality vs CPU)
    max_saved_looks: int             # per user

    max_wardrobe_items: int          # per user; bounds storage AND the prompt size per chat call
    chat_wardrobe_limit: int         # most-recent items sent to the LLM per message
    global_daily_ai_calls: int       # 0 = off. Hard stop on total metered AI calls per UTC day

    quota_free: Dict[str, int]       # feature -> monthly limit for the free plan

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"

    @property
    def expose_error_details(self) -> bool:
        """Tracebacks in HTTP responses are a dev-only convenience."""
        return not self.is_prod

    def quota_limit(self, feature: str, plan: str = "free") -> int:
        # Paid plans arrive in Phase 4; until then every user is on "free".
        return self.quota_free.get(feature, 0)

    def validate_for_runtime(self) -> None:
        """Fail fast on unsafe production configuration."""
        if self.is_prod:
            if self.jwt_secret == _DEV_JWT_SECRET or len(self.jwt_secret) < _MIN_JWT_SECRET_LEN:
                raise RuntimeError(
                    "JWT_SECRET must be set to a random string of at least "
                    f"{_MIN_JWT_SECRET_LEN} characters in production."
                )
        elif self.jwt_secret == _DEV_JWT_SECRET:
            log.warning("Using the built-in dev JWT secret — set JWT_SECRET before deploying.")


def _detect_env() -> str:
    # Cloud Run sets K_SERVICE. A deployed service is ALWAYS production — a stray
    # ENV=dev must not be able to switch on the dev secret, /docs and tracebacks there.
    if os.getenv("K_SERVICE"):
        return "prod"
    explicit = os.getenv("ENV", "").strip().lower()
    if not explicit:
        return "dev"
    explicit = {"production": "prod", "development": "dev"}.get(explicit, explicit)
    if explicit not in ("dev", "test", "prod"):
        # A typo like ENV=live must never silently fall back to the lenient dev mode
        # (dev secret, open docs, tracebacks in responses, no real quotas).
        raise RuntimeError(f"Unrecognised ENV={explicit!r}; expected dev, test or prod.")
    return explicit


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    env = _detect_env()
    strict = env == "prod"

    # Dev/test default to very high quotas so local testing is never blocked.
    quota_defaults = {
        "chat": 60 if strict else 100_000,
        "vision": 40 if strict else 100_000,
        "bgremove": 80 if strict else 100_000,
        "insights": 4 if strict else 100_000,
    }
    quota_free = {
        feature: _int(f"QUOTA_FREE_{feature.upper()}_MONTHLY", default)
        for feature, default in quota_defaults.items()
    }

    detail = os.getenv("OPENAI_VISION_DETAIL", "high").strip().lower()
    if detail not in ("low", "high", "auto"):
        detail = "high"

    # No JWT_SECRET: in prod validate_for_runtime() refuses to boot. Elsewhere use a random
    # per-process secret (never a constant that sits in the repo and could forge any user).
    # After a dev restart old access tokens fail and the app silently refreshes them.
    jwt_secret = os.getenv("JWT_SECRET", "").strip() or (
        _DEV_JWT_SECRET if strict else secrets.token_urlsafe(48)
    )

    return Settings(
        env=env,
        jwt_secret=jwt_secret,
        jwt_issuer=os.getenv("JWT_ISSUER", "closetmate"),
        access_token_minutes=_int("ACCESS_TOKEN_MINUTES", 15),
        refresh_token_days=_int("REFRESH_TOKEN_DAYS", 60),
        openai_chat_model=os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini").strip(),
        openai_vision_model=os.getenv("OPENAI_VISION_MODEL", "gpt-4o-mini").strip(),
        openai_vision_detail=detail,
        # Gemini 2.0 / 1.5 IDs were scheduled for shutdown in 2026 — run
        # `python scripts/check_models.py` to confirm these are still live.
        gemini_models=_csv("GEMINI_MODELS", ("gemini-2.5-flash", "gemini-2.5-flash-lite")),
        cors_origins=_csv("CORS_ORIGINS", () if strict else ("*",)),
        max_upload_bytes=_int("MAX_UPLOAD_BYTES", 12 * 1024 * 1024),
        # 36 MP ≈ 6000x6000: above any default phone capture, below pixel-bomb territory
        # (a 63 MP PNG that is only 77 KB on the wire would need ~250 MB to decode).
        max_image_pixels=_int("MAX_IMAGE_PIXELS", 36_000_000),
        # Cloud Run: 1 (its front end appends the real client IP). Behind another load
        # balancer set 2. Locally 0 = use the socket peer. Verify with a test request.
        trusted_proxy_hops=_int("TRUSTED_PROXY_HOPS", 1 if os.getenv("K_SERVICE") else 0),
        # Same small model production already ships. A larger one ("u2net", "isnet-general-use")
        # may cut cluttered phone photos more cleanly at ~1.5x the CPU — A/B before switching.
        studio_model=os.getenv("STUDIO_RMBG_MODEL", "u2netp").strip() or "u2netp",
        max_saved_looks=_int("MAX_SAVED_LOOKS", 200),
        max_wardrobe_items=_int("MAX_WARDROBE_ITEMS", 500),
        chat_wardrobe_limit=_int("CHAT_WARDROBE_LIMIT", 200),
        global_daily_ai_calls=_int("GLOBAL_DAILY_AI_CALLS", 20_000 if strict else 0),
        quota_free=quota_free,
    )


def reset_settings_cache() -> None:
    """Test hook: re-read the environment on the next get_settings() call."""
    get_settings.cache_clear()
