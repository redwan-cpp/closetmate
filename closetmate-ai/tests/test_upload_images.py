"""routers/upload.py and routers/images.py — upload guards, vision caching, bgremove metering and refunds."""
from __future__ import annotations

import base64
import hashlib
import io
import random

import pytest
from PIL import Image

import quota
from conftest import make_image_bytes

UPLOAD_ENDPOINTS = [
    "/upload/analyze-clothing",
    "/upload/upload-clothing",
    "/images/remove-bg",
    "/images/remove-background",
    "/images/style",
    "/images/analyze-lighting",
    "/remove-bg",
]

META = {
    "category": "top", "subcategory": "shirt", "primary_color": "blue", "material": "cotton",
    "pattern": "striped", "formality": "smart casual", "culture": "western",
}


def noisy_png(size=(64, 64), seed=1) -> bytes:
    """Incompressible image (bigger than a few KB) whose bytes differ per seed."""
    rng = random.Random(seed)
    img = Image.frombytes("RGB", size, rng.randbytes(size[0] * size[1] * 3))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def post_file(client, path, account, data, content_type="image/png", filename="photo.png"):
    return client.post(path, headers=account.headers, files={"file": (filename, data, content_type)})


class FakeVision:
    """Stands in for routers.upload.extract_clothing_metadata."""

    def __init__(self):
        self.calls = []
        self.result = dict(META)
        self.error = None
        self.billed = False

    async def __call__(self, image_bytes, user_id=None):
        self.calls.append({"bytes": image_bytes, "user_id": user_id})
        if self.billed:
            quota.mark_billed()
        if self.error is not None:
            raise self.error
        return self.result


@pytest.fixture
def fake_vision(monkeypatch) -> FakeVision:
    import routers.upload as upload

    fake = FakeVision()
    monkeypatch.setattr(upload, "extract_clothing_metadata", fake)
    return fake


# ---------------------------------------------------------------------------
# Shared upload guards
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", UPLOAD_ENDPOINTS)
class TestUploadGuards:
    def test_non_image_content_type_is_400(self, client, alice, path, usage_count):
        resp = post_file(client, path, alice, b"hello", content_type="text/plain", filename="a.txt")
        assert resp.status_code == 400
        assert resp.json()["detail"] == "File must be an image"

    def test_pdf_with_an_image_extension_is_400(self, client, alice, path):
        resp = post_file(client, path, alice, b"%PDF-1.4", content_type="application/pdf", filename="a.png")
        assert resp.status_code == 400

    def test_empty_body_is_400(self, client, alice, path):
        resp = post_file(client, path, alice, b"")
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Empty file"

    def test_bytes_that_are_not_an_image_are_422(self, client, alice, path):
        resp = post_file(client, path, alice, b"<html><script>alert(1)</script></html>")
        assert resp.status_code == 422
        assert resp.json()["detail"] == "Cannot decode image"

    def test_missing_file_field_is_422(self, client, alice, path):
        assert client.post(path, headers=alice.headers).status_code == 422

    def test_body_larger_than_the_limit_is_413(self, client, alice, path, set_env):
        data = noisy_png()
        set_env(MAX_UPLOAD_BYTES=len(data) - 1)
        resp = post_file(client, path, alice, data)
        assert resp.status_code == 413
        assert "too large" in resp.json()["detail"].lower()

    def test_image_with_too_many_pixels_is_413(self, client, alice, path, set_env):
        set_env(MAX_IMAGE_PIXELS=100)
        resp = post_file(client, path, alice, make_image_bytes(size=(20, 20)))        # 400 px
        assert resp.status_code == 413
        assert "resolution" in resp.json()["detail"].lower()

    def test_rejected_uploads_never_consume_quota(self, client, alice, path, set_env, sql):
        set_env(MAX_UPLOAD_BYTES=10)
        post_file(client, path, alice, noisy_png())
        post_file(client, path, alice, b"", content_type="image/png")
        post_file(client, path, alice, b"x", content_type="text/plain")
        assert sql("SELECT 1 FROM usage_counters") == []


class TestSizeBoundaries:
    def test_file_exactly_at_the_limit_is_accepted(self, client, alice, set_env):
        data = noisy_png()
        set_env(MAX_UPLOAD_BYTES=len(data))
        assert post_file(client, "/images/analyze-lighting", alice, data).status_code == 200

    def test_declared_content_length_over_the_cap_is_refused_before_the_body_is_read(self, client, app_module):
        declared = app_module._MAX_BODY_BYTES + 1
        resp = client.post("/auth/login", content=b"{}", headers={
            "Content-Length": str(declared), "Content-Type": "application/json", "X-Request-ID": "big-body-1",
        })
        assert resp.status_code == 413
        assert resp.json() == {"detail": "Request body too large"}
        assert resp.headers["x-request-id"] == "big-body-1"

    def test_the_content_length_guard_applies_to_authenticated_uploads_too(self, client, alice, app_module):
        resp = client.post("/upload/analyze-clothing", content=b"x", headers={
            **alice.headers, "Content-Length": str(app_module._MAX_BODY_BYTES + 1),
            "Content-Type": "multipart/form-data; boundary=x",
        })
        assert resp.status_code == 413

    def test_normal_sized_requests_are_unaffected(self, client, alice):
        assert client.get("/auth/usage", headers=alice.headers).status_code == 200


# ---------------------------------------------------------------------------
# /upload/analyze-clothing
# ---------------------------------------------------------------------------

class TestAnalyzeClothing:
    def test_first_call_consumes_a_vision_unit_and_is_not_cached(self, client, alice, fake_vision, png_bytes, usage_count):
        resp = post_file(client, "/upload/analyze-clothing", alice, png_bytes)
        assert resp.status_code == 200
        body = resp.json()
        assert body["cached"] is False
        assert body["suggested"] == {**META}
        assert body["image_path"] == f"uploads/analyzed/{hashlib.md5(png_bytes).hexdigest()}.jpg"
        assert usage_count(alice.user_id, "vision") == 1
        assert len(fake_vision.calls) == 1
        assert fake_vision.calls[0]["user_id"] == alice.user_id and fake_vision.calls[0]["bytes"] == png_bytes

    def test_result_is_written_to_the_db_cache(self, client, alice, fake_vision, png_bytes, sql):
        post_file(client, "/upload/analyze-clothing", alice, png_bytes)
        row = sql("SELECT * FROM clothing_metadata_cache")[0]
        assert row["image_hash"] == hashlib.md5(png_bytes).hexdigest()
        assert (row["category"], row["subcategory"], row["primary_color"]) == ("top", "shirt", "blue")

    def test_second_identical_upload_is_a_cache_hit_and_free(self, client, alice, fake_vision, png_bytes, usage_count):
        first = post_file(client, "/upload/analyze-clothing", alice, png_bytes).json()
        second = post_file(client, "/upload/analyze-clothing", alice, png_bytes)
        assert second.status_code == 200
        assert second.json()["cached"] is True
        assert second.json()["suggested"] == first["suggested"]
        assert len(fake_vision.calls) == 1
        assert usage_count(alice.user_id, "vision") == 1

    def test_cache_is_shared_between_users(self, client, two_users, fake_vision, png_bytes, usage_count):
        alice, bob = two_users
        post_file(client, "/upload/analyze-clothing", alice, png_bytes)
        resp = post_file(client, "/upload/analyze-clothing", bob, png_bytes)
        assert resp.json()["cached"] is True
        assert usage_count(bob.user_id, "vision") == 0

    def test_different_images_each_cost_a_unit(self, client, alice, fake_vision, usage_count):
        for seed in range(3):
            assert post_file(client, "/upload/analyze-clothing", alice, noisy_png(seed=seed)).status_code == 200
        assert usage_count(alice.user_id, "vision") == 3 and len(fake_vision.calls) == 3

    def test_over_the_monthly_cap_is_429_and_the_provider_is_not_called(self, client, alice, fake_vision):
        for seed in range(3):
            post_file(client, "/upload/analyze-clothing", alice, noisy_png(seed=seed))
        resp = post_file(client, "/upload/analyze-clothing", alice, noisy_png(seed=99))
        assert resp.status_code == 429
        assert resp.json()["detail"]["feature"] == "vision" and resp.json()["detail"]["limit"] == 3
        assert "retry-after" in resp.headers
        assert len(fake_vision.calls) == 3

    def test_cache_hits_still_work_after_the_cap_is_reached(self, client, alice, fake_vision):
        for seed in range(3):
            post_file(client, "/upload/analyze-clothing", alice, noisy_png(seed=seed))
        resp = post_file(client, "/upload/analyze-clothing", alice, noisy_png(seed=0))
        assert resp.status_code == 200 and resp.json()["cached"] is True

    def test_extraction_failure_is_a_generic_500_and_the_unit_is_refunded(
        self, client, alice, fake_vision, png_bytes, usage_count, sql
    ):
        fake_vision.error = RuntimeError("openai key sk-secret rejected for user 42")
        resp = post_file(client, "/upload/analyze-clothing", alice, png_bytes)
        assert resp.status_code == 500
        assert resp.json() == {"detail": "Could not analyze this image. Please try again."}
        assert "sk-secret" not in resp.text
        assert usage_count(alice.user_id, "vision") == 0
        assert sql("SELECT 1 FROM clothing_metadata_cache") == []

    def test_failure_after_a_paid_provider_call_is_not_refunded(self, client, alice, fake_vision, png_bytes, usage_count):
        fake_vision.billed = True
        fake_vision.error = ValueError("provider answered, but the JSON was unusable")
        assert post_file(client, "/upload/analyze-clothing", alice, png_bytes).status_code == 500
        assert usage_count(alice.user_id, "vision") == 1

    def test_repeated_failures_do_not_exhaust_the_cap(self, client, alice, fake_vision, usage_count):
        fake_vision.error = RuntimeError("down")
        for seed in range(6):
            assert post_file(client, "/upload/analyze-clothing", alice, noisy_png(seed=seed)).status_code == 500
        assert usage_count(alice.user_id, "vision") == 0

    def test_missing_fields_get_defaults(self, client, alice, fake_vision, png_bytes):
        fake_vision.result = {"category": "top"}
        suggested = post_file(client, "/upload/analyze-clothing", alice, png_bytes).json()["suggested"]
        assert suggested == {
            "category": "top", "subcategory": "unknown", "primary_color": "unknown", "material": "unknown",
            "pattern": "solid", "formality": "casual", "culture": "global",
        }

    def test_formality_level_alias_is_understood(self, client, alice, fake_vision, png_bytes):
        fake_vision.result = {**META, "formality": None, "formality_level": "festive"}
        assert post_file(client, "/upload/analyze-clothing", alice, png_bytes).json()["suggested"]["formality"] == "festive"

    def test_a_failing_cache_write_does_not_fail_the_request(self, client, alice, fake_vision, png_bytes, monkeypatch):
        import routers.upload as upload

        def boom(*_a):
            raise RuntimeError("disk full")

        monkeypatch.setattr(upload, "save_metadata_cache", boom)
        resp = post_file(client, "/upload/analyze-clothing", alice, png_bytes)
        assert resp.status_code == 200 and resp.json()["cached"] is False

    def test_is_rate_limited_per_user(self, client, alice, fake_vision, png_bytes):
        codes = [post_file(client, "/upload/analyze-clothing", alice, png_bytes).status_code for _ in range(21)]
        assert codes[:20] == [200] * 20          # 1 extraction + 19 free cache hits
        assert codes[20] == 429


# ---------------------------------------------------------------------------
# /upload/upload-clothing
# ---------------------------------------------------------------------------

class TestUploadClothing:
    def test_background_removed_copy_is_stored(self, client, alice, png_bytes, monkeypatch):
        import routers.upload as upload

        seen = []
        monkeypatch.setattr(upload, "remove_background_and_save", lambda body: seen.append(body) or "uploads/processed/ok.jpg")
        resp = post_file(client, "/upload/upload-clothing", alice, png_bytes)
        assert resp.status_code == 200
        assert resp.json() == {"image_path": "uploads/processed/ok.jpg", "status": "background_removed"}
        assert seen == [png_bytes]

    def test_falls_back_to_a_clean_copy_when_background_removal_fails(self, client, alice, png_bytes, monkeypatch):
        import routers.upload as upload

        def fail(_body):
            raise ValueError("rembg is not available")

        saved = []
        monkeypatch.setattr(upload, "remove_background_and_save", fail)
        monkeypatch.setattr(upload, "_save_original", lambda body: saved.append(body) or "uploads/processed/copy.jpg")
        resp = post_file(client, "/upload/upload-clothing", alice, png_bytes)
        assert resp.status_code == 200
        assert resp.json() == {"image_path": "uploads/processed/copy.jpg", "status": "original_saved"}
        assert saved == [png_bytes]

    def test_undecodable_fallback_is_422(self, client, alice, png_bytes, monkeypatch):
        import routers.upload as upload

        def fail(*_a):
            raise ValueError("bad image")

        monkeypatch.setattr(upload, "remove_background_and_save", fail)
        monkeypatch.setattr(upload, "_save_original", fail)
        resp = post_file(client, "/upload/upload-clothing", alice, png_bytes)
        assert resp.status_code == 422 and resp.json()["detail"] == "Cannot decode image"

    def test_client_filename_and_content_type_never_reach_storage(self, client, alice, png_bytes, monkeypatch):
        import routers.upload as upload
        import services.gcs_storage as gcs

        stored = {}

        def fake_upload(data, filename, content_type="image/jpeg"):
            stored.update(data=data, filename=filename, content_type=content_type)
            return "https://storage.googleapis.com/b/" + filename

        monkeypatch.setattr(upload, "remove_background_and_save", lambda _b: (_ for _ in ()).throw(ValueError("x")))
        monkeypatch.setattr(gcs, "upload_bytes", fake_upload)
        resp = post_file(client, "/upload/upload-clothing", alice, png_bytes,
                         content_type="image/svg+xml", filename="../../evil.php")
        assert resp.status_code == 200
        assert stored["content_type"] == "image/jpeg"
        assert stored["filename"].endswith(".jpg") and "evil" not in stored["filename"] and ".." not in stored["filename"]
        assert stored["data"][:3] == b"\xff\xd8\xff"                      # re-encoded JPEG, not the client's bytes
        assert stored["data"] != png_bytes


# ---------------------------------------------------------------------------
# Background removal endpoints
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_bg(monkeypatch):
    """Replace the CPU-heavy / model-backed pieces of services.image_processing as seen by the router."""
    import routers.images as images

    state = {"calls": 0, "error": None}

    def fake_process(body: bytes) -> bytes:
        state["calls"] += 1
        if state["error"]:
            raise state["error"]
        return b"FAKE-JPEG-BYTES"

    def fake_remove(image: Image.Image) -> Image.Image:
        state["calls"] += 1
        if state["error"]:
            raise state["error"]
        return image.convert("RGBA")

    monkeypatch.setattr(images, "process_image_bytes", fake_process)
    monkeypatch.setattr(images, "remove_background_image", fake_remove)
    return state


@pytest.mark.parametrize("path", ["/images/remove-bg", "/remove-bg"])
class TestRemoveBg:
    def test_returns_base64_and_consumes_a_bgremove_unit(self, client, alice, png_bytes, fake_bg, path, usage_count):
        resp = post_file(client, path, alice, png_bytes)
        assert resp.status_code == 200
        assert base64.b64decode(resp.json()["image"]) == b"FAKE-JPEG-BYTES"
        assert usage_count(alice.user_id, "bgremove") == 1

    def test_processing_failure_is_a_generic_500_and_refunded(self, client, alice, png_bytes, fake_bg, path, usage_count):
        fake_bg["error"] = ValueError("Background removal failed: onnx model /srv/secret/u2net.onnx missing")
        resp = post_file(client, path, alice, png_bytes)
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Image processing failed. Please try again."
        assert "onnx" not in resp.text and "/srv" not in resp.text
        assert usage_count(alice.user_id, "bgremove") == 0

    def test_fourth_request_hits_the_cap(self, client, alice, png_bytes, fake_bg, path):
        for _ in range(3):
            assert post_file(client, path, alice, png_bytes).status_code == 200
        resp = post_file(client, path, alice, png_bytes)
        assert resp.status_code == 429 and resp.json()["detail"]["feature"] == "bgremove"
        assert fake_bg["calls"] == 3

    def test_aliases_share_one_budget(self, client, alice, png_bytes, fake_bg, path, usage_count):
        other = "/remove-bg" if path == "/images/remove-bg" else "/images/remove-bg"
        post_file(client, path, alice, png_bytes)
        post_file(client, other, alice, png_bytes)
        assert usage_count(alice.user_id, "bgremove") == 2


class TestOtherImageEndpoints:
    def test_remove_background_returns_a_png(self, client, alice, png_bytes, fake_bg, usage_count):
        resp = post_file(client, "/images/remove-background", alice, png_bytes)
        assert resp.status_code == 200 and resp.headers["content-type"] == "image/png"
        assert Image.open(io.BytesIO(resp.content)).format == "PNG"
        assert usage_count(alice.user_id, "bgremove") == 1

    def test_style_returns_a_768_square_jpeg(self, client, alice, png_bytes, fake_bg):
        resp = post_file(client, "/images/style", alice, png_bytes)
        assert resp.status_code == 200 and resp.headers["content-type"] == "image/jpeg"
        img = Image.open(io.BytesIO(resp.content))
        assert img.format == "JPEG" and img.size == (768, 768)

    @pytest.mark.parametrize("path", ["/images/remove-background", "/images/style"])
    def test_truncated_image_is_a_500_and_refunded(self, client, alice, fake_bg, path, usage_count):
        truncated = make_image_bytes(size=(64, 64))[:60]            # valid header, missing pixel data
        resp = post_file(client, path, alice, truncated)
        assert resp.status_code == 500
        assert usage_count(alice.user_id, "bgremove") == 0

    def test_unexpected_exception_type_from_the_model_is_contained(self, client, alice, png_bytes, fake_bg, usage_count):
        fake_bg["error"] = MemoryError("out of memory")
        resp = post_file(client, "/images/remove-background", alice, png_bytes)
        assert resp.status_code in (500, 503)
        assert usage_count(alice.user_id, "bgremove") == 0


class TestAnalyzeLighting:
    def test_white_image(self, client, alice, usage_count):
        resp = post_file(client, "/images/analyze-lighting", alice, make_image_bytes(color=(255, 255, 255)))
        assert resp.status_code == 200
        assert resp.json() == {"brightness": 1.0, "contrast": 0.0, "warmth": 0.0}
        assert usage_count(alice.user_id, "bgremove") == 0                    # free, not metered

    def test_red_image_is_warm_and_dark(self, client, alice):
        body = post_file(client, "/images/analyze-lighting", alice, make_image_bytes(color=(255, 0, 0))).json()
        assert body["warmth"] == 1.0 and body["brightness"] < 0.5

    def test_blue_image_is_cool(self, client, alice):
        assert post_file(client, "/images/analyze-lighting", alice, make_image_bytes(color=(0, 0, 255))).json()["warmth"] == -1.0

    def test_works_with_jpeg_and_transparent_png(self, client, alice):
        assert post_file(client, "/images/analyze-lighting", alice,
                         make_image_bytes(fmt="JPEG"), content_type="image/jpeg", filename="a.jpg").status_code == 200
        buf = io.BytesIO()
        Image.new("RGBA", (4, 4), (10, 20, 30, 0)).save(buf, format="PNG")
        assert post_file(client, "/images/analyze-lighting", alice, buf.getvalue()).status_code == 200
