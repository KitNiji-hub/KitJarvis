# ADR 0022: Layered repository credential protection

Date: 2026-09-15
Status: Implemented locally; hosted enforcement requires owner verification

Use pinned Gitleaks defaults plus private-filename checks in the existing
`.githooks` system. Pre-commit reads staged blobs, and pre-push scans full
ancestry for all proposed refs before the existing test hook. Missing tools or
incomplete scans block Git. Neither hook performs network operations or changes
the index/history. A Windows installer configures only the current checkout.

Generate synthetic redaction fixtures at runtime. Preserve immutable historical
test fixtures with six exact reviewed fingerprints, never a broad baseline.
Safe examples remain content-scanned. Ignore private local settings, key files
and generated pytest temporary directories to avoid accidental staging.

GitHub Actions supplies a read-only, full-history scan with pinned tooling.
Local hooks and contributor-controlled CI can be bypassed, and CI runs after a
push. Secret Scanning, Push Protection, protected checks and configuration review
remain required separate server-side controls. No hosted setting was changed.

All repository Actions now use immutable commit SHAs, with automated static
verification and weekly Dependabot proposals for Python and Actions updates.
Read-only checkout jobs do not persist their job tokens. CODEOWNERS assigns the
security surface to the repository owner; independent approval is deferred until
a second trusted maintainer exists. The existing main ruleset is retained, but
authenticated hosted enforcement remains separate from the local changes.

Any real credential requires owner rotation and separate explicit authorization
for history cleanup. The tooling never validates credentials against providers,
revokes keys, commits, publishes or rewrites history.
