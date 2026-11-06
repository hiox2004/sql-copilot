"""Talk to the model server over the OpenAI-compatible HTTP API (llama.cpp's llama-server today).

Only the base URL and a model name are needed, so the engine can be swapped (for example for vLLM)
without touching the rest of the code. Standard library only: no extra dependency.
"""

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from t2sql.generation.prompt import OUTPUT_SCHEMA


class ModelServerError(Exception):
    """The server was unreachable or returned an error."""


@dataclass(frozen=True)
class Completion:
    text: str
    seconds: float
    prompt_tokens: int | None
    completion_tokens: int | None


def chat(
    base_url: str,
    messages: list[dict[str, str]],
    *,
    model: str = "local",
    max_tokens: int = 512,
    temperature: float = 0.0,
    json_schema: dict[str, Any] | None = OUTPUT_SCHEMA,
    timeout_s: float = 120.0,
) -> Completion:
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if json_schema is not None:
        body["response_format"] = {"type": "json_object", "schema": json_schema}
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            payload = json.load(response)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ModelServerError(f"model server request failed: {exc}") from exc
    seconds = time.perf_counter() - started
    try:
        text = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ModelServerError(f"unexpected response shape: {str(payload)[:200]}") from exc
    usage = payload.get("usage") or {}
    return Completion(text, seconds, usage.get("prompt_tokens"), usage.get("completion_tokens"))


def parse_model_json(text: str) -> dict[str, Any] | None:
    """Parse the model's reply; return None when it is not a JSON object with a string `sql`."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("sql"), str):
        return None
    return data
