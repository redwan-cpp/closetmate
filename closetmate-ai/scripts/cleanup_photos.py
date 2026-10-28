#!/usr/bin/env python
"""
Remove stored photos that nothing uses any more.

    venv\\Scripts\\python.exe scripts\\cleanup_photos.py                 # report only
    venv\\Scripts\\python.exe scripts\\cleanup_photos.py --apply         # actually delete
    venv\\Scripts\\python.exe scripts\\cleanup_photos.py --apply --older-than-hours 48

Two kinds of leftovers are handled:

  * photos of accounts that no longer exist — e.g. an upload that raced an account deletion
    (an access token outlives a deletion by up to 15 minutes);
  * photos that were stored but never became part of an item (the user cancelled, the app was
    killed before it could discard them), once they are older than --older-than-hours (default 24).

Run it from a scheduled job (Cloud Scheduler -> Cloud Run job) or by hand. It is safe to run any
time and as often as you like: a photo that an item uses is never touched, and without --apply
nothing is changed.
"""
from __future__ import annotations

import argparse
import pathlib
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from database import db_session  # noqa: E402
from services.photo_store import get_store  # noqa: E402


def find_leftovers(db, older_than_hours: float) -> dict:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=older_than_hours)).isoformat()
    gone = db.execute(text(
        "SELECT photo_id, user_id, key, thumb_key FROM photos "
        "WHERE user_id NOT IN (SELECT user_id FROM users)"
    )).fetchall()
    unused = db.execute(text(
        "SELECT photo_id, user_id, key, thumb_key FROM photos "
        "WHERE created_at < :cutoff "
        "AND user_id IN (SELECT user_id FROM users) "
        "AND key NOT IN (SELECT image_path FROM wardrobe_items WHERE image_path IS NOT NULL)"
    ), {"cutoff": cutoff}).fetchall()
    return {"accounts_gone": [dict(r._mapping) for r in gone], "never_attached": [dict(r._mapping) for r in unused]}


def remove(db, rows: list) -> int:
    store = get_store()
    removed = 0
    for row in rows:
        try:
            store.delete(row["key"])
            store.delete(row["thumb_key"])
        except Exception as exc:  # noqa: BLE001 — keep the record so the next run retries
            print(f"  could not delete {row['key']}: {type(exc).__name__}")
            continue
        db.execute(text("DELETE FROM photos WHERE photo_id = :p"), {"p": row["photo_id"]})
        removed += 1
    db.commit()
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="delete (default: only report)")
    parser.add_argument("--older-than-hours", type=float, default=24.0,
                        help="never-attached photos younger than this are left alone (default 24)")
    args = parser.parse_args()

    with db_session() as db:
        found = find_leftovers(db, args.older_than_hours)
        for label, rows in found.items():
            print(f"{label}: {len(rows)}")
        if not args.apply:
            print("\n(report only — run with --apply to delete)")
            return 0
        total = sum(remove(db, rows) for rows in found.values())
        print(f"\ndeleted {total} photo(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
