# Browser agent foundation and operator-present task route

This is a source contract, not an Opera connector or a complete runtime agent.
No module registers a tool in the daemon/reply path, starts a browser, installs
anything, or changes FAST/CHAT. The source now includes an operator-present
Settings connection screen, a read-only extension transport, and a single-task
route. The task route binds exactly one active task per controller and runs
catalogue, bridge, and model I/O in a background worker. Its handle is polled
by the trusted UI, which never receives a worker-thread callback. Cancellation
and route closure hide late in-flight results; the worker remains the active
task until it actually exits. Closure also revokes the controller. Already
completed results held by a trusted caller cannot be recalled.
Routes sharing one controller use a weak-keyed task registry, and worker-start
failure releases that slot. A new task may start only after the previous task
reaches its terminal state and completes its browser/model I/O.
Only explicit trusted caller construction can enable one single-use session.
The route requires an injected LocalPlanner and a live owner authorization.

The owner supplies task text and an immutable SessionGrant pinning tab AND
document, exact canonical HTTP(S) origins, operations, monotonic expiry, up to
16 steps, 120 seconds and 8192 characters per observation. Default duration is
30 seconds, 6 steps, 4096 characters. A future UI must issue grants from trusted
owner interaction; model/page text cannot issue them. No persistent grants.

An optional parent BrowserAuthorization adds two explicit visibility scopes:
SELECTED_TABS (default) and ALL_TABS (requires owner acknowledgment). All-tabs
covers existing/new normal HTTP(S) tabs in all windows of one connected
browser/profile, including a personal signed-in Opera profile. It excludes
incognito, other profiles/browsers, internal/file URLs and owner tab/site
exclusions. The owner connection UI asks once per authorization, not per tab.
This scope never expands action or cloud rights.

Parent-issued grants carry browser/profile/authorization binding and pin one
current tab/document/origin. The session requires the matching live parent and
checks its expiry/revocation/exclusions around every callback. Missing or wrong
parent blocks before I/O. Observations must match browser/profile as well as
tab/document. Parent revocation invalidates all linked tasks and future grants;
already read data or accepted I/O cannot be recalled. The bridge must validate
trusted current browser metadata before issuing grants and before DOM access;
the Python objects are not evidence about real browser tabs by themselves.
The Opera extension checks current normal tab, origin and main-frame document
before reading, uses document-scoped injection, and rechecks before delivering
bounded content. An operator-present Opera GX check has exercised selected-tab
read/revoke and all-site grant/revoke on a synthetic page in an unsigned-in
profile. Signed-in pages and packaged distribution remain unverified.
An MV3 worker restart loses the in-memory pairing token; startup must clear
stale optional all-sites permission before a new pair. Abrupt termination can
delay permission cleanup until restart, so the popup also has a manual revoke.

Each step asks the trusted adapter for an observation, validates its response,
then calls the local planner with the owner's task and untrusted page data.
Planner JSON is capped at 4096 characters and checked against a closed schema.
Callbacks receive remaining deadlines. No threads are spawned for callbacks.
Stop/revoke/expiry is checked around calls. Cooperative callbacks may overrun;
late data/results are discarded and no subsequent call is issued. Already
accepted I/O cannot be undone. Concurrent/repeated run cannot replay work.

The adapter MUST enforce actual tab/document/origin and deadline before DOM
reads, handle navigation races, cap data and exclude secrets/form values.
Controller validation is only defense in depth; an arbitrary injected adapter
is trusted code, not a sandbox. The Opera source adapter and extension have
synthetic tests plus the operator-present Opera GX fixture check; that narrow
check does not certify signed-in sites or future extension versions. Origin syntax
validation is not DNS/IP isolation. HTTP(S) grants can include explicitly
approved local web apps, but non-web schemes and wildcard origins are refused.

Only observation executes. All click/type/submit/navigation proposals return
needs_approval, with immutable action/session/tab/document/deadline binding,
after a fresh document check. There is NO approval-consumption/execution API.
No arbitrary JS, shell, storage/cookies, file transfer, keyboard or raw MCP
names. A new document needs a new grant. Existing MCP's automatic retry must
not be used for future mutation delivery without an at-most-once contract.

LocalPlanner requires a literal loopback backend URL. An explicit escalation
may call a configured CloudPlanner HTTPS backend only when cloud policy allows
it AND the trusted caller supplies a separately approved minimized cloud_task.
The private local task and prior planner output/history never transfer.
Page content and origin transfer only with separate page-context egress consent;
otherwise neither transfers. Backends are trusted dependencies: URL checks do
not constrain arbitrary backend code, HTTP redirects, proxies or logging.
Production integration must enforce transport egress/redirect policy and audit
backend logging before enabling private browser data. No model is loaded or
unloaded. The module does not certify runtime inference quality.

Every terminal state returns bounded immutable local report input: actual
observations/executed observations, status, optional pending action, content-free
audit. Completed means the planner has finished gathering observations, not
that its claims are verified or a proposed mutation occurred. CHAT must report
from evidence and preserve blocked/failed/cancelled/expired/budget states.
Observations are private local data; audit metadata excludes content and URLs.
No report model is called here; existing CHAT integration is still required.
The task route's BrowserTaskReport has a content-free deterministic summary and
keeps its SessionResult out of repr. Its session result is available only to a
trusted local caller while the task remains authorized. Planner `done` means
only that observation is sufficient. Route grants must contain OBSERVE alone
and deny cloud access; a live catalogue recheck still precedes each session.

Tests: tests/test_browser_agent.py, tests/test_browser_agent_task_route.py,
tests/test_opera_bridge.py, and
tests/opera_bridge.test.js. Source tests use synthetic/fake I/O; the separate
operator-present Opera GX fixture check is recorded under
collaboration/results/2026-09-24-opera-onboarding-live/. Daemon/UI task routing,
final CHAT rendering, signed-in site behavior, model quality and packaging
remain separate gates.
