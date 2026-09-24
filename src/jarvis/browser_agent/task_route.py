"""Operator-present, local-only route from one authorized tab to one session."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from weakref import WeakKeyDictionary

from jarvis.opera_bridge import TabMetadata

from .authorization import TabIdentity
from .opera import OperaConnectionController
from .planner import LocalPlanner
from .session import BrowserAgentSession
from .types import ActionType, SessionResult, SessionStatus, bounded_text


@dataclass(frozen=True)
class BrowserTaskReport:
    """Local report input. Private page evidence is never included in repr."""

    status: SessionStatus
    observation_count: int = 0
    read_only: bool = True
    summary: str = "No browser mutation was performed."
    session_result: SessionResult | None = field(default=None, repr=False)


def _report(result: SessionResult | None) -> BrowserTaskReport:
    if result is None:
        return BrowserTaskReport(SessionStatus.FAILED)
    # A planner's `done` means observation is sufficient, never an action receipt.
    if any(action.action_type is not ActionType.OBSERVE for action in result.executed_operations):
        return BrowserTaskReport(SessionStatus.BLOCKED)
    return BrowserTaskReport(result.status, len(result.observations), session_result=result)


class BrowserTaskHandle:
    """Poll from a UI thread; cancellation hides late page/model results at once."""

    def __init__(self):
        self._lock = threading.Lock()
        self._cancelled = threading.Event()
        self.worker_finished = threading.Event()
        self._session: BrowserAgentSession | None = None
        self._report: BrowserTaskReport | None = None

    def cancel(self) -> None:
        with self._lock:
            if self.worker_finished.is_set():
                return
            self._cancelled.set()
            self._report = BrowserTaskReport(SessionStatus.CANCELLED)
            session = self._session
            self._session = None
        if session is not None:
            session.cancel()

    def poll(self) -> BrowserTaskReport | None:
        with self._lock:
            return self._report

    def wait(self, timeout_sec: float | None = None) -> BrowserTaskReport | None:
        self.worker_finished.wait(timeout_sec)
        return self.poll()

    def _attach_session(self, session: BrowserAgentSession) -> bool:
        with self._lock:
            if self._cancelled.is_set():
                return False
            self._session = session
            return True

    def _finish(self, report: BrowserTaskReport) -> None:
        with self._lock:
            if not self._cancelled.is_set():
                self._report = report
            self._session = None
            self.worker_finished.set()


_controller_task_lock = threading.Lock()
_controller_tasks: WeakKeyDictionary[OperaConnectionController, BrowserTaskHandle] = WeakKeyDictionary()


class BrowserTaskRoute:
    """One active task for one trusted connection controller."""

    def __init__(self, controller: OperaConnectionController):
        self._controller = controller
        self._lock = threading.Lock()
        self._active: BrowserTaskHandle | None = None
        self._closed = False

    def start(self, tab: TabMetadata, task: str, planner: LocalPlanner) -> BrowserTaskHandle:
        """Return promptly; catalogue, bridge, and model calls run off-thread."""
        if not bounded_text(task, 2048):
            raise ValueError("invalid task text")
        if type(planner) is not LocalPlanner:
            raise ValueError("an exact local planner is required")
        if type(tab) is not TabMetadata:
            raise ValueError("an explicit tab is required")
        with self._lock:
            if self._closed:
                raise RuntimeError("route is closed")
            if self._active is not None and not self._active.worker_finished.is_set():
                raise RuntimeError("another task is active")
            # This in-memory check rejects obvious out-of-scope tabs before I/O.
            # issue_grant must still recheck the *live* catalogue on the worker.
            auth = self._controller.authorization
            identity = TabIdentity(auth.browser_id, tab.profile_id, str(tab.tab_id),
                                   tab.document_id, tab.origin) if auth else None
            if auth is None or not auth.permits(identity, now=time.monotonic()):
                raise PermissionError("browser scope unavailable")
            handle = BrowserTaskHandle()
            with _controller_task_lock:
                existing = _controller_tasks.get(self._controller)
                if existing is not None and not existing.worker_finished.is_set():
                    raise RuntimeError("another task is active")
                _controller_tasks[self._controller] = handle
            self._active = handle
            try:
                threading.Thread(target=self._run, args=(handle, tab, task, planner),
                                 daemon=True, name="kitjarvis-browser-task").start()
            except Exception:
                self._active = None
                with _controller_task_lock:
                    if _controller_tasks.get(self._controller) is handle:
                        del _controller_tasks[self._controller]
                raise
            return handle

    def _run(self, handle: BrowserTaskHandle, tab: TabMetadata, task: str,
             planner: LocalPlanner) -> None:
        report = BrowserTaskReport(SessionStatus.BLOCKED)
        try:
            if not handle._cancelled.is_set():
                grant = self._controller.issue_grant(tab)
                if (grant.allowed_operations != frozenset({ActionType.OBSERVE})
                        or grant.cloud_policy.allowed):
                    raise PermissionError("read-only local grant required")
                if not handle._cancelled.is_set():
                    session = BrowserAgentSession(
                        grant, adapter=self._controller.adapter(), local_planner=planner,
                        enabled=True, authorization=self._controller.authorization)
                    if handle._attach_session(session):
                        report = _report(session.run(task))
        except PermissionError:
            report = BrowserTaskReport(SessionStatus.BLOCKED)
        except Exception:
            report = BrowserTaskReport(SessionStatus.FAILED)
        finally:
            handle._finish(report)
            with _controller_task_lock:
                if _controller_tasks.get(self._controller) is handle:
                    del _controller_tasks[self._controller]
            with self._lock:
                if self._active is handle:
                    self._active = None

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            handle = self._active
        if handle is not None and not handle.worker_finished.is_set():
            handle.cancel()
        self._controller.revoke()
