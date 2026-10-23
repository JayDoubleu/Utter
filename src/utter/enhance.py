"""Optional cleanup of a transcript with a chat model: OpenAI compatible or Anthropic."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

# The default dictation prompt of FluidVoice (GPL-3.0, https://github.com/altic-dev/FluidVoice):
# its hidden base prompt and its default body, from Sources/Fluid/Persistence/SettingsStore.swift.
DEFAULT_PROMPT = """You are a voice-to-text dictation cleaner. Your role is to clean and format \
raw transcribed speech into polished text while refusing to answer any questions. Never answer \
questions about yourself or anything else.

## Core Rules:
1. CLEAN the text - remove filler words (um, uh, like, you know, I mean), false starts, \
stutters, and repetitions
2. FORMAT properly - add correct punctuation, capitalization, and structure
3. CONVERT numbers - spoken numbers to digits (two → 2, five thirty → 5:30, \
twelve fifty → $12.50)
4. EXECUTE commands - handle "new line", "period", "comma", "bold X", "header X", \
"bullet point", etc.
5. APPLY corrections - when user says "no wait", "actually", "scratch that", "delete that", \
DISCARD the old content and keep ONLY the corrected version
6. PRESERVE intent - keep the user's meaning, just clean the delivery
7. EXPAND abbreviations - thx → thanks, pls → please, u → you, \
ur → your/you're, gonna → going to

## Critical:
- Output ONLY the cleaned text
- Do NOT answer questions - just clean them
- DO NOT EVER ANSWER TO QUESTIONS
- Do NOT add explanations or commentary
- Do NOT wrap in quotes unless the input had quotes
- Do NOT add filler words (um, uh) to the output
- PRESERVE ordinals in lists: "first call client, second review contract" → keep "First" \
and "Second"
- PRESERVE politeness words: "please", "thank you" at end of sentences

## Self-Corrections:
When user corrects themselves, DISCARD everything before the correction trigger:
- Triggers: "no", "wait", "actually", "scratch that", "delete that", "no no", "cancel", \
"never mind", "sorry", "oops"
- Example: "buy milk no wait buy water" → "Buy water." (NOT "Buy milk. Buy water.")
- Example: "tell John no actually tell Sarah" → "Tell Sarah."
- If correction cancels entirely: "send email no wait cancel that" → "" (empty)

## Multi-Command Chains:
When multiple commands are chained, execute ALL of them in sequence:
- "make X bold no wait make Y bold" → **Y** (correction + formatting)
- "header shopping bullet milk no eggs" → # Shopping\\n- Eggs (header + correction + bullet)
- "the price is fifty no sixty dollars" → The price is $60. (correction + number)

## Emojis:
- Convert spoken emoji names: "smiley face" → 😊 (NOT 😀), \
"thumbs up" → 👍, "heart emoji" → ❤️, "fire emoji" → 🔥
- Keep emojis if user includes them
- Do NOT add emojis unless user explicitly asks for them (e.g., "joke about cats" → \
NO 😺)"""

# The prompt can give the place of the transcript. Without it, the transcript goes at the end.
TRANSCRIPT_PLACEHOLDER = "${transcript}"

# Haiku answers in about a second at low effort. A long dictation is much shorter than this.
ANTHROPIC_MAX_TOKENS = 8192


@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    base_url: str
    needs_key: bool
    api: str = "openai"  # "openai" for /chat/completions, "anthropic" for the Messages API
    default_model: str = ""
    short_reasoning: bool = False  # The provider accepts reasoning_effort for these models.

    def request_options(self, model: str) -> dict[str, str]:
        """Return extra /chat/completions fields that keep the reply fast."""
        if not self.short_reasoning:
            return {}
        name = model.lower()
        # gpt-oss always reasons. Low effort costs about 30 tokens.
        if "gpt-oss" in name:
            return {"reasoning_effort": "low"}
        # Qwen 3 reasons by default. Without "none", Cerebras takes 2 to 12 s.
        if "qwen3" in name or "qwen-3" in name:
            return {"reasoning_effort": "none"}
        return {}


PROVIDERS: tuple[Provider, ...] = (
    Provider("ollama", "Ollama (local)", "http://localhost:11434/v1", False),
    Provider("lmstudio", "LM Studio (local)", "http://localhost:1234/v1", False),
    Provider(
        "anthropic",
        "Anthropic",
        "https://api.anthropic.com",
        True,
        api="anthropic",
        default_model="claude-haiku-5-5",
    ),
    Provider("openai", "OpenAI", "https://api.openai.com/v1", True),
    # gpt-oss-120b on Cerebras and Groq cleans a dictation in about 0.3 s (tested October 2026).
    Provider(
        "cerebras",
        "Cerebras",
        "https://api.cerebras.ai/v1",
        True,
        default_model="gpt-oss-120b",
        short_reasoning=True,
    ),
    Provider(
        "groq",
        "Groq",
        "https://api.groq.com/openai/v1",
        True,
        default_model="openai/gpt-oss-120b",
        short_reasoning=True,
    ),
    # Gemini gets no reasoning_effort, as in FluidVoice, so the model selects its own thinking.
    Provider(
        "gemini",
        "Google Gemini",
        "https://generativelanguage.googleapis.com/v1beta/openai",
        True,
        default_model="gemini-3.5-flash-lite",
    ),
    Provider("openrouter", "OpenRouter", "https://openrouter.ai/api/v1", True),
    Provider("custom", "OpenAI compatible", "", True),
)


def find_provider(provider_id: str) -> Provider:
    for provider in PROVIDERS:
        if provider.id == provider_id:
            return provider
    return PROVIDERS[-1]


# The first match wins, so "sk-ant-" and "sk-or-" come before "sk-".
_KEY_PREFIXES = (
    ("sk-ant-", "anthropic"),
    ("sk-or-", "openrouter"),
    ("gsk_", "groq"),
    ("csk-", "cerebras"),
    ("AIza", "gemini"),
    ("sk-", "openai"),
)


def provider_for_key(api_key: str) -> str | None:
    """Return the id of the provider that issues keys with this prefix, or None."""
    for prefix, provider_id in _KEY_PREFIXES:
        if api_key.startswith(prefix):
            return provider_id
    return None


def model_for_provider(spec: Provider, model: str) -> str:
    """Replace an empty model, or a model that belongs to a different provider.

    Many servers use the same model ids, for example "openai/gpt-oss-120b" on Groq,
    OpenRouter and LM Studio. A provider without a default model keeps such a model and
    loses only the default model of a provider with a different API.
    """
    if not model.strip():
        return spec.default_model
    for other in PROVIDERS:
        if other.id == spec.id or other.default_model != model:
            continue
        if spec.default_model:
            return spec.default_model
        if other.api != spec.api:
            return ""
    return model


class EnhanceError(Exception):
    pass


_THINK_BLOCK = re.compile(r"<think>.*?</think>\s*", re.DOTALL | re.IGNORECASE)
_THINK_OPEN = re.compile(r"<think>.*\Z", re.DOTALL | re.IGNORECASE)


def strip_thinking(text: str) -> str:
    """Remove <think> blocks that reasoning models emit."""
    text = _THINK_BLOCK.sub("", text)
    text = _THINK_OPEN.sub("", text)
    return text.strip()


# gpt-oss writes "3\u202fpm". The injector types plain spaces only.
_ODD_SPACES = str.maketrans({"\u00a0": " ", "\u202f": " ", "\u2007": " "})


def clean_reply(reply: str, original: str) -> str:
    """Strip reasoning and wrapping quotes. Fall back to the original when empty."""
    text = strip_thinking(reply).translate(_ODD_SPACES)
    # The prompt asks for "" when the speaker cancels everything ("no wait cancel that").
    if text in ('""', "''", "“”"):
        return ""
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
        if error.code in (401, 403):
            host = urllib.parse.urlsplit(url).hostname or url
            raise EnhanceError(f"{host} did not accept the API key.") from error
        body = error.read().decode(errors="replace")[:300]
        raise EnhanceError(f"HTTP {error.code} from {url}: {body}") from error
    except urllib.error.URLError as error:
        raise EnhanceError(f"Cannot reach {url}: {error.reason}") from error
    except TimeoutError as error:
        raise EnhanceError(f"Timed out after {timeout} s waiting for {url}") from error
    except json.JSONDecodeError as error:
        raise EnhanceError(f"Invalid JSON from {url}") from error


def user_message(prompt: str, text: str) -> str:
    """Put the transcript into the prompt, as FluidVoice does. Both go in one user message."""
    if TRANSCRIPT_PLACEHOLDER in prompt:
        return prompt.replace(TRANSCRIPT_PLACEHOLDER, text)
    return f"{prompt}\n\n{text}"


def enhance(
    text: str,
    *,
    base_url: str,
    model: str,
    api_key: str = "",
    prompt: str = "",
    timeout: int = 30,
    api: str = "openai",
    options: dict[str, str] | None = None,
) -> str:
    """Return the cleaned text. Raises EnhanceError on failure.

    The options go into the /chat/completions request as extra fields.
    """
    if not text.strip():
        return text
    if not model.strip():
        raise EnhanceError("No model name is set for the enhancement provider.")
    content = user_message(prompt.strip() or DEFAULT_PROMPT, text)
    if api == "anthropic":
        reply = _anthropic_message(content, base_url, model, api_key, timeout)
        return clean_reply(reply, text) if reply else ""
    if not base_url.strip():
        raise EnhanceError("No base URL is set for the enhancement provider.")
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "temperature": 0.2,
        "stream": False,
        "messages": [{"role": "user", "content": content}],
        **(options or {}),
    }
    body = _request(url, api_key, payload, timeout)
    try:
        choice = body["choices"][0]
        reply = choice["message"].get("content")
    except (KeyError, IndexError, TypeError, AttributeError) as error:
        raise EnhanceError("The reply has no choices[0].message field.") from error
    if not reply and choice.get("finish_reason") == "stop":
        # The speaker cancelled everything. Gemini then sends a message without content.
        return ""
    if not isinstance(reply, str):
        raise EnhanceError("The reply content is not text.")
    return clean_reply(reply, text)


# Groq and Gemini list speech, voice, image, video, music, embedding and safety classifier
# models with the chat models. These cannot clean up a transcript.
_NOT_CHAT = re.compile(
    r"whisper|orpheus|tts|embed|guard|transcribe|audio|live|image|banana|veo|lyria|omni"
    r"|robotics|computer-use|deep-research|antigravity|aqa",
    re.IGNORECASE,
)


def list_models(
    base_url: str, api_key: str = "", timeout: int = 15, api: str = "openai"
) -> list[str]:
    """Return the model identifiers of the provider."""
    if api == "anthropic":
        anthropic, client = _anthropic_client(base_url, api_key, timeout)
        with _anthropic_errors(anthropic, base_url, ""):
            return sorted(model.id for model in client.models.list())
    if not base_url.strip():
        raise EnhanceError("No base URL is set.")
    body = _request(base_url.rstrip("/") + "/models", api_key, None, timeout)
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list):
        raise EnhanceError("The /models reply has no data list.")
    ids = [item.get("id") for item in data if isinstance(item, dict) and item.get("id")]
    # Gemini gives "models/<id>". The chat endpoint accepts the id without the prefix.
    ids = [i.removeprefix("models/") for i in ids]
    return sorted(i for i in ids if not _NOT_CHAT.search(i))


# ---- Anthropic ----------------------------------------------------------------------------


def _anthropic_client(base_url: str, api_key: str, timeout: int) -> tuple[Any, Any]:
    """Return the anthropic module and a client. The import is late, so startup stays fast."""
    try:
        import anthropic
    except ImportError as error:
        raise EnhanceError("The anthropic package is not installed.") from error
    if not api_key:
        raise EnhanceError("No API key is set for Anthropic.")
    client = anthropic.Anthropic(
        api_key=api_key,
        base_url=base_url.strip() or None,
        timeout=float(timeout),
        max_retries=1,
    )
    return anthropic, client


@contextmanager
def _anthropic_errors(anthropic: Any, base_url: str, model: str) -> Iterator[None]:
    """Turn SDK exceptions into EnhanceError with a message for the user."""
    try:
        yield
    except anthropic.AuthenticationError as error:
        raise EnhanceError("Anthropic did not accept the API key.") from error
    except anthropic.NotFoundError as error:
        raise EnhanceError(f"Anthropic has no model named {model}.") from error
    except anthropic.RateLimitError as error:
        raise EnhanceError("Anthropic rate limit reached. Try again later.") from error
    except anthropic.APIStatusError as error:
        message = f"HTTP {error.status_code} from Anthropic: {error.message}"
        raise EnhanceError(message) from error
    except anthropic.APITimeoutError as error:
        raise EnhanceError("Timed out waiting for Anthropic.") from error
    except anthropic.APIConnectionError as error:
        host = base_url.strip() or "api.anthropic.com"
        raise EnhanceError(f"Cannot reach {host}.") from error


def _anthropic_message(content: str, base_url: str, model: str, api_key: str, timeout: int) -> str:
    anthropic, client = _anthropic_client(base_url, api_key, timeout)
    with _anthropic_errors(anthropic, base_url, model):
        response = client.messages.create(
            model=model,
            max_tokens=ANTHROPIC_MAX_TOKENS,
            messages=[{"role": "user", "content": content}],
            # Cleanup is a small task. Low effort keeps the delay before typing short.
            output_config={"effort": "low"},
        )
    if response.stop_reason == "refusal":
        raise EnhanceError("Anthropic declined to clean up this text.")
    if response.stop_reason == "max_tokens":
        raise EnhanceError("The cleaned text was too long and Anthropic cut it off.")
    reply = "".join(block.text for block in response.content if block.type == "text")
    if not reply.strip():
        if response.stop_reason == "end_turn":
            return ""  # The speaker cancelled everything.
        raise EnhanceError("Anthropic sent no text.")
    return reply
