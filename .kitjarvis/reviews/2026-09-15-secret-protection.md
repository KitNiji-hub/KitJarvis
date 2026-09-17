# Credential protection verification — 2026-09-15

Branch: `kitniji/fast-pipeline`, HEAD `464fe16`.
Remotes inspected locally: origin `KitNiji-hub/KitJarvis`, fork
`KitNiji-hub/jarvis`, both GitHub HTTPS. No fetch, push, provider validation or
hosted settings change was performed. Extensive existing uncommitted work was
preserved. The real index started and ended with zero staged changes.

## Audit findings

- Initial Gitleaks 8.30.1 full local history: **477 commits**, 6 findings,
  exit 1. All six are synthetic redaction fixtures in
  `tests/test_dialogue_memory.py`, `tests/test_dialogue_memory_tool_carryover.py`,
  `tests/test_redact_extended.py`, and `tests/test_desktop_app.py`. The exact
  commits/lines are in `.gitleaksignore`. Current fixtures construct identical
  values at runtime; only historical fingerprints are excepted.
- Initial staged scan: exit 0; no staged changes.
- Broad `gitleaks dir .` audit (including ignored output/dependencies):
  **80 findings**, exit 1, about 1.15 GB scanned. Breakdown: 65 in `.venv`,
  1 in `dist`, 8 compiled test-cache matches, and 6 source test matches.
  Dependency matches include constants/types and upstream fixtures, not evidence
  that the user owns those credentials. Two Google API-key-shaped findings occur
  at line 6050 in `.venv/Lib/site-packages/PyQt6/Qt6/resources/qtwebengine_devtools_resources.debug.pak`
  and its `dist/Jarvis/_internal/PyQt6/Qt6/resources/` copy. Ownership, validity,
  restrictions and upstream disposition were **not verified**. No key was sent
  to a service. These files are ignored/untracked; none was added to the scanner
  allowlist. If the owner recognizes either as their own credential, rotate it.
- Windows denied access to `.pytest-phase10-scratch`; the broad audit is
  incomplete there. Generated `.pytest-*/` directories are now ignored to keep
  disposable runtime files out of commits. They are not included in subsequent
  Git-candidate scans. No user-owned real credential was confirmed and no
  revocation was performed.

## Commands and results

Scanner downloaded from the official v8.30.1 release before the audit and
verified against its published SHA-256. Stable local installation:
`$env:LOCALAPPDATA/KitJarvis/secret-tools/8.30.1/gitleaks.exe`.

Initial scans (reports/logs stayed local outside the repository; reports used
full redaction and only rule/path/line/commit metadata was displayed):

```powershell
$auditDir = Join-Path $env:TEMP 'kitjarvis-secret-audit-20260915'
& "$auditDir/gitleaks.exe" git . --log-opts='--all --full-history' --redact=100 --no-banner --no-color --report-format json --report-path "$auditDir/history.json"
& "$auditDir/gitleaks.exe" git . --pre-commit --staged --redact=100 --no-banner --no-color --report-format json --report-path "$auditDir/staged.json"
& "$auditDir/gitleaks.exe" dir . --redact=100 --no-banner --no-color --timeout 180 --report-format json --report-path "$auditDir/working.json"
```

Protection installation and verification:

```powershell
./scripts/install_secret_hooks.ps1 -GitleaksPath "$env:LOCALAPPDATA/KitJarvis/secret-tools/8.30.1/gitleaks.exe"
python scripts/test_secret_guard.py
python scripts/secret_guard.py history
python scripts/secret_guard.py worktree
python scripts/secret_guard.py staged
.venv/Scripts/python.exe -m pytest -q tests/test_redact_extended.py tests/test_dialogue_memory.py tests/test_dialogue_memory_tool_carryover.py tests/test_desktop_app.py -k 'redact or scrubbed or sensitive or report_issue_url_generation'
```

Results: installation succeeded; **8 guard tests passed**; final history,
worktree and staged scans exited 0; **26 existing regressions passed,
118 deselected**. Tests cover actual pre-commit invocation, clean data, runtime
fake tokens/passwords/private keys, force-added private paths, safe example
content scanning, missing scanner, inline bypass attempts, unstaged concealment,
multiple proposed refs, new branches, a secret removed by a subsequent commit,
deletion pushes and `SKIP_TESTS=1`. Disposable repositories use local commit
objects only for history tests; they have no remote and are deleted afterward.

A separate temporary `GIT_INDEX_FILE` was initialized with `git read-tree HEAD`,
then populated with `git add -- <protection files and four edited tests>`.
`python scripts/secret_guard.py tracked` against that prospective index passed.
The temporary index was deleted; the real index was never staged. The existing
HEAD/index still contains the old fixtures until the owner stages the reviewed
fixes; scanning that unchanged complete index can therefore still flag them.

## Review and remaining gates

The added workflow grants only `contents: read`, disables checkout credential
persistence, pins checkout to a verified release SHA, verifies the scanner
archive against a fixed hash, and uploads no report. Existing release workflow
permissions and behavior are untouched. All previously present file hashes were
checked; changes are limited to protection/docs and the four synthetic fixtures.
Existing `.gitattributes` rules were preserved and the LF hook rule appended.

GitHub Actions execution, Linux execution, GitHub Secret Scanning/Push Protection,
required branch checks and bypass policy remain unverified. No browser/API
inspection of repository settings followed the credential audit. Unfetched refs,
unreachable objects, LFS payloads, encrypted files, ignored output completeness,
and other clones are not certified. No live Jarvis, microphone, GPU, remote
route, Android, build, installer/package or full application test was needed.

After owner review, the new pre-commit hook must eventually be staged with
executable mode (`git add --chmod=+x .githooks/pre-commit`) for Unix clones.
No staging, commit or push is authorized by this report.

## Exact prospective-index verification command

Run in PowerShell from the repository root. Only the temporary index is staged.

```powershell
@'
import os, pathlib, subprocess, sys, tempfile
files = [
    ".gitattributes", ".gitignore", ".env.example", ".gitleaks.toml", ".gitleaksignore",
    ".githooks/pre-commit", ".githooks/pre-push", ".github/CODEOWNERS",
    ".github/dependabot.yml", ".github/workflows/build-desktop.yml",
    ".github/workflows/release-smoke.yml", ".github/workflows/release.yml",
    ".github/workflows/secret-scan.yml", ".github/workflows/tests.yml",
    "scripts/secret_guard.py", "scripts/secret_guard.spec.md",
    "scripts/install_secret_hooks.ps1", "scripts/test_secret_guard.py",
    "scripts/test_workflow_security.py",
    "README.md", "SECURITY.md", "tests/test_desktop_app.py",
    "tests/test_dialogue_memory.py", "tests/test_dialogue_memory_tool_carryover.py",
    "tests/test_redact_extended.py", ".kitjarvis/PROJECT_STATUS.md",
    ".kitjarvis/decisions/0022-repository-secret-protection.md",
    ".kitjarvis/reviews/2026-09-15-secret-protection.md",
]
with tempfile.TemporaryDirectory(prefix="kitjarvis-candidate-index-") as tmp:
    env = os.environ.copy()
    env["GIT_INDEX_FILE"] = str(pathlib.Path(tmp) / "index")
    for args in [["git", "read-tree", "HEAD"], ["git", "add", "--", *files]]:
        result = subprocess.run(args, env=env, capture_output=True)
        if result.returncode:
            raise SystemExit("Candidate-index preparation failed; diagnostics suppressed")
    result = subprocess.run([sys.executable, "scripts/secret_guard.py", "tracked"], env=env)
    if result.returncode:
        raise SystemExit(result.returncode)
print("Prospective index passed; temporary index removed; real index untouched.")
'@ | python -
```

Final static review also passed Python AST parsing, workflow YAML parsing,
read-only permission/trigger/SHA-pin assertions, and scoped `git diff --check`.
The shell hooks were normalized to LF; the clean pre-push shell path and the
secret-blocked path both passed their regression assertions.

Final preservation check covered 5,381 previously present files: only the ten
intended existing files changed, and the real staging area remained empty.
No disposable guard-test directories remained. Temporary audit downloads and
redacted raw reports were removed after this review was saved; the verified
scanner remains in its stable local installation for the hooks.

## Hosted hardening continuation

On 2026-09-15, public GitHub API evidence confirmed the repository is public,
owned by the individual `KitNiji-hub` account, defaults to `main`, and has three
public contributors. `main` is protected by active ruleset `Protect Main`.
The ruleset currently contains only deletion and non-fast-forward blocks, with
no public bypass actors. `kitniji/fast-pipeline` is unprotected. No public
`develop` branch exists, although legacy tests and release workflows refer to it.
Authenticated branch details, Actions permissions, security analysis settings
and alerts returned authentication-required responses.

Repository changes added CODEOWNERS, weekly pip and GitHub Actions Dependabot,
and `scripts/test_workflow_security.py`. Every external `uses:` reference across
five workflows was resolved from its official repository tag through GitHub's
public API, peeled to a commit when necessary, and pinned to a 40-character SHA.
Read-only checkout jobs now use `persist-credentials: false`; only the two
publishing paths retain checkout credentials for semantic-release or the
explicit fast-forward push. The secret workflow runs both guard suites.

Verification commands:

```powershell
python scripts/test_workflow_security.py
python scripts/test_secret_guard.py
python scripts/secret_guard.py worktree
python scripts/secret_guard.py history
git diff --check -- .github scripts/test_workflow_security.py
```

Results: workflow policy passed for five workflows and 16 SHA-pinned external
uses; eight guard tests passed; final worktree/history scans passed; diff check
passed apart from expected Git line-ending notices. Public tag/ref lookups
verified each pinned SHA belonged to its named Action repository.

The expanded prospective-index check also passed after adding CODEOWNERS,
Dependabot, all five workflow changes and the workflow-policy test to its exact
file list. The real index remained empty.

The GitHub CLI required by the GitHub operations workflow is not installed.
The available in-app browser was signed out and the settings URL returned a
logged-out 404. No credential was requested, read, printed or transmitted. No
GitHub setting was changed. The browser confirmation policy also requires a
fresh action-time confirmation before changing repository permissions or access,
even after the owner's general `Go for it` authorization.

## Authenticated hosted verification and ruleset update

After the owner completed authentication, the repository settings UI confirmed
that Secret Protection and Push Protection are enabled. The dependency graph,
Dependabot alerts, malware alerts, security updates and grouped updates are also
enabled. CodeQL default setup has a recorded recent scan. Actions defaults to a
read-only repository/packages token, and Actions cannot create or approve pull
requests.

The owner provided a separate action-time confirmation immediately before the
save. GitHub displayed `Ruleset updated`; a fresh reload then confirmed active
`Protect Main` requires a pull request before merging to `main`, requires zero
approvals, requires review conversations to be resolved, retains an empty bypass
list, blocks deletion, and blocks force pushes. Zero approvals avoids a
single-maintainer self-approval deadlock while preventing direct updates to
`main`.

Repository-wide Action SHA enforcement remains disabled until these pinned
workflow changes are published. The current remote workflows still reference
version tags, so enabling enforcement first could stop them from running.
Required status checks, including the new secret scan, also remain deferred
until GitHub has observed those checks on a published branch. No commit or push
was performed, and no secret-protection feature was disabled or otherwise
changed during authenticated review.

## Security-only staging receipt

After explicit owner authorization, the real index was populated with an exact
27-file credential-protection allowlist for review. `README.md`, `SECURITY.md`
and `tests/test_desktop_app.py` were constructed in the index from `HEAD` plus
only their security hunks; their unrelated working-tree changes remain visibly
unstaged. The unrelated untracked `.kitjarvis/PROJECT_STATUS.md` was not staged.
The new pre-commit hook is staged with mode `100755`.

The staged guard and actual pre-commit hook both passed. The workflow policy
test passed for five workflows and 16 full-SHA external Actions; all eight
disposable guard tests passed; 26 focused repository regressions passed with
118 deselected; the worktree guard and staged `git diff --check` passed. An
exact-set assertion confirmed no file outside the 27-file allowlist entered the
index. No commit or push was performed.
