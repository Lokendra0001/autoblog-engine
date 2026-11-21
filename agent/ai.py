"""AI client wrapper: Google Gemini (free tier) for all text generation.

Models are tried in order (GEMINI_MODELS in .env overrides the list). A model is skipped for the
rest of the run when it is not available to this API key or its daily free quota is used up.
Overload/timeouts are retried briefly on the same model, then the next model is tried, so a busy
model never stops an article. Hung requests time out instead of blocking the daily job.
"""

from __future__ import annotations

import os
import time

from google import genai
from google.genai import errors, types

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
_TIMEOUT_MS = 240_000  # one long article can take a couple of minutes
_gemini = (genai.Client(api_key=GEMINI_API_KEY, http_options=types.HttpOptions(
               api_version="v1beta", timeout=_TIMEOUT_MS, retry_options=types.HttpRetryOptions(attempts=1)))
           if GEMINI_API_KEY else None)

# Most reliable good writer first, then the others. Some API keys only have the 2.5 models,
# newer keys only the 3.x ones; unavailable models are skipped automatically.
MODELS = [m.strip() for m in os.getenv(
    "GEMINI_MODELS",
    "gemini-2.5-flash,gemini-3.8-flash,gemini-3.5-flash,gemini-3.1-flash-lite,gemini-2.5-flash-lite",
).split(",") if m.strip()]

_SMART_BUDGET = 1024           # 2.5 models: thinking tokens for writing
_THINKING_HEADROOM = 4096      # 3.x models: extra output room, as thinking counts against output
_TRANSIENT = (429, 500, 502, 503, 504)
_RETRY_WAITS = (15,)           # one retry per busy model, then the next model

_BUSY_COOLDOWN = 600          # seconds a busy model is tried last, so each request isn't slowed by it

_skipped: dict[str, str] = {}  # model -> reason ("quota" | "unavailable"), for this run
_busy_until: dict[str, float] = {}  # model -> time until which it is tried only after the others
_no_thinking_cfg: set[str] = set()  # models that rejected our thinking settings


def _config(model, system, max_tokens, tier, json_mode):
    if model in _no_thinking_cfg:
        thinking, extra = None, _THINKING_HEADROOM
    elif model.startswith("gemini-2."):
        budget = _SMART_BUDGET if tier == "smart" else 0
        thinking, extra = types.ThinkingConfig(thinking_budget=budget), budget
    else:
        thinking = types.ThinkingConfig(thinking_level="medium" if tier == "smart" else "low")
        extra = _THINKING_HEADROOM
    return types.GenerateContentConfig(
        system_instruction=system, max_output_tokens=max_tokens + extra, thinking_config=thinking,
        response_mime_type="application/json" if json_mode else None)


def _classify(e: errors.APIError) -> str:
    text = str(e)
    if e.code == 429 and "PerDay" in text:
        return "quota"
    if e.code == 404 or (e.code == 400 and "not found" in text.lower()):
        return "unavailable"
    if e.code == 400 and "thinking" in text.lower():
        return "thinking"
    if e.code in _TRANSIENT:
        return "transient"
    return "fatal"


def call_ai(messages, system=None, max_tokens=8192, tier="fast", cache_system=False, json_mode=False):
    """tier='fast' -> minimal thinking (short answers), tier='smart' -> more thinking (writing).

    cache_system is kept for call-site compatibility: Gemini caches repeated prompt prefixes
    automatically. json_mode=True asks for a JSON reply.
    """
    if not _gemini:
        raise RuntimeError("GEMINI_API_KEY is missing — set it in .env")
    contents = [types.Content(role="model" if m["role"] == "assistant" else "user",
                              parts=[types.Part(text=m["content"])]) for m in messages]

    busy = []
    now = time.time()
    candidates = [m for m in MODELS if m not in _skipped]
    # Models that were overloaded recently go to the back of the queue (stable order otherwise).
    candidates.sort(key=lambda m: _busy_until.get(m, 0) > now)
    for model in candidates:
        attempt = 0
        while True:
            try:
                resp = _gemini.models.generate_content(
                    model=model, contents=contents, config=_config(model, system, max_tokens, tier, json_mode))
                if not resp.text:
                    reason = resp.candidates[0].finish_reason if resp.candidates else "none"
                    raise RuntimeError(f"{model} returned no text (finish reason: {reason})")
                _busy_until.pop(model, None)
                return resp.text.strip()
            except errors.APIError as e:
                kind = _classify(e)
                if kind == "thinking" and model not in _no_thinking_cfg:
                    _no_thinking_cfg.add(model)
                    continue
                if kind in ("quota", "unavailable"):
                    print(f"[WARN] {model}: {'daily free quota used up' if kind == 'quota' else 'not available for this key'}"
                          " — switching model")
                    _skipped[model] = kind
                    break
                if kind == "fatal":
                    raise
                err = f"{e.code}"
            except RuntimeError:
                raise
            except Exception as e:  # network errors and timeouts
                err = type(e).__name__
            if attempt >= len(_RETRY_WAITS):
                print(f"[WARN] {model}: still failing ({err}) — trying the next model")
                busy.append(model)
                _busy_until[model] = time.time() + _BUSY_COOLDOWN
                break
            print(f"[WARN] {model}: {err}, retrying in {_RETRY_WAITS[attempt]}s")
            time.sleep(_RETRY_WAITS[attempt])
            attempt += 1

    if busy:
        raise RuntimeError(f"Gemini is temporarily unavailable (busy: {', '.join(busy)}); try again later")
    raise RuntimeError("All Gemini models are out of free quota for today")
