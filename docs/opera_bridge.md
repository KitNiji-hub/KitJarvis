# Opera source bridge: read-only connection

This source adds an unpacked MV3 extension under `extensions/kitjarvis_opera`,
a Python loopback service and a Browser Agent page in Settings. It is opt-in;
opening Settings does not start a listener. The owner starts pairing, copies a
single short-lived `PORT-CODE` string into the extension popup, and authorizes
selected tabs or all normal web tabs. The profile ID is generated inside that
extension profile and kept there; the Python side binds to it for the
connection. The browser ID is a local label, not cryptographic proof of the
Opera executable.

## Source-build setup

1. In Opera GX, open `opera://extensions`, enable Developer mode, choose
   **Load unpacked**, and select the folder shown on Jarvis Settings → Browser
   Agent → **Open Opera connection…**. The dialog has a **Copy folder** button
   when those source files are present. This manual install is a development
   path; a signed/store distribution and packaged extension assets are not yet
   available.
2. Open the KitJarvis extension popup, copy its extension ID, and paste that ID
   into the Jarvis dialog. In the dialog, choose **Start pairing**, then **Copy
   code**. Paste the resulting `PORT-CODE` string into the popup and choose
   **Connect** within 60 seconds. If it expires, choose **Generate new code**.
   The extension ID identifies the installed copy; the one-time code is not
   stored in extension storage.
3. For the default selected-tabs scope, open a normal web tab and choose
   **Allow this tab** in the popup, then authorize **Only tabs I choose** in
   Jarvis. Broad access is tucked under the popup's advanced section and needs
   a separate Opera permission plus the matching Jarvis all-tabs
   acknowledgement. **Disconnect** and **Stop and revoke** end the connection;
   the popup also exposes manual all-site permission revoke while disconnected.

The setup UI reduces copy/paste and explains the permission steps; it does not
install the extension automatically or make the current source build a
consumer-ready package. The selected-tab bridge was physically exercised on
one synthetic Opera GX page on 2026-09-24. No signed-in page or all-tabs
permission was used in that test.

The Python listener binds only to `127.0.0.1` on an ephemeral port. It accepts
only an exact configured extension Origin and Host, JSON POST on named routes,
one-time eight-digit pairing code (60 seconds, five attempts), then a random
bearer. Requests and responses are bounded. No CORS grant is sent to web origins.
Stop/revoke invalidates the bearer, clears pending work and stops the listener.
The extension removes and verifies its optional all-sites host permission on
disconnect and before accepting a new pair. A restarted MV3 worker repeats
that cleanup because its in-memory connection token is lost. It also attempts
cleanup during orderly suspension, but abrupt worker/browser termination may
leave a browser-granted permission until the worker next starts. The popup
provides a separate **Revoke all-site website permission** button; the owner
can also revoke site access in Opera's extension settings. The selected-tab
synthetic test did not exercise abrupt termination of a broad permission, so
do not claim instantaneous removal after that case.
A local process with the user's privileges is outside this boundary.

Selected mode requires the user to click **Allow this tab** in the popup for
each chosen tab; no page text is read at that point. All-tabs requires both the
Jarvis dialog acknowledgment and the browser's separate optional website
permission. The extension lists only normal HTTP(S) tab metadata after a
task-specific refresh and applies excluded tabs/sites before sending metadata;
Python filters it again. Newly opened tabs are discoverable on the next refresh.
Neither mode reads every page merely because it is visible.

For a read, the Python adapter checks the live parent authorization and paired
profile before sending a bounded command. The extension checks `tabs.get` and
main-frame `webNavigation.getFrame` (including `documentId`) before DOM access;
`scripting.executeScript` targets that exact document ID in the isolated world.
Returned document ID, origin, normal-tab status and current document are checked
again. It sends bounded `innerText` only, never form values, cookies, storage,
frames, screenshots, clicks, typing or arbitrary script. The Python server
matches request ID/profile/tab/document/origin and discards late results. Already
issued I/O cannot be recalled after revocation, so the controller also discards
results after a late parent revoke.

This connection screen closes and revokes its authorization. There is no daemon
task routing, spoken request path, action execution, cloud page disclosure or
background permission persistence in this patch. `document_is_current` returns
false for action proposals. The 2026-09-24 operator-present synthetic test
proved pairing, one selected page-text read, Python-side revoke, and a
disconnected popup after extension reload. It did not read personal tabs or
test optional all-site permission cleanup, action execution, agent routing, or
a packaged build. Further signed-in validation remains a separate gate.

API references checked 2026-09-24:

- https://help.opera.com/en/extensions/basics/
- https://help.opera.com/en/extensions/testing/
- https://developer.chrome.com/docs/extensions/reference/api/scripting
- https://developer.chrome.com/docs/extensions/develop/security-privacy/user-privacy
