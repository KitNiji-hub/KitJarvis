"""Immutable browser task contracts; these objects do not grant OS access."""
from __future__ import annotations

import ipaddress
import math
import re
import uuid
from dataclasses import dataclass, field
from enum import Enum
from urllib.parse import urlsplit


class SessionStatus(Enum):
    DISABLED = "disabled"
    UNAVAILABLE = "unavailable"
    COMPLETED = "completed"
    NEEDS_APPROVAL = "needs_approval"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    BUDGET_EXHAUSTED = "budget_exhausted"


class ActionType(Enum):
    OBSERVE = "observe"
    NAVIGATE = "navigate"
    CLICK = "click"
    TYPE = "type"
    SUBMIT = "submit"


def bounded_text(value: object, limit: int, *, empty: bool = False) -> bool:
    return (type(value) is str and len(value) <= limit
            and (empty or bool(value.strip())) and "\x00" not in value)


def canonical_origin(url: str, *, origin_only: bool = False) -> str:
    """Strict web syntax, not DNS/network isolation. No navigation ships here."""
    if not bounded_text(url, 2048) or any(c.isspace() or ord(c) < 32 for c in url):
        raise ValueError("invalid web URL")
    if "\\" in url:
        raise ValueError("invalid web URL")
    try:
        p = urlsplit(url)
        if p.scheme not in ("http", "https") or not p.netloc or "@" in p.netloc or "%" in p.netloc:
            raise ValueError
        if origin_only and (p.path not in ("", "/") or p.query or p.fragment):
            raise ValueError
        host, port = p.hostname, p.port
        if not host or host.endswith(".") or p.netloc.endswith(":"):
            raise ValueError
        if ":" in host:
            if not re.fullmatch(r"\[[0-9a-fA-F:.]+\](?::[0-9]+)?", p.netloc):
                raise ValueError
            host = "[" + str(ipaddress.IPv6Address(host)) + "]"
        elif len(host) > 253 or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", part) for part in host.split(".")):
            # Explicit ASCII/punycode input avoids visually ambiguous IDN grants.
            raise ValueError
        if port is not None and not 1 <= port <= 65535:
            raise ValueError
        suffix = "" if port in (None, 80 if p.scheme == "http" else 443) else f":{port}"
        return f"{p.scheme}://{host}{suffix}"
    except (ValueError, TypeError):
        raise ValueError("invalid web URL") from None


@dataclass(frozen=True)
class CloudPolicy:
    allowed: bool = False
    allow_page_content_egress: bool = False

    def __post_init__(self):
        if type(self.allowed) is not bool or type(self.allow_page_content_egress) is not bool:
            raise ValueError("invalid cloud policy")
        if self.allow_page_content_egress and not self.allowed:
            raise ValueError("page egress requires cloud permission")


@dataclass(frozen=True)
class SessionGrant:
    tab_id: str
    document_id: str
    allowed_origins: frozenset[str]
    allowed_operations: frozenset[ActionType]
    expiry_monotonic: float
    max_steps: int = 6
    cloud_policy: CloudPolicy = field(default_factory=CloudPolicy)
    max_duration_sec: float = 30.0
    max_content_chars: int = 4096
    browser_id: str = ""
    profile_id: str = ""
    authorization_id: str = ""
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex, init=False)

    def __post_init__(self):
        if not bounded_text(self.tab_id, 128) or not bounded_text(self.document_id, 128):
            raise ValueError("invalid browser identity")
        binding = (self.browser_id, self.profile_id, self.authorization_id)
        if any(type(v) is not str for v in binding) or (any(binding) and not all(bounded_text(v, 128) for v in binding)):
            raise ValueError("invalid parent authorization binding")
        if type(self.max_steps) is not int or not 1 <= self.max_steps <= 16:
            raise ValueError("invalid step budget")
        if type(self.max_content_chars) is not int or not 1 <= self.max_content_chars <= 8192:
            raise ValueError("invalid content budget")
        for value in (self.expiry_monotonic, self.max_duration_sec):
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError("invalid time budget")
        if self.max_duration_sec > 120:
            raise ValueError("invalid time budget")
        if type(self.cloud_policy) is not CloudPolicy:
            raise ValueError("invalid cloud policy")
        if type(self.allowed_origins) not in (set, frozenset) or not 1 <= len(self.allowed_origins) <= 16:
            raise ValueError("invalid origin grant")
        origins = frozenset(canonical_origin(o, origin_only=True) for o in self.allowed_origins)
        if (type(self.allowed_operations) not in (set, frozenset) or not self.allowed_operations
                or any(type(op) is not ActionType for op in self.allowed_operations)):
            raise ValueError("invalid operation grant")
        object.__setattr__(self, "allowed_origins", origins)
        object.__setattr__(self, "allowed_operations", frozenset(self.allowed_operations))


@dataclass(frozen=True)
class BrowserAction:
    action_type: ActionType
    target: str | None = None
    value: str | None = None


@dataclass(frozen=True)
class BrowserObservation:
    tab_id: str
    document_id: str
    origin: str
    content: str
    browser_id: str = ""
    profile_id: str = ""


@dataclass(frozen=True)
class ApprovalRequest:
    session_id: str
    tab_id: str
    document_id: str
    action: BrowserAction
    expires_at: float
    browser_id: str = ""
    profile_id: str = ""
    authorization_id: str = ""


@dataclass(frozen=True)
class AuditMetadata:
    task_id: str
    session_id: str
    step: int
    operation: str
    provider_lane: str
    status: str


@dataclass(frozen=True)
class SessionResult:
    status: SessionStatus
    executed_operations: tuple[BrowserAction, ...] = ()
    observations: tuple[BrowserObservation, ...] = ()
    audit_trail: tuple[AuditMetadata, ...] = ()
    pending_approval: ApprovalRequest | None = None
