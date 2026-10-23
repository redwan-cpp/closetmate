#!/usr/bin/env python
"""
Postgres smoke test — the things the SQLite-only pytest suite cannot tell you.

Run it against a THROW-AWAY Postgres (a local container, or a scratch Neon branch), never prod:

    docker run -d --name pg-smoke -e POSTGRES_PASSWORD=pw -e POSTGRES_DB=closetmate_smoke \
        -p 127.0.0.1:55432:5432 postgres:17
    set PG_SMOKE_URL=postgresql://postgres:pw@127.0.0.1:55432/closetmate_smoke
    venv\\Scripts\\python.exe scripts\\pg_smoke.py

It refuses to run unless the database name contains "smoke", "test", "scratch" or "tmp". It only
creates rows of its own (random e-mail addresses) and deletes them again at the end.

Covers: concurrent schema bootstrap (advisory lock), the unique e-mail index, refresh-token
rotation and reuse, expanding IN-queries, the `ON CONFLICT ... WHERE` quota upsert under
contention, refunds, the saved-looks lock (Postgres advisory lock alone, thread lock alone and a
no-lock control that must misbehave), and a real studio-shot request through the whole stack.
"""
from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

URL = os.environ.get("PG_SMOKE_URL", "").strip()
ROOT = Path(__file__).resolve().parent.parent


def refuse(message: str) -> None:
    print(f"pg_smoke: {message}")
    sys.exit(2)


if not URL.startswith(("postgresql://", "postgres://")):
    refuse("set PG_SMOKE_URL to a postgresql:// URL of a throw-away database.")
_db_name = urlparse(URL).path.lstrip("/").lower()
if not any(word in _db_name for word in ("smoke", "test", "scratch", "tmp")):
    refuse(f"database name {_db_name!r} doesn't look disposable (needs smoke/test/scratch/tmp in it).")

# Must be set before any application module is imported. Blank (not absent) keys stop a
# developer's .env from supplying real ones.
ENV = {
    "ENV": "dev",
    "DATABASE_URL": URL,
    "JWT_SECRET": "pg-smoke-secret-" + "x" * 40,
    "OPENAI_API_KEY": "",
    "GEMINI_API_KEY": "",
    "GCS_BUCKET": "",
    "K_SERVICE": "",
    "QUOTA_FREE_CHAT_MONTHLY": "3",
    "QUOTA_FREE_BGREMOVE_MONTHLY": "50",
    "MAX_SAVED_LOOKS": "",
    "STUDIO_RMBG_MODEL": "",
}
os.environ.update(ENV)
sys.path.insert(0, str(ROOT))

results: list[tuple[str, bool]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"   [{detail}]" if detail and not ok else ""))
    results.append((name, bool(ok)))
    return bool(ok)


def skip(name: str, why: str) -> None:
    print(f"SKIP  {name}   [{why}]")


# ---------------------------------------------------------------------------
# 1. Concurrent schema bootstrap
# ---------------------------------------------------------------------------

def bootstrap_checks() -> None:
    from sqlalchemy import create_engine, text

    engine = create_engine(URL)
    with engine.connect() as conn:
        fresh = conn.execute(text("SELECT to_regclass('public.users')")).scalar() is None
    if fresh:
        procs = [
            subprocess.Popen(
                [sys.executable, "-c", "import database; database.init_db(); print('ok')"],
                cwd=ROOT, env=os.environ.copy(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            for _ in range(6)
        ]
        outs = [p.communicate(timeout=120) for p in procs]
        check("six instances bootstrapping an empty database at once all succeed",
              all(p.returncode == 0 and "ok" in o[0] for p, o in zip(procs, outs)),
              "; ".join(o[1].strip().splitlines()[-1] for p, o in zip(procs, outs) if p.returncode != 0 and o[1].strip()))
    else:
        skip("concurrent bootstrap", "database already initialised")
        import database
        database.init_db()

    with engine.connect() as conn:
        tables = {r[0] for r in conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))}
        indexes = {r[0] for r in conn.execute(text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'"))}
    expected_tables = {"users", "wardrobe_items", "worn_logs", "refresh_tokens", "usage_counters",
                       "ai_usage", "clothing_metadata_cache", "saved_looks"}
    check("every table exists", expected_tables <= tables, f"missing {sorted(expected_tables - tables)}")
    check("indexes exist (case-insensitive e-mail key, looks)",
          {"users_email_lower_key", "idx_looks_user"} <= indexes, f"have {sorted(indexes)}")
    engine.dispose()


# ---------------------------------------------------------------------------
# 2. Application behaviour on Postgres
# ---------------------------------------------------------------------------

def run_app_checks() -> None:
    import database
    import quota
    import routers.wardrobe as wardrobe
    import settings
    from fastapi.testclient import TestClient
    from PIL import Image
    from sqlalchemy import text

    import main

    created_users: list[str] = []

    def sql(statement: str, **params):
        with database.engine.begin() as conn:
            result = conn.execute(text(statement), params)
            return [dict(r._mapping) for r in result] if result.returns_rows else []

    def set_env(**values: str) -> None:
        for key, value in values.items():
            os.environ[key] = str(value)
        settings.reset_settings_cache()

    with TestClient(main.app) as client:
        def account(label: str) -> dict:
            email = f"smoke-{label}-{uuid.uuid4().hex[:10]}@example.com"
            r = client.post("/auth/register", json={"name": label, "email": email, "password": "smoke-pass-12345",
                                                    "gender": "female"})
            assert r.status_code == 201, r.text
            uid = r.json()["user_id"]
            created_users.append(uid)
            r = client.post("/auth/login", json={"email": email, "password": "smoke-pass-12345"})
            assert r.status_code == 200, r.text
            body = r.json()
            return {"uid": uid, "email": email, "token": body["token"], "refresh": body["refresh_token"],
                    "h": {"Authorization": f"Bearer {body['token']}"}}

        def relogin(user: dict) -> dict:
            body = client.post("/auth/login", json={"email": user["email"], "password": "smoke-pass-12345"}).json()
            user.update(token=body["token"], refresh=body["refresh_token"],
                        h={"Authorization": f"Bearer {body['token']}"})
            return user

        alice, bob = account("alice"), account("bob")

        # --- auth ---------------------------------------------------------------
        dup = client.post("/auth/register", json={"name": "x", "email": alice["email"].upper(),
                                                  "password": "smoke-pass-12345", "gender": "female"})
        check("duplicate e-mail in other case is a clean 400, not a 500", dup.status_code == 400, str(dup.status_code))

        r1 = client.post("/auth/refresh", json={"refresh_token": alice["refresh"]})
        check("refresh rotates the token", r1.status_code == 200 and r1.json()["refresh_token"] != alice["refresh"])
        reuse = client.post("/auth/refresh", json={"refresh_token": alice["refresh"]})
        check("re-using a spent refresh token is refused", reuse.status_code == 401, str(reuse.status_code))
        after = client.post("/auth/refresh", json={"refresh_token": r1.json()["refresh_token"]})
        check("…and it revokes the whole family", after.status_code == 401, str(after.status_code))

        relogin(alice)
        spent = alice["refresh"]
        gate = threading.Barrier(2, timeout=10)

        def spend() -> int:
            gate.wait()
            return client.post("/auth/refresh", json={"refresh_token": spent}).status_code

        with ThreadPoolExecutor(2) as pool:
            codes = sorted(pool.map(lambda _: spend(), range(2)))
        check("two simultaneous refreshes with one token: never a 5xx, at most one succeeds",
              all(c < 500 for c in codes) and codes.count(200) <= 1, str(codes))
        relogin(alice)

        # --- wardrobe -----------------------------------------------------------
        def add(user: dict, category: str, sub: str, colour: str) -> str:
            r = client.post("/wardrobe/add-item", headers=user["h"], json={
                "user_id": user["uid"], "image_path": f"uploads/processed/{sub}.webp", "category": category,
                "subcategory": sub, "primary_color": colour, "material": "cotton", "pattern": "solid",
                "formality": "casual", "culture": "western"})
            assert r.status_code == 201, r.text
            return r.json()["item_id"]

        shirt, jeans = add(alice, "top", "shirt", "cream"), add(alice, "bottom", "jeans", "navy")
        add(alice, "footwear", "sneakers", "white")
        add(alice, "outerwear", "jacket", "tan")
        listing = client.get(f"/wardrobe/items/{alice['uid']}", headers=alice["h"])
        slots = {i["subcategory"]: i.get("slot") for i in listing.json()} if listing.status_code == 200 else {}
        check("wardrobe list returns every item with its slot",
              slots == {"shirt": "top", "jeans": "bottom", "sneakers": "shoes", "jacket": "outer"}, str(slots))
        check("another user cannot read it",
              client.get(f"/wardrobe/items/{alice['uid']}", headers=bob["h"]).status_code == 403)

        # --- saved looks --------------------------------------------------------
        def save(user: dict, ids: list[str]):
            return client.post("/wardrobe/looks", headers=user["h"], json={"user_id": user["uid"], "item_ids": ids})

        first = save(alice, [shirt, jeans])
        again = save(alice, [jeans, shirt])
        check("saving an outfit twice (any order) returns the same look",
              first.status_code == 201 and again.status_code == 200
              and first.json()["look_id"] == again.json()["look_id"], f"{first.status_code}/{again.status_code}")
        looks = client.get(f"/wardrobe/looks/{alice['uid']}", headers=alice["h"]).json()
        check("looks list joins items and slots in one query",
              len(looks) == 1 and sorted(i["slot"] for i in looks[0]["items"]) == ["bottom", "top"], str(looks)[:200])
        check("deleting a look works",
              client.delete(f"/wardrobe/looks/{first.json()['look_id']}", headers=alice["h"]).status_code == 200)
        sql("DELETE FROM saved_looks WHERE user_id = :u", u=alice["uid"])

        real_settings, real_owned = wardrobe.get_settings, wardrobe._owned_items
        real_locks, real_gate = wardrobe._SAVE_LOCKS, wardrobe._one_save_at_a_time

        def race(payloads: list[list[str]]):
            """Start every request together, with a wide gap between check and insert."""
            sql("DELETE FROM saved_looks WHERE user_id = :u", u=alice["uid"])
            start = threading.Barrier(len(payloads), timeout=15)

            def together(*a, **k):
                start.wait()
                return real_owned(*a, **k)

            def slow():
                time.sleep(0.4)
                return real_settings()

            wardrobe._owned_items, wardrobe.get_settings = together, slow
            try:
                with ThreadPoolExecutor(len(payloads)) as pool:
                    statuses = sorted(r.status_code for r in pool.map(lambda ids: save(alice, ids), payloads))
            finally:
                wardrobe._owned_items, wardrobe.get_settings = real_owned, real_settings
            rows = sql("SELECT count(*) AS n FROM saved_looks WHERE user_id = :u", u=alice["uid"])[0]["n"]
            return statuses, rows

        # Postgres advisory lock alone (thread locks neutralised): proves the multi-instance path.
        wardrobe._SAVE_LOCKS = tuple(contextlib.nullcontext() for _ in range(64))
        statuses, rows = race([[shirt, jeans], [jeans, shirt]])
        check("double tap, advisory lock only → one look stored", rows == 1 and statuses == [200, 201], f"{statuses} rows={rows}")
        set_env(MAX_SAVED_LOOKS="1")
        statuses, rows = race([[shirt], [jeans]])
        check("two racing saves at the cap, advisory lock only → cap holds", rows == 1 and statuses == [201, 403], f"{statuses} rows={rows}")
        set_env(MAX_SAVED_LOOKS="")

        # Control: with neither lock the race MUST show duplicates, otherwise the checks above prove nothing.
        @contextlib.contextmanager
        def no_lock(db, uid):
            yield

        wardrobe._one_save_at_a_time = no_lock
        statuses, rows = race([[shirt, jeans], [jeans, shirt]])
        check("CONTROL: without any lock the same race stores duplicates (the check is sensitive)", rows == 2, f"{statuses} rows={rows}")
        wardrobe._one_save_at_a_time, wardrobe._SAVE_LOCKS = real_gate, real_locks

        statuses, rows = race([[shirt, jeans], [jeans, shirt]])
        check("double tap, normal locks → one look stored", rows == 1 and statuses == [200, 201], f"{statuses} rows={rows}")
        sql("DELETE FROM saved_looks WHERE user_id = :u", u=alice["uid"])

        # --- quota --------------------------------------------------------------
        set_env(QUOTA_FREE_CHAT_MONTHLY="3")
        with ThreadPoolExecutor(10) as pool:
            granted = sum(1 for r in pool.map(lambda _: quota.consume_quota(bob["uid"], "chat"), range(10)) if r.allowed)
        used = quota.usage_summary(bob["uid"])["chat"]["used"]
        check("10 concurrent requests against a limit of 3 → exactly 3 granted", granted == 3 and used == 3, f"granted={granted} used={used}")
        quota.refund_quota(bob["uid"], "chat")
        check("refund gives one unit back", quota.usage_summary(bob["uid"])["chat"]["used"] == 2)
        period = "smoke-" + uuid.uuid4().hex[:6]
        with ThreadPoolExecutor(8) as pool:
            global_ok = sum(1 for ok in pool.map(lambda _: quota.consume_global(period, 2), range(8)) if ok)
        check("global daily cap under contention → exactly 2 granted", global_ok == 2, str(global_ok))
        sql("DELETE FROM usage_counters WHERE period = :p", p=period)

        before = quota.usage_summary(alice["uid"])["chat"]["used"]
        chat = client.post("/chat/message", headers=alice["h"],
                           json={"user_id": alice["uid"], "message": "what should I wear?", "history": []})
        after_used = quota.usage_summary(alice["uid"])["chat"]["used"]
        check("chat with no provider keys: 503, and the unit is refunded",
              chat.status_code == 503 and after_used == before, f"{chat.status_code} used={after_used} before={before}")

        # --- metadata cache upsert (ON CONFLICT DO UPDATE) -----------------------
        digest = uuid.uuid4().hex
        database.save_metadata_cache(digest, {"category": "top", "primary_color": "red"})
        database.save_metadata_cache(digest, {"category": "top", "primary_color": "blue"})
        cached = database.get_cached_metadata(digest)
        check("metadata cache upsert keeps the latest value", bool(cached) and cached.get("primary_color") == "blue", str(cached))
        sql("DELETE FROM clothing_metadata_cache WHERE image_hash = :h", h=digest)

        # --- studio shot through the whole stack -------------------------------
        def photo(draw) -> bytes:
            img = Image.new("RGB", (900, 1200), (214, 214, 210))
            draw(img)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=92)
            return buf.getvalue()

        def shirt_shape(img):
            from PIL import ImageDraw
            ImageDraw.Draw(img).polygon(
                [(250, 260), (420, 220), (480, 220), (650, 260), (760, 480), (660, 540), (620, 470),
                 (620, 1000), (280, 1000), (280, 470), (240, 540), (140, 480)], fill=(176, 38, 52))

        why = ""
        try:
            r = client.post("/studio-shot", headers=alice["h"], files={"file": ("shirt.jpg", photo(shirt_shape), "image/jpeg")})
        except Exception as exc:  # noqa: BLE001 — typically: the rembg model could not be loaded
            r, why = None, repr(exc)[:160]
        if r is None or r.status_code >= 500:
            skip("studio shot end to end", why or f"HTTP {r.status_code}: {r.text[:160]}")
        else:
            import base64
            body = r.json()
            full = Image.open(io.BytesIO(base64.b64decode(body["image"])))
            thumb = Image.open(io.BytesIO(base64.b64decode(body["thumb"])))
            alpha = full.convert("RGBA").getchannel("A")
            check("studio shot returns a 640x800 WebP with a transparent background and a 320x400 thumbnail",
                  r.status_code == 200 and full.size == (640, 800) and thumb.size == (320, 400) and full.format == "WEBP"
                  and alpha.getpixel((5, 5)) == 0 and alpha.getpixel((320, 400)) >= 240,
                  f"{r.status_code} {full.size} {thumb.size} corner={alpha.getpixel((5, 5))} centre={alpha.getpixel((320, 400))}")
            used_bg = quota.usage_summary(alice["uid"])["bgremove"]["used"]
            blank = client.post("/studio-shot", headers=alice["h"],
                                files={"file": ("blank.jpg", photo(lambda img: None), "image/jpeg")})
            now_bg = quota.usage_summary(alice["uid"])["bgremove"]["used"]
            check("a photo with no garment is a 422 that doesn't cost the user a unit",
                  blank.status_code == 422 and now_bg == used_bg, f"{blank.status_code} used {used_bg}→{now_bg}")

    # --- cleanup: only what this run created ------------------------------------
    for table in ("saved_looks", "worn_logs", "wardrobe_items", "refresh_tokens", "usage_counters", "ai_usage", "users"):
        for uid in created_users:
            sql(f"DELETE FROM {table} WHERE user_id = :u", u=uid)
    sql("DELETE FROM usage_counters WHERE user_id = '__global__' AND feature = 'ai_calls' AND period LIKE 'smoke-%'")
    database.engine.dispose()


def main() -> int:
    started = time.time()
    bootstrap_checks()
    run_app_checks()
    failed = [name for name, ok in results if not ok]
    print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed in {time.time() - started:.1f}s")
    for name in failed:
        print(f"  FAILED: {name}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
