import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from utter.enhance import (
    DEFAULT_PROMPT,
    EnhanceError,
    clean_reply,
    enhance,
    find_provider,
    list_models,
    model_for_provider,
    provider_for_key,
    strip_thinking,
)


class Handler(BaseHTTPRequestHandler):
    last_request: dict = {}
    status = 200

    def log_message(self, *_args):
        pass

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        Handler.last_request = json.loads(self.rfile.read(length))
        Handler.last_request["_auth"] = self.headers.get("Authorization")
        if Handler.status != 200:
            self.send_error(Handler.status)
            return
        reply = {"choices": [{"message": {"content": '<think>hmm</think>"Cleaned text."'}}]}
        body = json.dumps(reply).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        models = [
            "b-model",
            "models/a-model",
            "whisper-large-v3",
            "meta-llama/llama-prompt-guard-2-22m",
            "models/gemini-3.1-flash-image",
            "models/gemini-3.8-flash-tts",
            "models/gemini-embedding-2",
            "models/veo-3.1-generate-preview",
        ]
        body = json.dumps({"data": [{"id": m} for m in models]}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def server():
    Handler.status = 200
    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}/v1"
    httpd.shutdown()


def test_enhance_round_trip(server):
    out = enhance("raw text", base_url=server, model="m", api_key="k", prompt="")
    assert out == "Cleaned text."
    assert Handler.last_request["model"] == "m"
    assert json.loads(Handler.last_request["messages"][1]["content"]) == {"transcript": "raw text"}
    assert Handler.last_request["_auth"] == "Bearer k"


def test_enhance_sends_options(server):
    enhance("raw text", base_url=server, model="m", options={"reasoning_effort": "low"})
    assert Handler.last_request["reasoning_effort"] == "low"


def test_providers_keep_reasoning_short():
    for provider_id in ("cerebras", "groq"):
        spec = find_provider(provider_id)
        assert spec.request_options(spec.default_model) == {"reasoning_effort": "low"}
        assert spec.request_options("qwen-3.8-27b") == {"reasoning_effort": "none"}
        assert spec.request_options("llama-3.3-70b") == {}
    gemini = find_provider("gemini")
    assert gemini.request_options(gemini.default_model) == {"reasoning_effort": "low"}
    assert gemini.request_options("gemma-4-31b-it") == {}
    assert find_provider("ollama").request_options("gpt-oss:20b") == {}


def test_provider_for_key():
    assert provider_for_key("sk-ant-api03-x") == "anthropic"
    assert provider_for_key("sk-or-v1-x") == "openrouter"
    assert provider_for_key("sk-proj-x") == "openai"
    assert provider_for_key("gsk_x") == "groq"
    assert provider_for_key("csk-x") == "cerebras"
    assert provider_for_key("AIzaSyX") == "gemini"
    assert provider_for_key("abc") is None


def test_model_for_provider_replaces_a_model_of_a_different_provider():
    groq = find_provider("groq")
    assert model_for_provider(groq, "claude-haiku-5-5") == "openai/gpt-oss-120b"
    assert model_for_provider(groq, "") == "openai/gpt-oss-120b"
    assert model_for_provider(groq, "qwen/qwen3.8-27b") == "qwen/qwen3.8-27b"
    assert model_for_provider(find_provider("cerebras"), "openai/gpt-oss-120b") == "gpt-oss-120b"
    openrouter = find_provider("openrouter")
    assert model_for_provider(openrouter, "openai/gpt-oss-120b") == "openai/gpt-oss-120b"
    assert model_for_provider(openrouter, "claude-haiku-5-5") == ""
    assert model_for_provider(find_provider("ollama"), "llama3") == "llama3"
    assert model_for_provider(find_provider("anthropic"), "gpt-oss-120b") == "claude-haiku-5-5"
    gemini = find_provider("gemini")
    assert model_for_provider(gemini, "openai/gpt-oss-120b") == "gemini-3.5-flash-lite"
    assert model_for_provider(gemini, "gemini-3.8-flash") == "gemini-3.8-flash"


def test_list_models_sorted(server):
    assert list_models(server) == ["a-model", "b-model"]


def test_enhance_requires_model():
    with pytest.raises(EnhanceError):
        enhance("x", base_url="http://localhost:1", model="")


def test_enhance_bad_key(server):
    Handler.status = 401
    with pytest.raises(EnhanceError, match="127.0.0.1 did not accept the API key"):
        enhance("x", base_url=server, model="m", api_key="wrong")


def test_enhance_unreachable():
    with pytest.raises(EnhanceError):
        enhance("x", base_url="http://127.0.0.1:9", model="m", timeout=2)


def test_strip_thinking_and_clean_reply():
    assert strip_thinking("<think>a\nb</think>  Hi") == "Hi"
    assert strip_thinking("<think>unterminated") == ""
    assert clean_reply("", "orig") == "orig"
    assert clean_reply("```\ncode\n```", "orig") == "code"
    assert clean_reply('"quoted"', '"quoted"') == '"quoted"'
    assert clean_reply("At 3\u202fpm", "orig") == "At 3 pm"


class AnthropicHandler(BaseHTTPRequestHandler):
    """A fake Messages API. reply_status and stop_reason set the next reply."""

    last_request: dict = {}
    last_api_key: str | None = None
    reply_status = 200
    stop_reason = "end_turn"

    def log_message(self, *_args):
        pass

    def _send(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        AnthropicHandler.last_request = json.loads(self.rfile.read(length))
        AnthropicHandler.last_api_key = self.headers.get("x-api-key")
        if self.reply_status != 200:
            error = {"type": "authentication_error", "message": "invalid x-api-key"}
            self._send(self.reply_status, {"type": "error", "error": error})
            return
        self._send(
            200,
            {
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": AnthropicHandler.last_request["model"],
                "content": [{"type": "text", "text": "Cleaned by Claude."}],
                "stop_reason": self.stop_reason,
                "stop_sequence": None,
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
        )

    def do_GET(self):
        models = [
            {"type": "model", "id": i, "display_name": i, "created_at": "2026-01-01T00:00:00Z"}
            for i in ("claude-sonnet-5-5", "claude-haiku-5-5")
        ]
        self._send(
            200,
            {"data": models, "has_more": False, "first_id": models[0]["id"], "last_id": None},
        )


@pytest.fixture
def anthropic_server():
    AnthropicHandler.reply_status = 200
    AnthropicHandler.stop_reason = "end_turn"
    httpd = HTTPServer(("127.0.0.1", 0), AnthropicHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


def anthropic_enhance(base_url: str, api_key: str = "sk-test") -> str:
    return enhance(
        "um so the meeting is at three",
        base_url=base_url,
        model="claude-haiku-5-5",
        api_key=api_key,
        api="anthropic",
        timeout=5,
    )


def test_anthropic_round_trip(anthropic_server):
    assert anthropic_enhance(anthropic_server) == "Cleaned by Claude."
    request = AnthropicHandler.last_request
    assert request["model"] == "claude-haiku-5-5"
    assert request["system"] == DEFAULT_PROMPT
    assert request["output_config"] == {"effort": "low"}
    content = json.loads(request["messages"][0]["content"])
    assert content == {"transcript": "um so the meeting is at three"}
    assert AnthropicHandler.last_api_key == "sk-test"


def test_anthropic_refusal_is_an_error(anthropic_server):
    AnthropicHandler.stop_reason = "refusal"
    with pytest.raises(EnhanceError, match="declined"):
        anthropic_enhance(anthropic_server)


def test_anthropic_cut_off_text_is_an_error(anthropic_server):
    AnthropicHandler.stop_reason = "max_tokens"
    with pytest.raises(EnhanceError, match="cut it off"):
        anthropic_enhance(anthropic_server)


def test_anthropic_bad_key(anthropic_server):
    AnthropicHandler.reply_status = 401
    with pytest.raises(EnhanceError, match="API key"):
        anthropic_enhance(anthropic_server)


def test_anthropic_needs_a_key():
    with pytest.raises(EnhanceError, match="No API key"):
        anthropic_enhance("http://127.0.0.1:9", api_key="")


def test_anthropic_list_models(anthropic_server):
    models = list_models(anthropic_server, "sk-test", api="anthropic")
    assert models == ["claude-haiku-5-5", "claude-sonnet-5-5"]
