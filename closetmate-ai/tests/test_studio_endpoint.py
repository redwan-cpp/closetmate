"""POST /images/studio-shot and POST /studio-shot — auth, bgremove metering, upload guards, error mapping."""
from __future__ import annotations

import base64
import io

import numpy as np
import pytest
from PIL import Image

from conftest import bearer, make_photo

PATHS = ["/images/studio-shot", "/studio-shot"]
RESPONSE_KEYS = {"image", "thumb", "mime", "width", "height", "cutout_ok"}
BOX = (100, 100, 300, 400)
PHOTO = make_photo(size=(400, 500), subjects=[(BOX, (200, 30, 30))])
GENERIC_500 = "Image processing failed. Please try again."


def post_photo(client, path, account, data=PHOTO, content_type="image/png", filename="photo.png"):
    return client.post(path, headers=account.headers, files={"file": (filename, data, content_type)})


def decode_b64(value: str) -> Image.Image:
    raw = base64.b64decode(value, validate=True)             # strict: standard alphabet, correct padding
    img = Image.open(io.BytesIO(raw))
    img.load()
    return img


@pytest.fixture
def model(fake_cutout):
    """The stubbed rembg cutout: keeps the photo's central subject box by default."""
    fake_cutout.boxes = [BOX]
    return fake_cutout


@pytest.fixture
def fake_remove_bg(monkeypatch):
    import routers.images as images

    calls = []
    monkeypatch.setattr(images, "process_image_bytes", lambda body: calls.append(body) or b"FAKE-JPEG")
    return calls


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", PATHS)
class TestSuccess:
    def test_response_shape(self, client, alice, model, path):
        resp = post_photo(client, path, alice)
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"].startswith("application/json")
        body = resp.json()
        assert set(body) == RESPONSE_KEYS
        assert body["mime"] == "image/webp"
        assert body["width"] == 640 and body["height"] == 800
        assert body["cutout_ok"] is True

    def test_image_and_thumb_decode_as_webp_of_the_right_sizes(self, client, alice, model, path):
        body = post_photo(client, path, alice).json()
        full, thumb = decode_b64(body["image"]), decode_b64(body["thumb"])
        assert (full.format, full.mode, full.size) == ("WEBP", "RGBA", (640, 800))
        assert (thumb.format, thumb.mode, thumb.size) == ("WEBP", "RGBA", (320, 400))

    def test_the_cutout_is_transparent_around_a_centred_item(self, client, alice, model, path):
        full = decode_b64(post_photo(client, path, alice).json()["image"])
        alpha = np.array(full)[:, :, 3]
        assert int(alpha[0, 0]) == int(alpha[-1, -1]) == int(alpha[0, -1]) == int(alpha[-1, 0]) == 0
        ys, xs = np.where(alpha > 24)
        assert abs((xs.min() + xs.max() + 1) / 2 - 320) <= 3
        assert int(alpha[(ys.min() + ys.max()) // 2, (xs.min() + xs.max()) // 2]) == 255

    def test_the_real_pipeline_runs_on_the_uploaded_bytes(self, client, alice, model, path):
        post_photo(client, path, alice)
        assert len(model.calls) == 1 and model.calls[0].size == (400, 500)

    def test_consumes_exactly_one_bgremove_unit(self, client, alice, model, path, usage_count):
        post_photo(client, path, alice)
        assert usage_count(alice.user_id, "bgremove") == 1
        assert usage_count(alice.user_id, "vision") == usage_count(alice.user_id, "chat") == 0

    def test_a_failed_cutout_is_reported_as_cutout_ok_false(self, client, alice, model, path):
        model.opaque = True
        resp = post_photo(client, path, alice)
        assert resp.status_code == 200 and resp.json()["cutout_ok"] is False
        assert decode_b64(resp.json()["image"]).size == (640, 800)

    def test_jpeg_uploads_work(self, client, alice, model, path):
        jpeg = make_photo(size=(400, 500), subjects=[(BOX, (30, 90, 200))], fmt="JPEG")
        assert post_photo(client, path, alice, jpeg, "image/jpeg", "photo.jpg").status_code == 200

    def test_the_declared_content_type_only_has_to_be_an_image_type(self, client, alice, model, path):
        assert post_photo(client, path, alice, content_type="image/heic", filename="x.heic").status_code == 200

    def test_unicode_filenames_are_harmless(self, client, alice, model, path):
        assert post_photo(client, path, alice, filename="フォト 📸 ../../etc/passwd.png").status_code == 200

    def test_the_original_photo_is_not_echoed_back(self, client, alice, model, path):
        body = post_photo(client, path, alice).json()
        assert base64.b64decode(body["image"]) != PHOTO and base64.b64decode(body["thumb"]) != PHOTO


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", PATHS)
class TestAuth:
    def test_no_token_is_401(self, client, model, path):
        resp = client.post(path, files={"file": ("p.png", PHOTO, "image/png")})
        assert resp.status_code == 401 and resp.headers["www-authenticate"] == "Bearer"
        assert model.calls == []

    @pytest.mark.parametrize("token", ["not.a.jwt", "dev-1234-legacy", ""])
    def test_bad_tokens_are_401(self, client, model, path, token):
        resp = client.post(path, headers=bearer(token), files={"file": ("p.png", PHOTO, "image/png")})
        assert resp.status_code == 401
        assert model.calls == []

    def test_a_refresh_token_is_not_an_access_token(self, client, alice, model, path):
        resp = client.post(path, headers=bearer(alice.refresh_token), files={"file": ("p.png", PHOTO, "image/png")})
        assert resp.status_code == 401

    def test_an_unauthenticated_call_costs_nothing(self, client, alice, model, path, sql):
        client.post(path, files={"file": ("p.png", PHOTO, "image/png")})
        assert sql("SELECT 1 FROM usage_counters") == []


# ---------------------------------------------------------------------------
# Upload guards (identical to the other image endpoints, and free)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", PATHS)
class TestUploadGuards:
    def test_non_image_content_type_is_400(self, client, alice, model, path):
        resp = post_photo(client, path, alice, b"hello", "text/plain", "a.txt")
        assert resp.status_code == 400 and resp.json()["detail"] == "File must be an image"

    def test_pdf_posing_as_png_by_name_only_is_400(self, client, alice, model, path):
        assert post_photo(client, path, alice, b"%PDF-1.4", "application/pdf", "a.png").status_code == 400

    def test_empty_file_is_400(self, client, alice, model, path):
        resp = post_photo(client, path, alice, b"")
        assert resp.status_code == 400 and resp.json()["detail"] == "Empty file"

    def test_undecodable_bytes_are_422(self, client, alice, model, path):
        resp = post_photo(client, path, alice, b"<html>definitely not a picture</html>")
        assert resp.status_code == 422 and resp.json()["detail"] == "Cannot decode image"

    def test_missing_file_field_is_422(self, client, alice, model, path):
        assert client.post(path, headers=alice.headers).status_code == 422

    def test_oversize_upload_is_413(self, client, alice, model, path, set_env):
        set_env(MAX_UPLOAD_BYTES=len(PHOTO) - 1)
        resp = post_photo(client, path, alice)
        assert resp.status_code == 413 and "too large" in resp.json()["detail"].lower()

    def test_an_upload_exactly_at_the_limit_is_accepted(self, client, alice, model, path, set_env):
        set_env(MAX_UPLOAD_BYTES=len(PHOTO))
        assert post_photo(client, path, alice).status_code == 200

    def test_too_many_pixels_is_413(self, client, alice, model, path, set_env):
        set_env(MAX_IMAGE_PIXELS=100)
        resp = post_photo(client, path, alice, make_photo(size=(20, 20)))
        assert resp.status_code == 413 and "resolution" in resp.json()["detail"].lower()

    def test_rejected_uploads_never_reach_the_model_or_the_quota(self, client, alice, model, path, set_env, sql):
        post_photo(client, path, alice, b"x", "text/plain", "a.txt")
        post_photo(client, path, alice, b"")
        post_photo(client, path, alice, b"garbage")
        set_env(MAX_UPLOAD_BYTES=10)
        post_photo(client, path, alice)
        assert model.calls == []
        assert sql("SELECT 1 FROM usage_counters") == []


# ---------------------------------------------------------------------------
# Photos the pipeline refuses
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", PATHS)
class TestStudioShotErrors:
    def test_nothing_found_is_422_with_the_human_message(self, client, alice, model, path):
        model.boxes = []
        resp = post_photo(client, path, alice)
        assert resp.status_code == 422
        assert resp.json() == {"detail": "We couldn't find the item in this photo. Try a plainer background."}

    def test_item_too_small_is_422_with_the_human_message(self, client, alice, model, path):
        model.boxes = [(10, 10, 30, 30)]                           # 0.2% of the 400x500 photo
        resp = post_photo(client, path, alice)
        assert resp.status_code == 422
        assert resp.json() == {"detail": "The item is too small in this photo. Move closer and try again."}

    def test_a_refused_photo_returns_no_image_data(self, client, alice, model, path):
        model.boxes = []
        assert set(post_photo(client, path, alice).json()) == {"detail"}

    def test_a_refused_photo_gives_the_unit_back(self, client, alice, model, path, usage_count):
        # Segmentation is local CPU work (no provider was billed) and "no garment found" is an
        # ordinary thing to try, so the user isn't charged. Abuse is bounded by the rate limit.
        model.boxes = []
        assert post_photo(client, path, alice).status_code == 422
        assert usage_count(alice.user_id, "bgremove") == 0

    def test_a_too_small_item_also_gives_the_unit_back(self, client, alice, model, path, usage_count):
        model.boxes = [(10, 10, 30, 30)]
        assert post_photo(client, path, alice).status_code == 422
        assert usage_count(alice.user_id, "bgremove") == 0

    def test_a_refused_photo_does_not_refund_a_unit_spent_on_a_good_one(self, client, alice, model, path, usage_count):
        assert post_photo(client, path, alice).status_code == 200
        model.boxes = []
        assert post_photo(client, path, alice).status_code == 422
        assert usage_count(alice.user_id, "bgremove") == 1

    def test_the_refund_never_goes_below_zero_after_repeated_refusals(self, client, alice, model, path, usage_count):
        model.boxes = []
        for _ in range(3):
            assert post_photo(client, path, alice).status_code == 422
        assert usage_count(alice.user_id, "bgremove") == 0

    @pytest.mark.parametrize("error", [
        RuntimeError("onnx runtime: /srv/models/u2net.onnx not found"),
        ValueError("rembg is not available (ModuleNotFoundError)."),     # a ValueError that is NOT a StudioShotError
        MemoryError("out of memory"),
    ])
    def test_a_model_failure_is_a_generic_500_and_the_unit_is_refunded(self, client, alice, model, path, usage_count, error):
        model.error = error
        resp = post_photo(client, path, alice)
        assert resp.status_code in (500, 503)
        if resp.status_code == 500:
            assert resp.json()["detail"] == GENERIC_500
        assert "onnx" not in resp.text and "/srv" not in resp.text and "rembg" not in resp.text
        assert usage_count(alice.user_id, "bgremove") == 0

    def test_the_model_error_does_not_poison_the_next_request(self, client, alice, model, path):
        model.error = RuntimeError("boom")
        assert post_photo(client, path, alice).status_code == 500
        model.error = None
        assert post_photo(client, path, alice).status_code == 200


# ---------------------------------------------------------------------------
# Quota: the bgremove budget
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", PATHS)
class TestQuota:
    def test_the_fourth_request_this_month_is_429_with_a_structured_detail(self, client, alice, model, path):
        for _ in range(3):
            assert post_photo(client, path, alice).status_code == 200
        resp = post_photo(client, path, alice)
        assert resp.status_code == 429
        detail = resp.json()["detail"]
        assert detail["code"] == "quota_exceeded" and detail["feature"] == "bgremove" and detail["limit"] == 3
        assert "3" in detail["message"]
        assert int(resp.headers["retry-after"]) >= 1
        assert len(model.calls) == 3                                    # the model never ran for the refused one

    def test_the_limit_comes_from_the_environment(self, client, alice, model, path, set_env, usage_count):
        set_env(QUOTA_FREE_BGREMOVE_MONTHLY=1)
        assert post_photo(client, path, alice).status_code == 200
        resp = post_photo(client, path, alice)
        assert resp.status_code == 429 and resp.json()["detail"]["limit"] == 1
        assert usage_count(alice.user_id, "bgremove") == 1

    def test_a_limit_of_zero_disables_the_feature(self, client, alice, model, path, set_env):
        set_env(QUOTA_FREE_BGREMOVE_MONTHLY=0)
        resp = post_photo(client, path, alice)
        assert resp.status_code == 429 and resp.json()["detail"]["limit"] == 0
        assert model.calls == []

    def test_raising_the_limit_takes_effect_immediately(self, client, alice, model, path, set_env):
        set_env(QUOTA_FREE_BGREMOVE_MONTHLY=1)
        post_photo(client, path, alice)
        assert post_photo(client, path, alice).status_code == 429
        set_env(QUOTA_FREE_BGREMOVE_MONTHLY=2)
        assert post_photo(client, path, alice).status_code == 200

    def test_each_user_has_their_own_budget(self, client, two_users, model, path):
        alice, bob = two_users
        for _ in range(3):
            post_photo(client, path, alice)
        assert post_photo(client, path, alice).status_code == 429
        assert post_photo(client, path, bob).status_code == 200

    def test_it_shares_one_budget_with_remove_bg(self, client, alice, model, fake_remove_bg, path, set_env, usage_count):
        set_env(QUOTA_FREE_BGREMOVE_MONTHLY=2)
        assert post_photo(client, "/images/remove-bg", alice).status_code == 200
        assert post_photo(client, path, alice).status_code == 200
        assert usage_count(alice.user_id, "bgremove") == 2
        assert post_photo(client, path, alice).status_code == 429
        assert post_photo(client, "/remove-bg", alice).status_code == 429

    def test_studio_shots_use_up_the_budget_remove_bg_would_have_used(self, client, alice, model, fake_remove_bg, path, set_env):
        set_env(QUOTA_FREE_BGREMOVE_MONTHLY=2)
        post_photo(client, path, alice)
        post_photo(client, path, alice)
        resp = post_photo(client, "/images/remove-bg", alice)
        assert resp.status_code == 429 and fake_remove_bg == []

    def test_both_routes_count_against_the_same_budget(self, client, alice, model, path, usage_count):
        other = "/studio-shot" if path == "/images/studio-shot" else "/images/studio-shot"
        post_photo(client, path, alice)
        post_photo(client, other, alice)
        assert usage_count(alice.user_id, "bgremove") == 2

    def test_other_features_are_not_charged(self, client, alice, model, path, sql):
        post_photo(client, path, alice)
        assert {r["feature"] for r in sql("SELECT feature FROM usage_counters")} == {"bgremove"}

    def test_a_refused_request_does_not_burn_extra_units(self, client, alice, model, path, usage_count, set_env):
        set_env(QUOTA_FREE_BGREMOVE_MONTHLY=1)
        post_photo(client, path, alice)
        for _ in range(3):
            assert post_photo(client, path, alice).status_code == 429
        assert usage_count(alice.user_id, "bgremove") == 1

    def test_the_usage_endpoint_reflects_the_consumption(self, client, alice, model, path):
        post_photo(client, path, alice)
        assert client.get("/auth/usage", headers=alice.headers).json()["bgremove"] == {"used": 1, "limit": 3}


class TestRateLimit:
    def test_twenty_a_minute_per_user_then_429_rate_limited(self, client, two_users, model, set_env):
        alice, bob = two_users
        set_env(QUOTA_FREE_BGREMOVE_MONTHLY=100)
        for _ in range(20):
            assert post_photo(client, "/images/studio-shot", alice).status_code == 200
        resp = post_photo(client, "/studio-shot", alice)               # the alias shares the bucket
        assert resp.status_code == 429
        assert resp.json()["detail"]["code"] == "rate_limited" and int(resp.headers["retry-after"]) >= 1
        assert post_photo(client, "/images/studio-shot", bob).status_code == 200


class TestOpenApi:
    def test_both_routes_are_documented_as_post_only(self, client):
        paths = client.get("/openapi.json").json()["paths"]
        for path in PATHS:
            assert set(paths[path]) == {"post"}

    @pytest.mark.parametrize("path", PATHS)
    def test_get_is_405(self, client, alice, path):
        assert client.get(path, headers=alice.headers).status_code == 405
