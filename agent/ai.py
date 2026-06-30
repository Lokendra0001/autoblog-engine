"""AI client wrapper: DeepSeek primary, Claude fallback.

Ported from the proven NaviGo pipeline. Platform-level (one bill for the agency),
so keys come from the environment, not per-client config.
"""

from __future__ import annotations

import os

try:
    import openai
except ImportError:
    openai = None
try:
    import anthropic
except ImportError:
    anthropic = None

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

_deepseek = (
    openai.OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
    if (openai and DEEPSEEK_API_KEY) else None
)
_claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if (anthropic and ANTHROPIC_API_KEY) else None


def call_ai(messages, system=None, max_tokens=8192, tier="fast", cache_system=False):
    """tier='fast' -> claude-haiku-4-5 (cheap), tier='smart' -> claude-sonnet-4-6 (writing).

    cache_system=True marks the (large, static) system prompt as cacheable. On the
    DeepSeek path this happens automatically (server-side prefix caching) as long as
    the system prompt is a stable prefix; on the Claude path we attach cache_control
    so the static template is billed once, then read from cache (~10x cheaper).
    """
    claude_model = "claude-haiku-4-5-20251001" if tier == "fast" else "claude-sonnet-4-6"

    if _deepseek:
        try:
            ds_messages = []
            if system:
                # System first = stable prefix -> DeepSeek auto-caches it across calls.
                ds_messages.append({"role": "system", "content": system})
            ds_messages.extend(messages)
            resp = _deepseek.chat.completions.create(
                model="deepseek-chat", max_tokens=max_tokens, messages=ds_messages,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            print(f"[WARN] DeepSeek failed: {e} — falling back to Claude")

    if not _claude:
        raise RuntimeError("No AI client available (DEEPSEEK_API_KEY and ANTHROPIC_API_KEY both missing)")
    kwargs = {"model": claude_model, "max_tokens": max_tokens, "messages": messages}
    if system and cache_system:
        kwargs["system"] = [{"type": "text", "text": system,
                             "cache_control": {"type": "ephemeral"}}]
        return _claude.messages.create(**kwargs).content[0].text.strip()
    if system:
        kwargs["system"] = system
    return _claude.messages.create(**kwargs).content[0].text.strip()
