"""Single-use observation sessions. Browser mutations are deliberately absent."""
from __future__ import annotations
import threading
import time
import uuid
from .adapter import BrowserAdapter, validate_observation
from .authorization import BrowserAuthorization
from .planner import CloudPlanner, LocalPlanner, PlannerResult
from .types import (ActionType, ApprovalRequest, AuditMetadata, BrowserAction,
                    SessionGrant, SessionResult, SessionStatus, bounded_text, canonical_origin)


class BrowserAgentSession:
    def __init__(self, grant: SessionGrant, adapter: BrowserAdapter | None = None,
                 local_planner: LocalPlanner | None = None,
                 cloud_planner: CloudPlanner | None = None, *, enabled: bool = False,
                 clock=time.monotonic, authorization: BrowserAuthorization | None = None):
        if type(grant) is not SessionGrant or type(enabled) is not bool:
            raise ValueError("invalid session configuration")
        self.grant, self.adapter = grant, adapter
        self.local_planner, self.cloud_planner = local_planner, cloud_planner
        self.enabled, self._clock = enabled, clock
        if authorization is not None and (type(authorization) is not BrowserAuthorization or not grant.authorization_id):
            raise ValueError("invalid parent authorization")
        self.authorization = authorization
        self._cancelled, self._revoked = threading.Event(), threading.Event()
        self._lock = threading.Lock()
        self._used, self._result = False, None
        self.task_id = uuid.uuid4().hex

    def cancel(self):
        self._cancelled.set()

    def revoke(self):
        self._revoked.set()

    def _stop(self, deadline):
        if self._cancelled.is_set():
            return SessionStatus.CANCELLED
        if self._revoked.is_set():
            return SessionStatus.BLOCKED
        now = self._clock()
        if now >= self.grant.expiry_monotonic:
            return SessionStatus.EXPIRED
        if self.grant.authorization_id:
            if not self.authorization or not self.authorization.permits_grant(self.grant, now=now):
                return SessionStatus.BLOCKED
        if now >= deadline:
            return SessionStatus.BUDGET_EXHAUSTED
        return None

    def run(self, task: str, *, cloud_task: str | None = None) -> SessionResult:
        with self._lock:
            if self._used:
                return self._result or SessionResult(SessionStatus.BLOCKED)
            self._used = True
        executed, observations, audit = [], [], []
        deadline = min(self.grant.expiry_monotonic, self._clock() + self.grant.max_duration_sec)

        def finish(status, pending=None):
            audit.append(AuditMetadata(self.task_id, self.grant.session_id, len(executed),
                                       "session", "controller", status.value))
            result = SessionResult(status, tuple(executed), tuple(observations), tuple(audit), pending)
            with self._lock:
                self._result = result
            return result

        def remaining():
            return max(0.001, deadline - self._clock())

        if not self.enabled:
            return finish(SessionStatus.DISABLED)
        if not self.adapter or not self.local_planner:
            return finish(SessionStatus.UNAVAILABLE)
        if not bounded_text(task, 2048) or ActionType.OBSERVE not in self.grant.allowed_operations:
            return finish(SessionStatus.BLOCKED)

        for step in range(self.grant.max_steps):
            stopped = self._stop(deadline)
            if stopped:
                return finish(stopped)
            try:
                obs = self.adapter.snapshot(self.grant, timeout_sec=remaining())
                stopped = self._stop(deadline)
                if stopped:
                    return finish(stopped)  # discard late data
                validate_observation(self.grant, obs)
            except Exception:
                return finish(self._stop(deadline) or SessionStatus.FAILED)
            observations.append(obs)
            executed.append(BrowserAction(ActionType.OBSERVE))
            audit.append(AuditMetadata(self.task_id, self.grant.session_id, step,
                                       "observe", "browser", "completed"))
            lane = "local"
            try:
                stopped = self._stop(deadline)
                if stopped:
                    return finish(stopped)
                result = self.local_planner.plan_next_step(self.grant, task, obs, timeout_sec=remaining())
                stopped = self._stop(deadline)
                if stopped:
                    return finish(stopped)
                if type(result) is not PlannerResult:
                    return finish(SessionStatus.FAILED)
                if result.needs_escalation:
                    if (not self.grant.cloud_policy.allowed or not self.cloud_planner
                            or not bounded_text(cloud_task, 2048)):
                        return finish(SessionStatus.BLOCKED)
                    stopped = self._stop(deadline)
                    if stopped:
                        return finish(stopped)
                    lane = "cloud"
                    result = self.cloud_planner.plan_next_step(
                        self.grant, task, obs, timeout_sec=remaining(), cloud_task=cloud_task)
                    stopped = self._stop(deadline)
                    if stopped:
                        return finish(stopped)
                if type(result) is not PlannerResult or result.error or result.needs_escalation:
                    return finish(SessionStatus.FAILED)
                if result.done == (result.action is not None):
                    return finish(SessionStatus.FAILED)
                audit.append(AuditMetadata(self.task_id, self.grant.session_id, step,
                                           "plan", lane, "completed"))
                if result.done:
                    # Observation available to local report; never a mutation claim.
                    return finish(SessionStatus.COMPLETED)
                action = result.action
                if type(action) is not BrowserAction or action.action_type not in self.grant.allowed_operations:
                    return finish(SessionStatus.BLOCKED)
                if action.action_type is ActionType.OBSERVE:
                    continue
                if action.action_type is ActionType.NAVIGATE:
                    if canonical_origin(action.target) not in self.grant.allowed_origins:
                        return finish(SessionStatus.BLOCKED)
                stopped = self._stop(deadline)
                if stopped:
                    return finish(stopped)
                current = self.adapter.document_is_current(self.grant, timeout_sec=remaining())
                stopped = self._stop(deadline)
                if stopped:
                    return finish(stopped)
                if current is not True:
                    return finish(SessionStatus.BLOCKED)
                pending = ApprovalRequest(self.grant.session_id, self.grant.tab_id,
                                          self.grant.document_id, action, deadline,
                                          self.grant.browser_id, self.grant.profile_id, self.grant.authorization_id)
                return finish(SessionStatus.NEEDS_APPROVAL, pending)
            except Exception:
                return finish(self._stop(deadline) or SessionStatus.FAILED)
        return finish(SessionStatus.BUDGET_EXHAUSTED)
