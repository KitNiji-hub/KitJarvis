# Repository credential protection

This tooling is independent of the Jarvis runtime. Git for Windows and Python
3.11+ run repository hooks with a locally installed Gitleaks 8.30.1 executable.
No hook downloads software, fetches refs, contacts credential providers, or
changes the index or history. Missing tools, incomplete scans and unresolved
indexes block the operation. Reports expose location/rule metadata only.

- `staged`: checks private filenames across the index and scans the complete
  index blob for every added/copied/modified/renamed staged file. Unstaged edits
  cannot conceal credentials. Deletions are allowed.
- `tracked`: scans all index blobs, including checked-out files on CI.
- `worktree`: scans tracked working files and nonignored untracked files.
  Ignored local settings, virtual environments and output are outside this mode.
- `history`: scans all locally available refs and all parent-specific merge
  diffs, including deleted content. Shallow repositories fail closed.
- `pre-push`: consumes every Git ref update, skips deletions and scans every
  ancestor of each proposed commit/tag tip. This conservative policy scans more
  than the outgoing range, covering first pushes, force pushes and unknown remote
  tips without networking. Non-commit tags and submodules require manual review.

`.gitleaksignore` contains only reviewed fingerprints for existing synthetic
historical tests. No baseline, blanket test exemption or inline allow comment
may suppress a new secret. Safe environment templates and the existing
`examples/config.json` remain content-scanned. `.gitignore` and filename guards
are separate protections; force-adding an ignored private path still blocks Git.

Local hooks and PR-controlled configuration can be edited/bypassed by a user.
This is accidental-leak protection, not an adversarial authorization boundary.
GitHub Secret Scanning, Push Protection and protected required checks are the
additional server-side layers. CI observes pushes after they arrive.
