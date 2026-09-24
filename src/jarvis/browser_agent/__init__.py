"""Opt-in foundation; no browser connection or live tool registration."""
from .adapter import BrowserAdapter
from .authorization import BrowserAuthorization, BrowserScope, TabIdentity
from .opera import OperaBrowserAdapter, OperaConnectionController
from .planner import CloudPlanner, LocalPlanner
from .session import BrowserAgentSession
from .task_route import BrowserTaskHandle, BrowserTaskReport, BrowserTaskRoute
from .types import (ActionType, ApprovalRequest, AuditMetadata, BrowserAction,
                    BrowserObservation, CloudPolicy, SessionGrant, SessionResult, SessionStatus)

__all__ = ["BrowserAuthorization", "BrowserScope", "TabIdentity", "BrowserAdapter", "CloudPlanner", "LocalPlanner", "BrowserAgentSession",
           "OperaBrowserAdapter", "OperaConnectionController", "ActionType", "ApprovalRequest", "AuditMetadata", "BrowserAction",
           "BrowserObservation", "CloudPolicy", "SessionGrant", "SessionResult", "SessionStatus", "BrowserTaskRoute", "BrowserTaskHandle", "BrowserTaskReport"]
