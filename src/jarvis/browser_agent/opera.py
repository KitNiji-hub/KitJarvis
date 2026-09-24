"""Owner-scoped composition of the Opera extension transport and browser agent."""
from __future__ import annotations

import time

from jarvis.opera_bridge import (BridgeState, OperaBridge, ReadRequest, TabMetadata)

from .adapter import BrowserAdapter
from .authorization import BrowserAuthorization, BrowserScope, TabIdentity
from .types import BrowserObservation, SessionGrant


BROWSER_ID = "opera-gx"


class OperaBrowserAdapter(BrowserAdapter):
    """The extension checks real tab/document identity before each DOM read."""

    def __init__(self, bridge: OperaBridge, authorization: BrowserAuthorization,
                 clock=time.monotonic):
        self.bridge, self.authorization, self.clock = bridge, authorization, clock

    def snapshot(self, grant: SessionGrant, *, timeout_sec: float) -> BrowserObservation:
        now = self.clock()
        status = self.bridge.get_status()
        if (grant.browser_id != BROWSER_ID or status.state is not BridgeState.PAIRED
                or status.profile_id != grant.profile_id
                or not self.authorization.permits_grant(grant, now=now)
                or len(grant.allowed_origins) != 1):
            raise PermissionError("browser grant unavailable")
        try:
            tab_id = int(grant.tab_id)
            if str(tab_id) != grant.tab_id:
                raise ValueError
        except ValueError:
            raise PermissionError("browser grant unavailable") from None
        request = ReadRequest(grant.profile_id, tab_id, grant.document_id,
                              next(iter(grant.allowed_origins)),
                              grant.max_content_chars, min(float(timeout_sec), 30.0))
        response = self.bridge.request_read(request)
        if (not response.success or response.text is None or
                not self.authorization.permits_grant(grant, now=self.clock())):
            raise PermissionError("browser read unavailable")
        return BrowserObservation(grant.tab_id, grant.document_id, request.expected_origin,
                                  response.text, grant.browser_id, grant.profile_id)

    def document_is_current(self, grant: SessionGrant, *, timeout_sec: float) -> bool:
        # No action approval/execution is enabled by this initial read-only bridge.
        return False


class OperaConnectionController:
    """In-memory owner connection. Closing/revoking stops every linked task."""

    def __init__(self, extension_origin: str, *, clock=time.monotonic):
        self.bridge = OperaBridge(extension_origin)
        self.clock = clock
        self.authorization: BrowserAuthorization | None = None

    def start_pairing(self):
        if self.authorization is not None:
            raise RuntimeError("revoke the current authorization first")
        return self.bridge.start_pairing()

    def authorize(self, scope: BrowserScope, *, excluded_tab_ids: frozenset[str] = frozenset(),
                  excluded_origins: frozenset[str] = frozenset(),
                  all_tabs_acknowledged: bool = False, lifetime_sec: int = 1800) -> BrowserAuthorization:
        status = self.bridge.get_status()
        if (self.authorization is not None or status.state is not BridgeState.PAIRED
                or not status.profile_id or type(lifetime_sec) is not int
                or not 1 <= lifetime_sec <= 3600):
            raise PermissionError("browser connection unavailable")
        selected = frozenset(str(tab.tab_id) for tab in self.bridge.selected_tabs())
        grant = BrowserAuthorization(
            BROWSER_ID, status.profile_id, self.clock() + lifetime_sec,
            scope=scope, selected_tab_ids=selected,
            excluded_tab_ids=excluded_tab_ids, excluded_origins=excluded_origins,
            all_tabs_acknowledged=all_tabs_acknowledged)
        self.authorization = grant
        return grant

    def list_tabs(self, *, timeout_sec: float = 5.0) -> tuple[TabMetadata, ...]:
        auth = self.authorization
        if auth is None or auth.revoked or self.bridge.get_status().profile_id != auth.profile_id:
            return ()
        if auth.scope is BrowserScope.SELECTED_TABS:
            tabs = self.bridge.selected_tabs()
        else:
            catalogue = self.bridge.request_catalogue(
                excluded_tab_ids=frozenset(int(v) for v in auth.excluded_tab_ids),
                excluded_origins=auth.excluded_origins, timeout_seconds=timeout_sec)
            tabs = catalogue.tabs if catalogue.status == "completed" else ()
        return tuple(tab for tab in tabs if auth.permits(
            TabIdentity(BROWSER_ID, tab.profile_id, str(tab.tab_id), tab.document_id, tab.origin),
            now=self.clock()))

    def issue_grant(self, tab: TabMetadata) -> SessionGrant:
        auth = self.authorization
        if auth is None or type(tab) is not TabMetadata or tab not in self.list_tabs():
            raise PermissionError("browser scope unavailable")
        return auth.issue_grant(
            TabIdentity(BROWSER_ID, tab.profile_id, str(tab.tab_id), tab.document_id, tab.origin),
            now=self.clock())

    def adapter(self) -> OperaBrowserAdapter:
        if not self.authorization:
            raise PermissionError("browser scope unavailable")
        return OperaBrowserAdapter(self.bridge, self.authorization, self.clock)

    def revoke(self) -> None:
        if self.authorization:
            self.authorization.revoke()
            self.authorization = None
        self.bridge.stop()
