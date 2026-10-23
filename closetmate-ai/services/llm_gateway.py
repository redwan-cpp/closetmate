"""
llm_gateway.py — the single place that talks to text-LLM providers.

* Model IDs, timeouts and (soon) retries live here, not scattered in routers.
* Every call — success or failure — is recorded in ``ai_usage`` (tokens, latency).
* OpenAI is primary; Gemini is the fallback, tried model by model from
  ``settings.gemini_models``. A retired model ID (HTTP 404) just moves on to
  the next one and shows up in the usage table as a failed call.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Dict, List, Optional

import requests
from openai import AsyncOpenAI

from quota import mark_billed
from services.ai_usage import error_label, log_ai_usage
from settings import get_secret, get_settings

log = logging.getLogger(__name__)

_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

Message = Dict[str, str]


class LLMUnavailable(RuntimeError):
    """No provider could be reached (missing key, outage, timeout)."""


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------

async def openai_chat(
    messages: List[Message],
    *,
    feature: str,
    user_id: Optional[str],
    max_tokens: int,
    temperature: float,
    timeout: float,
    json_mode: bool = False,
) -> str:
    """Return the assistant text, or raise (LLMUnavailable / provider error / TimeoutError)."""
    api_key = get_secret("OPENAI_API_KEY")
    if not api_key:
        raise LLMUnavailable("OPENAI_API_KEY is not configured")

    model = get_settings().openai_chat_model
    # max_retries=0: the SDK's silent retries would blow our latency budget; we own fallback.
    client = AsyncOpenAI(api_key=api_key, timeout=timeout, max_retries=0)
    kwargs = dict(model=model, messages=messages, max_tokens=max_tokens, temperature=temperature)
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    started = time.perf_counter()
    try:
        resp = await asyncio.wait_for(client.chat.completions.create(**kwargs), timeout=timeout)
    except Exception as exc:
        await asyncio.to_thread(
            log_ai_usage, user_id=user_id, feature=feature, provider="openai", model=model,
            latency_ms=_elapsed_ms(started), ok=False, error=error_label(exc),
        )
        raise

    usage = getattr(resp, "usage", None)
    await asyncio.to_thread(
        log_ai_usage, user_id=user_id, feature=feature, provider="openai", model=model,
        input_tokens=getattr(usage, "prompt_tokens", None),
        output_tokens=getattr(usage, "completion_tokens", None),
        latency_ms=_elapsed_ms(started), ok=True,
    )
    mark_billed()   # the provider answered (and charged us): no refunds from here on
    return (resp.choices[0].message.content or "").strip()


# ---------------------------------------------------------------------------
# Gemini (REST — no SDK dependency)
# ---------------------------------------------------------------------------

def _gemini_post(model: str, api_key: str, payload: dict, timeout: float) -> requests.Response:
    # Key goes in a header, not the query string, so it can't leak via URL logging.
    return requests.post(
        _GEMINI_URL.format(model=model),
        headers={"x-goog-api-key": api_key},
        json=payload,
        timeout=timeout,
    )


async def gemini_generate(
    messages: List[Message],
    *,
    feature: str,
    user_id: Optional[str],
    max_tokens: int,
    temperature: float,
    timeout: float,
    json_mode: bool = False,
) -> Optional[str]:
    """Try each configured Gemini model in order. Returns None if none succeeds."""
    api_key = get_secret("GEMINI_API_KEY")
    if not api_key:
        log.warning("GEMINI_API_KEY not set — no fallback available")
        return None

    system_text = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    contents = [
        {"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
        for m in messages
        if m["role"] in ("user", "assistant")
    ]
    if not contents:                       # prompt was passed as a lone "system" message
        contents = [{"role": "user", "parts": [{"text": system_text}]}]
        system_text = ""

    for model in get_settings().gemini_models:
        generation_config: dict = {"temperature": temperature, "maxOutputTokens": max_tokens}
        if json_mode:
            generation_config["responseMimeType"] = "application/json"
        if "2.5" in model:
            # 2.5 models "think" by default and thinking tokens count against
            # maxOutputTokens, which would truncate short answers to nothing.
            generation_config["thinkingConfig"] = {"thinkingBudget": 0}
        payload: dict = {"contents": contents, "generationConfig": generation_config}
        if system_text:
            payload["systemInstruction"] = {"parts": [{"text": system_text}]}

        started = time.perf_counter()
        try:
            resp = await asyncio.to_thread(_gemini_post, model, api_key, payload, timeout)
        except Exception as exc:  # noqa: BLE001
            log.warning("Gemini %s request failed: %s", model, error_label(exc))
            await asyncio.to_thread(
                log_ai_usage, user_id=user_id, feature=feature, provider="gemini", model=model,
                latency_ms=_elapsed_ms(started), ok=False, error=error_label(exc),
            )
            continue

        if resp.status_code != 200:
            log.warning("Gemini %s returned HTTP %d", model, resp.status_code)
            await asyncio.to_thread(
                log_ai_usage, user_id=user_id, feature=feature, provider="gemini", model=model,
                latency_ms=_elapsed_ms(started), ok=False, error=f"HTTP {resp.status_code}",
            )
            continue

        try:
            data = resp.json()
            text_out = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        except (KeyError, IndexError, TypeError, ValueError):
            await asyncio.to_thread(
                log_ai_usage, user_id=user_id, feature=feature, provider="gemini", model=model,
                latency_ms=_elapsed_ms(started), ok=False, error="bad_response",
            )
            continue

        meta = data.get("usageMetadata") or {}
        await asyncio.to_thread(
            log_ai_usage, user_id=user_id, feature=feature, provider="gemini", model=model,
            input_tokens=meta.get("promptTokenCount"),
            output_tokens=meta.get("candidatesTokenCount"),
            latency_ms=_elapsed_ms(started), ok=True,
        )
        mark_billed()
        return text_out

    return None
