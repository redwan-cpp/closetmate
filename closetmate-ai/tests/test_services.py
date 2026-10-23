"""services/ai_usage.py, services/llm_gateway.py, services/uploads.py, services/image_processing.normalize_to_jpeg."""
from __future__ import annotations

import asyncio
import contextlib
import io
import logging
from datetime import datetime
from types import SimpleNamespace

import pytest
import requests
from PIL import Image
from starlette.datastructures import Headers, UploadFile

import quota
import services.ai_usage as ai_usage
import services.llm_gateway as gateway
from conftest import make_image_bytes
from fastapi import HTTPException
from services.image_processing import normalize_to_jpeg
from services.llm_gateway import LLMUnavailable, gemini_generate, openai_chat
from services.uploads import read_upload, require_image_content_type

MESSAGES = [
    {"role": "system", "content": "You are a stylist."},
    {"role": "user", "content": "What goes with navy?"},
]
CALL = dict(feature="chat", user_id="u1", max_tokens=100, temperature=0.2, timeout=5.0)


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# ai_usage
# ---------------------------------------------------------------------------

class TestLogAiUsage:
    def test_inserts_a_complete_row(self, sql):
        ai_usage.log_ai_usage(user_id="u1", feature="chat", provider="openai", model="gpt-x",
                              input_tokens=10, output_tokens=5, latency_ms=123, ok=True)
        row = sql("SELECT * FROM ai_usage")[0]
        assert (row["user_id"], row["feature"], row["provider"], row["model"]) == ("u1", "chat", "openai", "gpt-x")
        assert (row["input_tokens"], row["output_tokens"], row["latency_ms"]) == (10, 5, 123)
        assert row["ok"] == 1 and row["error"] is None
        datetime.fromisoformat(row["created_at"])

    def test_failures_are_recorded_with_ok_zero(self, sql):
        ai_usage.log_ai_usage(user_id=None, feature="vision", provider="gemini", model="m", ok=False, error="HTTP 404")
        row = sql("SELECT * FROM ai_usage")[0]
        assert row["ok"] == 0 and row["error"] == "HTTP 404" and row["user_id"] is None

    def test_error_text_is_truncated_to_120_chars(self, sql):
        ai_usage.log_ai_usage(user_id="u", feature="chat", provider="openai", model="m", ok=False, error="E" * 500)
        assert sql("SELECT error FROM ai_usage")[0]["error"] == "E" * 120

    def test_token_counts_are_optional(self, sql):
        ai_usage.log_ai_usage(user_id="u", feature="chat", provider="openai", model="m")
        row = sql("SELECT input_tokens, output_tokens, latency_ms FROM ai_usage")[0]
        assert row == {"input_tokens": None, "output_tokens": None, "latency_ms": None}

    def test_every_call_adds_a_row(self, sql):
        for _ in range(3):
            ai_usage.log_ai_usage(user_id="u", feature="chat", provider="openai", model="m")
        assert len(sql("SELECT 1 FROM ai_usage")) == 3

    def test_never_raises_when_the_session_cannot_be_opened(self, monkeypatch, caplog):
        @contextlib.contextmanager
        def broken():
            raise RuntimeError("database unreachable")
            yield  # pragma: no cover

        monkeypatch.setattr(ai_usage, "db_session", broken)
        with caplog.at_level(logging.WARNING, logger="services.ai_usage"):
            assert ai_usage.log_ai_usage(user_id="u", feature="chat", provider="openai", model="m") is None
        assert "could not record ai usage" in caplog.text

    def test_never_raises_when_the_insert_fails(self, monkeypatch):
        class Exploding:
            def execute(self, *_a, **_k):
                raise RuntimeError("disk full")

        @contextlib.contextmanager
        def session():
            yield Exploding()

        monkeypatch.setattr(ai_usage, "db_session", session)
        ai_usage.log_ai_usage(user_id="u", feature="chat", provider="openai", model="m")

    def test_never_raises_on_constraint_violations(self, sql):
        ai_usage.log_ai_usage(user_id="u", feature=None, provider="openai", model="m")        # feature is NOT NULL
        assert sql("SELECT 1 FROM ai_usage") == []

    def test_error_label_is_the_class_name_only(self):
        assert ai_usage.error_label(ValueError("contains the prompt text")) == "ValueError"
        assert ai_usage.error_label(TimeoutError()) == "TimeoutError"


# ---------------------------------------------------------------------------
# llm_gateway.openai_chat
# ---------------------------------------------------------------------------

class FakeOpenAI:
    """Controller + factory standing in for services.llm_gateway.AsyncOpenAI."""

    def __init__(self):
        self.reply = "  Wear the navy blazer.  "
        self.usage = SimpleNamespace(prompt_tokens=11, completion_tokens=7)
        self.error = None
        self.delay = 0.0
        self.clients = []
        self.create_calls = []

    def __call__(self, **init_kwargs):
        controller = self
        controller.clients.append(init_kwargs)

        async def create(**kwargs):
            controller.create_calls.append(kwargs)
            if controller.delay:
                await asyncio.sleep(controller.delay)
            if controller.error is not None:
                raise controller.error
            return SimpleNamespace(
                usage=controller.usage,
                choices=[SimpleNamespace(message=SimpleNamespace(content=controller.reply))],
            )

        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


@pytest.fixture
def fake_openai(monkeypatch, set_env) -> FakeOpenAI:
    fake = FakeOpenAI()
    monkeypatch.setattr(gateway, "AsyncOpenAI", fake)
    set_env(OPENAI_API_KEY="sk-test-123")
    return fake


class TestOpenAIChat:
    def test_returns_the_stripped_assistant_text(self, fake_openai):
        assert run(openai_chat(MESSAGES, **CALL)) == "Wear the navy blazer."

    def test_records_token_usage_on_success(self, fake_openai, sql):
        run(openai_chat(MESSAGES, **CALL))
        row = sql("SELECT * FROM ai_usage")[0]
        assert (row["provider"], row["model"], row["feature"], row["user_id"]) == ("openai", "gpt-4o-mini", "chat", "u1")
        assert (row["input_tokens"], row["output_tokens"], row["ok"], row["error"]) == (11, 7, 1, None)
        assert row["latency_ms"] >= 0

    def test_failure_is_re_raised_and_recorded_with_only_the_class_name(self, fake_openai, sql):
        fake_openai.error = ValueError("the prompt said: my password is hunter2")
        with pytest.raises(ValueError):
            run(openai_chat(MESSAGES, **CALL))
        row = sql("SELECT * FROM ai_usage")[0]
        assert row["ok"] == 0 and row["error"] == "ValueError"
        assert "hunter2" not in str(row)
        assert row["input_tokens"] is None

    def test_slow_provider_times_out(self, fake_openai, sql):
        fake_openai.delay = 2.0
        with pytest.raises(TimeoutError):
            run(openai_chat(MESSAGES, **{**CALL, "timeout": 0.05}))
        row = sql("SELECT ok, error FROM ai_usage")[0]
        assert row == {"ok": 0, "error": "TimeoutError"}

    def test_sdk_retries_are_disabled_and_timeout_is_passed(self, fake_openai):
        run(openai_chat(MESSAGES, **{**CALL, "timeout": 7.5}))
        assert fake_openai.clients == [{"api_key": "sk-test-123", "timeout": 7.5, "max_retries": 0}]

    def test_request_parameters(self, fake_openai):
        run(openai_chat(MESSAGES, **CALL))
        sent = fake_openai.create_calls[0]
        assert sent == {"model": "gpt-4o-mini", "messages": MESSAGES, "max_tokens": 100, "temperature": 0.2}

    def test_json_mode_requests_a_json_object(self, fake_openai):
        run(openai_chat(MESSAGES, **CALL, json_mode=True))
        assert fake_openai.create_calls[0]["response_format"] == {"type": "json_object"}

    def test_model_comes_from_settings(self, fake_openai, set_env, sql):
        set_env(OPENAI_CHAT_MODEL="gpt-custom")
        run(openai_chat(MESSAGES, **CALL))
        assert fake_openai.create_calls[0]["model"] == "gpt-custom"
        assert sql("SELECT model FROM ai_usage")[0]["model"] == "gpt-custom"

    @pytest.mark.parametrize("key", [None, "", "   "])
    def test_missing_api_key_raises_llm_unavailable_without_calling_out(self, fake_openai, set_env, sql, key):
        set_env(OPENAI_API_KEY=key)
        with pytest.raises(LLMUnavailable):
            run(openai_chat(MESSAGES, **CALL))
        assert fake_openai.clients == [] and sql("SELECT 1 FROM ai_usage") == []

    def test_llm_unavailable_is_a_runtime_error(self):
        assert issubclass(LLMUnavailable, RuntimeError)

    def test_empty_content_and_missing_usage_are_tolerated(self, fake_openai, sql):
        fake_openai.reply = None
        fake_openai.usage = None
        assert run(openai_chat(MESSAGES, **CALL)) == ""
        row = sql("SELECT input_tokens, output_tokens, ok FROM ai_usage")[0]
        assert row == {"input_tokens": None, "output_tokens": None, "ok": 1}

    def test_a_successful_call_marks_the_request_as_billed(self, fake_openai):
        async def scenario():
            quota._begin_tracking()
            await openai_chat(MESSAGES, **CALL)
            return quota.was_billed()

        assert run(scenario()) is True

    def test_a_failed_call_does_not_mark_the_request_as_billed(self, fake_openai):
        fake_openai.error = RuntimeError("503 from provider")

        async def scenario():
            quota._begin_tracking()
            with pytest.raises(RuntimeError):
                await openai_chat(MESSAGES, **CALL)
            return quota.was_billed()

        assert run(scenario()) is False

    def test_the_api_key_is_never_written_to_the_usage_table(self, fake_openai, sql):
        run(openai_chat(MESSAGES, **CALL))
        assert "sk-test-123" not in str(sql("SELECT * FROM ai_usage"))


# ---------------------------------------------------------------------------
# llm_gateway.gemini_generate
# ---------------------------------------------------------------------------

def gemini_ok(text="Gemini says hi.", prompt=21, out=9):
    return SimpleNamespace(
        status_code=200,
        json=lambda: {
            "candidates": [{"content": {"parts": [{"text": f"  {text}  "}]}}],
            "usageMetadata": {"promptTokenCount": prompt, "candidatesTokenCount": out},
        },
    )


def gemini_status(code):
    return SimpleNamespace(status_code=code, json=lambda: {"error": {"message": "nope"}})


class FakeGemini:
    def __init__(self):
        self.script = {}                 # model -> response | exception | callable
        self.calls = []

    def __call__(self, model, api_key, payload, timeout):
        self.calls.append({"model": model, "api_key": api_key, "payload": payload, "timeout": timeout})
        outcome = self.script.get(model, gemini_status(500))
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    @property
    def models(self):
        return [c["model"] for c in self.calls]


@pytest.fixture
def fake_gemini(monkeypatch, set_env) -> FakeGemini:
    fake = FakeGemini()
    monkeypatch.setattr(gateway, "_gemini_post", fake)
    set_env(GEMINI_API_KEY="g-test-key")
    return fake


class TestGeminiGenerate:
    def test_first_model_success_short_circuits(self, fake_gemini):
        fake_gemini.script["gemini-2.5-flash"] = gemini_ok("First.")
        assert run(gemini_generate(MESSAGES, **CALL)) == "First."
        assert fake_gemini.models == ["gemini-2.5-flash"]

    def test_a_404_model_is_skipped_and_the_next_one_answers(self, fake_gemini, sql):
        fake_gemini.script["gemini-2.5-flash"] = gemini_status(404)
        fake_gemini.script["gemini-2.5-flash-lite"] = gemini_ok("Second.")
        assert run(gemini_generate(MESSAGES, **CALL)) == "Second."
        assert fake_gemini.models == ["gemini-2.5-flash", "gemini-2.5-flash-lite"]
        rows = sql("SELECT model, ok, error, input_tokens, output_tokens FROM ai_usage ORDER BY id")
        assert rows == [
            {"model": "gemini-2.5-flash", "ok": 0, "error": "HTTP 404", "input_tokens": None, "output_tokens": None},
            {"model": "gemini-2.5-flash-lite", "ok": 1, "error": None, "input_tokens": 21, "output_tokens": 9},
        ]

    def test_models_are_tried_in_the_configured_order(self, fake_gemini, set_env):
        set_env(GEMINI_MODELS="model-c,model-a,model-b")
        fake_gemini.script["model-b"] = gemini_ok("Third.")
        assert run(gemini_generate(MESSAGES, **CALL)) == "Third."
        assert fake_gemini.models == ["model-c", "model-a", "model-b"]

    def test_returns_none_when_every_model_fails(self, fake_gemini, sql):
        for model in ("gemini-2.5-flash", "gemini-2.5-flash-lite"):
            fake_gemini.script[model] = gemini_status(503)
        assert run(gemini_generate(MESSAGES, **CALL)) is None
        assert [r["ok"] for r in sql("SELECT ok FROM ai_usage")] == [0, 0]

    def test_network_errors_are_recorded_and_the_next_model_is_tried(self, fake_gemini, sql):
        fake_gemini.script["gemini-2.5-flash"] = requests.ConnectionError("dns failure for host x")
        fake_gemini.script["gemini-2.5-flash-lite"] = gemini_ok("Recovered.")
        assert run(gemini_generate(MESSAGES, **CALL)) == "Recovered."
        first = sql("SELECT ok, error FROM ai_usage ORDER BY id")[0]
        assert first == {"ok": 0, "error": "ConnectionError"}

    @pytest.mark.parametrize(
        "body",
        [{}, {"candidates": []}, {"candidates": [{"content": {"parts": []}}]}, {"candidates": [{"content": {}}]}, {"candidates": None}],
    )
    def test_malformed_200_responses_are_skipped(self, fake_gemini, sql, body):
        fake_gemini.script["gemini-2.5-flash"] = SimpleNamespace(status_code=200, json=lambda: body)
        fake_gemini.script["gemini-2.5-flash-lite"] = gemini_ok("Fine.")
        assert run(gemini_generate(MESSAGES, **CALL)) == "Fine."
        assert sql("SELECT error FROM ai_usage ORDER BY id")[0]["error"] == "bad_response"

    def test_non_json_200_is_treated_as_bad_response(self, fake_gemini):
        def bad_json():
            raise ValueError("no json")

        fake_gemini.script["gemini-2.5-flash"] = SimpleNamespace(status_code=200, json=bad_json)
        fake_gemini.script["gemini-2.5-flash-lite"] = gemini_ok("Fine.")
        assert run(gemini_generate(MESSAGES, **CALL)) == "Fine."

    @pytest.mark.parametrize("key", [None, "", "  "])
    def test_missing_api_key_returns_none_without_any_request(self, fake_gemini, set_env, key):
        set_env(GEMINI_API_KEY=key)
        assert run(gemini_generate(MESSAGES, **CALL)) is None
        assert fake_gemini.calls == []

    def test_system_and_conversation_roles_are_mapped(self, fake_gemini):
        fake_gemini.script["gemini-2.5-flash"] = gemini_ok()
        conversation = [*MESSAGES[:1], {"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"},
                        {"role": "user", "content": "outfit?"}]
        run(gemini_generate(conversation, **CALL))
        payload = fake_gemini.calls[0]["payload"]
        assert payload["systemInstruction"] == {"parts": [{"text": "You are a stylist."}]}
        assert [c["role"] for c in payload["contents"]] == ["user", "model", "user"]
        assert payload["generationConfig"]["maxOutputTokens"] == 100
        assert payload["generationConfig"]["temperature"] == 0.2

    def test_a_lone_system_prompt_becomes_the_user_turn(self, fake_gemini):
        fake_gemini.script["gemini-2.5-flash"] = gemini_ok()
        run(gemini_generate(MESSAGES[:1], **CALL))
        payload = fake_gemini.calls[0]["payload"]
        assert "systemInstruction" not in payload
        assert payload["contents"] == [{"role": "user", "parts": [{"text": "You are a stylist."}]}]

    def test_thinking_is_disabled_only_for_2_5_models(self, fake_gemini, set_env):
        set_env(GEMINI_MODELS="gemini-2.5-flash,gemini-3-pro")
        run(gemini_generate(MESSAGES, **CALL))
        configs = [c["payload"]["generationConfig"] for c in fake_gemini.calls]
        assert configs[0]["thinkingConfig"] == {"thinkingBudget": 0}
        assert "thinkingConfig" not in configs[1]

    def test_json_mode_sets_the_response_mime_type(self, fake_gemini):
        fake_gemini.script["gemini-2.5-flash"] = gemini_ok()
        run(gemini_generate(MESSAGES, **CALL, json_mode=True))
        assert fake_gemini.calls[0]["payload"]["generationConfig"]["responseMimeType"] == "application/json"

    def test_api_key_and_timeout_are_passed_to_the_transport(self, fake_gemini):
        fake_gemini.script["gemini-2.5-flash"] = gemini_ok()
        run(gemini_generate(MESSAGES, **{**CALL, "timeout": 3.5}))
        assert fake_gemini.calls[0]["api_key"] == "g-test-key" and fake_gemini.calls[0]["timeout"] == 3.5

    def test_success_marks_the_request_as_billed_failure_does_not(self, fake_gemini):
        async def scenario(model_response):
            fake_gemini.script["gemini-2.5-flash"] = model_response
            fake_gemini.script["gemini-2.5-flash-lite"] = model_response
            quota._begin_tracking()
            await gemini_generate(MESSAGES, **CALL)
            return quota.was_billed()

        assert run(scenario(gemini_status(500))) is False
        assert run(scenario(gemini_ok())) is True


class TestGeminiTransport:
    def test_api_key_travels_in_a_header_never_in_the_url(self, monkeypatch):
        captured = {}

        def fake_post(url, **kwargs):
            captured.update(url=url, **kwargs)
            return "response"

        monkeypatch.setattr(gateway.requests, "post", fake_post)
        result = gateway._gemini_post("gemini-2.5-flash", "SECRET-KEY-123", {"contents": []}, 4.0)
        assert result == "response"
        assert captured["headers"] == {"x-goog-api-key": "SECRET-KEY-123"}
        assert "SECRET-KEY-123" not in captured["url"] and "key=" not in captured["url"]
        assert captured["url"].endswith("/models/gemini-2.5-flash:generateContent")
        assert captured["url"].startswith("https://")
        assert captured["json"] == {"contents": []} and captured["timeout"] == 4.0


# ---------------------------------------------------------------------------
# uploads
# ---------------------------------------------------------------------------

def upload_file(data: bytes, content_type="image/png", filename="a.png") -> UploadFile:
    headers = Headers({"content-type": content_type}) if content_type else Headers({})
    return UploadFile(file=io.BytesIO(data), filename=filename, headers=headers)


class TestReadUpload:
    def test_returns_the_bytes(self):
        data = make_image_bytes()
        assert run(read_upload(upload_file(data))) == data

    def test_multi_chunk_bodies_are_reassembled(self):
        data = b"A" * (64 * 1024 * 2 + 123)
        assert run(read_upload(upload_file(data), max_bytes=10_000_000, check_image=False)) == data

    def test_empty_body_is_400(self):
        with pytest.raises(HTTPException) as exc:
            run(read_upload(upload_file(b"")))
        assert exc.value.status_code == 400 and exc.value.detail == "Empty file"

    def test_one_byte_over_the_limit_is_413(self):
        with pytest.raises(HTTPException) as exc:
            run(read_upload(upload_file(b"x" * 11), max_bytes=10, check_image=False))
        assert exc.value.status_code == 413

    def test_exactly_the_limit_is_accepted(self):
        assert run(read_upload(upload_file(b"x" * 10), max_bytes=10, check_image=False)) == b"x" * 10

    def test_oversize_is_detected_mid_stream_for_large_bodies(self):
        with pytest.raises(HTTPException) as exc:
            run(read_upload(upload_file(b"x" * (200 * 1024)), max_bytes=100 * 1024, check_image=False))
        assert exc.value.status_code == 413

    def test_default_limit_comes_from_settings(self, set_env):
        set_env(MAX_UPLOAD_BYTES=5)
        with pytest.raises(HTTPException) as exc:
            run(read_upload(upload_file(b"123456"), check_image=False))
        assert exc.value.status_code == 413

    def test_explicit_limit_overrides_settings(self, set_env):
        set_env(MAX_UPLOAD_BYTES=5)
        assert run(read_upload(upload_file(b"123456"), max_bytes=100, check_image=False)) == b"123456"

    def test_non_image_bytes_are_422_when_checking(self):
        with pytest.raises(HTTPException) as exc:
            run(read_upload(upload_file(b"just some text")))
        assert exc.value.status_code == 422

    def test_non_image_bytes_pass_when_the_check_is_disabled(self):
        assert run(read_upload(upload_file(b"just some text"), check_image=False)) == b"just some text"

    def test_pixel_bomb_is_413(self, set_env):
        set_env(MAX_IMAGE_PIXELS=50)
        with pytest.raises(HTTPException) as exc:
            run(read_upload(upload_file(make_image_bytes(size=(10, 10)))))
        assert exc.value.status_code == 413 and "resolution" in exc.value.detail

    def test_image_at_the_pixel_limit_is_accepted(self, set_env):
        set_env(MAX_IMAGE_PIXELS=100)
        run(read_upload(upload_file(make_image_bytes(size=(10, 10)))))

    def test_truncated_image_header_is_422(self):
        with pytest.raises(HTTPException) as exc:
            run(read_upload(upload_file(make_image_bytes()[:12])))
        assert exc.value.status_code == 422


class TestRequireImageContentType:
    @pytest.mark.parametrize("ctype", ["image/png", "image/jpeg", "image/webp", "image/heic", "image/anything"])
    def test_image_types_pass(self, ctype):
        require_image_content_type(upload_file(b"x", content_type=ctype))

    @pytest.mark.parametrize("ctype", ["text/plain", "application/pdf", "application/octet-stream", "multipart/form-data", None])
    def test_other_types_are_400(self, ctype):
        with pytest.raises(HTTPException) as exc:
            require_image_content_type(upload_file(b"x", content_type=ctype))
        assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# normalize_to_jpeg
# ---------------------------------------------------------------------------

class TestNormalizeToJpeg:
    def test_output_is_a_real_jpeg(self):
        out = normalize_to_jpeg(make_image_bytes(fmt="PNG"))
        assert out[:3] == b"\xff\xd8\xff"
        assert Image.open(io.BytesIO(out)).format == "JPEG"

    def test_transparency_is_flattened_to_rgb(self):
        buf = io.BytesIO()
        Image.new("RGBA", (8, 8), (255, 0, 0, 0)).save(buf, format="PNG")
        assert Image.open(io.BytesIO(normalize_to_jpeg(buf.getvalue()))).mode == "RGB"

    def test_exif_metadata_including_location_is_stripped(self):
        exif = Image.Exif()
        exif[0x010F] = "SpyCam 3000"                       # Make
        exif[0x8825] = {1: "N", 2: (23.0, 48.0, 0.0)}      # GPSInfo
        buf = io.BytesIO()
        Image.new("RGB", (8, 8), (1, 2, 3)).save(buf, format="JPEG", exif=exif.tobytes())
        assert len(Image.open(io.BytesIO(buf.getvalue())).getexif()) > 0           # the input really has EXIF
        cleaned = normalize_to_jpeg(buf.getvalue())
        assert len(Image.open(io.BytesIO(cleaned)).getexif()) == 0
        assert b"SpyCam" not in cleaned

    def test_exif_orientation_is_applied_before_stripping(self):
        exif = Image.Exif()
        exif[0x0112] = 6                                    # rotate 90 degrees
        buf = io.BytesIO()
        Image.new("RGB", (40, 20), (9, 9, 9)).save(buf, format="JPEG", exif=exif.tobytes())
        assert Image.open(io.BytesIO(normalize_to_jpeg(buf.getvalue()))).size == (20, 40)

    def test_large_images_are_downscaled(self):
        out = Image.open(io.BytesIO(normalize_to_jpeg(make_image_bytes(size=(3000, 1500)))))
        assert max(out.size) == 1600 and out.size == (1600, 800)

    def test_small_images_are_not_upscaled(self):
        assert Image.open(io.BytesIO(normalize_to_jpeg(make_image_bytes(size=(30, 20))))).size == (30, 20)

    def test_max_side_is_configurable(self):
        out = Image.open(io.BytesIO(normalize_to_jpeg(make_image_bytes(size=(400, 200)), max_side=100)))
        assert out.size == (100, 50)

    @pytest.mark.parametrize("junk", [b"", b"<svg onload=alert(1)>", b"GIF89a", b"\x89PNG\r\n\x1a\n"])
    def test_non_images_raise_value_error_without_echoing_the_bytes(self, junk):
        with pytest.raises(ValueError) as exc:
            normalize_to_jpeg(junk)
        assert "svg" not in str(exc.value)
