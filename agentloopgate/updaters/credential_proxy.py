"""Loopback-only, single-provider relay that keeps the provider key out of the updater."""

from __future__ import annotations

import hmac
import json
import secrets
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

MAX_REQUEST_BYTES = 10 * 1024 * 1024
MAX_USAGE_BUFFER = 1024 * 1024


class _UsageParser:
    """Extract only token counters from a JSON or SSE provider response."""

    def __init__(self, content_type: str) -> None:
        self.streaming = content_type.lower().startswith("text/event-stream")
        self.buffer = b""
        self.usage = None
        self.done = False
        self.invalid = False

    def feed(self, chunk: bytes) -> None:
        if self.invalid:
            return
        self.buffer += chunk
        if self.streaming:
            while b"\n" in self.buffer:
                line, self.buffer = self.buffer.split(b"\n", 1)
                if line.startswith(b"data:"):
                    data = line[5:].strip()
                    if data == b"[DONE]":
                        self.done = True
                    else:
                        self._read_usage(data)
        if len(self.buffer) > MAX_USAGE_BUFFER:
            self.invalid = True
            self.buffer = b""

    def _read_usage(self, data: bytes) -> None:
        try:
            payload = json.loads(data)
        except (ValueError, UnicodeDecodeError):
            return
        if not isinstance(payload, dict) or not isinstance(payload.get("usage"), dict):
            return
        usage = payload["usage"]
        total = usage.get("input_tokens", usage.get("prompt_tokens"))
        output = usage.get("completion_tokens", usage.get("output_tokens"))
        details = usage.get("prompt_tokens_details") or {}
        if not isinstance(details, dict):
            return
        cached = usage.get(
            "prompt_cache_hit_tokens",
            usage.get("cache_read_input_tokens", details.get("cached_tokens", 0)),
        )
        if (
            any(type(value) is not int or value < 0 for value in (total, cached, output))
            or cached > total
        ):
            self.invalid = True
            return
        self.usage = (total - cached, cached, output)

    def finish(self) -> tuple[int, int, int] | None:
        if self.invalid:
            return None
        if not self.streaming:
            self._read_usage(self.buffer)
        elif not self.done:
            return None
        return self.usage


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class CredentialProxy:
    def __init__(self, base_url: str, api_key: str, *, direct: bool = False) -> None:
        parts = urlsplit(base_url)
        if (
            parts.scheme != "https" or parts.hostname != "api.deepseek.com"
            or parts.port not in (None, 443) or parts.username or parts.password
            or parts.path not in ("", "/", "/v1", "/v1/")
            or parts.query or parts.fragment
        ):
            raise ValueError("updater provider must be the fixed DeepSeek HTTPS endpoint")
        if not api_key:
            raise ValueError("provider credential is unavailable")
        self._upstream = base_url.rstrip("/") + "/chat/completions"
        self._api_key = api_key
        self._counts_lock = threading.Lock()
        self._started = 0
        self._pending = 0
        self._usage_records: list[tuple[int, int, int] | None] = []
        self.token = secrets.token_urlsafe(32)
        self._opener = urllib.request.build_opener(
            _NoRedirect(), *([urllib.request.ProxyHandler({})] if direct else [])
        )
        proxy = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def do_POST(self):
                if self.path != "/chat/completions":
                    self.send_error(404)
                    return
                if self.headers.get("Transfer-Encoding") is not None:
                    self.send_error(400)
                    return
                authorization = self.headers.get("Authorization", "")
                if not hmac.compare_digest(authorization, f"Bearer {proxy.token}"):
                    self.send_error(403)
                    return
                try:
                    length = int(self.headers.get("Content-Length", "-1"))
                except ValueError:
                    length = -1
                if not 0 <= length <= MAX_REQUEST_BYTES:
                    self.send_error(413)
                    return
                body = self.rfile.read(length)
                if len(body) != length:
                    self.send_error(400)
                    return
                request = urllib.request.Request(
                    proxy._upstream,
                    data=body,
                    headers={"Authorization": f"Bearer {proxy._api_key}",
                             "Content-Type": "application/json"},
                    method="POST",
                )
                with proxy._counts_lock:
                    proxy._started += 1
                captured_usage = None
                try:
                    try:
                        response = proxy._opener.open(request, timeout=120)
                    except urllib.error.HTTPError as error:
                        response = error
                    with response:
                        parser = _UsageParser(response.headers.get("Content-Type", ""))
                        self.send_response(response.status)
                        for key in ("Content-Type", "Content-Length"):
                            value = response.headers.get(key)
                            if value is not None:
                                self.send_header(key, value)
                        self.end_headers()
                        read = getattr(response, "read1", response.read)
                        while chunk := read(8192):
                            parser.feed(chunk)
                            self.wfile.write(chunk)
                            self.wfile.flush()
                        if 200 <= response.status < 300:
                            captured_usage = parser.finish()
                except (OSError, urllib.error.URLError):
                    self.close_connection = True
                finally:
                    with proxy._counts_lock:
                        proxy._usage_records.append(captured_usage)

        class Server(ThreadingHTTPServer):
            def handle_error(self, request, client_address):
                # Request data and client details must never appear in daemon stderr.
                pass

            def process_request(self, request, client_address):
                with proxy._counts_lock:
                    proxy._pending += 1
                try:
                    super().process_request(request, client_address)
                except BaseException:
                    with proxy._counts_lock:
                        proxy._pending -= 1
                    raise

            def process_request_thread(self, request, client_address):
                try:
                    super().process_request_thread(request, client_address)
                finally:
                    with proxy._counts_lock:
                        proxy._pending -= 1

        self._server = Server(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def counts(self) -> tuple[int, int]:
        with self._counts_lock:
            return self._started, self._pending

    def usage_totals(self) -> tuple[int, int, int] | None:
        with self._counts_lock:
            if len(self._usage_records) != self._started or any(
                value is None for value in self._usage_records
            ):
                return None
            return tuple(sum(value[index] for value in self._usage_records) for index in range(3))

    def __enter__(self) -> CredentialProxy:
        self._thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()
