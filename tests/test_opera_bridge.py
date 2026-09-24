"""Synthetic loopback protocol checks; no Opera or personal pages are used."""
import http.client
import json
import threading
import time

import pytest

from jarvis.opera_bridge import (BridgeState, BridgeStatus, CatalogueResponse,
                                 OperaBridge, ReadRequest, ReadResponse, TabMetadata)
from jarvis.browser_agent import BrowserScope, OperaConnectionController


ORIGIN = "chrome-extension://" + "a" * 32
PROFILE = "b" * 32


def send(port, path, data, *, origin=ORIGIN, token=None, host=None, method="POST"):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    headers = {"Origin": origin, "Content-Type": "application/json",
               "Host": host or f"127.0.0.1:{port}"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    conn.request(method, path, json.dumps(data).encode(), headers)
    res = conn.getresponse()
    status, payload = res.status, res.read()
    conn.close()
    return status, json.loads(payload) if payload else {}


@pytest.fixture
def bridge():
    instance = OperaBridge(ORIGIN)
    yield instance
    instance.stop()


def paired(bridge):
    info = bridge.start_pairing()
    status, body = send(info.port, "/pair", {"code": info.code, "profile_id": PROFILE})
    assert status == 200
    return info.port, body["bearer_token"]


def test_pairing_scope_and_replay(bridge):
    info = bridge.start_pairing()
    assert bridge.get_status().state is BridgeState.PAIRING
    assert send(info.port, "/pair", {"code": info.code, "profile_id": PROFILE},
                origin="https://evil.test")[0] == 403
    assert send(info.port, "/pair", {"code": info.code, "profile_id": PROFILE},
                host="127.0.0.1:%s.evil.test" % info.port)[0] == 403
    assert send(info.port, "/pair", {"code": "0" * 8, "profile_id": PROFILE})[0] == 401
    assert send(info.port, "/pair", {"code": info.code, "profile_id": PROFILE})[0] == 200
    assert send(info.port, "/pair", {"code": info.code, "profile_id": PROFILE})[0] == 401
    assert bridge.get_status().profile_id == PROFILE
    bridge.stop()
    assert bridge.get_status().state is BridgeState.STOPPED


def test_cors_only_for_exact_extension(bridge):
    info = bridge.start_pairing()
    conn = http.client.HTTPConnection("127.0.0.1", info.port, timeout=3)
    conn.request("OPTIONS", "/pair", headers={
        "Host": f"127.0.0.1:{info.port}", "Origin": ORIGIN,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization, content-type"})
    res = conn.getresponse()
    assert res.status == 204 and res.getheader("Access-Control-Allow-Origin") == ORIGIN
    res.read()
    conn.close()
    conn = http.client.HTTPConnection("127.0.0.1", info.port, timeout=3)
    conn.request("OPTIONS", "/pair", headers={
        "Host": f"127.0.0.1:{info.port}", "Origin": "https://evil.test",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type"})
    res = conn.getresponse()
    assert res.status == 403 and res.getheader("Access-Control-Allow-Origin") is None
    res.read()
    conn.close()
    assert send(info.port, "/poll", {}, token="wrong")[0] == 401


def test_extension_disconnect_revokes_connection(bridge):
    port, token = paired(bridge)
    assert send(port, "/disconnect", {}, token=token)[0] == 200
    deadline = time.monotonic() + 3
    while bridge.get_status().state is not BridgeState.STOPPED and time.monotonic() < deadline:
        time.sleep(0.01)
    assert bridge.get_status().state is BridgeState.STOPPED
    assert bridge.get_status().profile_id is None


def test_read_matches_request_and_discards_wrong_or_late_result(bridge):
    port, token = paired(bridge)
    got = []
    req = ReadRequest(PROFILE, 12, "document-1", "https://example.test", 20, 2)
    thread = threading.Thread(target=lambda: got.append(bridge.request_read(req)))
    thread.start()
    status, body = send(port, "/poll", {}, token=token)
    assert status == 200 and body["command"]["type"] == "read"
    job = body["command"]
    response = {"request_id": job["request_id"], "success": True,
                "profile_id": PROFILE, "tab_id": 12, "document_id": "document-1",
                "origin": "https://example.test", "text": "synthetic page"}
    assert send(port, "/result", response | {"document_id": "other"}, token=token)[0] == 409
    assert send(port, "/result", response | {"text": "x" * 21}, token=token)[0] == 409
    assert send(port, "/result", response, token=token)[0] == 200
    thread.join(3)
    assert len(got) == 1 and got[0].success and got[0].text == "synthetic page"
    assert send(port, "/result", response, token=token)[0] == 409


def test_stop_discards_inflight_and_invalidates_token(bridge):
    port, token = paired(bridge)
    got = []
    thread = threading.Thread(target=lambda: got.append(bridge.request_read(
        ReadRequest(PROFILE, 1, "doc", "https://example.test", timeout_seconds=3))))
    thread.start()
    assert send(port, "/poll", {}, token=token)[1]["command"]["type"] == "read"
    bridge.stop()
    thread.join(3)
    assert len(got) == 1 and got[0].status == "revoked" and not got[0].text
    assert bridge.get_status().state is BridgeState.STOPPED


def test_selected_and_all_tab_catalogue_exclusions(bridge):
    port, token = paired(bridge)
    first = {"profile_id": PROFILE, "tab_id": 1, "document_id": "doc-1",
             "origin": "https://example.test", "incognito": False}
    second = first | {"tab_id": 2, "document_id": "doc-2", "origin": "https://other.test"}
    assert send(port, "/select", first | {"incognito": True}, token=token)[0] == 409
    assert send(port, "/select", first, token=token)[0] == 200
    assert [tab.tab_id for tab in bridge.selected_tabs()] == [1]
    got = []
    thread = threading.Thread(target=lambda: got.append(bridge.request_catalogue(
        excluded_origins=frozenset({"https://other.test"}), timeout_seconds=2)))
    thread.start()
    command = send(port, "/poll", {}, token=token)[1]["command"]
    assert command["type"] == "catalogue" and command["excluded_origins"] == ["https://other.test"]
    assert send(port, "/result", {"kind": "catalogue", "request_id": command["request_id"],
                                   "profile_id": PROFILE, "tabs": [first, second]}, token=token)[0] == 200
    thread.join(3)
    assert len(got) == 1 and [tab.tab_id for tab in got[0].tabs] == [1]


@pytest.mark.parametrize("origin", ["file:///x", "https://*.test", "https://u:p@example.test",
                                     "https://example.test/path", "https://example.test:443"])
def test_invalid_read_origin(origin):
    with pytest.raises(ValueError):
        ReadRequest(PROFILE, 1, "doc", origin)


class FakeTransport:
    def __init__(self):
        self.tab = TabMetadata(PROFILE, 1, "doc-1", "https://example.test")
        self.reads = 0

    def get_status(self):
        return BridgeStatus(BridgeState.PAIRED, 9999, ORIGIN, PROFILE)

    def selected_tabs(self):
        return (self.tab,)

    def request_catalogue(self, **kwargs):
        return CatalogueResponse("completed", (self.tab, TabMetadata(
            PROFILE, 2, "doc-2", "https://other.test")))

    def request_read(self, request):
        self.reads += 1
        return ReadResponse("synthetic", True, "approved evidence", "completed")

    def stop(self):
        pass


def test_selected_connection_uses_live_metadata_and_revoke_blocks_read():
    controller = OperaConnectionController(ORIGIN, clock=lambda: 1)
    fake = FakeTransport()
    controller.bridge = fake
    auth = controller.authorize(BrowserScope.SELECTED_TABS)
    assert [t.tab_id for t in controller.list_tabs()] == [1]
    with pytest.raises(PermissionError):
        controller.issue_grant(TabMetadata(PROFILE, 99, "invented", "https://example.test"))
    grant = controller.issue_grant(fake.tab)
    assert controller.adapter().snapshot(grant, timeout_sec=1).content == "approved evidence"
    assert fake.reads == 1
    auth.revoke()
    with pytest.raises(PermissionError):
        controller.adapter().snapshot(grant, timeout_sec=1)
    assert fake.reads == 1


def test_all_tab_scope_filters_exclusions_and_future_tab_without_reapproval():
    controller = OperaConnectionController(ORIGIN, clock=lambda: 1)
    fake = FakeTransport()
    controller.bridge = fake
    with pytest.raises(ValueError):
        controller.authorize(BrowserScope.ALL_TABS)
    controller.authorize(BrowserScope.ALL_TABS, all_tabs_acknowledged=True,
                         excluded_origins=frozenset({"https://other.test"}))
    assert [t.tab_id for t in controller.list_tabs()] == [1]
    fake.tab = TabMetadata(PROFILE, 3, "doc-3", "https://new.test")
    assert [t.tab_id for t in controller.list_tabs()] == [3]
    assert controller.issue_grant(fake.tab).tab_id == "3"
