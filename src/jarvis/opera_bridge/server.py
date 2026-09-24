"""Explicitly started, read-only loopback bridge for one extension profile."""
from __future__ import annotations

import http.server
import json
import queue
import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from .api import (BridgeState, BridgeStatus, CatalogueResponse, PairingInfo,
                  ReadRequest, ReadResponse, TabMetadata)

_EXTENSION_ORIGIN = re.compile(r"chrome-extension://[a-p]{32}\Z")
_PROFILE_ID = re.compile(r"[0-9a-f]{32}\Z")
_MAX_BODY = 32_768
_MAX_PENDING = 8


def canonical_web_origin(value: str) -> str:
    """An exact web origin, not an arbitrary URL or wildcard."""
    if (type(value) is not str or not 1 <= len(value) <= 512 or
            any(ch.isspace() or ch == "\\" or ord(ch) < 32 for ch in value)):
        raise ValueError("invalid origin")
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.path or parsed.query or parsed.fragment
                or "@" in parsed.netloc or "%" in parsed.netloc):
            raise ValueError
        port = parsed.port
        if port is not None and not 1 <= port <= 65535:
            raise ValueError
        host = parsed.hostname
        if host.endswith(".") or not re.fullmatch(r"[a-z0-9.-]+", host):
            raise ValueError
        if any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
               for label in host.split(".")):
            raise ValueError
        suffix = "" if port in (None, 80 if parsed.scheme == "http" else 443) else f":{port}"
        result = f"{parsed.scheme}://{host}{suffix}"
        if result != value:
            raise ValueError
        return result
    except (ValueError, TypeError):
        raise ValueError("invalid origin") from None


@dataclass
class _Pending:
    request_id: str
    request: ReadRequest | tuple[frozenset[int], frozenset[str]]
    event: threading.Event = field(default_factory=threading.Event)
    result: ReadResponse | CatalogueResponse | None = None


class _HTTPServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, bridge: "OperaBridge"):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.bridge = bridge


class _Handler(http.server.BaseHTTPRequestHandler):
    server: _HTTPServer
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        # Neither URLs nor request headers/page data belong in standard logs.
        return

    def _reply(self, status: int, data: dict | None = None) -> None:
        body = json.dumps(data or {}, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if self.headers.get("Origin") == self.server.bridge.extension_origin:
            self.send_header("Access-Control-Allow-Origin", self.server.bridge.extension_origin)
            self.send_header("Vary", "Origin")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _headers_allowed(self) -> bool:
        expected_host = f"127.0.0.1:{self.server.server_port}"
        return (self.headers.get("Host") == expected_host
                and self.headers.get("Origin") == self.server.bridge.extension_origin)

    def do_OPTIONS(self) -> None:
        if (not self._headers_allowed() or self.path not in ("/pair", "/poll", "/result", "/select", "/disconnect")
                or self.headers.get("Access-Control-Request-Method") != "POST"):
            self._reply(403)
            return
        requested = self.headers.get("Access-Control-Request-Headers", "").lower()
        if any(part.strip() not in ("authorization", "content-type") for part in requested.split(",") if part.strip()):
            self._reply(403)
            return
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.send_header("Access-Control-Allow-Origin", self.server.bridge.extension_origin)
        self.send_header("Access-Control-Allow-Methods", "POST")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Max-Age", "0")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def do_GET(self) -> None:
        self._reply(405)

    def do_POST(self) -> None:
        if not self._headers_allowed() or self.path not in ("/pair", "/poll", "/result", "/select", "/disconnect"):
            self._reply(403)
            return
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            self._reply(415)
            return
        try:
            length = int(self.headers.get("Content-Length", ""))
            if not 1 <= length <= _MAX_BODY:
                raise ValueError
            data = json.loads(self.rfile.read(length))
            if type(data) is not dict:
                raise ValueError
        except (ValueError, TypeError, UnicodeError):
            self._reply(400)
            return
        bridge = self.server.bridge
        if self.path == "/pair":
            token = bridge._attempt_pair(data.get("code"), data.get("profile_id"))
            self._reply(200, {"bearer_token": token}) if token else self._reply(401)
            return
        header = self.headers.get("Authorization", "")
        if not header.startswith("Bearer ") or not bridge._authorized(header[7:]):
            self._reply(401)
            return
        if self.path == "/poll":
            if data:
                self._reply(400)
            else:
                self._reply(200, {"command": bridge._poll()})
            return
        if self.path == "/disconnect":
            if data:
                self._reply(400)
            else:
                self._reply(200)
                threading.Thread(target=bridge.stop, daemon=True).start()
            return
        if self.path == "/select":
            self._reply(200 if bridge._select_tab(data) else 409)
            return
        self._reply(200 if bridge._submit_result(data) else 409)


class OperaBridge:
    """The owner UI starts this explicitly; no automatic browser discovery."""

    def __init__(self, extension_origin: str):
        if type(extension_origin) is not str or not _EXTENSION_ORIGIN.fullmatch(extension_origin):
            raise ValueError("expected exact extension origin")
        self.extension_origin = extension_origin
        self._lock = threading.RLock()
        self._state = BridgeState.STOPPED
        self._server: _HTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._code: str | None = None
        self._pair_deadline = 0.0
        self._attempts = 0
        self._token: str | None = None
        self._profile_id: str | None = None
        self._commands: queue.Queue[dict] = queue.Queue(maxsize=_MAX_PENDING)
        self._pending: dict[str, _Pending] = {}
        self._selected: dict[int, TabMetadata] = {}

    def get_status(self) -> BridgeStatus:
        with self._lock:
            return BridgeStatus(self._state, self._server.server_port if self._server else None,
                                self.extension_origin if self._state is not BridgeState.STOPPED else None,
                                self._profile_id)

    def start_pairing(self) -> PairingInfo:
        with self._lock:
            if self._state is not BridgeState.STOPPED:
                raise RuntimeError("stop existing connection first")
            server = _HTTPServer(self)
            self._server = server
            self._code = f"{secrets.randbelow(100_000_000):08d}"
            self._pair_deadline = time.monotonic() + 60
            self._attempts = 0
            self._token = None
            self._profile_id = None
            self._state = BridgeState.PAIRING
            self._thread = threading.Thread(target=server.serve_forever, daemon=True)
            self._thread.start()
            return PairingInfo(self._code, server.server_port, self._pair_deadline)

    def stop(self) -> None:
        with self._lock:
            server, thread = self._server, self._thread
            self._state = BridgeState.STOPPED
            self._server = self._thread = None
            self._code = self._token = self._profile_id = None
            for item in self._pending.values():
                item.result = (ReadResponse(item.request_id, False, status="revoked")
                               if type(item.request) is ReadRequest else CatalogueResponse("revoked"))
                item.event.set()
            self._pending.clear()
            self._selected.clear()
            self._commands = queue.Queue(maxsize=_MAX_PENDING)
        if server:
            server.shutdown()
            server.server_close()
        if thread and thread is not threading.current_thread():
            thread.join(timeout=2)

    def _attempt_pair(self, code: object, profile_id: object) -> str | None:
        with self._lock:
            if (self._state is not BridgeState.PAIRING or time.monotonic() >= self._pair_deadline
                    or self._attempts >= 5 or type(code) is not str
                    or type(profile_id) is not str or not _PROFILE_ID.fullmatch(profile_id)):
                return None
            self._attempts += 1
            if not secrets.compare_digest(code, self._code or ""):
                return None
            self._code = None
            self._profile_id = profile_id
            self._token = secrets.token_urlsafe(32)
            self._state = BridgeState.PAIRED
            return self._token

    def _authorized(self, token: str) -> bool:
        with self._lock:
            return (self._state is BridgeState.PAIRED and type(token) is str
                    and self._token is not None and secrets.compare_digest(token, self._token))

    def _poll(self) -> dict:
        try:
            command = self._commands.get(timeout=0.5)
        except queue.Empty:
            return {"type": "none"}
        with self._lock:
            if self._state is not BridgeState.PAIRED or command["request_id"] not in self._pending:
                return {"type": "none"}
        return command

    def _submit_result(self, data: dict) -> bool:
        request_id = data.get("request_id")
        if type(request_id) is not str:
            return False
        with self._lock:
            item = self._pending.get(request_id)
            if self._state is not BridgeState.PAIRED or not item or item.event.is_set():
                return False
            req = item.request
            if type(req) is tuple:
                if (set(data) != {"kind", "request_id", "profile_id", "tabs"}
                        or data["kind"] != "catalogue" or data["profile_id"] != self._profile_id
                        or type(data["tabs"]) is not list or len(data["tabs"]) > 128):
                    return False
                excluded_ids, excluded_origins = req
                tabs: list[TabMetadata] = []
                seen: set[int] = set()
                for raw in data["tabs"]:
                    tab = self._parse_tab(raw)
                    if tab is None:
                        return False
                    if tab.tab_id in seen:
                        return False
                    seen.add(tab.tab_id)
                    if tab.tab_id not in excluded_ids and tab.origin not in excluded_origins:
                        tabs.append(tab)
                item.result = CatalogueResponse("completed", tuple(tabs))
                item.event.set()
                return True
            if (set(data) != {"request_id", "success", "profile_id", "tab_id", "document_id", "origin", "text"}
                    or type(data["success"]) is not bool
                    or data["profile_id"] != req.profile_id
                    or type(data["tab_id"]) is not int or data["tab_id"] != req.tab_id
                    or data["document_id"] != req.document_id
                    or data["origin"] != req.expected_origin
                    or type(data["text"]) is not str
                    or len(data["text"]) > req.max_chars):
                return False
            item.result = ReadResponse(request_id, data["success"],
                                       data["text"] if data["success"] else None,
                                       "completed" if data["success"] else "failed")
            item.event.set()
            return True

    def _parse_tab(self, raw: object) -> TabMetadata | None:
        if type(raw) is not dict or set(raw) != {"profile_id", "tab_id", "document_id", "origin", "incognito"}:
            return None
        if (raw["profile_id"] != self._profile_id or raw["incognito"] is not False
                or type(raw["tab_id"]) is not int or not 0 <= raw["tab_id"] <= 2**31 - 1
                or type(raw["document_id"]) is not str or not 1 <= len(raw["document_id"]) <= 128):
            return None
        try:
            canonical_web_origin(raw["origin"])
        except ValueError:
            return None
        return TabMetadata(raw["profile_id"], raw["tab_id"], raw["document_id"], raw["origin"])

    def _select_tab(self, raw: dict) -> bool:
        with self._lock:
            if self._state is not BridgeState.PAIRED:
                return False
            tab = self._parse_tab(raw)
            if tab is None or len(self._selected) >= 128 and tab.tab_id not in self._selected:
                return False
            self._selected[tab.tab_id] = tab
            return True

    def selected_tabs(self) -> tuple[TabMetadata, ...]:
        with self._lock:
            return tuple(self._selected.values()) if self._state is BridgeState.PAIRED else ()

    def request_catalogue(self, *, excluded_tab_ids: frozenset[int] = frozenset(),
                          excluded_origins: frozenset[str] = frozenset(),
                          timeout_seconds: float = 5.0) -> CatalogueResponse:
        if (type(excluded_tab_ids) is not frozenset or len(excluded_tab_ids) > 128
                or any(type(i) is not int or i < 0 for i in excluded_tab_ids)
                or type(excluded_origins) is not frozenset or len(excluded_origins) > 128
                or type(timeout_seconds) not in (int, float) or not 0 < timeout_seconds <= 30):
            raise ValueError("invalid catalogue request")
        for origin in excluded_origins:
            canonical_web_origin(origin)
        request_id = secrets.token_hex(16)
        with self._lock:
            if self._state is not BridgeState.PAIRED or len(self._pending) >= _MAX_PENDING:
                return CatalogueResponse("unavailable")
            item = _Pending(request_id, (excluded_tab_ids, excluded_origins))
            self._pending[request_id] = item
            try:
                self._commands.put_nowait({"type": "catalogue", "request_id": request_id,
                                           "profile_id": self._profile_id,
                                           "excluded_tab_ids": sorted(excluded_tab_ids),
                                           "excluded_origins": sorted(excluded_origins)})
            except queue.Full:
                self._pending.pop(request_id, None)
                return CatalogueResponse("busy")
        item.event.wait(timeout_seconds)
        with self._lock:
            self._pending.pop(request_id, None)
            if self._state is not BridgeState.PAIRED:
                return CatalogueResponse("revoked")
            return item.result or CatalogueResponse("timeout")

    def request_read(self, request: ReadRequest) -> ReadResponse:
        if type(request) is not ReadRequest:
            raise ValueError("invalid read request")
        request_id = secrets.token_hex(16)
        with self._lock:
            if self._state is not BridgeState.PAIRED or request.profile_id != self._profile_id:
                return ReadResponse(request_id, False, status="unavailable")
            if len(self._pending) >= _MAX_PENDING:
                return ReadResponse(request_id, False, status="busy")
            item = _Pending(request_id, request)
            self._pending[request_id] = item
            try:
                self._commands.put_nowait({"type": "read", "request_id": request_id,
                                           "profile_id": request.profile_id, "tab_id": request.tab_id,
                                           "document_id": request.document_id,
                                           "expected_origin": request.expected_origin,
                                           "max_chars": request.max_chars})
            except queue.Full:
                self._pending.pop(request_id, None)
                return ReadResponse(request_id, False, status="busy")
        item.event.wait(request.timeout_seconds)
        with self._lock:
            self._pending.pop(request_id, None)
            if self._state is not BridgeState.PAIRED:
                return ReadResponse(request_id, False, status="revoked")
            return item.result or ReadResponse(request_id, False, status="timeout")
