"""
check_models.py — confirm every configured AI model ID is still live.

Model retirements are the quietest way for an AI app to break: the provider
returns 404, the fallback swallows it, and nobody notices. Run this after any
config change, on a schedule, and in CI:

    python scripts/check_models.py            # warn if only the fallback is down
    python scripts/check_models.py --strict   # fail if ANY configured model is dead

It sends ~1-token prompts, so a run costs a fraction of a cent. API keys are
read from the environment / .env and are never printed.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import requests  # noqa: E402

from settings import get_secret, get_settings, load_env  # noqa: E402


def _check_openai(model: str) -> str:
    key = get_secret("OPENAI_API_KEY")
    if not key:
        return "FAIL  OPENAI_API_KEY not set"
    from openai import OpenAI

    try:
        OpenAI(api_key=key, timeout=20, max_retries=0).chat.completions.create(
            model=model, messages=[{"role": "user", "content": "ping"}], max_tokens=1
        )
        return "OK"
    except Exception as exc:  # noqa: BLE001
        # Class + HTTP status only: provider error text can echo a masked copy of the API key.
        status = getattr(exc, "status_code", "")
        return f"FAIL  {type(exc).__name__} {status}".rstrip()


def _check_gemini(model: str) -> str:
    key = get_secret("GEMINI_API_KEY")
    if not key:
        return "FAIL  GEMINI_API_KEY not set"
    try:
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={"x-goog-api-key": key},
            json={
                "contents": [{"role": "user", "parts": [{"text": "ping"}]}],
                "generationConfig": {"maxOutputTokens": 8},
            },
            timeout=20,
        )
    except Exception as exc:  # noqa: BLE001
        return f"FAIL  {type(exc).__name__}"
    if resp.status_code == 200:
        return "OK"
    try:
        # Google's `status` field (e.g. NOT_FOUND, INVALID_ARGUMENT) is safe to show; free text is not.
        reason = str(resp.json().get("error", {}).get("status", ""))[:40]
    except ValueError:
        reason = ""
    return f"FAIL  HTTP {resp.status_code} {reason}".rstrip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--strict", action="store_true", help="fail if any Gemini fallback model is dead")
    args = parser.parse_args()

    load_env()
    s = get_settings()

    rows = [("openai", "chat", s.openai_chat_model, _check_openai(s.openai_chat_model))]
    if s.openai_vision_model != s.openai_chat_model:
        rows.append(("openai", "vision", s.openai_vision_model, _check_openai(s.openai_vision_model)))
    gemini_rows = [("gemini", "fallback", m, _check_gemini(m)) for m in s.gemini_models]
    rows += gemini_rows

    width = max(len(r[2]) for r in rows)
    for provider, role, model, result in rows:
        print(f"{provider:<7} {role:<9} {model:<{width}}  {result}")

    primary_ok = all(r[3] == "OK" for r in rows if r[0] == "openai")
    fallback_ok = any(r[3] == "OK" for r in gemini_rows)
    all_fallback_ok = all(r[3] == "OK" for r in gemini_rows)

    if not primary_ok:
        print("\nPRIMARY MODEL UNAVAILABLE — the app's AI features are down.")
        return 1
    if not fallback_ok:
        print("\nWARNING: no Gemini fallback model works — an OpenAI outage would take the stylist down.")
        return 1 if args.strict else 0
    if args.strict and not all_fallback_ok:
        print("\nOne or more configured Gemini models are dead; remove or replace them in GEMINI_MODELS.")
        return 1
    print("\nAll good.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
