"""LLM API calling wrapper for ai-pm-skills.

Supports two providers:
- "openai": OpenAI-compatible API (default, works with local proxies)
- "anthropic": Anthropic Claude API

Configured via config.json: llm_provider, openai_base_url, openai_api_key.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shared.config import Config

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAYS = [2, 5, 15]


def call_llm(
    prompt: str,
    config: "Config",
    depth: int = 0,
    system_prompt: str = "",
    max_tokens: int = 8192,
    temperature: float = 0.3,
) -> str:
    model = config.get_model_for_depth(depth)

    if config.llm_provider == "codex":
        return _call_codex(prompt, system_prompt)
    if config.llm_provider == "anthropic":
        return _call_anthropic(prompt, model, system_prompt, max_tokens, temperature)
    return _call_openai(prompt, model, system_prompt, max_tokens, temperature, config)


def _call_codex(
    prompt: str,
    system_prompt: str,
) -> str:
    import subprocess

    full_prompt = ""
    if system_prompt:
        full_prompt += f"[System]\n{system_prompt}\n\n"
    full_prompt += f"[User]\n{prompt}"

    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            result = subprocess.run(
                ["codex", "exec", "-"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=180,
                shell=True,
                input=full_prompt,
            )
            if result.returncode != 0:
                raise RuntimeError(f"codex exit {result.returncode}: {result.stderr[:300]}")
            output = result.stdout.strip()
            if len(output) > 5:
                return output
            raise RuntimeError("codex returned empty response")
        except (subprocess.TimeoutExpired, RuntimeError) as e:
            last_error = e
            delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
            logger.warning(f"Codex failed (attempt {attempt + 1}): {e}, retrying in {delay}s")
            time.sleep(delay)

    raise RuntimeError(f"Codex call failed after {MAX_RETRIES} retries: {last_error}")


def _call_openai(
    prompt: str,
    model: str,
    system_prompt: str,
    max_tokens: int,
    temperature: float,
    config: "Config",
) -> str:
    import openai

    kwargs: dict = {
        "base_url": config.openai_base_url,
        "api_key": config.openai_api_key,
        "timeout": 120.0,
        "max_retries": 5,
    }
    if config.openai_custom_headers:
        kwargs["default_headers"] = config.openai_custom_headers
    client = openai.OpenAI(**kwargs)

    messages: list[dict] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return response.choices[0].message.content or ""
        except openai.RateLimitError as e:
            last_error = e
            delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
            logger.warning(f"Rate limited (attempt {attempt + 1}), retrying in {delay}s")
            time.sleep(delay)
        except openai.APIStatusError as e:
            if e.status_code >= 500:
                last_error = e
                delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
                logger.warning(f"API error {e.status_code} (attempt {attempt + 1}), retrying in {delay}s")
                time.sleep(delay)
            else:
                raise

    raise RuntimeError(f"LLM call failed after {MAX_RETRIES} retries: {last_error}")


def _call_anthropic(
    prompt: str,
    model: str,
    system_prompt: str,
    max_tokens: int,
    temperature: float,
) -> str:
    import anthropic

    client = anthropic.Anthropic()
    messages = [{"role": "user", "content": prompt}]
    kwargs: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
        "temperature": temperature,
    }
    if system_prompt:
        kwargs["system"] = system_prompt

    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            response = client.messages.create(**kwargs)
            text_blocks = [
                block.text for block in response.content
                if block.type == "text"
            ]
            return "\n".join(text_blocks)
        except anthropic.RateLimitError as e:
            last_error = e
            delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
            logger.warning(f"Rate limited (attempt {attempt + 1}), retrying in {delay}s")
            time.sleep(delay)
        except anthropic.APIStatusError as e:
            if e.status_code >= 500:
                last_error = e
                delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
                logger.warning(f"API error {e.status_code} (attempt {attempt + 1}), retrying in {delay}s")
                time.sleep(delay)
            else:
                raise

    raise RuntimeError(f"LLM call failed after {MAX_RETRIES} retries: {last_error}")


def call_llm_with_json(
    prompt: str,
    config: "Config",
    depth: int = 0,
    system_prompt: str = "",
    max_tokens: int = 8192,
) -> str:
    full_system = system_prompt + (
        "\n\nIMPORTANT: Your response must contain a valid JSON block "
        "enclosed in ```json ... ``` markers."
    )
    return call_llm(
        prompt=prompt,
        config=config,
        depth=depth,
        system_prompt=full_system,
        max_tokens=max_tokens,
    )


def estimate_tokens(text: str) -> int:
    return len(text) // 4
