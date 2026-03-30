import os
import sqlite3
from datetime import datetime, timezone
from typing import Generator, Optional

DB_FILENAME = "closetmate.db"
DB_PATH = os.path.join(os.path.dirname(__file__), DB_FILENAME)


def init_db() -> None:
  """
  Initialize the SQLite database and ensure required tables exist.
  Safe to call multiple times.
  """
  conn = sqlite3.connect(DB_PATH)
  try:
    conn.execute(
      """
      CREATE TABLE IF NOT EXISTS users (
        user_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        gender TEXT NOT NULL,
        body_shape TEXT,
        skin_tone TEXT,
        style_preference TEXT,
        created_at TEXT NOT NULL
      )
      """
    )
    conn.execute(
      """
      CREATE TABLE IF NOT EXISTS wardrobe_items (
        item_id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        category TEXT,
        primary_color TEXT,
        material TEXT,
        pattern TEXT,
        formality_level TEXT,
        cultural_style TEXT,
        image_path TEXT,
        created_at TEXT NOT NULL
      )
      """
    )
    conn.execute(
      """
      CREATE TABLE IF NOT EXISTS clothing_metadata_cache (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        image_hash TEXT    NOT NULL UNIQUE,
        category   TEXT,
        subcategory TEXT,
        primary_color TEXT,
        material   TEXT,
        pattern    TEXT,
        formality  TEXT,
        culture    TEXT,
        created_at TEXT    NOT NULL
      )
      """
    )
    conn.commit()
  finally:
    conn.close()


def get_db() -> Generator[sqlite3.Connection, None, None]:
  """
  Provide a SQLite connection for a request.
  Connections are short‑lived and closed after use.
  """
  conn = sqlite3.connect(DB_PATH)
  conn.row_factory = sqlite3.Row
  try:
    yield conn
  finally:
    conn.close()


def get_cached_metadata(image_hash: str) -> Optional[dict]:
  """Return cached metadata for the given MD5 hash, or None if not cached."""
  conn = sqlite3.connect(DB_PATH)
  conn.row_factory = sqlite3.Row
  try:
    row = conn.execute(
      "SELECT * FROM clothing_metadata_cache WHERE image_hash = ?",
      (image_hash,),
    ).fetchone()
    return dict(row) if row else None
  finally:
    conn.close()


def save_metadata_cache(image_hash: str, metadata: dict) -> None:
  """Upsert metadata into the cache table keyed by MD5 hash."""
  now = datetime.now(timezone.utc).isoformat()
  conn = sqlite3.connect(DB_PATH)
  try:
    conn.execute(
      """
      INSERT OR REPLACE INTO clothing_metadata_cache
        (image_hash, category, subcategory, primary_color, material,
         pattern, formality, culture, created_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
      """,
      (
        image_hash,
        metadata.get("category"),
        metadata.get("subcategory"),
        metadata.get("primary_color"),
        metadata.get("material"),
        metadata.get("pattern"),
        metadata.get("formality") or metadata.get("formality_level"),
        metadata.get("culture"),
        now,
      ),
    )
    conn.commit()
  finally:
    conn.close()

