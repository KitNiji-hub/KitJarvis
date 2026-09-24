"""Offline task-handle checks: no Opera, model server, Qt, or socket I/O."""

import threading
import time

import pytest

from jarvis.browser_agent import (
    ActionType, BrowserAdapter, BrowserAuthorization, BrowserObservation,
    BrowserScope, CloudPlanner, LocalPlanner, SessionStatus, TabIdentity,
)
from jarvis.browser_agent.task_route import BrowserTaskRoute
from jarvis.opera_bridge import TabMetadata


TAB = TabMetadata("test-profile", 7, "doc-1", "https://example.test")
OTHER_TAB = TabMetadata("test-profile", 8, "doc-2", "https://example.test")


class FakeAdapter(BrowserAdapter):
    def __init__(self):
        self.reads = 0

    def snapshot(self, grant, *, timeout_sec):
        self.reads += 1
        return BrowserObservation(grant.tab_id, grant.document_id,
                                  next(iter(grant.allowed_origins)), "private fixture text",
                                  grant.browser_id, grant.profile_id)

    def document_is_current(self, grant, *, timeout_sec):
        return True


class FakeBackend:
    base_url = "http://127.0.0.1:8081/v1"

    def __init__(self, *, entered=None, release=None):
        self.calls = 0
        self.entered, self.release = entered, release

    def direct(self, **kwargs):
        self.calls += 1
        if self.entered:
            self.entered.set()
        if self.release:
            assert self.release.wait(3)
        return '{"action":"done"}'


class FakeController:
    def __init__(self, *, scope=BrowserScope.SELECTED_TABS, excluded=False,
                 grant_entered=None, grant_release=None):
        self.authorization = BrowserAuthorization(
            "opera-gx", TAB.profile_id, time.monotonic() + 60,
            scope=scope, selected_tab_ids=frozenset({str(TAB.tab_id)}),
            excluded_tab_ids=frozenset({str(TAB.tab_id)}) if excluded else frozenset(),
            all_tabs_acknowledged=scope is BrowserScope.ALL_TABS,
        )
        self.fake_adapter = FakeAdapter()
        self.grants = []
        self.revokes = 0
        self.grant_entered, self.grant_release = grant_entered, grant_release

    def issue_grant(self, tab):
        if self.grant_entered:
            self.grant_entered.set()
        if self.grant_release:
            assert self.grant_release.wait(3)
        if tab != TAB:
            raise PermissionError("tab not in live catalogue")
        grant = self.authorization.issue_grant(
            TabIdentity("opera-gx", tab.profile_id, str(tab.tab_id),
                        tab.document_id, tab.origin), now=time.monotonic())
        self.grants.append(grant)
        return grant

    def adapter(self):
        return self.fake_adapter

    def revoke(self):
        self.revokes += 1
        self.authorization.revoke()


@pytest.mark.parametrize("scope", [BrowserScope.SELECTED_TABS, BrowserScope.ALL_TABS])
def test_one_document_local_observation_is_a_read_only_report(scope):
    controller = FakeController(scope=scope)
    backend = FakeBackend()
    route = BrowserTaskRoute(controller)

    report = route.start(TAB, "What is on this page?", LocalPlanner(backend, "local")).wait(2)

    assert report.status is SessionStatus.COMPLETED
    assert report.read_only is True
    assert report.observation_count == 1
    assert report.session_result.observations[0].content == "private fixture text"
    assert "private fixture text" not in repr(report)
    assert "private fixture text" not in report.summary
    assert "No browser mutation was performed" in report.summary
    assert {a.action_type for a in report.session_result.executed_operations} == {ActionType.OBSERVE}
    assert controller.grants[0].allowed_origins == frozenset({TAB.origin})
    assert controller.grants[0].document_id == TAB.document_id
    assert backend.calls == 1
    route.close()


@pytest.mark.parametrize("tab,excluded", [(OTHER_TAB, False), (TAB, True)])
def test_out_of_scope_tab_never_reaches_browser_or_model(tab, excluded):
    controller = FakeController(excluded=excluded)
    backend = FakeBackend()
    route = BrowserTaskRoute(controller)

    with pytest.raises(PermissionError):
        route.start(tab, "Read", LocalPlanner(backend, "local"))
    assert controller.fake_adapter.reads == backend.calls == 0
    route.close()


def test_cancel_during_planner_discards_late_success_and_keeps_active_bound():
    entered, release = threading.Event(), threading.Event()
    controller = FakeController()
    route = BrowserTaskRoute(controller)
    handle = route.start(TAB, "Read", LocalPlanner(FakeBackend(entered=entered, release=release), "local"))

    assert entered.wait(2)
    with pytest.raises(RuntimeError):
        route.start(TAB, "Another task", LocalPlanner(FakeBackend(), "local"))
    handle.cancel()
    assert handle.poll().status is SessionStatus.CANCELLED
    with pytest.raises(RuntimeError):
        route.start(TAB, "Another task", LocalPlanner(FakeBackend(), "local"))
    release.set()
    assert handle.wait(2).status is SessionStatus.CANCELLED
    assert handle.worker_finished.wait(2)
    assert handle.poll().observation_count == 0
    route.close()


def test_close_while_grant_is_pending_prevents_any_read_or_late_report():
    entered, release = threading.Event(), threading.Event()
    controller = FakeController(grant_entered=entered, grant_release=release)
    backend = FakeBackend()
    route = BrowserTaskRoute(controller)
    handle = route.start(TAB, "Read", LocalPlanner(backend, "local"))

    assert entered.wait(2)
    route.close()
    assert handle.poll().status is SessionStatus.CANCELLED
    release.set()
    assert handle.worker_finished.wait(2)
    assert handle.poll().status is SessionStatus.CANCELLED
    assert controller.authorization.revoked
    assert controller.fake_adapter.reads == backend.calls == 0
    assert controller.revokes == 1
    with pytest.raises(RuntimeError):
        route.start(TAB, "Read again", LocalPlanner(FakeBackend(), "local"))


def test_grant_lookup_is_off_thread_and_stale_document_is_blocked():
    entered, release = threading.Event(), threading.Event()
    controller = FakeController(grant_entered=entered, grant_release=release)
    backend = FakeBackend()
    route = BrowserTaskRoute(controller)
    started = time.monotonic()
    handle = route.start(TAB, "Read", LocalPlanner(backend, "local"))
    assert time.monotonic() - started < 0.5
    assert entered.wait(2)
    controller.authorization.revoke()
    release.set()
    assert handle.wait(2).status is SessionStatus.BLOCKED
    assert controller.fake_adapter.reads == backend.calls == 0
    route.close()


def test_mutation_proposal_does_not_become_action_receipt():
    controller = FakeController()
    backend = FakeBackend()
    backend.direct = lambda **kwargs: '{"action":"click","target":"button"}'
    route = BrowserTaskRoute(controller)
    report = route.start(TAB, "Click it", LocalPlanner(backend, "local")).wait(2)
    assert report.status is SessionStatus.BLOCKED
    assert {action.action_type for action in report.session_result.executed_operations} == {ActionType.OBSERVE}
    assert "No browser mutation was performed" in report.summary
    route.close()


def test_two_routes_cannot_run_concurrently_on_same_controller():
    entered, release = threading.Event(), threading.Event()
    controller = FakeController()
    first, second = BrowserTaskRoute(controller), BrowserTaskRoute(controller)
    handle = first.start(TAB, "Read", LocalPlanner(FakeBackend(entered=entered, release=release), "local"))
    assert entered.wait(2)
    try:
        with pytest.raises(RuntimeError, match="another task is active"):
            second.start(TAB, "Read again", LocalPlanner(FakeBackend(), "local"))
    finally:
        release.set()
        assert handle.wait(2) is not None
        first.close()
        second.close()


def test_thread_start_failure_does_not_poison_route(monkeypatch):
    controller = FakeController()
    route = BrowserTaskRoute(controller)
    original_start = threading.Thread.start

    def fail_start(self):
        raise RuntimeError("worker unavailable")

    monkeypatch.setattr(threading.Thread, "start", fail_start)
    with pytest.raises(RuntimeError, match="worker unavailable"):
        route.start(TAB, "Read", LocalPlanner(FakeBackend(), "local"))
    monkeypatch.setattr(threading.Thread, "start", original_start)
    assert route.start(TAB, "Read", LocalPlanner(FakeBackend(), "local")).wait(2).status is SessionStatus.COMPLETED
    route.close()


def test_completed_result_stays_completed_when_cancel_or_close_arrives_later():
    controller = FakeController()
    route = BrowserTaskRoute(controller)
    handle = route.start(TAB, "Read", LocalPlanner(FakeBackend(), "local"))
    report = handle.wait(2)
    assert report.status is SessionStatus.COMPLETED
    handle.cancel()
    route.close()
    assert handle.poll() is report


def test_cloud_planner_and_invalid_task_are_rejected_before_grant():
    controller = FakeController()
    route = BrowserTaskRoute(controller)
    with pytest.raises(ValueError):
        route.start(TAB, "", LocalPlanner(FakeBackend(), "local"))
    cloud_backend = FakeBackend()
    cloud_backend.base_url = "https://provider.example/v1"
    with pytest.raises(ValueError):
        route.start(TAB, "Read", CloudPlanner(cloud_backend, "cloud"))
    assert not controller.grants
    route.close()
