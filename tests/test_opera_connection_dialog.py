"""Source-only onboarding checks; no live Opera or bridge process is started."""
from __future__ import annotations

import os
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

from desktop_app import opera_connection_dialog as dialog_module
from jarvis.browser_agent import BrowserScope
from jarvis.opera_bridge import BridgeState


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance


def test_onboarding_shows_source_folder_and_keeps_broad_scope_collapsed(app):
    dialog = dialog_module.OperaConnectionDialog()
    try:
        assert dialog.extension_folder.text().endswith("extensions\\kitjarvis_opera")
        assert dialog.copy_folder_button.isEnabled()
        assert dialog.scope.currentData() is BrowserScope.SELECTED_TABS
        assert dialog.all_ack.isHidden()
        dialog.scope.setCurrentIndex(1)
        assert dialog.all_ack.isHidden() is False
        dialog.all_ack.setChecked(True)
        dialog.scope.setCurrentIndex(0)
        assert dialog.all_ack.isHidden()
        assert not dialog.all_ack.isChecked()
    finally:
        dialog.close()


def test_one_paste_pairing_code_copy_expiry_and_regeneration(app, monkeypatch):
    created = []

    class FakeBridge:
        def __init__(self):
            self.state = BridgeState.PAIRING

        def get_status(self):
            return SimpleNamespace(state=self.state)

    class FakeController:
        def __init__(self, origin):
            assert origin == "chrome-extension://" + "a" * 32
            self.bridge = FakeBridge()
            self.authorization = None
            self.revoked = False
            created.append(self)

        def start_pairing(self):
            return SimpleNamespace(port=45001, code="00123456",
                                   expires_at_monotonic=time.monotonic() - 1)

        def revoke(self):
            self.revoked = True
            self.bridge.state = BridgeState.STOPPED

    monkeypatch.setattr(dialog_module, "OperaConnectionController", FakeController)
    dialog = dialog_module.OperaConnectionDialog()
    copied = []
    monkeypatch.setattr(dialog, "_copy_text", copied.append)
    try:
        dialog.extension_id.setText("a" * 32)
        dialog.start_pairing()
        assert dialog.pairing_code.text() == "45001-00123456"
        assert dialog.copy_pairing_button.isEnabled()
        dialog.copy_pairing_button.click()
        assert copied == ["45001-00123456"]

        dialog._check_expiry()
        assert dialog.pairing_code.text() == ""
        assert not dialog.copy_pairing_button.isEnabled()
        assert dialog.start_button.text() == "Generate new code"

        dialog.start_pairing()
        assert len(created) == 2 and created[0].revoked
        assert dialog.pairing_code.text() == "45001-00123456"
        dialog.revoke()
        assert created[1].revoked
        assert dialog.pairing_code.text() == ""
    finally:
        dialog.close()


def test_pairing_code_clears_when_extension_connects(app, monkeypatch):
    class FakeController:
        def __init__(self, _origin):
            self.state = BridgeState.PAIRING
            self.bridge = self
            self.authorization = None

        def get_status(self):
            return SimpleNamespace(state=self.state)

        def start_pairing(self):
            return SimpleNamespace(port=45002, code="12345678",
                                   expires_at_monotonic=time.monotonic() + 60)

        def revoke(self):
            self.state = BridgeState.STOPPED

    monkeypatch.setattr(dialog_module, "OperaConnectionController", FakeController)
    dialog = dialog_module.OperaConnectionDialog()
    try:
        dialog.extension_id.setText("a" * 32)
        dialog.start_pairing()
        assert dialog.copy_pairing_button.isEnabled()
        dialog.controller.state = BridgeState.PAIRED
        dialog._check_expiry()
        assert not dialog.copy_pairing_button.isEnabled()
        assert dialog.pairing_code.text() == ""
        assert "Connected" in dialog.pairing_text.text()
    finally:
        dialog.close()
