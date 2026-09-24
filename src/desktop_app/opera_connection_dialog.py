"""Operator-present, in-memory Opera visibility authorization screen."""
from __future__ import annotations

import re
import time
from pathlib import Path

from PyQt6.QtCore import QTimer

from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel,
                             QLineEdit, QListWidget, QPlainTextEdit, QPushButton,
                             QScrollArea, QVBoxLayout, QWidget)

from jarvis.browser_agent import BrowserScope, OperaConnectionController
from jarvis.opera_bridge import BridgeState


class OperaConnectionDialog(QDialog):
    """Closing this screen revokes the connection and every issued child grant."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Opera connection")
        self.setMinimumSize(620, 500)
        self.controller: OperaConnectionController | None = None
        self._pairing_expires_at = 0.0
        self._paired_message_shown = False
        self._expiry_timer = QTimer(self)
        self._expiry_timer.setInterval(1000)
        self._expiry_timer.timeout.connect(self._check_expiry)
        self._expiry_timer.start()
        outer_layout = QVBoxLayout(self)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        outer_layout.addWidget(scroll)
        content = QWidget(scroll)
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        intro = QLabel("Connect your existing Opera GX profile in three steps. "
                       "Jarvis can only read pages you authorize in this phase.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        install_help = QLabel("1. In Opera, open opera://extensions, turn on Developer mode, "
                              "and choose Load unpacked. Select this extension folder:")
        install_help.setWordWrap(True)
        layout.addWidget(install_help)
        folder = Path(__file__).resolve().parents[2] / "extensions" / "kitjarvis_opera"
        folder_available = (folder / "manifest.json").is_file()
        folder_row = QHBoxLayout()
        self.extension_folder = QLineEdit(str(folder) if folder_available else
                                          "Extension files are not included in this build")
        self.extension_folder.setObjectName("operaExtensionFolder")
        self.extension_folder.setReadOnly(True)
        folder_row.addWidget(self.extension_folder, 1)
        self.copy_folder_button = QPushButton("Copy folder")
        self.copy_folder_button.setEnabled(folder_available)
        self.copy_folder_button.clicked.connect(
            lambda: self._copy_text(self.extension_folder.text()))
        folder_row.addWidget(self.copy_folder_button)
        layout.addLayout(folder_row)

        layout.addWidget(QLabel("2. Open the KitJarvis extension popup and paste its Extension ID:"))

        self.extension_id = QLineEdit()
        self.extension_id.setObjectName("operaExtensionId")
        self.extension_id.setPlaceholderText("Extension ID shown in the Opera extension popup")
        layout.addWidget(self.extension_id)
        self.start_button = QPushButton("Start pairing")
        self.start_button.clicked.connect(self.start_pairing)
        layout.addWidget(self.start_button)
        self.pairing_text = QLabel("Disconnected. No browser listener is running.")
        self.pairing_text.setObjectName("operaPairingStatus")
        self.pairing_text.setWordWrap(True)
        layout.addWidget(self.pairing_text)

        layout.addWidget(QLabel("3. Copy this one-time connection code into the extension popup:"))
        pairing_row = QHBoxLayout()
        self.pairing_code = QLineEdit()
        self.pairing_code.setObjectName("operaPairingCode")
        self.pairing_code.setReadOnly(True)
        self.pairing_code.setPlaceholderText("Start pairing to generate a code")
        pairing_row.addWidget(self.pairing_code, 1)
        self.copy_pairing_button = QPushButton("Copy code")
        self.copy_pairing_button.setObjectName("operaCopyPairingCode")
        self.copy_pairing_button.setEnabled(False)
        self.copy_pairing_button.clicked.connect(
            lambda: self._copy_text(self.pairing_code.text()))
        pairing_row.addWidget(self.copy_pairing_button)
        layout.addLayout(pairing_row)

        scope_row = QHBoxLayout()
        scope_row.addWidget(QLabel("Access:"))
        self.scope = QComboBox()
        self.scope.setObjectName("operaScope")
        self.scope.addItem("Only tabs I choose", BrowserScope.SELECTED_TABS)
        self.scope.addItem("All my Opera tabs", BrowserScope.ALL_TABS)
        self.scope.currentIndexChanged.connect(self._on_scope_changed)
        scope_row.addWidget(self.scope, 1)
        layout.addLayout(scope_row)
        self.all_ack = QCheckBox("I authorize all normal web tabs in this profile")
        self.all_ack.setObjectName("operaAllTabsAcknowledged")
        layout.addWidget(self.all_ack)
        self.all_explanation = QLabel(
            "This includes current and new normal web tabs, including signed-in pages, "
            "until you revoke or this session expires. Private tabs remain excluded.")
        self.all_explanation.setWordWrap(True)
        layout.addWidget(self.all_explanation)
        self._on_scope_changed()
        layout.addWidget(QLabel("Excluded sites (one exact https:// or http:// origin per line):"))
        self.excluded_origins = QPlainTextEdit()
        self.excluded_origins.setObjectName("operaExcludedOrigins")
        self.excluded_origins.setMaximumHeight(80)
        layout.addWidget(self.excluded_origins)
        layout.addWidget(QLabel("Excluded tab IDs (comma separated; shown below after discovery):"))
        self.excluded_tabs = QLineEdit()
        self.excluded_tabs.setObjectName("operaExcludedTabs")
        layout.addWidget(self.excluded_tabs)
        buttons = QHBoxLayout()
        self.authorize_button = QPushButton("Authorize this scope")
        self.authorize_button.clicked.connect(self.authorize)
        self.refresh_button = QPushButton("Refresh available tabs")
        self.refresh_button.clicked.connect(self.refresh_tabs)
        self.revoke_button = QPushButton("Stop and revoke")
        self.revoke_button.clicked.connect(self.revoke)
        for button in (self.authorize_button, self.refresh_button, self.revoke_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.tabs = QListWidget()
        self.tabs.setObjectName("operaAvailableTabs")
        layout.addWidget(self.tabs, 1)
        note = QLabel("Selected mode: click 'Allow this tab' in the extension popup first. "
                      "All-tabs mode also requires the extension's separate site permission. "
                      "No clicks, typing, sending or cloud disclosure are granted here.")
        note.setWordWrap(True)
        layout.addWidget(note)

    @staticmethod
    def _copy_text(value: str) -> None:
        if value:
            QApplication.clipboard().setText(value)

    def _on_scope_changed(self) -> None:
        broad = self.scope.currentData() is BrowserScope.ALL_TABS
        self.all_ack.setVisible(broad)
        self.all_explanation.setVisible(broad)
        if not broad:
            self.all_ack.setChecked(False)

    def start_pairing(self) -> None:
        if self.controller:
            if (self.controller.bridge.get_status().state is BridgeState.PAIRING
                    and time.monotonic() >= self._pairing_expires_at):
                self.revoke()
            else:
                self.pairing_text.setText("Stop the current connection before pairing again.")
                return
        extension_id = self.extension_id.text().strip()
        if not re.fullmatch(r"[a-p]{32}", extension_id):
            self.pairing_text.setText("Enter the exact 32-character extension ID from Opera.")
            return
        try:
            controller = OperaConnectionController("chrome-extension://" + extension_id)
            info = controller.start_pairing()
        except Exception:
            self.pairing_text.setText("Could not start local pairing.")
            return
        self.controller = controller
        self._pairing_expires_at = info.expires_at_monotonic
        self._paired_message_shown = False
        self.pairing_code.setText(f"{info.port}-{info.code}")
        self.copy_pairing_button.setEnabled(True)
        self.start_button.setText("Start pairing")
        self.pairing_text.setText(
            "Paste the code above into the extension popup and choose Connect. "
            "It expires in 60 seconds; generate another if needed.")

    def authorize(self) -> None:
        if not self.controller:
            self.pairing_text.setText("Start pairing first.")
            return
        scope = self.scope.currentData()
        try:
            origins = frozenset(v.strip() for v in self.excluded_origins.toPlainText().splitlines()
                                if v.strip())
            tabs = frozenset(v.strip() for v in self.excluded_tabs.text().split(",") if v.strip())
            self.controller.authorize(scope, excluded_tab_ids=tabs, excluded_origins=origins,
                                      all_tabs_acknowledged=self.all_ack.isChecked())
        except (ValueError, PermissionError):
            self.pairing_text.setText(
                "Authorization unavailable. Check pairing, selected tabs, exclusions and all-tabs acknowledgment.")
            return
        self.pairing_text.setText("Authorized for up to 30 minutes while this screen remains open. "
                                  "Stop and revoke ends all linked tasks.")
        self.refresh_tabs()

    def refresh_tabs(self) -> None:
        self.tabs.clear()
        if not self.controller or not self.controller.authorization:
            self.pairing_text.setText("Authorize a connected scope first.")
            return
        try:
            available = self.controller.list_tabs(timeout_sec=2)
        except (ValueError, PermissionError):
            available = ()
        for tab in available:
            self.tabs.addItem(f"Tab {tab.tab_id} — {tab.origin}")
        if not available:
            self.tabs.addItem("No accessible tabs; check the extension permission and exclusions.")

    def revoke(self) -> None:
        if self.controller:
            self.controller.revoke()
            self.controller = None
        self.tabs.clear()
        self.pairing_code.clear()
        self.copy_pairing_button.setEnabled(False)
        self._pairing_expires_at = 0.0
        self._paired_message_shown = False
        self.start_button.setText("Start pairing")
        self.pairing_text.setText("Revoked. No browser listener is running.")

    def _check_expiry(self) -> None:
        if self.controller:
            state = self.controller.bridge.get_status().state
            if state is BridgeState.PAIRED and not self._paired_message_shown:
                self._paired_message_shown = True
                self.pairing_code.clear()
                self.copy_pairing_button.setEnabled(False)
                self.pairing_text.setText("Connected. Choose access below; selected tabs are the default.")
            elif (state is BridgeState.PAIRING and self._pairing_expires_at
                  and time.monotonic() >= self._pairing_expires_at
                  and self.copy_pairing_button.isEnabled()):
                self.pairing_code.clear()
                self.copy_pairing_button.setEnabled(False)
                self.start_button.setText("Generate new code")
                self.pairing_text.setText("Connection code expired. Generate a new one to continue.")
        authorization = self.controller.authorization if self.controller else None
        if authorization and time.monotonic() >= authorization.expiry_monotonic:
            self.revoke()
            self.pairing_text.setText("Authorization expired. Reconnect to choose a new scope.")

    def closeEvent(self, event) -> None:
        self._expiry_timer.stop()
        self.revoke()
        super().closeEvent(event)
