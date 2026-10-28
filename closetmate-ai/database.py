"""
database.py — SQLAlchemy-backed database layer for ClosetMate.

Production : DATABASE_URL must be set to a PostgreSQL connection string.
             e.g. postgresql://user:pass@host/dbname?sslmode=require
Local demo : Leave DATABASE_URL unset (or set to "sqlite") to auto-use a
             local SQLite file at closetmate.db — zero configuration needed.
             An explicit ``sqlite:///path/to/file.db`` URL is honoured (the
             test-suite uses this so it never touches your dev database).

Transactions
------------
Routers use sqlite3-style calls: ``db.execute(...)`` then ``db.commit()``.
Each request gets its own connection in "commit as you go" mode, so
``commit()`` really commits *before* the handler returns (FastAPI runs the
exit code of a ``yield`` dependency after the response has been sent, so we
must not rely on it for durability). If a handler wrote but forgot to commit,
the session commits on clean exit as a safety net and rolls back on error.

Use ``db_session()`` instead of ``Depends(get_db)`` when a handler has to do
slow I/O (an LLM call) — it lets you release the pooled connection first.
"""

from __future__ import annotations

import logging
import os
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Generator, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

_DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

# Auto-fallback: if not set or explicitly set to "sqlite", use local SQLite.
_USE_SQLITE = (
    not _DATABASE_URL
    or _DATABASE_URL.lower() in ("sqlite", "local")
    or _DATABASE_URL.startswith("sqlite")
)

if _USE_SQLITE:
    import pathlib
    if _DATABASE_URL.lower().startswith("sqlite:///") and len(_DATABASE_URL) > len("sqlite:///"):
        pass  # explicit file path — keep it as given
    else:
        _db_path = pathlib.Path(__file__).parent / "closetmate.db"
        _DATABASE_URL = f"sqlite:///{_db_path}"
    if os.getenv("K_SERVICE") or os.getenv("ENV", "").strip().lower() == "prod":
        # Cloud Run's filesystem is per-instance and ephemeral: SQLite there silently loses
        # every account on the next revision and diverges between instances.
        raise RuntimeError("DATABASE_URL must point at PostgreSQL in production (SQLite is dev-only).")
    engine = create_engine(
        _DATABASE_URL,
        connect_args={"check_same_thread": False},  # needed for FastAPI threading
        hide_parameters=True,
    )
    log.info("[database] Using SQLite: %s", engine.url.database)
else:
    # Normalize legacy "postgres://" prefix (some providers still emit it)
    if _DATABASE_URL.startswith("postgres://"):
        _DATABASE_URL = _DATABASE_URL.replace("postgres://", "postgresql://", 1)
    # Connection budget = (pool_size + max_overflow) x Cloud Run max-instances must stay well
    # under the database's connection limit. Defaults are deliberately small; point
    # DATABASE_URL at Neon's *pooled* host (the "-pooler" endpoint) and tune via env.
    engine = create_engine(
        _DATABASE_URL,
        pool_size=int(os.getenv("DB_POOL_SIZE", "3")),
        max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "4")),
        pool_timeout=10,          # fail fast under load instead of queueing for 30 s
        pool_pre_ping=True,       # detect stale connections — essential for Neon
        pool_recycle=1800,        # recycle connections every 30 min (Neon idle limit)
        pool_use_lifo=True,       # reuse hot connections so idle ones can be closed
        hide_parameters=True,     # SQL errors must not dump bound values (password hashes, PII)
        connect_args={
            "connect_timeout": 10,
            "keepalives": 1, "keepalives_idle": 30, "keepalives_interval": 10, "keepalives_count": 3,
        },
    )
    # Never log the URL itself — it contains the password.
    log.info("[database] Using PostgreSQL: host=%s db=%s", engine.url.host, engine.url.database)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def init_db() -> None:
    """
    Create required tables if they do not already exist.
    Safe to call multiple times (idempotent).
    Uses INTEGER PRIMARY KEY AUTOINCREMENT for SQLite, SERIAL for PostgreSQL.

    NOTE: this is bootstrap-only. Schema *changes* need versioned migrations
    (Alembic — Phase 3); CREATE TABLE IF NOT EXISTS never alters a live table.
    """
    # Dialect-aware auto-increment column type
    _id_col = "INTEGER PRIMARY KEY AUTOINCREMENT" if _USE_SQLITE else "SERIAL PRIMARY KEY"

    with engine.begin() as conn:
        if not _USE_SQLITE:
            # Several Cloud Run instances can boot at once. Concurrent CREATE TABLE/INDEX IF NOT
            # EXISTS race on Postgres' catalogs, so serialise schema bootstrap behind a
            # transaction-scoped advisory lock. (Real migrations — Alembic — are the Phase 3 fix.)
            conn.execute(text("SELECT pg_advisory_xact_lock(727274001)"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS users (
                user_id          TEXT PRIMARY KEY,
                name             TEXT NOT NULL,
                email            TEXT NOT NULL UNIQUE,
                password_hash    TEXT NOT NULL,
                gender           TEXT NOT NULL,
                body_shape       TEXT,
                skin_tone        TEXT,
                style_preference TEXT,
                created_at       TEXT NOT NULL
            )
        """))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS wardrobe_items (
                item_id          TEXT PRIMARY KEY,
                user_id          TEXT NOT NULL,
                category         TEXT,
                subcategory      TEXT,
                primary_color    TEXT,
                material         TEXT,
                pattern          TEXT,
                formality_level  TEXT,
                cultural_style   TEXT,
                image_path       TEXT,
                created_at       TEXT NOT NULL
            )
        """))

        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS clothing_metadata_cache (
                id            {_id_col},
                image_hash    TEXT NOT NULL UNIQUE,
                category      TEXT,
                subcategory   TEXT,
                primary_color TEXT,
                material      TEXT,
                pattern       TEXT,
                formality     TEXT,
                culture       TEXT,
                created_at    TEXT NOT NULL
            )
        """))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS worn_logs (
                log_id      TEXT PRIMARY KEY,
                user_id     TEXT NOT NULL,
                worn_date   TEXT NOT NULL,
                item_ids    TEXT NOT NULL,
                created_at  TEXT NOT NULL
            )
        """))

        # Opaque, rotating refresh tokens. Only the SHA-256 of the token is stored.
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS refresh_tokens (
                token_hash  TEXT PRIMARY KEY,
                user_id     TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                expires_at  TEXT NOT NULL,
                revoked_at  TEXT
            )
        """))

        # One row per AI call — the raw material for per-user cost reporting.
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS ai_usage (
                id            {_id_col},
                user_id       TEXT,
                feature       TEXT NOT NULL,
                provider      TEXT NOT NULL,
                model         TEXT NOT NULL,
                input_tokens  INTEGER,
                output_tokens INTEGER,
                latency_ms    INTEGER,
                ok            INTEGER NOT NULL,
                error         TEXT,
                created_at    TEXT NOT NULL
            )
        """))

        # Closet photos kept in object storage (see services/photo_store.py). One row per stored
        # photo: it bounds each user's storage and lets account deletion and clean-up find
        # everything. `key` / `thumb_key` are object keys, e.g. photos/<user_id>/<photo_id>.webp
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS photos (
                photo_id    TEXT PRIMARY KEY,
                user_id     TEXT NOT NULL,
                key         TEXT NOT NULL,
                thumb_key   TEXT NOT NULL,
                size_bytes  INTEGER NOT NULL,
                created_at  TEXT NOT NULL
            )
        """))

        # Outfits the user chose to keep ("Looks"). item_ids is a JSON array of item_id strings.
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS saved_looks (
                look_id     TEXT PRIMARY KEY,
                user_id     TEXT NOT NULL,
                name        TEXT,
                item_ids    TEXT NOT NULL,
                created_at  TEXT NOT NULL
            )
        """))

        # Per-user, per-feature, per-month usage counters (free-plan quotas).
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS usage_counters (
                user_id  TEXT NOT NULL,
                feature  TEXT NOT NULL,
                period   TEXT NOT NULL,
                count    INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, feature, period)
            )
        """))

        # Every per-user query filters on user_id; without these each request
        # is a full table scan.
        for ddl in (
            # Case-insensitive uniqueness backstop (the app lowercases emails already).
            "CREATE UNIQUE INDEX IF NOT EXISTS users_email_lower_key ON users (lower(email))",
            "CREATE INDEX IF NOT EXISTS idx_wardrobe_user ON wardrobe_items (user_id, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_worn_user_date ON worn_logs (user_id, worn_date)",
            "CREATE INDEX IF NOT EXISTS idx_looks_user ON saved_looks (user_id, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_photos_user ON photos (user_id, created_at)",
            # One stored photo backs at most one item, even when two requests race. The predicate
            # is an equality on a prefix, never a < / >= range: Postgres orders text by the
            # database collation (en_US ignores punctuation), so a range like
            # `>= 'photos/' AND < 'photos0'` silently matches nothing there and the index would
            # enforce nothing. SQLite compares bytes and would not have shown it.
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_items_photo ON wardrobe_items (image_path) "
            "WHERE substr(image_path, 1, 7) = 'photos/'",
            "CREATE INDEX IF NOT EXISTS idx_refresh_user ON refresh_tokens (user_id)",
            "CREATE INDEX IF NOT EXISTS idx_ai_usage_created ON ai_usage (created_at)",
            "CREATE INDEX IF NOT EXISTS idx_ai_usage_user ON ai_usage (user_id, created_at)",
        ):
            conn.execute(text(ddl))


def ping_db() -> None:
    """Raise if the database is unreachable (used by the /ready probe)."""
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))


# ---------------------------------------------------------------------------
# SQL placeholder patching (?/%s → :p0, :p1, …)
# ---------------------------------------------------------------------------

def _patch_sql(sql: str) -> str:
    """Replace ? or %s positional placeholders with :p0, :p1, … for SQLAlchemy text()."""
    counter = [0]

    def _repl(_match):
        name = f":p{counter[0]}"
        counter[0] += 1
        return name

    return re.sub(r"\?|%s", _repl, sql)


# ---------------------------------------------------------------------------
# Row / Result proxies — keep sqlite3-style dict access across routers
# ---------------------------------------------------------------------------

class _RowProxy:
    """
    Thin wrapper around a SQLAlchemy Row that supports dict-style key access,
    matching the sqlite3.Row interface used throughout the routers.
    """
    def __init__(self, row, keys):
        self._data = dict(zip(keys, row))

    def __getitem__(self, key):
        return self._data[key]

    def get(self, key, default=None):
        return self._data.get(key, default)

    def keys(self):
        return self._data.keys()

    def __iter__(self):
        return iter(self._data.values())

    def __len__(self):
        return len(self._data)

    @property
    def _mapping(self):
        """SQLAlchemy Row-compatible mapping attribute — returns the underlying dict."""
        return self._data

    def items(self):
        return self._data.items()

    def values(self):
        return self._data.values()


class _ResultProxy:
    """Cursor-like wrapper around a SQLAlchemy CursorResult."""

    def __init__(self, result):
        self._result = result
        self._keys = list(result.keys()) if result.returns_rows else []

    def fetchone(self):
        row = self._result.fetchone()
        if row is None:
            return None
        return _RowProxy(row, self._keys)

    def fetchall(self):
        rows = self._result.fetchall()
        return [_RowProxy(r, self._keys) for r in rows]

    @property
    def rowcount(self):
        return self._result.rowcount


# ---------------------------------------------------------------------------
# Connection wrapper — exposes sqlite3-style API over SQLAlchemy
# ---------------------------------------------------------------------------

_WRITE_RE = re.compile(r"^\s*(INSERT|UPDATE|DELETE|REPLACE)\b", re.IGNORECASE)


class _ConnectionWrapper:
    """
    Wraps a SQLAlchemy Connection to expose the sqlite3-style API used
    throughout the routers:
      conn.execute(sql, params)  → returns a cursor-like object
      conn.commit()              → commits now (further statements start a new transaction)
    """

    def __init__(self, conn: Connection):
        self._conn = conn
        self._dirty = False       # a write has been issued since the last commit
        self.row_factory = None   # compatibility attribute; not used

    def execute(self, sql, params=()) -> _ResultProxy:
        from sqlalchemy.sql import ClauseElement
        if isinstance(sql, ClauseElement):
            named = params if isinstance(params, dict) else {}
            result = self._conn.execute(sql, named)
            statement = str(sql)
        else:
            # Raw SQL string — patch ? / %s placeholders and bind positionally
            statement = _patch_sql(str(sql))
            if isinstance(params, dict):
                named = params
            else:
                named = {f"p{i}": v for i, v in enumerate(params)}
            result = self._conn.execute(text(statement), named)
        if _WRITE_RE.match(statement):
            self._dirty = True
        return _ResultProxy(result)

    def commit(self):
        self._conn.commit()
        self._dirty = False

    def rollback(self):
        self._conn.rollback()
        self._dirty = False

    def close(self):
        pass  # Handled by db_session()


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

@contextmanager
def db_session(*, commit_on_exit: bool = True) -> Generator[_ConnectionWrapper, None, None]:
    """
    Short-lived DB session: commits on clean exit if anything was written
    (unless ``commit_on_exit=False``), rolls back on any exception, and always
    returns the connection to the pool.

        with db_session() as db:
            rows = db.execute(text("SELECT ..."), {...}).fetchall()
        # connection released here — safe to make a slow LLM call now
    """
    with engine.connect() as conn:
        wrapper = _ConnectionWrapper(conn)
        try:
            yield wrapper
            if commit_on_exit and wrapper._dirty:
                wrapper.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001 — a dead connection must not mask the real error
                log.warning("rollback failed", exc_info=True)
            raise


def get_db() -> Generator[_ConnectionWrapper, None, None]:
    """
    FastAPI dependency: one DB session for the lifetime of a request.

    Handlers must call ``db.commit()`` themselves. FastAPI (>=0.118) runs the exit code of
    a ``yield`` dependency AFTER the response has been sent, so an implicit commit there
    could lose a write the client was already told succeeded; anything uncommitted is
    rolled back instead.

    Usage in routers:
        db: Any = Depends(get_db)
    """
    with db_session(commit_on_exit=False) as db:
        yield db


# ---------------------------------------------------------------------------
# Standalone cache helpers (used outside FastAPI DI — e.g. upload.py)
# ---------------------------------------------------------------------------

def get_cached_metadata(image_hash: str) -> Optional[dict]:
    """Return cached metadata for the given MD5 hash, or None if not cached."""
    sql = _patch_sql("SELECT * FROM clothing_metadata_cache WHERE image_hash = ?")
    with engine.connect() as conn:
        result = conn.execute(text(sql), {"p0": image_hash})
        keys = list(result.keys())
        row = result.fetchone()
        if row is None:
            return None
        return dict(zip(keys, row))


def save_metadata_cache(image_hash: str, metadata: dict) -> None:
    """Upsert metadata into the cache table keyed by MD5 hash."""
    now = datetime.now(timezone.utc).isoformat()
    params = {
        "p0": image_hash,
        "p1": metadata.get("category"),
        "p2": metadata.get("subcategory"),
        "p3": metadata.get("primary_color"),
        "p4": metadata.get("material"),
        "p5": metadata.get("pattern"),
        "p6": metadata.get("formality") or metadata.get("formality_level"),
        "p7": metadata.get("culture"),
        "p8": now,
    }
    if _USE_SQLITE:
        # SQLite uses INSERT OR REPLACE (UPSERT via REPLACE)
        sql = """
            INSERT OR REPLACE INTO clothing_metadata_cache
              (image_hash, category, subcategory, primary_color, material,
               pattern, formality, culture, created_at)
            VALUES (:p0, :p1, :p2, :p3, :p4, :p5, :p6, :p7, :p8)
        """
    else:
        # PostgreSQL ON CONFLICT ... DO UPDATE
        sql = """
            INSERT INTO clothing_metadata_cache
              (image_hash, category, subcategory, primary_color, material,
               pattern, formality, culture, created_at)
            VALUES (:p0, :p1, :p2, :p3, :p4, :p5, :p6, :p7, :p8)
            ON CONFLICT (image_hash) DO UPDATE SET
              category      = EXCLUDED.category,
              subcategory   = EXCLUDED.subcategory,
              primary_color = EXCLUDED.primary_color,
              material      = EXCLUDED.material,
              pattern       = EXCLUDED.pattern,
              formality     = EXCLUDED.formality,
              culture       = EXCLUDED.culture,
              created_at    = EXCLUDED.created_at
        """
    with engine.begin() as conn:
        conn.execute(text(sql), params)
