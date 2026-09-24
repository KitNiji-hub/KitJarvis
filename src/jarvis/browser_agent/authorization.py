"""Owner-issued browser visibility, separate from action and cloud permissions."""
from __future__ import annotations

import math
import threading
import uuid
from dataclasses import dataclass, field
from enum import Enum

from .types import ActionType, CloudPolicy, SessionGrant, bounded_text, canonical_origin


class BrowserScope(Enum):
    SELECTED_TABS = "selected_tabs"
    ALL_TABS = "all_tabs"


@dataclass(frozen=True)
class TabIdentity:
    browser_id: str
    profile_id: str
    tab_id: str
    document_id: str
    origin: str
    incognito: bool = False


@dataclass(frozen=True)
class BrowserAuthorization:
    """Created only by the trusted owner UI, never by a model or page.

    ALL_TABS includes existing/new normal web tabs in every window of one
    connected profile, including the owner's ordinary signed-in Opera profile.
    This is not authority over other profiles, private tabs, credentials, actions
    or cloud disclosure. The future bridge enforces identity BEFORE DOM access.
    """
    browser_id: str
    profile_id: str
    expiry_monotonic: float
    scope: BrowserScope = BrowserScope.SELECTED_TABS
    selected_tab_ids: frozenset[str] = frozenset()
    excluded_tab_ids: frozenset[str] = frozenset()
    excluded_origins: frozenset[str] = frozenset()
    all_tabs_acknowledged: bool = False
    authorization_id: str = field(default_factory=lambda: uuid.uuid4().hex, init=False)
    _revoked: threading.Event = field(default_factory=threading.Event, init=False, repr=False, compare=False)

    def __post_init__(self):
        if not bounded_text(self.browser_id, 128) or not bounded_text(self.profile_id, 128):
            raise ValueError("invalid browser identity")
        if (type(self.expiry_monotonic) not in (int, float)
                or not math.isfinite(self.expiry_monotonic) or self.expiry_monotonic <= 0):
            raise ValueError("invalid authorization expiry")
        if type(self.scope) is not BrowserScope or type(self.all_tabs_acknowledged) is not bool:
            raise ValueError("invalid browser scope")
        if self.scope is BrowserScope.ALL_TABS and not self.all_tabs_acknowledged:
            raise ValueError("all-tabs authorization requires explicit owner acknowledgment")
        for name in ("selected_tab_ids", "excluded_tab_ids"):
            value = getattr(self, name)
            if type(value) not in (set, frozenset) or len(value) > 512 or any(not bounded_text(v, 128) for v in value):
                raise ValueError("invalid tab selection")
            object.__setattr__(self, name, frozenset(value))
        if self.scope is BrowserScope.SELECTED_TABS and not self.selected_tab_ids:
            raise ValueError("selected-tabs authorization needs a selection")
        if type(self.excluded_origins) not in (set, frozenset) or len(self.excluded_origins) > 128:
            raise ValueError("invalid site exclusions")
        object.__setattr__(self, "excluded_origins", frozenset(
            canonical_origin(o, origin_only=True) for o in self.excluded_origins))

    @property
    def revoked(self) -> bool:
        return self._revoked.is_set()

    def revoke(self) -> None:
        """Immediately invalidates future admission in all linked sessions."""
        self._revoked.set()

    def permits(self, tab: TabIdentity, *, now: float) -> bool:
        if (self.revoked or type(now) not in (int, float) or not math.isfinite(now)
                or now < 0 or now >= self.expiry_monotonic or type(tab) is not TabIdentity):
            return False
        if (tab.browser_id != self.browser_id or tab.profile_id != self.profile_id
                or tab.incognito is not False
                or not bounded_text(tab.tab_id, 128) or not bounded_text(tab.document_id, 128)
                or tab.tab_id in self.excluded_tab_ids):
            return False
        try:
            origin = canonical_origin(tab.origin, origin_only=True)
        except (ValueError, TypeError):
            return False
        return (origin not in self.excluded_origins and
                (self.scope is BrowserScope.ALL_TABS or tab.tab_id in self.selected_tab_ids))

    def issue_grant(self, tab: TabIdentity, *, now: float,
                    allowed_operations=frozenset({ActionType.OBSERVE}),
                    cloud_policy: CloudPolicy = CloudPolicy(), max_steps: int = 6,
                    max_duration_sec: float = 30.0, max_content_chars: int = 4096) -> SessionGrant:
        """Bridge metadata selects a tab, then task authority pins its document.

        Action/cloud options are separately owner-supplied. All-tabs scope alone
        issues observation-only, local-only grants. Never accept model metadata
        as proof that a real tab belongs to this browser/profile.
        """
        if not self.permits(tab, now=now):
            raise PermissionError("browser scope unavailable")
        return SessionGrant(
            tab.tab_id, tab.document_id, frozenset({canonical_origin(tab.origin, origin_only=True)}),
            allowed_operations, self.expiry_monotonic, max_steps, cloud_policy,
            max_duration_sec, max_content_chars,
            browser_id=self.browser_id, profile_id=self.profile_id, authorization_id=self.authorization_id)

    def permits_grant(self, grant: SessionGrant, *, now: float) -> bool:
        if (type(grant) is not SessionGrant or grant.authorization_id != self.authorization_id
                or grant.expiry_monotonic > self.expiry_monotonic):
            return False
        return all(self.permits(TabIdentity(grant.browser_id, grant.profile_id,
                                           grant.tab_id, grant.document_id, origin), now=now)
                   for origin in grant.allowed_origins)
