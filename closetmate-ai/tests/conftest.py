"""
Shared fixtures for the ClosetMate backend test-suite.

Hard rules enforced here
------------------------
* The environment is configured at *import time of this file*, i.e. before any
  application module is imported (``database.py`` reads DATABASE_URL on import).
* The suite only ever talks to a throw-away SQLite file in the OS temp dir; a
  guard refuses to run if the engine points anywhere else (the per-test wipe
  deletes every row).
* No network: ``requests`` and the real httpx transports (used by the OpenAI SDK)
  raise if anything tries to leave the machine. rembg is never loaded.
* bcrypt cost is lowered to 4 rounds for speed; ``real_bcrypt_cost`` restores
  the production cost for the one test that asserts it.
"""
from __future__ import annotations

import itertools
import os
import pathlib
import shutil
import tempfile
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

import bcrypt
import pytest

# ---------------------------------------------------------------------------
# 1. Environment — must happen before `import main` / `import database`
# ---------------------------------------------------------------------------

_TMP_DIR = pathlib.Path(tempfile.mkdtemp(prefix="closetmate-tests-"))
DB_FILE = _TMP_DIR / "closetmate-test.db"
TEST_JWT_SECRET = "unit-test-jwt-secret-" + "k" * 32          # >= 32 chars

# Test quotas are deliberately tiny so the cap is reachable in a few requests.
TEST_QUOTAS = {"chat": 2, "vision": 3, "bgremove": 3, "insights": 2}

_FORCED_ENV = {
    "ENV": "test",
    "DATABASE_URL": f"sqlite:///{DB_FILE.as_posix()}",
    "JWT_SECRET": TEST_JWT_SECRET,
    "QUOTA_FREE_CHAT_MONTHLY": str(TEST_QUOTAS["chat"]),
    "QUOTA_FREE_VISION_MONTHLY": str(TEST_QUOTAS["vision"]),
    "QUOTA_FREE_BGREMOVE_MONTHLY": str(TEST_QUOTAS["bgremove"]),
    "QUOTA_FREE_INSIGHTS_MONTHLY": str(TEST_QUOTAS["insights"]),
    # Empty (not absent) so settings.load_env() will not pull real keys from a
    # developer's .env file: it only fills variables that are not yet defined.
    "OPENAI_API_KEY": "",
    "GEMINI_API_KEY": "",
    "GCS_BUCKET": "",
    "K_SERVICE": "",
    # Blank = "use the default", and being defined stops a developer's .env from supplying them.
    "MAX_SAVED_LOOKS": "",
    "STUDIO_RMBG_MODEL": "",
}
_CLEARED_ENV = (
    "JWT_ISSUER", "ACCESS_TOKEN_MINUTES", "REFRESH_TOKEN_DAYS",
    "OPENAI_CHAT_MODEL", "OPENAI_VISION_MODEL", "OPENAI_VISION_DETAIL",
    "GEMINI_MODELS", "CORS_ORIGINS", "MAX_UPLOAD_BYTES", "MAX_IMAGE_PIXELS",
)
for _key in _CLEARED_ENV:
    os.environ.pop(_key, None)
os.environ.update(_FORCED_ENV)

_REAL_GENSALT = bcrypt.gensalt

DEFAULT_PASSWORD = "correct-horse-battery"

_TABLES = (
    "users", "wardrobe_items", "worn_logs", "refresh_tokens",
    "usage_counters", "ai_usage", "clothing_metadata_cache", "saved_looks", "photos",
)


# ---------------------------------------------------------------------------
# 2. Session-scoped plumbing
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def app_module():
    """Import ``main`` exactly once, after the environment above is in place."""
    import database
    import main

    db_path = pathlib.Path(str(database.engine.url.database)).resolve()
    if db_path != DB_FILE.resolve():          # never wipe a developer's database
        pytest.exit(f"Refusing to run: engine points at {db_path}, expected {DB_FILE}", returncode=2)

    # The throw-away database does not need crash safety: skipping fsync makes the many
    # tiny commits in this suite several times faster on Windows.
    from sqlalchemy import event

    @event.listens_for(database.engine, "connect")
    def _fast_sqlite(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA synchronous=OFF")
        cursor.execute("PRAGMA journal_mode=MEMORY")
        cursor.close()

    database.engine.dispose()                 # drop pooled connections created before the hook
    yield main
    database.engine.dispose()
    shutil.rmtree(_TMP_DIR, ignore_errors=True)


@pytest.fixture(scope="session", autouse=True)
def _fast_bcrypt():
    """4 rounds instead of 12: the suite hashes a lot of passwords."""
    mp = pytest.MonkeyPatch()
    mp.setattr(bcrypt, "gensalt", lambda *a, **k: _REAL_GENSALT(rounds=4))
    yield
    mp.undo()


@pytest.fixture
def real_bcrypt_cost(monkeypatch):
    """Use the production bcrypt work factor for this test."""
    monkeypatch.setattr(bcrypt, "gensalt", _REAL_GENSALT)


@pytest.fixture(scope="session")
def client(app_module):
    from fastapi.testclient import TestClient

    with TestClient(app_module.app) as c:
        yield c


@pytest.fixture(scope="session")
def client_no_raise(app_module):
    """Like ``client`` but unhandled server errors become 500 responses."""
    from fastapi.testclient import TestClient

    with TestClient(app_module.app, raise_server_exceptions=False) as c:
        yield c


# ---------------------------------------------------------------------------
# 3. Per-test isolation (autouse)
# ---------------------------------------------------------------------------

def _wipe_database() -> None:
    import database
    from sqlalchemy import text

    with database.engine.begin() as conn:
        for table in _TABLES:
            conn.execute(text(f"DELETE FROM {table}"))


@pytest.fixture(autouse=True)
def _isolate(app_module):
    """Clean DB + limiter state + settings cache before AND after every test."""
    import ratelimit
    import settings
    from routers import auth

    _wipe_database()
    ratelimit.reset_all()
    auth._LOGIN_FAILURES.reset()
    settings.reset_settings_cache()
    yield
    # monkeypatch has already restored the environment (it was set up later, so
    # it is torn down earlier); drop any Settings built from patched env vars.
    settings.reset_settings_cache()


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Any attempt to reach the internet (OpenAI, Gemini, weather) fails loudly."""
    import httpx
    import requests.adapters

    def _blocked(*_a, **_k):
        raise AssertionError("Network access attempted during a test")

    async def _blocked_async(*_a, **_k):
        raise AssertionError("Network access attempted during a test")

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", _blocked)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _blocked)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _blocked_async)


@pytest.fixture(autouse=True)
def _photo_store(tmp_path):
    """Every test stores photos in its own throw-away folder (never the real photo_store/)."""
    from services import photo_store

    store = photo_store.DiskStore(tmp_path / "photo-root")
    photo_store.set_store(store)
    yield store
    photo_store.set_store(None)


@pytest.fixture(autouse=True)
def _never_load_rembg(monkeypatch):
    """Loading the ONNX model is slow and may download it; tests must stub the callers."""
    import services.image_processing as ip

    def _refuse():
        raise RuntimeError("rembg model load attempted inside a test")

    def _refuse_with_model(*_a, **_k):
        raise RuntimeError("rembg model load attempted inside a test (studio pipeline: stub services.studio._cutout)")

    monkeypatch.setattr(ip, "_load_rembg", _refuse)
    # The studio pipeline loads its own (named) model through this function; both the
    # defining module and the name studio.py imported are guarded.
    monkeypatch.setattr(ip, "remove_background_with_model", _refuse_with_model)
    import services.studio as studio

    monkeypatch.setattr(studio, "remove_background_with_model", _refuse_with_model)


# ---------------------------------------------------------------------------
# 4. Settings / env helper
# ---------------------------------------------------------------------------

@pytest.fixture
def set_env(monkeypatch):
    """``set_env(QUOTA_FREE_CHAT_MONTHLY=5, GEMINI_API_KEY="k")`` then re-read Settings.

    Pass ``None`` to unset a variable. Everything is undone (and the Settings
    cache dropped) automatically at the end of the test.
    """
    import settings

    def _set(**values: Any) -> None:
        for name, value in values.items():
            if value is None:
                monkeypatch.delenv(name, raising=False)
            else:
                monkeypatch.setenv(name, str(value))
        settings.reset_settings_cache()

    return _set


# ---------------------------------------------------------------------------
# 5. Database helpers for assertions
# ---------------------------------------------------------------------------

@pytest.fixture
def sql(app_module):
    """``sql("SELECT ... WHERE x = :x", x=1)`` -> list of dict rows (autocommit for writes)."""
    import database
    from sqlalchemy import text

    def _run(statement: str, **params: Any) -> List[Dict[str, Any]]:
        with database.engine.begin() as conn:
            result = conn.execute(text(statement), params)
            if result.returns_rows:
                return [dict(r._mapping) for r in result]
            return []

    return _run


@pytest.fixture
def usage_count(sql):
    """Current-month counter for (user_id, feature); 0 when no row exists."""
    from quota import current_period

    def _count(user_id: str, feature: str) -> int:
        rows = sql(
            "SELECT count FROM usage_counters WHERE user_id = :u AND feature = :f AND period = :p",
            u=user_id, f=feature, p=current_period(),
        )
        return int(rows[0]["count"]) if rows else 0

    return _count


# ---------------------------------------------------------------------------
# 6. Account helpers
# ---------------------------------------------------------------------------

@dataclass
class Account:
    user_id: str
    email: str
    password: str
    token: str = ""
    refresh_token: str = ""

    @property
    def headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


def bearer(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def auth_headers() -> Callable[[Any], Dict[str, str]]:
    """``auth_headers(account_or_token)`` -> ``{"Authorization": "Bearer ..."}``."""

    def _headers(who: Any) -> Dict[str, str]:
        return bearer(who.token if isinstance(who, Account) else str(who))

    return _headers


@pytest.fixture
def register_user(client):
    """Register an account through the API (not logged in). Returns an ``Account``."""
    counter = itertools.count(1)

    def _register(
        *,
        name: str = "Test User",
        email: Optional[str] = None,
        password: str = DEFAULT_PASSWORD,
        gender: str = "female",
        **extra: Any,
    ) -> Account:
        email = email or f"user{next(counter)}@example.com"
        resp = client.post(
            "/auth/register",
            json={"name": name, "email": email, "password": password, "gender": gender, **extra},
        )
        assert resp.status_code == 201, resp.text
        return Account(user_id=resp.json()["user_id"], email=email, password=password)

    return _register


@pytest.fixture
def login_user(client):
    """Log an ``Account`` in and fill in its access/refresh tokens."""

    def _login(account: Account) -> Account:
        resp = client.post("/auth/login", json={"email": account.email, "password": account.password})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        account.token = body["token"]
        account.refresh_token = body["refresh_token"]
        return account

    return _login


@pytest.fixture
def make_account(register_user, login_user):
    """Register + log in in one go."""

    def _make(**kwargs: Any) -> Account:
        return login_user(register_user(**kwargs))

    return _make


@pytest.fixture
def alice(make_account) -> Account:
    return make_account(name="Alice", email="alice@example.com")


@pytest.fixture
def bob(make_account) -> Account:
    return make_account(name="Bob", email="bob@example.com")


@pytest.fixture
def two_users(alice, bob):
    """(alice, bob): two independent, logged-in accounts."""
    return alice, bob


@pytest.fixture
def add_item(client):
    """``add_item(account, category="top", ...)`` -> item_id (asserts 201)."""

    def _add(account: Account, **overrides: Any) -> str:
        payload = {
            "user_id": account.user_id,
            "image_path": "uploads/processed/shirt.jpg",
            "category": "top",
            "subcategory": "shirt",
            "primary_color": "white",
            "material": "cotton",
            "pattern": "solid",
            "formality": "casual",
            "culture": "western",
            **overrides,
        }
        resp = client.post("/wardrobe/add-item", json=payload, headers=account.headers)
        assert resp.status_code == 201, resp.text
        return resp.json()["item_id"]

    return _add


# ---------------------------------------------------------------------------
# 7. Fake LLM providers for the chat router
# ---------------------------------------------------------------------------

class FakeLLM:
    """Stands in for ``routers.chat.openai_chat`` / ``gemini_generate``."""

    def __init__(self) -> None:
        self.openai_reply: Any = "Wear the white shirt."
        self.openai_error: Optional[BaseException] = None
        self.gemini_reply: Optional[str] = None
        self.mark_billed = False          # behave like a provider call that was answered (and charged)
        self.openai_calls: List[Dict[str, Any]] = []
        self.gemini_calls: List[Dict[str, Any]] = []

    async def openai_chat(self, messages, **kwargs):
        self.openai_calls.append({"messages": messages, **kwargs})
        if self.mark_billed:
            import quota

            quota.mark_billed()
        if self.openai_error is not None:
            raise self.openai_error
        return self.openai_reply

    async def gemini_generate(self, messages, **kwargs):
        self.gemini_calls.append({"messages": messages, **kwargs})
        return self.gemini_reply


@pytest.fixture
def fake_llm(monkeypatch) -> FakeLLM:
    import routers.chat as chat

    fake = FakeLLM()
    monkeypatch.setattr(chat, "openai_chat", fake.openai_chat)
    monkeypatch.setattr(chat, "gemini_generate", fake.gemini_generate)
    return fake


# ---------------------------------------------------------------------------
# 8. Image fixtures
# ---------------------------------------------------------------------------

def make_image_bytes(color=(200, 30, 30), size=(8, 8), fmt="PNG") -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format=fmt)
    return buf.getvalue()


@pytest.fixture
def png_bytes() -> bytes:
    return make_image_bytes()


@pytest.fixture
def image_factory() -> Callable[..., bytes]:
    """Distinct images have distinct MD5s: vary ``color`` to get different cache keys."""
    return make_image_bytes


# ---------------------------------------------------------------------------
# 9. Studio-shot pipeline: synthetic photos and a stand-in for the rembg cutout
# ---------------------------------------------------------------------------

def make_photo(
    size=(400, 500),
    background=(235, 235, 235),
    subjects=(),
    fmt: str = "PNG",
    exif_orientation: Optional[int] = None,
) -> bytes:
    """A flat-colour photo with solid rectangles: ``subjects=[((x0, y0, x1, y1), (r, g, b)), ...]``.

    Boxes are in pixels, ``x1``/``y1`` exclusive. ``exif_orientation`` writes an EXIF tag (JPEG).
    """
    import io

    from PIL import Image

    img = Image.new("RGB", size, background)
    for (x0, y0, x1, y1), colour in subjects:
        img.paste(colour, (x0, y0, x1, y1))
    save_kwargs: Dict[str, Any] = {}
    if exif_orientation is not None:
        exif = Image.Exif()
        exif[0x0112] = exif_orientation
        save_kwargs["exif"] = exif
    buf = io.BytesIO()
    img.save(buf, format=fmt, **save_kwargs)
    return buf.getvalue()


class FakeCutout:
    """Stands in for ``services.studio._cutout`` (the rembg call) — no model is ever loaded.

    ``boxes`` decides which source pixels the "model" keeps (alpha 255, everything else 0):
      * ``None``  (default)  the central 50% of the image;
      * ``[]``               nothing: a fully transparent cutout;
      * ``[(x0, y0, x1, y1), ...]``  those pixel rectangles (``x1``/``y1`` exclusive).
    ``opaque=True`` keeps the whole photo (a model that failed to separate anything).
    ``haze`` is the faint alpha (0-255) the "model" leaves everywhere outside the boxes.
    ``rgb_only=True`` returns an RGB image with no alpha channel at all.
    ``error`` is raised instead, as if the model crashed.
    """

    def __init__(self) -> None:
        self.boxes: Optional[List[tuple]] = None
        self.opaque = False
        self.haze = 0
        self.rgb_only = False
        self.error: Optional[BaseException] = None
        self.calls: List[Any] = []

    def __call__(self, image):
        import numpy as np
        from PIL import Image

        self.calls.append(image)
        if self.error is not None:
            raise self.error
        rgba = image.convert("RGBA")
        if self.rgb_only:
            return rgba.convert("RGB")
        width, height = rgba.size
        alpha = np.full((height, width), self.haze, dtype=np.uint8)
        if self.opaque:
            alpha[:, :] = 255
        else:
            boxes = self.boxes
            if boxes is None:
                boxes = [(width // 4, height // 4, width - width // 4, height - height // 4)]
            for x0, y0, x1, y1 in boxes:
                alpha[y0:y1, x0:x1] = 255
        rgba.putalpha(Image.fromarray(alpha, "L"))
        return rgba


@pytest.fixture
def fake_cutout(monkeypatch) -> FakeCutout:
    import services.studio as studio

    fake = FakeCutout()
    monkeypatch.setattr(studio, "_cutout", fake)
    return fake
