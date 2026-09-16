import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from utter.enhance import EnhanceError, clean_reply, enhance, list_models, strip_thinking


class Handler(BaseHTTPRequestHandler):
    last_request: dict = {}

    def log_message(self, *_args):
        pass

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        Handler.last_request = json.loads(self.rfile.read(length))
        Handler.last_request["_auth"] = self.headers.get("Authorization")
        reply = {"choices": [{"message": {"content": '<think>hmm</think>"Cleaned text."'}}]}
        body = json.dumps(reply).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        body = json.dumps({"data": [{"id": "b-model"}, {"id": "a-model"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def server():
    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}/v1"
    httpd.shutdown()


def test_enhance_round_trip(server):
    out = enhance("raw text", base_url=server, model="m", api_key="k", prompt="")
    assert out == "Cleaned text."
    assert Handler.last_request["model"] == "m"
    assert Handler.last_request["messages"][1]["content"] == "raw text"
    assert Handler.last_request["_auth"] == "Bearer k"


def test_list_models_sorted(server):
    assert list_models(server) == ["a-model", "b-model"]


def test_enhance_requires_model():
    with pytest.raises(EnhanceError):
        enhance("x", base_url="http://localhost:1", model="")


def test_enhance_unreachable():
    with pytest.raises(EnhanceError):
        enhance("x", base_url="http://127.0.0.1:9", model="m", timeout=2)


def test_strip_thinking_and_clean_reply():
    assert strip_thinking("<think>a\nb</think>  Hi") == "Hi"
    assert strip_thinking("<think>unterminated") == ""
    assert clean_reply("", "orig") == "orig"
    assert clean_reply("```\ncode\n```", "orig") == "code"
    assert clean_reply('"quoted"', '"quoted"') == '"quoted"'
