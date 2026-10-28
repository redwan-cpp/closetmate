"""main.py — probes, request ids, error handling, headers, CORS, docs, production boot."""
from __future__ import annotations

import dataclasses
import json
import logging
import os
import pathlib
import re
import subprocess
import sys
import textwrap

import pytest

import database

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture
def as_prod(monkeypatch, app_module):
    """Make the already-imported app behave as production for request-time decisions."""
    monkeypatch.setattr(app_module, "_settings", dataclasses.replace(app_module._settings, env="prod"))


@pytest.fixture
def boom_route(app_module):
    """A temporary route whose handler raises, to exercise the global exception handler."""
    app = app_module.app

    async def boom():
        raise RuntimeError("kaboom: password=hunter2")

    app.add_api_route("/__boom", boom, methods=["GET"])
    route = app.router.routes[-1]
    yield "/__boom"
    app.router.routes.remove(route)


# ---------------------------------------------------------------------------
# Probes
# ---------------------------------------------------------------------------

class TestProbes:
    def test_root(self, client):
        assert client.get("/").json() == {"message": "ClosetMate Backend Running"}

    def test_health_reports_ok_and_version(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "version": "0.2.0"}

    def test_health_does_not_touch_the_database(self, client, monkeypatch, app_module):
        def boom(*_a, **_k):
            raise AssertionError("the database must not be touched by /health")

        monkeypatch.setattr(app_module, "ping_db", boom)
        monkeypatch.setattr(database.engine, "connect", boom)
        assert client.get("/health").status_code == 200

    def test_ready_is_200_when_the_database_answers(self, client):
        resp = client.get("/ready")
        assert resp.status_code == 200 and resp.json() == {"status": "ready"}

    def test_ready_is_503_when_the_database_is_down(self, client, monkeypatch, app_module):
        def down():
            raise RuntimeError("connection to server at 10.0.0.5 failed: password authentication failed")

        monkeypatch.setattr(app_module, "ping_db", down)
        resp = client.get("/ready")
        assert resp.status_code == 503
        assert resp.json() == {"status": "unavailable"}
        assert "10.0.0.5" not in resp.text and "password" not in resp.text

    def test_ready_uses_a_real_connection(self, client, monkeypatch):
        def refuse(*_a, **_k):
            raise database.engine.dialect.dbapi.OperationalError("unable to open database file")

        monkeypatch.setattr(database.engine, "connect", refuse)
        assert client.get("/ready").status_code == 503

    def test_probe_requests_do_not_need_authentication(self, client):
        for path in ("/", "/health", "/ready"):
            assert client.get(path).status_code == 200


# ---------------------------------------------------------------------------
# Request id
# ---------------------------------------------------------------------------

class TestRequestId:
    def test_every_response_has_a_generated_request_id(self, client):
        rid = client.get("/health").headers["x-request-id"]
        assert re.fullmatch(r"[0-9a-f]{16}", rid)

    def test_ids_are_unique_per_request(self, client):
        ids = {client.get("/health").headers["x-request-id"] for _ in range(5)}
        assert len(ids) == 5

    def test_client_supplied_id_is_echoed(self, client):
        resp = client.get("/health", headers={"X-Request-ID": "trace-abc.123_x"})
        assert resp.headers["x-request-id"] == "trace-abc.123_x"

    def test_supplied_id_is_truncated_to_64_chars(self, client):
        resp = client.get("/health", headers={"X-Request-ID": "a" * 200})
        assert resp.headers["x-request-id"] == "a" * 64

    def test_unsafe_characters_are_stripped(self, client):
        resp = client.get("/health", headers={"X-Request-ID": "ab c/d<e>;f,g\"h'"})
        assert resp.headers["x-request-id"] == "abcdefgh"

    @pytest.mark.parametrize("value", ["!!!", "   ", "<>"])
    def test_ids_with_no_safe_characters_are_replaced(self, client, value):
        rid = client.get("/health", headers={"X-Request-ID": value}).headers["x-request-id"]
        assert re.fullmatch(r"[0-9a-f]{16}", rid)

    def test_log_injection_attempt_is_neutralised(self, client, caplog):
        with caplog.at_level(logging.INFO, logger="closetmate"):
            resp = client.get("/", headers={"X-Request-ID": "x%0aINJECTED"})
        assert "\n" not in resp.headers["x-request-id"] and "%" not in resp.headers["x-request-id"]

    @pytest.mark.parametrize(
        "method,path,expected",
        [("GET", "/nope", 404), ("GET", "/auth/profile", 401), ("POST", "/auth/login", 422), ("POST", "/health", 405)],
    )
    def test_present_on_error_responses_too(self, client, method, path, expected):
        resp = client.request(method, path, headers={"X-Request-ID": "err-1"})
        assert resp.status_code == expected
        assert resp.headers["x-request-id"] == "err-1"


# ---------------------------------------------------------------------------
# Unhandled exceptions
# ---------------------------------------------------------------------------

class TestUnhandledExceptions:
    def test_returns_a_json_500_with_the_request_id(self, client_no_raise, boom_route):
        resp = client_no_raise.get(boom_route, headers={"X-Request-ID": "boom-1"})
        assert resp.status_code == 500
        body = resp.json()
        assert body["detail"] == "Internal server error"
        assert body["request_id"] == "boom-1"
        assert resp.headers["x-request-id"] == "boom-1"

    def test_non_production_includes_the_error_summary(self, client_no_raise, boom_route):
        body = client_no_raise.get(boom_route).json()
        assert body["error"].startswith("RuntimeError: kaboom")

    def test_production_response_contains_no_internals(self, client_no_raise, boom_route, as_prod):
        resp = client_no_raise.get(boom_route, headers={"X-Request-ID": "prod-1"})
        assert resp.status_code == 500
        assert resp.json() == {"detail": "Internal server error", "request_id": "prod-1"}
        assert "error" not in resp.json()                      # the dev-only summary key is absent
        blob = resp.text + str(dict(resp.headers))
        for leak in ("kaboom", "hunter2", "Traceback", "RuntimeError", ".py"):
            assert leak not in blob, leak

    def test_generated_request_id_is_returned_when_none_was_supplied(self, client_no_raise, boom_route):
        resp = client_no_raise.get(boom_route)
        assert re.fullmatch(r"[0-9a-f]{16}", resp.json()["request_id"])
        assert resp.headers["x-request-id"] == resp.json()["request_id"]

    def test_the_traceback_is_logged_server_side(self, client_no_raise, boom_route, caplog, as_prod):
        with caplog.at_level(logging.ERROR, logger="closetmate"):
            client_no_raise.get(boom_route)
        records = [r for r in caplog.records if "Unhandled exception" in r.getMessage()]
        assert records and records[0].exc_info and "kaboom" in str(records[0].exc_info[1])

    def test_server_keeps_serving_after_an_unhandled_error(self, client_no_raise, boom_route):
        client_no_raise.get(boom_route)
        assert client_no_raise.get("/health").status_code == 200


class TestValidationErrorShape:
    def test_422_has_no_input_echo(self, client):
        resp = client.post("/auth/login", json={"email": "not-an-email", "password": "hunter2-secret"})
        assert resp.status_code == 422
        assert "hunter2-secret" not in resp.text
        for err in resp.json()["detail"]:
            assert set(err) == {"loc", "msg", "type"}

    def test_malformed_json_is_422_not_500(self, client):
        resp = client.post("/auth/login", content=b"{not json", headers={"Content-Type": "application/json"})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Response headers, CORS, docs
# ---------------------------------------------------------------------------

class TestHeaders:
    def test_nosniff_and_no_store_on_api_responses(self, client):
        resp = client.get("/health")
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert resp.headers["cache-control"] == "no-store"

    def test_per_user_responses_are_not_cacheable(self, client, alice):
        resp = client.get("/auth/profile", headers=alice.headers)
        assert resp.headers["cache-control"] == "no-store"

    def test_static_uploads_are_exempt_from_no_store(self, client):
        resp = client.get("/uploads/definitely-missing.jpg")
        assert resp.status_code == 404
        assert "no-store" not in resp.headers.get("cache-control", "")

    def test_hsts_is_not_sent_outside_production(self, client):
        assert "strict-transport-security" not in client.get("/health").headers

    def test_hsts_is_sent_in_production(self, client, as_prod):
        assert "max-age=31536000" in client.get("/health").headers["strict-transport-security"]


class TestCors:
    def test_dev_preflight_allows_any_origin_without_credentials(self, client):
        resp = client.options("/auth/login", headers={
            "Origin": "https://web.example.test", "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        })
        assert resp.status_code == 200
        assert resp.headers["access-control-allow-origin"] == "*"
        assert "access-control-allow-credentials" not in resp.headers


class TestDocs:
    def test_swagger_ui_is_served_outside_production(self, client):
        resp = client.get("/docs")
        assert resp.status_code == 200 and "swagger" in resp.text.lower()

    def test_openapi_schema_lists_the_public_surface(self, client):
        paths = client.get("/openapi.json").json()["paths"]
        for expected in ("/auth/login", "/auth/register", "/wardrobe/add-item", "/chat/message", "/health"):
            assert expected in paths

    def test_redoc_is_disabled(self, client):
        assert client.get("/redoc").status_code == 404


# ---------------------------------------------------------------------------
# Production boot (separate interpreter: module-level configuration cannot be re-imported safely)
# ---------------------------------------------------------------------------

def run_python(code: str, **env: str) -> subprocess.CompletedProcess:
    base = {k: v for k, v in os.environ.items()
            if k in ("PATH", "SYSTEMROOT", "TEMP", "TMP", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "HOME")}
    base.update({"PYTHONIOENCODING": "utf-8", **env})
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        cwd=PROJECT_ROOT, env=base, capture_output=True, text=True, timeout=120,
    )


@pytest.mark.slow
class TestProductionBoot:
    PROD_ENV = {
        "ENV": "prod",
        "JWT_SECRET": "p" * 48,
        "DATABASE_URL": "postgresql://user:pw@127.0.0.1:1/db",      # never connected to: init_db is stubbed
        "OPENAI_API_KEY": "", "GEMINI_API_KEY": "", "GCS_BUCKET": "test-bucket",   # prod refuses to boot without one
    }

    def test_refuses_to_boot_without_a_real_jwt_secret(self):
        proc = run_python("import main", ENV="prod", DATABASE_URL="postgresql://u:p@127.0.0.1:1/db",
                          OPENAI_API_KEY="", GEMINI_API_KEY="")
        assert proc.returncode != 0
        assert "RuntimeError" in proc.stderr and "JWT_SECRET" in proc.stderr

    def test_production_app_hides_docs_cors_and_adds_hsts(self):
        script = """
            import json
            import database
            database.init_db = lambda: None          # no PostgreSQL in the test environment
            import main
            from fastapi.testclient import TestClient
            from fastapi.middleware.cors import CORSMiddleware

            c = TestClient(main.app, raise_server_exceptions=False)
            health = c.get("/health")
            print(json.dumps({
                "docs": c.get("/docs").status_code,
                "openapi": c.get("/openapi.json").status_code,
                "health": health.status_code,
                "hsts": health.headers.get("strict-transport-security"),
                "cors": any(m.cls is CORSMiddleware for m in main.app.user_middleware),
                "protected": c.get("/wardrobe/items/x").status_code,
            }))
        """
        proc = run_python(script, **self.PROD_ENV)
        assert proc.returncode == 0, proc.stderr[-2000:]
        result = json.loads(proc.stdout.strip().splitlines()[-1])
        assert result["docs"] == 404 and result["openapi"] == 404
        assert result["health"] == 200 and "max-age" in result["hsts"]
        assert result["cors"] is False
        assert result["protected"] == 401

    def test_sqlite_is_refused_in_production(self):
        proc = run_python("import database", ENV="prod", DATABASE_URL="sqlite:///C:/should/not/matter.db")
        assert proc.returncode != 0 and "PostgreSQL" in proc.stderr
