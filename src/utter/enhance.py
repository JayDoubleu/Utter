"""Optional cleanup of a transcript with an OpenAI-compatible chat model."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

DEFAULT_PROMPT = """You clean up dictated text.
Fix punctuation, capitalisation and obvious speech recognition errors.
Remove filler words such as "um" and "uh" and repeated words.
Keep the meaning, the language and the tone of the speaker.
Do not add information. Do not answer questions in the text. Do not add commentary.
Return only the cleaned text."""


@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    base_url: str
    needs_key: bool


PROVIDERS: tuple[Provider, ...] = (
    Provider("ollama", "Ollama (local)", "http://localhost:11434/v1", False),
    Provider("lmstudio", "LM Studio (local)", "http://localhost:1234/v1", False),
    Provider("openai", "OpenAI", "https://api.openai.com/v1", True),
    Provider("groq", "Groq", "https://api.groq.com/openai/v1", True),
    Provider("openrouter", "OpenRouter", "https://openrouter.ai/api/v1", True),
    Provider("custom", "OpenAI compatible", "", True),
)


def find_provider(provider_id: str) -> Provider:
    for provider in PROVIDERS:
        if provider.id == provider_id:
            return provider
    return PROVIDERS[-1]


class EnhanceError(Exception):
    pass


_THINK_BLOCK = re.compile(r"<think>.*?</think>\s*", re.DOTALL | re.IGNORECASE)
_THINK_OPEN = re.compile(r"<think>.*\Z", re.DOTALL | re.IGNORECASE)


def strip_thinking(text: str) -> str:
    """Remove <think> blocks that reasoning models emit."""
    text = _THINK_BLOCK.sub("", text)
    text = _THINK_OPEN.sub("", text)
    return text.strip()


def clean_reply(reply: str, original: str) -> str:
    """Strip reasoning and wrapping quotes. Fall back to the original when empty."""
    text = strip_thinking(reply)
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'“”":
        inner = text[1:-1].strip()
        if inner and not (original.startswith(text[0]) and original.endswith(text[-1])):
            text = inner
    if text.startswith("```") and text.endswith("```"):
        text = text.strip("`").strip()
    return text or original


def _request(url: str, api_key: str, payload: dict | None, timeout: int) -> dict:
    headers = {"Content-Type": "application/json", "User-Agent": "Utter"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        url, data=data, headers=headers, method="POST" if data else "GET"
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        body = error.read().decode(errors="replace")[:300]
        raise EnhanceError(f"HTTP {error.code} from {url}: {body}") from error
    except urllib.error.URLError as error:
        raise EnhanceError(f"Cannot reach {url}: {error.reason}") from error
    except TimeoutError as error:
        raise EnhanceError(f"Timed out after {timeout} s waiting for {url}") from error
    except json.JSONDecodeError as error:
        raise EnhanceError(f"Invalid JSON from {url}") from error


def enhance(
    text: str,
    *,
    base_url: str,
    model: str,
    api_key: str = "",
    prompt: str = "",
    timeout: int = 30,
) -> str:
    """Return the cleaned text. Raises EnhanceError on failure."""
    if not text.strip():
        return text
    if not base_url.strip():
        raise EnhanceError("No base URL is set for the enhancement provider.")
    if not model.strip():
        raise EnhanceError("No model name is set for the enhancement provider.")
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "temperature": 0.2,
        "stream": False,
        "messages": [
            {"role": "system", "content": prompt.strip() or DEFAULT_PROMPT},
            {"role": "user", "content": text},
        ],
    }
    body = _request(url, api_key, payload, timeout)
    try:
        reply = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise EnhanceError("The reply has no choices[0].message.content field.") from error
    if not isinstance(reply, str):
        raise EnhanceError("The reply content is not text.")
    return clean_reply(reply, text)


def list_models(base_url: str, api_key: str = "", timeout: int = 15) -> list[str]:
    """Return model identifiers from GET /models."""
    if not base_url.strip():
        raise EnhanceError("No base URL is set.")
    body = _request(base_url.rstrip("/") + "/models", api_key, None, timeout)
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list):
        raise EnhanceError("The /models reply has no data list.")
    ids = [item.get("id") for item in data if isinstance(item, dict) and item.get("id")]
    return sorted(ids)
