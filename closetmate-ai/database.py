"""
database.py — SQLAlchemy-backed database layer for ClosetMate.

Local dev  : DATABASE_URL is unset → falls back to SQLite (closetmate.db)
Production : Set DATABASE_URL=postgresql://user:pass@host/dbname
             (Heroku sets this automatically when you add the Postgres add-on)

The get_db() generator yields a SQLAlchemy Connection that supports the same
.execute() / .fetchone() / .fetchall() / .commit() calls used throughout the
routers, so no router changes are needed.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Generator, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

_DATABASE_URL = os.getenv("DATABASE_URL")

if not _DATABASE_URL:
    # Default to local SQLite file
    _db_dir = os.path.dirname(__file__)
    _DATABASE_URL = f"sqlite:///{os.path.join(_db_dir, 'closetmate.db')}"

# Heroku exports DATABASE_URL starting with "postgres://" (old format).
# SQLAlchemy 1.4+ requires "postgresql://".
if _DATABASE_URL.startswith("postgres://"):
    _DATABASE_URL = _DATABASE_URL.replace("postgres://", "postgresql://", 1)

_is_sqlite = _DATABASE_URL.startswith("sqlite")

_connect_args = {"check_same_thread": False} if _is_sqlite else {}

engine = create_engine(
    _DATABASE_URL,
    connect_args=_connect_args,
    pool_pre_ping=True,   # Detect stale connections (important for Postgres)
)


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------

def _placeholder(n: int) -> str:
    """Return the correct positional placeholder for the active DB dialect."""
    return "?" if _is_sqlite else "%s"


def init_db() -> None:
    """
    Create required tables if they do not already exist.
    Safe to call multiple times (idempotent).
    """
    with engine.begin() as conn:
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

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS clothing_metadata_cache (
                id            SERIAL PRIMARY KEY,
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
        """ if not _is_sqlite else """
            CREATE TABLE IF NOT EXISTS clothing_metadata_cache (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
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

        # Safe migration: add subcategory column if missing (older SQLite DBs)
        if _is_sqlite:
            try:
                conn.execute(text("ALTER TABLE wardrobe_items ADD COLUMN subcategory TEXT"))
            except Exception:
                pass  # Column already exists — fine


# ---------------------------------------------------------------------------
# Request-scoped connection (used as FastAPI Dependency)
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


class _ConnectionWrapper:
    """
    Wraps a SQLAlchemy Connection to expose the sqlite3-style API:
      conn.execute(sql, params)  → returns a cursor-like object
      conn.commit()              → commits (no-op inside begin() blocks)
      conn.row_factory           → ignored (handled by _RowProxy)

    This lets all existing routers work without modification.
    """

    def __init__(self, conn: Connection):
        self._conn = conn
        self.row_factory = None  # compatibility attribute; not used

    def execute(self, sql: str, params=()) -> "_ResultProxy":
        # SQLAlchemy text() is required for raw SQL strings
        result = self._conn.execute(text(sql), _bind_params(sql, params))
        return _ResultProxy(result)

    def commit(self):
        # SQLAlchemy autocommit is managed by the context manager in get_db().
        # Explicit commit() calls from routers are safe to no-op here because
        # the connection is committed when the with-block exits.
        self._conn.commit()

    def close(self):
        pass  # Handled by the generator's finally block


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


def _bind_params(sql: str, params):
    """
    Convert positional params tuple to a dict keyed by position for SQLAlchemy.
    SQLAlchemy's text() uses :param_name style; we convert ? / %s on the fly.
    """
    if not params:
        return {}

    # Replace positional placeholders with :p0, :p1, … so SQLAlchemy can bind
    named = {}
    idx = 0
    new_sql = sql  # We don't need to rebuild sql here — handled below

    return dict((f"p{i}", v) for i, v in enumerate(params))


def _patch_sql(sql: str) -> str:
    """Replace ? or %s placeholders with :p0, :p1, … for SQLAlchemy text()."""
    import re
    counter = [0]

    def _repl(_match):
        name = f":p{counter[0]}"
        counter[0] += 1
        return name

    return re.sub(r"\?|%s", _repl, sql)


# Override execute to patch SQL placeholders automatically
_original_execute = _ConnectionWrapper.execute


def _patched_execute(self, sql, params=()):
    from sqlalchemy.sql import ClauseElement
    # Already a SQLAlchemy expression (text(), select(), etc.) — pass straight through
    if isinstance(sql, ClauseElement):
        named = params if isinstance(params, dict) else {}
        result = self._conn.execute(sql, named)
        return _ResultProxy(result)
    # Legacy: raw SQL string with ? or %s → convert to :p0, :p1, …
    patched = _patch_sql(sql)
    named = {f"p{i}": v for i, v in enumerate(params)}
    result = self._conn.execute(text(patched), named)
    return _ResultProxy(result)


_ConnectionWrapper.execute = _patched_execute


def get_db() -> Generator[_ConnectionWrapper, None, None]:
    """
    FastAPI dependency that provides a DB connection for the lifetime of a request.
    Usage in routers:  db: sqlite3.Connection = Depends(get_db)  (type hint unchanged)
    """
    with engine.begin() as conn:
        yield _ConnectionWrapper(conn)


# ---------------------------------------------------------------------------
# Standalone cache helpers (used outside FastAPI DI — e.g. upload.py)
# ---------------------------------------------------------------------------

def get_cached_metadata(image_hash: str) -> Optional[dict]:
    """Return cached metadata for the given MD5 hash, or None if not cached."""
    with engine.connect() as conn:
        sql = _patch_sql("SELECT * FROM clothing_metadata_cache WHERE image_hash = ?")
        result = conn.execute(text(sql), {"p0": image_hash})
        keys = list(result.keys())
        row = result.fetchone()
        if row is None:
            return None
        return dict(zip(keys, row))


def save_metadata_cache(image_hash: str, metadata: dict) -> None:
    """Upsert metadata into the cache table keyed by MD5 hash."""
    now = datetime.now(timezone.utc).isoformat()

    if _is_sqlite:
        sql = _patch_sql("""
            INSERT OR REPLACE INTO clothing_metadata_cache
              (image_hash, category, subcategory, primary_color, material,
               pattern, formality, culture, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """)
    else:
        # PostgreSQL upsert
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

    with engine.begin() as conn:
        conn.execute(text(sql), params)
