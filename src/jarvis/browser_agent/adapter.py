"""Trusted bridge contract. No real browser adapter is enabled in this slice."""
from abc import ABC, abstractmethod
from .types import BrowserObservation, SessionGrant, bounded_text, canonical_origin


class BrowserAdapter(ABC):
    """Trusted code, never model-selected raw MCP tools.

    snapshot MUST enforce browser/profile/session/tab/document/origin and deadline BEFORE DOM
    access, including navigation races. Cap content at the grant limit and omit
    secrets/form values. Caller checks cannot retroactively prevent a malicious
    adapter from reading data. Do NOT implement this with an unguarded MCP
    snapshot plus a later URL check. Each call is at most once. Deadlines and
    cancellation are cooperative; issued browser I/O cannot be undone.
    """

    @abstractmethod
    def snapshot(self, grant: SessionGrant, *, timeout_sec: float) -> BrowserObservation:
        """Return bounded data only from the exact approved document."""

    @abstractmethod
    def document_is_current(self, grant: SessionGrant, *, timeout_sec: float) -> bool:
        """Validate exact granted document, without reading page content."""


def validate_observation(grant: SessionGrant, obs: BrowserObservation) -> None:
    """Defense in depth on a trusted response; NOT a pre-read sandbox."""
    if (type(obs) is not BrowserObservation or obs.tab_id != grant.tab_id
            or obs.document_id != grant.document_id
            or (grant.authorization_id and (obs.browser_id != grant.browser_id or obs.profile_id != grant.profile_id))
            or not bounded_text(obs.content, grant.max_content_chars, empty=True)
            or canonical_origin(obs.origin, origin_only=True) not in grant.allowed_origins):
        raise ValueError("invalid browser observation")
