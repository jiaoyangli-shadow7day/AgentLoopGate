from __future__ import annotations

import http.client
import io
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from agentloopgate.updaters.ahe import AheSandbox
from agentloopgate.updaters.credential_proxy import CredentialProxy, _UsageParser


def test_provider_usage_parser_handles_json_and_fragmented_sse() -> None:
    parser = _UsageParser("application/json")
    parser.feed(b'{"usage":{"prompt_tokens":100,"prompt_cache_hit_tokens":20,')
    parser.feed(b'"completion_tokens":6}}')
    assert parser.finish() == (80, 20, 6)

    parser = _UsageParser("text/event-stream; charset=utf-8")
    for chunk in (
        b'data: {"choices":[]}\n\ndata: {"usage":{"prompt_tokens":100,',
        b'"prompt_tokens_details":{"cached_tokens":20},"completion_tokens":6}}\n',
        b'\ndata: [DO', b'NE]\n\n',
    ):
        parser.feed(chunk)
    assert parser.finish() == (80, 20, 6)

    truncated = _UsageParser("text/event-stream")
    truncated.feed(b'data: {"usage":{"prompt_tokens":1,"completion_tokens":1}}\n')
    assert truncated.finish() is None
    invalid = _UsageParser("application/json")
    invalid.feed(b'{"usage":{"prompt_tokens":1,"prompt_cache_hit_tokens":2,"completion_tokens":1}}')
    assert invalid.finish() is None


def test_relay_captures_usage_without_retaining_response_text() -> None:
    body = b'{"message":"private-content","usage":{"prompt_tokens":9,"completion_tokens":4}}'

    class Response(io.BytesIO):
        status = 200
        headers = {"Content-Type": "application/json", "Content-Length": str(len(body))}

    with CredentialProxy("https://api.deepseek.com", "fixture") as proxy:
        proxy._opener.open = lambda *_args, **_kwargs: Response(body)
        client = http.client.HTTPConnection("127.0.0.1", proxy.port, timeout=5)
        client.request("POST", "/chat/completions", body=b'{}',
                       headers={"Authorization": f"Bearer {proxy.token}"})
        assert client.getresponse().read() == body
        client.close()
    assert proxy.usage_totals() == (9, 0, 4)
    assert "private-content" not in repr(proxy._usage_records)


def test_relay_keeps_real_key_out_of_child_requests_and_limits_endpoint() -> None:
    observed = []

    class Response(io.BytesIO):
        status = 200
        headers = {"Content-Type": "application/json", "Content-Length": "11"}

    with CredentialProxy("https://api.deepseek.com", "synthetic-provider-secret") as proxy:
        def fake_open(request, *, timeout):
            observed.append((request.full_url, request.get_header("Authorization"), request.data))
            return Response(b'{"ok":true}')

        proxy._opener.open = fake_open
        client = http.client.HTTPConnection("127.0.0.1", proxy.port, timeout=5)
        client.request("POST", "/chat/completions", body=b'{}',
                       headers={"Authorization": f"Bearer {proxy.token}"})
        response = client.getresponse()
        assert response.status == 200
        assert response.read() == b'{"ok":true}'
        client.close()
        assert observed == [("https://api.deepseek.com/chat/completions",
                             "Bearer synthetic-provider-secret", b'{}')]
        client = http.client.HTTPConnection("127.0.0.1", proxy.port, timeout=5)
        client.request("POST", "/chat/completions", body=b'{}',
                       headers={"Authorization": "Bearer wrong"})
        assert client.getresponse().status == 403
        client.close()
        client = http.client.HTTPConnection("127.0.0.1", proxy.port, timeout=5)
        client.request("POST", "/other", body=b'{}',
                       headers={"Authorization": f"Bearer {proxy.token}"})
        assert client.getresponse().status == 404
        client.close()
        assert len(observed) == 1


@pytest.mark.parametrize("url", ["http://api.deepseek.com", "https://example.com",
                                  "https://api.deepseek.com.evil.test"])
def test_relay_rejects_untrusted_provider(url: str) -> None:
    with pytest.raises(ValueError, match="fixed DeepSeek"):
        CredentialProxy(url, "fixture")


def test_relay_does_not_follow_upstream_redirect() -> None:
    calls = []

    class Attacker(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def do_GET(self):
            calls.append(self.headers.get("Authorization"))
            self.send_response(200)
            self.end_headers()

    attacker = ThreadingHTTPServer(("127.0.0.1", 0), Attacker)

    class Redirect(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def do_POST(self):
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{attacker.server_address[1]}/")
            self.end_headers()

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
    for server in (attacker, upstream):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with CredentialProxy("https://api.deepseek.com", "synthetic-secret", direct=True) as proxy:
            proxy._upstream = f"http://127.0.0.1:{upstream.server_address[1]}/chat/completions"
            client = http.client.HTTPConnection("127.0.0.1", proxy.port, timeout=5)
            client.request("POST", "/chat/completions", body=b'{}',
                           headers={"Authorization": f"Bearer {proxy.token}"})
            response = client.getresponse()
            assert response.status == 302
            assert response.getheader("Location") is None
            response.read()
            client.close()
        assert calls == []
    finally:
        for server in (attacker, upstream):
            server.shutdown()
            server.server_close()


def test_relay_reports_pending_handler_when_client_stops_mid_request() -> None:
    with CredentialProxy("https://api.deepseek.com", "fixture") as proxy:
        client = socket.create_connection(("127.0.0.1", proxy.port), timeout=3)
        client.sendall(
            b"POST /chat/completions HTTP/1.0\r\n"
            + f"Authorization: Bearer {proxy.token}\r\n".encode()
            + b"Content-Length: 20\r\n\r\n{"
        )
        deadline = time.monotonic() + 3
        while proxy.counts()[1] == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert proxy.counts() == (0, 1)
    assert proxy.counts() == (0, 1)
    client.close()


@pytest.mark.skipif(not Path("/usr/bin/sandbox-exec").is_file(), reason="macOS only")
def test_updater_sandbox_only_connects_to_relay_port(tmp_path: Path) -> None:
    sockets = []
    for _ in range(2):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.settimeout(3)
        sockets.append(listener)
    allowed, denied = [item.getsockname()[1] for item in sockets]

    def respond(listener):
        try:
            connection, _ = listener.accept()
            with connection:
                connection.recv(2048)
                connection.sendall(b"HTTP/1.0 200 OK\r\nContent-Length: 2\r\n\r\nok")
        except OSError:
            pass

    threads = [threading.Thread(target=respond, args=(listener,), daemon=True)
               for listener in sockets]
    for thread in threads:
        thread.start()
    try:
        profile = AheSandbox(tmp_path, proxy_port=allowed).profile()
        results = []
        for port in (allowed, denied):
            results.append(subprocess.run(
                ["/usr/bin/sandbox-exec", "-p", profile, "/usr/bin/curl", "-sS",
                 "--max-time", "2", "--noproxy", "*", f"http://127.0.0.1:{port}/"],
                capture_output=True, text=True,
            ))
        assert results[0].returncode == 0 and results[0].stdout == "ok"
        assert results[1].returncode != 0
    finally:
        for listener in sockets:
            listener.close()


@pytest.mark.skipif(not Path("/usr/bin/sandbox-exec").is_file(), reason="macOS only")
def test_sandboxed_client_can_use_relay_without_real_credential(tmp_path: Path) -> None:
    observed = []

    class Response(io.BytesIO):
        status = 200
        headers = {"Content-Type": "application/json", "Content-Length": "11"}

    with CredentialProxy("https://api.deepseek.com", "synthetic-real-key") as proxy:
        def fake_open(request, *, timeout):
            observed.append(request.get_header("Authorization"))
            return Response(b'{"ok":true}')

        proxy._opener.open = fake_open
        profile = AheSandbox(tmp_path, proxy_port=proxy.port).profile()
        command = [
            "/usr/bin/sandbox-exec", "-p", profile, "/usr/bin/curl", "-sS",
            "--max-time", "5", "--noproxy", "*", "-X", "POST", "-H",
            f"Authorization: Bearer {proxy.token}", "-d", "{}",
            f"{proxy.base_url}/chat/completions",
        ]
        assert "synthetic-real-key" not in " ".join(command)
        result = subprocess.run(command, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        assert result.stdout == '{"ok":true}'
        assert observed == ["Bearer synthetic-real-key"]
