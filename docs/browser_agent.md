# Browser-agent foundation and next integration gates

The owner wants Jarvis to use approved signed-in accounts, work locally first,
escalate complex tasks to an optional cloud model, then report through Bonsai.
This combined source patch provides an opt-in session/controller contract, a
read-only extension bridge and a Settings connection screen. Nothing is installed
or activated in the running Jarvis or Opera; no autonomous browser action route
is registered. Do not register raw browser MCP tools to bypass the grant.

## Signed-in browser choice

### Authorization choice when connecting

Ask once when connecting a browser, with **Only tabs I choose** selected by
default. The second choice is **All my Opera tabs**. Identify the actual
connected profile (including the owner's ordinary profile), not a forced Jarvis
profile. Remember the choice for the lifetime of this connection authorization;
do not ask again per tab. On expiry, revocation or reconnection, ask again.

Second-authorization wording:

> Allow Jarvis to discover and read all normal web tabs in this connected Opera
> profile, including signed-in pages, across its windows. Include tabs I open
> while this authorization is active. Keep my excluded tabs and sites private.
> I can stop or revoke this access at any time.

The Settings Browser Agent page opens an operator-present connection dialog.
Enter the ID shown in the extension popup, start pairing, and paste the displayed
single `PORT-CODE` string into the popup. For selected mode, click **Allow
this tab** in each desired normal tab before authorizing. For all-tabs mode,
acknowledge the wider scope in Jarvis and separately grant the optional website
permission in the extension. Exact site and tab exclusions live in the dialog.
Refresh discovers current normal tabs when needed, including tabs opened since
authorization, without per-tab reapproval. Closing the dialog revokes its grant.
The extension popup separately offers a website-permission revoke control. A
worker restart removes stale optional site permission before another pair; an
abrupt termination can delay that cleanup until the extension next wakes.

The trusted owner UI records an explicit all-tabs acknowledgment. Private tabs,
other profiles/browsers, and internal browser/file pages remain outside this
choice. Actions and cloud disclosure retain their separate controls. A profile
authorization is visibility, not permission to send email, buy, delete or upload.

`BrowserAuthorization` implements selected/all-tabs modes, optional tab/site
exclusions, expiry and shared revocation. It issues a document-pinned SessionGrant
from trusted bridge metadata, with observation-only/local-only defaults. Pass
the same authorization into each BrowserAgentSession so revocation invalidates
all linked tasks. The bridge must recheck actual browser/profile/tab/document
identity before reads. All-tabs does not mean harvesting every tab into a model
prompt; read only what a task needs and enforce existing per-task budgets.

The source extension must still be deliberately loaded in Opera by the owner;
there is no signed/store distribution or packaged extension asset yet. One
synthetic selected-tab read, revoke and extension reload were exercised in Opera
GX on 2026-09-24. The revised popup was then reloaded and repeated the same
selected-tab read/revoke successfully; its disconnected manual permission-
cleanup control reported both optional site origins removed. A separate fresh,
unsigned-in Opera GX Standard profile then completed an operator-present
all-site grant/revoke check against one synthetic loopback page: the bridge
discovered and read that page, omitted its form value, lost catalogue access
after Opera permission revoke, and denied reads after Jarvis session revoke.
No signed-in page was read. The browser UI observations are owner-reported;
the probe saved only boolean results.

A separately created profile needs deliberate sign-ins; it cannot automatically
inherit existing authentication. Reusing selected tabs through an explicitly
approved extension is working for the synthetic selected-tab check. Never copy
passwords/cookie databases. Browser access also
does not grant authority to send email or change calendar events.

## Composition contract

The connection controller constructs BrowserAuthorization from the UI choice and
trusted extension metadata, then issues document-pinned SessionGrants. Its
OperaBrowserAdapter enforces the live parent before queuing a read; the extension
checks actual normal-tab status, URL and main-frame document ID before DOM text,
injects only into that document, and rechecks after injection. Python validates
returned identity and size. The transport does not certify the extension process
as Opera rather than another Chromium profile; deliberate setup and the paired
extension ID are the current identity boundary.

Trusted caller constructs SessionGrant(tab_id, document_id, allowed_origins,
allowed_operations, expiry_monotonic, ...), a verified BrowserAdapter,
LocalPlanner(loopback_backend, model_name), and optionally
CloudPlanner(explicit_https_backend, model_name). BrowserAgentSession defaults
enabled=False. After explicit enablement, run(owner_task,
cloud_task=separately_approved_minimized_task) returns SessionResult locally.
Cloud task text is optional and never auto-derived from a private task or page.
Without an explicitly connected adapter the session returns unavailable. The
daemon/reply route does not yet create a browser task session. Never substitute a
fake browser at runtime. Test doubles exist only in the tests.

Do not rewrite global FAST/CHAT settings. Hand SessionResult to the existing
local CHAT reporter, separating completed observations from proposed actions
and failures. No mutating action executes; needs_approval is a proposal, not an
execution receipt. Cancellation/revocation are per-session, and run is single-use.

## Before enabling live use

1. Independently review the combined patch and obtain owner integration decision.
2. Connect the owner session to the daemon/reply task route and grounded CHAT
   reporting, with lifecycle ownership when the Settings screen closes.
3. Verify local backend egress, redirects/proxies and logging before passing
   private pages. Configure any cloud provider explicitly, preserving separate
   task/page egress choices. A subscription or development CLI is not a runtime
   cloud integration.
4. Compare Bonsai and already-installed candidates on the same synthetic
   browser tasks before choosing a replacement or downloading one. Validate
   residency changes separately; preserve a running Jarvis or game.
5. Add fresh action approval and at-most-once delivery before mutations.
   Continue to exclude shell, uploads/downloads and arbitrary browser scripts.

No live model, Opera page, account, microphone or package was exercised by the
source tests. The local loopback tests use synthetic protocol messages only.
The connection screen has an offscreen Qt source smoke check; package parity,
actual Settings interaction, and signed-in-page behavior remain unverified.
See docs/opera_bridge.md.

## Computer-wide agent path

This extension is the browser observation entry point, not a Windows control
grant. A later shared agent task route can coordinate a separately permissioned
desktop adapter with the browser adapter, then return observed status and a
grounded report through the local chat model. Desktop observation and actions
need their own explicit scope, foreground indication, cancellation, per-action
approval for consequential steps, and synthetic validation before any live
computer control. Browser all-tabs authorization never implies desktop control,
and a remote glasses/phone request must pass its separate device/session gate.

References checked 2026-09-23:
- https://github.com/microsoft/playwright/blob/main/packages/extension/README.md
- https://playwright.dev/mcp/configuration/browser-extension
- https://help.opera.com/en/extensions/
