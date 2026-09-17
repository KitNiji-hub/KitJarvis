# Security Policy

## Supported Versions

See [repository credential protection](#repository-credential-protection) for
required contributor setup, GitHub protections and credential incident response.

This repository is a personal, local-first Jarvis fork under active development.

| Version / Branch | Supported |
| ---------------- | --------- |
| `kitniji/fast-pipeline` | Yes |
| Latest published release | Yes |
| Older releases and tags | Best effort only |

Security fixes are developed on `kitniji/fast-pipeline` first and may later
be included in a tagged release.

## Reporting a Vulnerability

Please use GitHub's private vulnerability reporting / Security Advisory
features when available.

Do not post sensitive vulnerability details, API keys, credentials, personal
information, or private local data in a public issue.

A useful report should include:

- The affected commit, branch, or release.
- Steps needed to reproduce the issue.
- The security impact.
- Relevant logs with secrets and personal information removed.
- Whether the issue requires a particular tool, MCP server, or configuration.

This is a personal/experimental project, so response times are best effort.

## Local-First Security Model

Jarvis is intended to run locally wherever practical. Local model inference,
speech recognition, text-to-speech, memory, and other components can remain
on the user's machine.

Optional features may communicate outside the computer when explicitly
configured, including web search, browser tools, MCP servers, email/calendar
integrations, or other external services.

Users should review the permissions and network behavior of optional tools
before enabling them.

## Security Priorities

Issues are considered especially important when they could cause:

- Unintended remote network exposure.
- Unauthorized command or tool execution.
- Access to files outside an intended scope.
- Credential, token, or private-data disclosure.
- Unsafe MCP or external-service access.
- Unexpected persistence or background execution.

## Repository credential protection

Every clone must install the hooks. Gitignore does not protect tracked files,
and CI runs after a push reaches GitHub. Scanners cannot identify every password
or credential format; local hooks can be edited or bypassed.

### Windows setup

Requirements: Git for Windows, Python 3.11+ on PATH, and **Gitleaks 8.30.1**.
No Jarvis runtime dependencies or administrator privileges are needed.

1. Download `gitleaks_8.30.1_windows_x64.zip` from the
   [official release](https://github.com/gitleaks/gitleaks/releases/tag/v8.30.1).
2. Run `Get-FileHash ./gitleaks_8.30.1_windows_x64.zip -Algorithm SHA256`.
   It must equal
   `d29144deff3a68aa93ced33dddf84b7fdc26070add4aa0f4513094c8332afc4e`.
   Stop on mismatch. Extract the verified archive to a stable local folder.
3. Run from the repository root:

   ```powershell
   ./scripts/install_secret_hooks.ps1 -GitleaksPath C:/path/to/gitleaks.exe
   python scripts/test_secret_guard.py
   python scripts/secret_guard.py worktree
   python scripts/secret_guard.py history
   ```

The installer sets only this checkout's `core.hooksPath=.githooks` and
`secretguard.gitleaksPath`. It refuses a different configured hook directory.
New clones need installation; Git does not activate checked-in hooks itself.
Git GUI clients need Python on PATH too. The LF hooks run under Git for Windows.
Unix users must also make both hooks executable (`chmod +x .githooks/pre-*`).
When staging the new hook after review on Windows, preserve the executable Git
mode with `git add --chmod=+x .githooks/pre-commit`; the existing pre-push hook
already has executable mode. This setup does not stage changes for you.
Linux CI uses the pinned x64 archive with SHA-256
`551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb`.

### Normal use

Keep credentials in private local configuration or a credential manager.
`.env.example`, `.env.sample`, `.env.template` and `examples/config.json` may
contain safe examples; their content is still scanned. Never paste real values
into examples, docs, logs or screenshots. Integration names in `.env.example`
are illustrative placeholders; use the application's documented local config
fields rather than assuming each example environment variable is consumed.

- `python scripts/secret_guard.py staged` scans complete staged blobs for
  changed files. Unstaged edits cannot conceal staged credentials.
- `python scripts/secret_guard.py tracked` scans every file in the index.
- `python scripts/secret_guard.py worktree` scans tracked working files and
  nonignored untracked files. Ignored private files, dependencies and build
  output require a separately scoped redacted audit; never upload raw reports.
- `python scripts/secret_guard.py history` scans all locally available refs,
  removed content and merge diffs. Unfetched refs, other clones, GitHub caches,
  LFS content and encrypted archives are not certified.
- Pre-push scans every ancestor of every proposed branch/tag commit, covering
  new branches, unknown remote tips and force pushes without fetching. Deletions
  are skipped. Shallow history, incomplete scans, missing tools, submodules and
  non-commit refs fail closed and require review.

Private filenames are blocked even when force-added. The existing pre-push test
behavior remains: `SKIP_TESTS=1` skips only tests. Do not use `--no-verify` or
disable hooks to get a credential through. Reports expose rule, path, line and
commit metadata only; temporary reports are deleted.

### False positives

Review the referenced location privately. Prefer runtime-generated synthetic
test values and obvious placeholders. For a proven historical fixture, add
only its exact commit/path/rule/line fingerprint to `.gitleaksignore` with a
reason; never rewrite history merely to fix a synthetic test. The six initial
entries identify reviewed synthetic redaction tests. Never baseline a real key,
blanket-ignore tests/directories/rules, or bypass a block without understanding
it. Inline `gitleaks:allow` comments cannot bypass the guard. Changes to scanner
code, config, hooks, ignore entries and workflows require security review.

### Required GitHub layer

An administrator must verify **Secret Scanning** and **Push Protection** are
enabled under Settings → Code security / Secret Protection, where available
for the repository visibility and plan. Follow GitHub's
[enablement instructions](https://docs.github.com/en/code-security/how-tos/secure-your-secrets/prevent-future-leaks/enable-push-protection).
Enable generic-secret detection where available, review alerts and bypasses,
and restrict bypass permissions where supported. Require the
`Secret protection / secret-scan` status check on protected branches and review
changes to protection configuration. A workflow does not enable those settings.

The new workflow scans pushes/PRs with full history, `contents: read`, no
persisted checkout credentials, a SHA-pinned checkout action and a
checksum-pinned scanner. It uploads no reports, uses no repository secrets and
does not use `pull_request_target`. A PR can modify its own config/workflow;
server-side protections and review remain essential. Existing release workflow
publishing permissions are separate and unchanged.

All external Actions references are pinned to full commit SHAs. Dependabot
checks Python and GitHub Actions weekly so pin updates arrive as reviewable pull
requests. `python scripts/test_workflow_security.py` rejects movable external
action references, `pull_request_target`, missing read-only workflow defaults,
or missing ownership/update coverage. Read-only checkout jobs do not retain the
job token. The two publishing checkouts retain it only where semantic-release
or the explicit fast-forward release push requires authenticated Git access.

`/.github/CODEOWNERS` assigns the repository and its security-sensitive Git,
workflow, hook, scanner and release controls to `@KitNiji-hub`. For the current
single-maintainer repository, this documents ownership and requests review;
requiring an independent code-owner approval would make self-authored changes
unmergeable. Add a second trusted maintainer before enabling that requirement.

Hosted enforcement checklist after the protection commit reaches GitHub:

1. Keep the existing `Protect Main` ruleset's deletion and non-fast-forward
   blocks, and add pull-request and required-check rules appropriate to the
   release flow.
2. Require `Secret protection / secret-scan` after its first successful run.
3. Protect the active integration branch if it accepts direct or collaborative
   pushes. As of the local 2026-09-15 review, `kitniji/fast-pipeline` was public
   and unprotected.
4. Set default workflow token permissions to read-only and disallow Actions from
   creating or approving pull requests unless a reviewed workflow needs it.
5. Require full-SHA Action references only after the SHA-pin migration is
   published; enabling the policy beforehand would reject existing remote
   workflows that still use movable tags.
6. Verify Secret Scanning, Push Protection, generic-secret detection, alert
   resolution, bypass restrictions and required checks through an authenticated
   administrator session.

The repository currently has no public `develop` branch, but legacy test and
release workflows still refer to it. Replacing that release branch is a separate
publishing decision: validate the intended integration/release topology before
editing triggers or the fast-forward release job.

### If a real credential was ever committed

1. Stop pushing/sharing logs. Record only provider/type and affected file/commit.
   Treat the key as compromised even if a later commit deleted it.
2. The owner must revoke or rotate it, update private local settings, and review
   provider usage/access logs. Never test validity by sending it to a service.
3. Remove it from current source and use placeholders/runtime-generated tests.
4. Coordinate any history rewrite, remote cleanup and collaborator re-cloning
   separately with explicit owner approval. Rewriting cannot invalidate a key
   or guarantee copies are gone. Never automatically revoke, rewrite or force
   push; never add real leaked keys to the ignore list.
5. Rerun local scans and review GitHub alerts before resuming publication.
