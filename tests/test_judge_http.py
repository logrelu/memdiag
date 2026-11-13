"""OpenAICompatJudge against a local fake server: no network, no model."""
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from memdiag.judge import OpenAICompatJudge, JudgeUnavailable
from memdiag.prompt import Prompt

P = Prompt("facts", 1, "Extract from: $message")


@pytest.fixture
def server():
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
            if body["model"] == "broken":
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b"model crashed")
                return
            reply = {"choices": [{"message": {"content": '{"facts": []}'}}],
                     "usage": {"prompt_tokens": 12, "completion_tokens": 5}}
            data = {"empty": json.dumps({"choices": []}).encode(), "html": b"<html>oops</html>",
                    "null": json.dumps({"choices": [{"message": {"content": None}}]}).encode(),
                    }.get(body["model"], json.dumps(reply).encode())
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}/v1", seen
    httpd.shutdown()


def test_request_shape_auth_and_usage(server):
    url, seen = server
    judge = OpenAICompatJudge("qwen2.5:7b", base_url=url, api_key="secret-key")
    r = judge.ask(P, role="extractor", as_json=True, message="We moved.")
    assert r.data == {"facts": []} and (r.prompt_tokens, r.completion_tokens) == (12, 5)
    (req,) = seen
    assert req["path"] == "/v1/chat/completions" and req["auth"] == "Bearer secret-key"
    assert req["body"]["temperature"] == 0 and req["body"]["seed"] == 0
    assert req["body"]["response_format"] == {"type": "json_object"}
    assert req["body"]["messages"] == [{"role": "user", "content": "Extract from: We moved."}]
    assert "secret-key" not in repr(judge)


def test_no_key_no_auth_header_and_plain_mode(server, monkeypatch):
    monkeypatch.delenv("MEMDIAG_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    url, seen = server
    OpenAICompatJudge(base_url=url).ask(P, message="m")
    assert seen[0]["auth"] is None and "response_format" not in seen[0]["body"]


def test_http_error_and_unreachable_endpoint(server):
    url, _ = server
    with pytest.raises(JudgeUnavailable, match="HTTP 500: model crashed"):
        OpenAICompatJudge("broken", base_url=url).ask(P, message="m")
    with socket.socket() as s:  # a port with nothing listening
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    with pytest.raises(JudgeUnavailable, match="ollama serve"):
        OpenAICompatJudge(base_url=f"http://127.0.0.1:{port}/v1", timeout=2).ask(P, message="m")


def test_base_url_from_environment(monkeypatch):
    monkeypatch.setenv("MEMDIAG_BASE_URL", "http://example.invalid/v1/")
    assert OpenAICompatJudge().base_url == "http://example.invalid/v1"


def test_malformed_responses_raise_judge_unavailable(server):
    url, _ = server
    for model in ("empty", "html"):
        for as_json in (True, False):
            with pytest.raises(JudgeUnavailable, match="unexpected response"):
                OpenAICompatJudge(model, base_url=url).ask(P, as_json=as_json, message="m")
    r = OpenAICompatJudge("null", base_url=url).ask(P, message="m")  # null content is empty text
    assert r.text == ""


def test_seed_can_be_omitted_and_endpoint_is_in_cache_identity(server):
    url, seen = server
    OpenAICompatJudge(base_url=url, seed=None).ask(P, message="m")
    assert "seed" not in seen[0]["body"]
    assert OpenAICompatJudge(base_url="http://a/v1").cache_identity != OpenAICompatJudge(base_url="http://b/v1").cache_identity
