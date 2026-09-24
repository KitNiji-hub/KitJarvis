"""Typed, content-bounded messages for an opt-in Opera extension connection."""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum


class BridgeState(Enum):
    STOPPED = "stopped"
    PAIRING = "pairing"
    PAIRED = "paired"


@dataclass(frozen=True)
class BridgeStatus:
    state: BridgeState
    port: int | None = None
    extension_origin: str | None = None
    profile_id: str | None = None


@dataclass(frozen=True)
class PairingInfo:
    code: str
    port: int
    expires_at_monotonic: float


@dataclass(frozen=True)
class ReadRequest:
    profile_id: str
    tab_id: int
    document_id: str
    expected_origin: str
    max_chars: int = 4096
    timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        if (type(self.profile_id) is not str or not 1 <= len(self.profile_id) <= 128
                or type(self.tab_id) is not int or not 0 <= self.tab_id <= 2**31 - 1
                or type(self.document_id) is not str or not 1 <= len(self.document_id) <= 128
                or type(self.max_chars) is not int or not 1 <= self.max_chars <= 8192
                or type(self.timeout_seconds) not in (int, float)
                or not math.isfinite(self.timeout_seconds)
                or not 0 < self.timeout_seconds <= 30):
            raise ValueError("invalid read request")
        from .server import canonical_web_origin
        if canonical_web_origin(self.expected_origin) != self.expected_origin:
            raise ValueError("invalid origin")


@dataclass(frozen=True)
class ReadResponse:
    request_id: str
    success: bool
    text: str | None = None
    status: str = "failed"


@dataclass(frozen=True)
class TabMetadata:
    profile_id: str
    tab_id: int
    document_id: str
    origin: str


@dataclass(frozen=True)
class CatalogueResponse:
    status: str
    tabs: tuple[TabMetadata, ...] = ()
