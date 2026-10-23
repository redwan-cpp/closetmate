"""database.py — engine selection, schema bootstrap, session/transaction semantics, metadata cache."""
from __future__ import annotations

import importlib.util
import logging
import pathlib
import uuid

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

import database
from conftest import DB_FILE
from database import (
    _ConnectionWrapper,
    _patch_sql,
    _RowProxy,
    db_session,
    get_cached_metadata,
    get_db,
    init_db,
    ping_db,
    save_metadata_cache,
)

DATABASE_PY = pathlib.Path(database.__file__)


def load_fresh_database(monkeypatch, **env):
    """Execute database.py again under a throw-away module name with the given environment."""
    for name, value in env.items():
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    spec = importlib.util.spec_from_file_location(f"database_fresh_{uuid.uuid4().hex[:8]}", DATABASE_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def insert_counter(db, user="u1", feature="chat", period="2026-01", count=1):
    db.execute(
        text("INSERT INTO usage_counters (user_id, feature, period, count) VALUES (:u, :f, :p, :c)"),
        {"u": user, "f": feature, "p": period, "c": count},
    )


def counter_rows(sql):
    return sql("SELECT user_id, count FROM usage_counters ORDER BY user_id")


# ---------------------------------------------------------------------------
# Engine selection
# ---------------------------------------------------------------------------

class TestEngineSelection:
    def test_the_suite_runs_against_the_explicit_sqlite_url(self):
        assert database._USE_SQLITE is True
        assert pathlib.Path(database.engine.url.database).resolve() == DB_FILE.resolve()

    def test_explicit_sqlite_path_is_honoured(self, monkeypatch, tmp_path):
        target = tmp_path / "other.db"
        fresh = load_fresh_database(monkeypatch, DATABASE_URL=f"sqlite:///{target.as_posix()}")
        try:
            assert pathlib.Path(fresh.engine.url.database) == target
            assert fresh._USE_SQLITE is True
        finally:
            fresh.engine.dispose()

    @pytest.mark.parametrize("value", ["", "sqlite", "LOCAL", "sqlite:///"])
    def test_unset_or_bare_sqlite_falls_back_to_the_local_dev_file(self, monkeypatch, value):
        fresh = load_fresh_database(monkeypatch, DATABASE_URL=value)
        try:
            assert pathlib.Path(fresh.engine.url.database) == DATABASE_PY.parent / "closetmate.db"
        finally:
            fresh.engine.dispose()

    @pytest.mark.parametrize("env", [{"ENV": "prod"}, {"K_SERVICE": "closetmate-api"}])
    def test_sqlite_is_refused_in_production(self, monkeypatch, env):
        with pytest.raises(RuntimeError, match="PostgreSQL"):
            load_fresh_database(monkeypatch, DATABASE_URL="", **env)

    def test_explicit_sqlite_url_is_refused_in_production_too(self, monkeypatch, tmp_path):
        with pytest.raises(RuntimeError, match="PostgreSQL"):
            load_fresh_database(monkeypatch, ENV="prod", DATABASE_URL=f"sqlite:///{(tmp_path / 'x.db').as_posix()}")

    def test_legacy_postgres_scheme_is_normalised_and_pool_is_bounded(self, monkeypatch, caplog):
        with caplog.at_level(logging.INFO):
            fresh = load_fresh_database(
                monkeypatch, ENV="test", DATABASE_URL="postgres://app:s3cr3tpw@db.example.test:5432/closet",
                DB_POOL_SIZE="2", DB_MAX_OVERFLOW="1",
            )
        try:
            assert fresh._USE_SQLITE is False
            assert fresh.engine.url.drivername == "postgresql"
            assert fresh.engine.url.host == "db.example.test" and fresh.engine.url.database == "closet"
            assert fresh.engine.pool.size() == 2
            assert fresh.engine.hide_parameters is True
            assert "s3cr3tpw" not in caplog.text                     # the URL / password is never logged
        finally:
            fresh.engine.dispose()

    def test_postgres_pool_defaults_are_small(self, monkeypatch):
        fresh = load_fresh_database(monkeypatch, ENV="test", DATABASE_URL="postgresql://u:p@h/db",
                                    DB_POOL_SIZE=None, DB_MAX_OVERFLOW=None)
        try:
            assert fresh.engine.pool.size() == 3
        finally:
            fresh.engine.dispose()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

EXPECTED_TABLES = {
    "users", "wardrobe_items", "clothing_metadata_cache", "worn_logs",
    "refresh_tokens", "ai_usage", "usage_counters", "saved_looks",
}
EXPECTED_INDEXES = {
    "idx_wardrobe_user", "idx_worn_user_date", "idx_refresh_user",
    "idx_ai_usage_created", "idx_ai_usage_user", "users_email_lower_key", "idx_looks_user",
}


class TestInitDb:
    def test_creates_every_table(self):
        assert EXPECTED_TABLES <= set(inspect(database.engine).get_table_names())

    def test_creates_every_index(self, sql):
        # Queried from sqlite_master: SQLAlchemy cannot reflect the expression index on lower(email).
        names = {r["name"] for r in sql("SELECT name FROM sqlite_master WHERE type = 'index'")}
        assert EXPECTED_INDEXES <= names

    def test_is_idempotent_and_keeps_existing_data(self, sql):
        sql("INSERT INTO usage_counters VALUES ('keep-me', 'chat', '2026-01', 7)")
        init_db()
        init_db()
        assert counter_rows(sql) == [{"user_id": "keep-me", "count": 7}]

    def test_usage_counters_primary_key_is_composite(self, sql):
        sql("INSERT INTO usage_counters VALUES ('u', 'chat', '2026-01', 1)")
        sql("INSERT INTO usage_counters VALUES ('u', 'chat', '2026-02', 1)")          # other period: fine
        sql("INSERT INTO usage_counters VALUES ('u', 'vision', '2026-01', 1)")        # other feature: fine
        with pytest.raises(IntegrityError):
            sql("INSERT INTO usage_counters VALUES ('u', 'chat', '2026-01', 1)")

    def test_user_emails_are_unique_case_insensitively(self, sql):
        insert = ("INSERT INTO users (user_id, name, email, password_hash, gender, created_at) "
                  "VALUES (:id, 'N', :email, 'h', 'x', '2026-01-01')")
        sql(insert, id="1", email="Mixed@Example.com")
        with pytest.raises(IntegrityError):
            sql(insert, id="2", email="mixed@example.COM")

    def test_cache_hash_is_unique(self, sql):
        insert = "INSERT INTO clothing_metadata_cache (image_hash, created_at) VALUES ('h', 'now')"
        sql(insert)
        with pytest.raises(IntegrityError):
            sql(insert)

    def test_ping_db_succeeds(self):
        assert ping_db() is None

    def test_ping_db_raises_when_the_connection_fails(self, monkeypatch):
        def refuse(*_a, **_k):
            raise RuntimeError("server closed the connection")

        monkeypatch.setattr(database.engine, "connect", refuse)
        with pytest.raises(RuntimeError):
            ping_db()


# ---------------------------------------------------------------------------
# SQL helpers and row proxies
# ---------------------------------------------------------------------------

class TestPatchSql:
    def test_question_marks_become_numbered_named_params(self):
        assert _patch_sql("SELECT * FROM t WHERE a = ? AND b = ?") == "SELECT * FROM t WHERE a = :p0 AND b = :p1"

    def test_percent_s_placeholders_are_supported_and_numbering_is_shared(self):
        assert _patch_sql("a = %s AND b = ? AND c = %s") == "a = :p0 AND b = :p1 AND c = :p2"

    def test_sql_without_placeholders_is_unchanged(self):
        assert _patch_sql("SELECT 1") == "SELECT 1"


class TestRowProxy:
    def make(self):
        return _RowProxy((1, "two"), ["a", "b"])

    def test_dict_style_access(self):
        row = self.make()
        assert row["a"] == 1 and row["b"] == "two"
        assert row.get("a") == 1 and row.get("missing") is None and row.get("missing", 5) == 5
        with pytest.raises(KeyError):
            row["missing"]

    def test_mapping_helpers(self):
        row = self.make()
        assert list(row.keys()) == ["a", "b"] and list(row.values()) == [1, "two"]
        assert dict(row.items()) == {"a": 1, "b": "two"} and row._mapping == {"a": 1, "b": "two"}
        assert len(row) == 2 and list(row) == [1, "two"]


class TestConnectionWrapper:
    def test_accepts_text_clauses_named_params(self):
        with db_session() as db:
            insert_counter(db)
            row = db.execute(text("SELECT count FROM usage_counters WHERE user_id = :u"), {"u": "u1"}).fetchone()
        assert row["count"] == 1

    def test_accepts_raw_strings_with_positional_params(self):
        with db_session() as db:
            db.execute("INSERT INTO usage_counters (user_id, feature, period, count) VALUES (?, ?, ?, ?)",
                       ("u9", "chat", "2026-01", 3))
            row = db.execute("SELECT count FROM usage_counters WHERE user_id = ?", ("u9",)).fetchone()
        assert row["count"] == 3

    def test_accepts_raw_strings_with_named_params(self):
        with db_session() as db:
            db.execute("INSERT INTO usage_counters (user_id, feature, period, count) VALUES (:a, 'chat', 'p', 1)", {"a": "n"})
            assert db.execute("SELECT 1 FROM usage_counters WHERE user_id = :a", {"a": "n"}).fetchone() is not None

    def test_fetch_helpers_and_rowcount(self):
        with db_session() as db:
            for n in range(3):
                insert_counter(db, user=f"u{n}")
            assert len(db.execute(text("SELECT * FROM usage_counters")).fetchall()) == 3
            assert db.execute(text("SELECT * FROM usage_counters WHERE user_id = 'nobody'")).fetchone() is None
            assert db.execute(text("UPDATE usage_counters SET count = 5")).rowcount == 3

    def test_non_row_statements_have_no_keys(self):
        with db_session() as db:
            result = db.execute(text("DELETE FROM usage_counters"))
            assert result.rowcount == 0

    @pytest.mark.parametrize(
        "statement,dirty",
        [
            ("INSERT INTO usage_counters VALUES ('u', 'f', 'p', 1)", True),
            ("  insert into usage_counters values ('u2', 'f', 'p', 1)", True),
            ("UPDATE usage_counters SET count = 2", True),
            ("DELETE FROM usage_counters", True),
            ("SELECT * FROM usage_counters", False),
        ],
    )
    def test_writes_mark_the_wrapper_dirty(self, statement, dirty):
        with database.engine.connect() as conn:
            wrapper = _ConnectionWrapper(conn)
            wrapper.execute(statement)
            assert wrapper._dirty is dirty
            wrapper.rollback()
            assert wrapper._dirty is False

    def test_close_is_a_noop_and_row_factory_is_a_compat_attribute(self):
        with db_session() as db:
            assert db.close() is None and db.row_factory is None
            db.execute(text("SELECT 1"))                                      # still usable


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------

class TestDbSession:
    def test_commits_on_clean_exit_when_a_write_happened(self, sql):
        with db_session() as db:
            insert_counter(db, user="written")
        assert counter_rows(sql) == [{"user_id": "written", "count": 1}]

    def test_rolls_back_and_reraises_on_exception(self, sql):
        with pytest.raises(RuntimeError, match="boom"):
            with db_session() as db:
                insert_counter(db, user="lost")
                raise RuntimeError("boom")
        assert counter_rows(sql) == []

    def test_read_only_sessions_do_not_write(self, sql):
        with db_session() as db:
            db.execute(text("SELECT * FROM usage_counters")).fetchall()
        assert counter_rows(sql) == []

    def test_commit_on_exit_false_discards_uncommitted_writes(self, sql):
        with db_session(commit_on_exit=False) as db:
            insert_counter(db, user="discarded")
        assert counter_rows(sql) == []

    def test_commit_on_exit_false_still_keeps_explicit_commits(self, sql):
        with db_session(commit_on_exit=False) as db:
            insert_counter(db, user="kept")
            db.commit()
        assert counter_rows(sql) == [{"user_id": "kept", "count": 1}]

    def test_commit_then_select_in_the_same_session_works(self, sql):
        """REGRESSION: committing and then SELECTing used to fail with 'closed transaction'."""
        with db_session() as db:
            insert_counter(db, user="first")
            db.commit()
            row = db.execute(text("SELECT user_id FROM usage_counters WHERE user_id = 'first'")).fetchone()
            assert row["user_id"] == "first"
            insert_counter(db, user="second")              # and a second transaction can start
            db.commit()
            assert len(db.execute(text("SELECT * FROM usage_counters")).fetchall()) == 2
        assert len(counter_rows(sql)) == 2

    def test_data_committed_before_an_error_survives_it(self, sql):
        with pytest.raises(RuntimeError):
            with db_session() as db:
                insert_counter(db, user="committed")
                db.commit()
                insert_counter(db, user="pending")
                raise RuntimeError("late failure")
        assert counter_rows(sql) == [{"user_id": "committed", "count": 1}]

    def test_explicit_rollback_discards_pending_writes(self, sql):
        with db_session() as db:
            insert_counter(db, user="gone")
            db.rollback()
            assert db.execute(text("SELECT * FROM usage_counters")).fetchall() == []
        assert counter_rows(sql) == []

    def test_integrity_errors_propagate_and_leave_nothing_behind(self, sql):
        with db_session() as db:
            insert_counter(db, user="dup")
        with pytest.raises(IntegrityError):
            with db_session() as db:
                insert_counter(db, user="other")
                insert_counter(db, user="dup")
        assert counter_rows(sql) == [{"user_id": "dup", "count": 1}]

    def test_a_failing_rollback_does_not_mask_the_original_error(self, caplog):
        def broken_rollback():
            raise ConnectionError("connection already closed")

        with caplog.at_level(logging.WARNING, logger="database"):
            with pytest.raises(RuntimeError, match="the real problem"):
                with db_session() as db:
                    db._conn.rollback = broken_rollback
                    raise RuntimeError("the real problem")
        assert "rollback failed" in caplog.text

    def test_connections_are_always_returned_to_the_pool(self):
        for _ in range(3):
            with db_session() as db:
                db.execute(text("SELECT 1"))
        with pytest.raises(ValueError):
            with db_session() as db:
                raise ValueError("x")
        assert database.engine.pool.checkedout() == 0

    def test_sessions_are_isolated_until_commit(self, sql):
        with db_session(commit_on_exit=False) as writer:
            insert_counter(writer, user="in-flight")
            assert counter_rows(sql) == []                 # not visible to another connection yet
            writer.commit()
            assert counter_rows(sql) == [{"user_id": "in-flight", "count": 1}]


class TestGetDb:
    def test_uncommitted_writes_are_rolled_back(self, sql):
        """The handler must commit itself: a post-response implicit commit could lose acknowledged writes."""
        gen = get_db()
        db = next(gen)
        insert_counter(db, user="forgot-to-commit")
        with pytest.raises(StopIteration):
            next(gen)
        assert counter_rows(sql) == []

    def test_explicit_commit_persists(self, sql):
        gen = get_db()
        db = next(gen)
        insert_counter(db, user="committed")
        db.commit()
        with pytest.raises(StopIteration):
            next(gen)
        assert counter_rows(sql) == [{"user_id": "committed", "count": 1}]

    def test_handler_errors_roll_back_and_release_the_connection(self, sql):
        gen = get_db()
        db = next(gen)
        insert_counter(db, user="aborted")
        with pytest.raises(RuntimeError):
            gen.throw(RuntimeError("handler failed"))
        assert counter_rows(sql) == []
        assert database.engine.pool.checkedout() == 0


# ---------------------------------------------------------------------------
# Metadata cache
# ---------------------------------------------------------------------------

META = {
    "category": "top", "subcategory": "shirt", "primary_color": "blue", "material": "cotton",
    "pattern": "striped", "formality": "smart casual", "culture": "western",
}


class TestMetadataCache:
    def test_unknown_hash_is_none(self):
        assert get_cached_metadata("0" * 32) is None

    def test_round_trip(self):
        save_metadata_cache("abc123", META)
        cached = get_cached_metadata("abc123")
        assert {k: cached[k] for k in META} == META
        assert cached["image_hash"] == "abc123" and cached["created_at"]

    def test_saving_again_overwrites_without_duplicating(self, sql):
        save_metadata_cache("h1", META)
        save_metadata_cache("h1", {**META, "primary_color": "red"})
        assert get_cached_metadata("h1")["primary_color"] == "red"
        assert len(sql("SELECT 1 FROM clothing_metadata_cache")) == 1

    def test_formality_level_alias_is_stored_as_formality(self):
        save_metadata_cache("h2", {"formality_level": "festive"})
        assert get_cached_metadata("h2")["formality"] == "festive"

    def test_missing_keys_are_stored_as_null(self):
        save_metadata_cache("h3", {})
        cached = get_cached_metadata("h3")
        assert all(cached[k] is None for k in ("category", "subcategory", "primary_color", "material",
                                               "pattern", "formality", "culture"))

    def test_hashes_do_not_collide(self):
        save_metadata_cache("h-a", {"category": "a"})
        save_metadata_cache("h-b", {"category": "b"})
        assert get_cached_metadata("h-a")["category"] == "a" and get_cached_metadata("h-b")["category"] == "b"

    def test_sql_metacharacters_in_the_hash_are_inert(self):
        evil = "x' OR '1'='1"
        save_metadata_cache("real", META)
        assert get_cached_metadata(evil) is None
