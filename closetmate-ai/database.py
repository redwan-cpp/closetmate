"""
database.py — SQLAlchemy-backed database layer for ClosetMate.

Production : DATABASE_URL must be set to a PostgreSQL connection string.
             e.g. postgresql://user:pass@host/dbname?sslmode=require
Local dev  : Set DATABASE_URL in .env — no SQLite fallback in this version.

The get_db() generator yields a _ConnectionWrapper that supports the same
.execute() / .fetchone() / .fetchall() / .commit() calls used throughout the
routers, so no router changes are needed.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Generator, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

_DATABASE_URL = os.getenv("DATABASE_URL")

if not _DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL environment variable is not set. "
        "Please configure it with your Neon PostgreSQL connection string."
    )

# Normalize legacy "postgres://" prefix (some providers still emit it)
if _DATABASE_URL.startswith("postgres://"):
    _DATABASE_URL = _DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(
    _DATABASE_URL,
    pool_pre_ping=True,       # detect stale connections — essential for Neon
    pool_size=5,              # keep a small pool for Cloud Run concurrency
    max_overflow=10,
    pool_recycle=1800,        # recycle connections every 30 min (Neon idle limit)
)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

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

class _ConnectionWrapper:
    """
    Wraps a SQLAlchemy Connection to expose the sqlite3-style API used
    throughout the routers:
      conn.execute(sql, params)  → returns a cursor-like object
      conn.commit()              → commits (auto-managed inside begin() blocks)
    """

    def __init__(self, conn: Connection):
        self._conn = conn
        self.row_factory = None   # compatibility attribute; not used

    def execute(self, sql, params=()) -> _ResultProxy:
        from sqlalchemy.sql import ClauseElement
        if isinstance(sql, ClauseElement):
            named = params if isinstance(params, dict) else {}
            result = self._conn.execute(sql, named)
            return _ResultProxy(result)
        # Raw SQL string — patch ? / %s placeholders and bind positionally
        patched = _patch_sql(str(sql))
        if isinstance(params, dict):
            named = params
        else:
            named = {f"p{i}": v for i, v in enumerate(params)}
        result = self._conn.execute(text(patched), named)
        return _ResultProxy(result)

    def commit(self):
        # Transactions are managed by engine.begin() context manager.
        # Explicit commit() calls in routers are forwarded to keep compatibility.
        self._conn.commit()

    def close(self):
        pass  # Handled by the generator's finally block


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------

def get_db() -> Generator[_ConnectionWrapper, None, None]:
    """
    FastAPI dependency that provides a transactional DB connection for the
    lifetime of a request. Auto-commits on success, rolls back on exception.

    Usage in routers:
        db: Any = Depends(get_db)
    """
    with engine.begin() as conn:
        yield _ConnectionWrapper(conn)


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
